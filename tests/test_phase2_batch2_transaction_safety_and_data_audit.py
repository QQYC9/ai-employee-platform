from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProviderError
from packages.core.database import SessionLocal
from packages.models.domain import (
    Conversation,
    Customer,
    ExecutionStep,
    ExecutionTrace,
    Message,
    Permission,
    Task,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.execution_tracing_service import (
    ExecutionTracingService,
    sanitize_value,
)
from packages.services.task_execution_service import TaskExecutionService
from packages.tools.contract import ToolExecutionContext
from packages.tools.executor import ToolExecutor


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def create_tenant(db: Session, name: str = "Audit Tenant") -> Tenant:
    tenant = Tenant(
        id=uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()
    return tenant


def create_conversation(
    db: Session,
    tenant_id: UUID,
    customer_id: UUID | None = None,
) -> Conversation:
    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        customer_id=customer_id,
        status="open",
        metadata_json={"channel": "telegram"},
    )
    db.add(conv)
    db.flush()
    return conv


def create_message(
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    sender_type: str = "customer",
    content: str = "مرحبا، أريد الاستفسار عن خدماتكم",
    sender_id: UUID | None = None,
    customer_id: UUID | None = None,
    metadata_json: dict | None = None,
) -> Message:
    msg = Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
        sender_type=sender_type,
        sender_id=sender_id,
        content=content,
        metadata_json=metadata_json or {},
    )
    db.add(msg)
    db.flush()
    return msg


class MockAIProvider:
    def __init__(self, responses: list[str] | None = None, should_fail: bool = False):
        self.responses = responses or ["أهلاً بك، نسعد بخدمتك."]
        self.should_fail = should_fail
        self._idx = 0

    def generate_text(self, prompt: str, *, system_instruction: str | None = None, temperature: float = 0.2) -> str:
        if self.should_fail:
            raise AIProviderError("Provider error with secret sk-12345678901234567890 and Bearer tok_1234567890")
        resp = self.responses[self._idx % len(self.responses)]
        self._idx += 1
        return resp

    def generate_json(self, prompt: str, *, system_instruction: str | None = None, schema: dict | None = None) -> dict:
        return {"response": "mock_json"}


# ==============================================================================
# SECTION 1: TRANSACTION SAFETY & SAVEPOINTS AUDIT (Real PostgreSQL)
# ==============================================================================

def test_real_db_error_in_start_trace_preserves_outer_business_transaction(db: Session):
    """
    Scenario 1: Active business transaction + start_trace fails due to a real DB error
    (violating composite foreign key fk_traces_conv_tenant with a non-existent conversation).
    Verifies:
      1. start_trace returns None safely.
      2. Nested savepoint is rolled back.
      3. Outer transaction remains healthy and retains business records.
      4. Outer transaction can commit successfully.
    """
    tenant = create_tenant(db, "Audit Tx S1")

    # Business entity created in outer transaction
    customer = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Business Customer",
        status="active",
    )
    db.add(customer)
    db.flush()

    tracing_svc = ExecutionTracingService(db)

    # Intentionally trigger a REAL PostgreSQL foreign key violation inside start_trace
    # by providing a non-existent conversation_id
    fake_conv_id = uuid4()
    trace = tracing_svc.start_trace(
        tenant_id=tenant.id,
        conversation_id=fake_conv_id,
        trigger_type="inbound_message",
    )

    # 1. start_trace failed safely and returned None
    assert trace is None

    # 2. Outer transaction was NOT aborted / not in PendingRollbackError
    # We can still query the customer and add another business entity
    queried_customer = db.scalar(select(Customer).where(Customer.id == customer.id))
    assert queried_customer is not None
    assert queried_customer.name == "Business Customer"

    # 3. We can write more to the outer transaction and flush without error
    conv = create_conversation(db, tenant.id, customer_id=customer.id)
    assert conv.id is not None
    db.flush()


def test_real_db_error_in_record_step_preserves_outer_business_transaction(db: Session):
    """
    Scenario 2: Active business transaction + record_step fails due to a real DB error
    (violating composite FK or non-existent trace_id).
    Verifies:
      1. record_step returns None safely.
      2. Outer session remains usable for business queries and updates.
    """
    tenant = create_tenant(db, "Audit Tx S2")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="طلب شراء منتج")

    tracing_svc = ExecutionTracingService(db)

    # Trigger real DB FK violation: step referencing a non-existent trace_id
    non_existent_trace_id = uuid4()
    step = tracing_svc.record_step(
        tenant_id=tenant.id,
        trace_id=non_existent_trace_id,
        step_name="failing_step",
        step_type="test",
        status="completed",
    )

    # Step failed safely
    assert step is None

    # Outer transaction still intact: message still exists and is modifiable
    db.refresh(msg)
    assert msg.content == "طلب شراء منتج"
    msg.metadata_json = {"business_status": "approved"}
    db.flush()
    assert msg.metadata_json["business_status"] == "approved"


def test_real_db_error_in_complete_trace_preserves_business_reply(db: Session):
    """
    Scenario 3: Business reply message is generated, but complete_trace fails due to DB error.
    Verifies:
      1. complete_trace returns None safely.
      2. The generated business reply message is NOT lost or rolled back.
    """
    tenant = create_tenant(db, "Audit Tx S3")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="استفسار")

    tracing_svc = ExecutionTracingService(db)
    trace = tracing_svc.start_trace(tenant_id=tenant.id, conversation_id=conv.id)
    assert trace is not None

    # Business generates a real reply message
    reply_msg = create_message(db, tenant.id, conv.id, sender_type="agent", content="الرد الإداري المعتمد")
    db.flush()

    # Intentionally cause complete_trace to fail on real DB constraint
    # (pass a non-existent reply_message_id to trigger fk_traces_reply_msg_tenant)
    fake_reply_id = uuid4()
    completed_trace = tracing_svc.complete_trace(
        tenant_id=tenant.id,
        trace_id=trace.id,
        reply_message_id=fake_reply_id,
        status="completed",
    )

    # complete_trace returned None safely
    assert completed_trace is None

    # Crucial: Outer transaction is still valid and the real business reply is intact!
    db.refresh(reply_msg)
    assert reply_msg.content == "الرد الإداري المعتمد"


def test_business_failure_is_not_masked_by_tracing(db: Session):
    """
    Scenario 5: When the business operation fails (e.g. AI provider raises error),
    tracing must NOT hide the business error, and must NOT record a false 'completed' success.
    """
    tenant = create_tenant(db, "Audit Tx S5")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="رسالة تؤدي لخطأ في المزود")

    failing_provider = MockAIProvider(should_fail=True)
    engine = ConversationalAgentEngine(db=db, ai_provider=failing_provider)

    result = engine.process_incoming_message(tenant.id, msg.id)

    # Business result correctly reflects failure
    assert result.success is False
    assert result.error is not None
    assert result.reply_message_id is None

    # Verify tracing recorded 'failed' status and NOT 'completed'
    trace = db.scalar(select(ExecutionTrace).where(ExecutionTrace.id == result.trace_id))
    assert trace is not None
    assert trace.status == "failed"


# ==============================================================================
# SECTION 2: PREVENTION OF BUSINESS RE-EXECUTION AUDIT
# ==============================================================================

def test_tool_side_effect_executed_exactly_once_when_tracing_fails(db: Session):
    """
    Scenario 4 / Re-execution audit:
    An observable side-effect counter is incremented by a tool.
    Tracing record_step is forced to fail AFTER tool execution.
    Verifies:
      1. Tool is executed EXACTLY ONCE.
      2. Tool execution result is returned successfully.
      3. No duplicate invocation or retry of the business tool occurs.
    """
    tenant = create_tenant(db, "Audit Re-exec Tool")
    tool = Tool(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Side Effect Tool",
        slug="side_effect_tool",
        tool_type="business",
    )
    db.add(tool)

    perm = Permission(
        id=uuid4(),
        tenant_id=tenant.id,
        action="execute:side_effect_tool",
        resource="tools:side_effect_tool",
        effect="allow",
    )
    db.add(perm)
    db.flush()

    execution_counter = {"count": 0}

    def real_side_effect_handler(**kwargs):
        execution_counter["count"] += 1
        return {"result": "order_placed_12345", "counter": execution_counter["count"]}

    tracing_svc = ExecutionTracingService(db)
    trace = tracing_svc.start_trace(tenant_id=tenant.id, trigger_type="tool_test")
    assert trace is not None

    executor = ToolExecutor(db, execution_tracing_service=tracing_svc)
    executor.register_handler("side_effect_tool", real_side_effect_handler)

    # Monkeypatch tracing_service.record_step on executor to simulate DB crash during post-execution tracing
    real_record_step = tracing_svc.record_step
    def failing_record_step(*args, **kwargs):
        raise RuntimeError("Simulated DB connection crash during step recording")

    executor.tracing_service.record_step = failing_record_step

    # Execute tool
    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:side_effect_tool",
        resource="tools:side_effect_tool",
        parameters={"order_id": 999},
        trace_id=trace.id,
    )

    # 1. Tool execution succeeded
    assert result.status == "executed"
    assert result.output["result"] == "order_placed_12345"

    # 2. Tool side-effect happened EXACTLY ONCE (not re-executed)
    assert execution_counter["count"] == 1


# ==============================================================================
# SECTION 3: SENSITIVE DATA SANITIZATION AUDIT
# ==============================================================================

def test_sanitization_comprehensive_cases():
    """
    Test all 8 sanitization cases:
    1. API keys (sk-...), Bearer tokens, JWT.
    2. Passwords, credentials, private keys.
    3. Nested dictionaries and lists.
    4. Exception strings containing secrets.
    5. Long texts (>120 chars).
    6. None, integers, booleans.
    7. Key variations: apiKey, API-KEY, api_key.
    8. Secret in the middle of a string.
    """
    # Case 1: sk-..., Bearer, JWT
    c1 = sanitize_value("Header Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz and key sk-abcdef123456789012")
    assert "Bearer [REDACTED]" in c1
    assert "[REDACTED_API_KEY]" in c1

    # Case 2: Passwords in key-value format
    c2 = sanitize_value({"password": "PlainPassword123", "secret": "shhh", "private_key": "MIIB..."})
    assert c2["password"] == "[REDACTED]"
    assert c2["secret"] == "[REDACTED]"
    assert c2["private_key"] == "[REDACTED]"

    # Case 3: Nested dictionaries and lists
    c3 = sanitize_value({
        "data": {
            "sub": [{"token": "tok_xyz"}, "Bearer abcdef1234567890"]
        }
    })
    assert c3["data"]["sub"][0]["token"] == "[REDACTED]"
    assert "Bearer [REDACTED]" in c3["data"]["sub"][1]

    # Case 4: Exception string with secret
    c4 = sanitize_value("Exception: Database auth failed for password='SecretPassword99!' at host 10.0.0.1")
    assert "SecretPassword99!" not in c4
    assert "password: [REDACTED]" in c4

    # Case 5: Long text truncation
    long_msg = "مرحبا، أود الاستفسار عن تفاصيل الشحن والتوصيل والأسعار المتوفرة لديكم لطلب كميات كبيرة من المنتجات إلى الرياض " * 3
    c5 = sanitize_value(long_msg, max_text_len=120)
    assert len(c5) <= 150
    assert "... [truncated " in c5

    # Case 6: Non-string and None
    assert sanitize_value(None) is None
    assert sanitize_value(42) == 42
    assert sanitize_value(True) is True
    assert sanitize_value(3.14) == 3.14

    # Case 7: Key variations (camelCase, kebab-case, flat, snake_case) and safe keys
    c7 = sanitize_value({
        "apiKey": "super_secret_apiKey_val",
        "API-KEY": "super_secret_API_KEY_val",
        "api-key": "super_secret_kebab_val",
        "apikey": "super_secret_flat_val",
        "accessToken": "secret_access_token_val",
        "clientSecret": "secret_client_secret_val",
        "private-key": "secret_private_key_val",
        "password": "secret_password_val",
        "credentials": "secret_credentials_val",
        "authorization": "secret_auth_val",
        # Non-sensitive keys that MUST NOT be redacted
        "primary_key": 999,
        "token_count": 50,
        "prompt_tokens": 40,
        "completion_tokens": 10,
        "author": "Antigravity",
    })
    assert c7["apiKey"] == "[REDACTED]"
    assert c7["API-KEY"] == "[REDACTED]"
    assert c7["api-key"] == "[REDACTED]"
    assert c7["apikey"] == "[REDACTED]"
    assert c7["accessToken"] == "[REDACTED]"
    assert c7["clientSecret"] == "[REDACTED]"
    assert c7["private-key"] == "[REDACTED]"
    assert c7["password"] == "[REDACTED]"
    assert c7["credentials"] == "[REDACTED]"
    assert c7["authorization"] == "[REDACTED]"
    # Non-sensitive verification
    assert c7["primary_key"] == 999
    assert c7["token_count"] == 50
    assert c7["prompt_tokens"] == 40
    assert c7["completion_tokens"] == 10
    assert c7["author"] == "Antigravity"

    # Case 8: Secret in the middle of text (OpenAI and Google API keys)
    c8_openai = sanitize_value("The system encountered an error connecting to sk-123456789012345678 during initialization.")
    assert "sk-123456789012345678" not in c8_openai
    assert "[REDACTED_API_KEY]" in c8_openai

    # Google Gemini AIza API key in beginning, middle, and end
    google_key = "AIzaSyD_TestGeminiAPIKey123456789"
    c8_google_beg = sanitize_value(f"{google_key} is the active Google API Key.")
    c8_google_mid = sanitize_value(f"Exception during LLM call with key {google_key} timeout occurred.")
    c8_google_end = sanitize_value(f"Failed using Gemini key: {google_key}")

    assert google_key not in c8_google_beg
    assert google_key not in c8_google_mid
    assert google_key not in c8_google_end

    assert c8_google_beg == "[REDACTED_API_KEY] is the active Google API Key."
    assert c8_google_mid == "Exception during LLM call with key [REDACTED_API_KEY] timeout occurred."
    assert c8_google_end == "Failed using Gemini key: [REDACTED_API_KEY]"
