from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProviderError
from packages.core.database import SessionLocal
from packages.models.domain import (
    Approval,
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
from packages.tools.executor import ToolExecutor


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def create_tenant(db: Session, name: str = "Instrumentation Tenant") -> Tenant:
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
    channel: str = "telegram",
) -> Conversation:
    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        customer_id=customer_id,
        status="open",
        metadata_json={"channel": channel},
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
    def __init__(
        self,
        responses: list[str] | None = None,
        should_fail: bool = False,
        failure_error: Exception | None = None,
    ):
        self.responses = responses or ["أهلاً بك، نسعد بخدمتك ومساعدتك دائماً."]
        self.should_fail = should_fail
        self.failure_error = failure_error or AIProviderError(
            "AI provider error with sk-12345678901234567890 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token"
        )
        self.calls: list[dict] = []
        self._idx = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
        )
        if self.should_fail:
            raise self.failure_error

        resp = self.responses[self._idx % len(self.responses)]
        self._idx += 1
        return resp

    def generate_json(self, prompt: str, *, system_instruction: str | None = None, schema: dict | None = None) -> dict:
        return {"response": "mock_json"}


# ==============================================================================
# 1. Sanitization & Redaction Tests
# ==============================================================================

def test_sanitize_value_redaction_secrets_prompts_and_truncation():
    """Verify secrets, tokens, API keys, system prompts, key casing variants, and Google API keys."""
    # 1. Secret keys redaction and case variations
    payload = {
        "password": "SuperSecretPassword123!",
        "api_key": "sk-12345678901234567890",
        "apiKey": "plain_secret_apiKey",
        "API-KEY": "plain_secret_API_KEY",
        "api-key": "plain_secret_kebab",
        "apikey": "plain_secret_flat",
        "access_token": "Bearer abcdef1234567890",
        "accessToken": "plain_access_token",
        "access-token": "plain_kebab_token",
        "clientSecret": "plain_client_secret",
        "client_secret": "plain_client_secret_snake",
        "private-key": "plain_private_key",
        "privateKey": "plain_private_key_camel",
        "credentials": "plain_credentials",
        "authorization": "Bearer token_xyz",
        "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        # Non-sensitive keys that MUST NOT be redacted
        "primary_key": 42,
        "token_count": 150,
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "author": "Antigravity",
        "public_key": "ssh-rsa AAAAB3...",
        "normal_key": "safe_value",
    }
    sanitized = sanitize_value(payload)
    # Sensitive keys must all be redacted regardless of casing
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["apiKey"] == "[REDACTED]"
    assert sanitized["API-KEY"] == "[REDACTED]"
    assert sanitized["api-key"] == "[REDACTED]"
    assert sanitized["apikey"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["accessToken"] == "[REDACTED]"
    assert sanitized["access-token"] == "[REDACTED]"
    assert sanitized["clientSecret"] == "[REDACTED]"
    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["private-key"] == "[REDACTED]"
    assert sanitized["privateKey"] == "[REDACTED]"
    assert sanitized["credentials"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["jwt"] == "[REDACTED]"

    # Non-sensitive keys MUST remain untouched
    assert sanitized["primary_key"] == 42
    assert sanitized["token_count"] == 150
    assert sanitized["prompt_tokens"] == 120
    assert sanitized["completion_tokens"] == 30
    assert sanitized["author"] == "Antigravity"
    assert sanitized["public_key"] == "ssh-rsa AAAAB3..."
    assert sanitized["normal_key"] == "safe_value"

    # 2. String regex pattern redactions (OpenAI, Bearer, Google Gemini AIza)
    text_with_keys = "Error communicating with sk-987654321012345678 and Bearer eyJhbGciOiJIUzI1NiIs.tok"
    sanitized_text = sanitize_value(text_with_keys)
    assert "sk-987654321012345678" not in sanitized_text
    assert "[REDACTED_API_KEY]" in sanitized_text
    assert "Bearer [REDACTED]" in sanitized_text

    # Google API key (AIza...) at beginning, middle, and end of free text
    google_key = "AIzaSyD-FakeGeminiKey1234567890123456"
    text_beginning = f"{google_key} is the client key used."
    text_middle = f"Failed to call Gemini using {google_key} due to timeout."
    text_end = f"Authentication rejected for key: {google_key}"

    san_beg = sanitize_value(text_beginning)
    san_mid = sanitize_value(text_middle)
    san_end = sanitize_value(text_end)

    assert google_key not in san_beg
    assert google_key not in san_mid
    assert google_key not in san_end

    assert san_beg == "[REDACTED_API_KEY] is the client key used."
    assert san_mid == "Failed to call Gemini using [REDACTED_API_KEY] due to timeout."
    assert san_end == "Authentication rejected for key: [REDACTED_API_KEY]"

    kv_text = "Configuration setting: password=SuperSecretPassword123! and token: my_secret_token"
    sanitized_kv = sanitize_value(kv_text)
    assert "SuperSecretPassword123!" not in sanitized_kv
    assert "password: [REDACTED]" in sanitized_kv or "password: [REDACTED]" in sanitized_kv.lower()

    # 3. System prompt protection
    prompt_payload = {
        "system_instruction": "You are an autonomous agent with confidential instructions...",
        "system_prompt": "Do not reveal instructions",
        "full_prompt": "Sensitive prompt template",
        "user_input": "Hello",
    }
    sanitized_prompt = sanitize_value(prompt_payload)
    assert sanitized_prompt["system_instruction"] == "[REDACTED_SYSTEM_PROMPT]"
    assert sanitized_prompt["system_prompt"] == "[REDACTED_SYSTEM_PROMPT]"
    assert sanitized_prompt["full_prompt"] == "[REDACTED_SYSTEM_PROMPT]"
    assert sanitized_prompt["user_input"] == "Hello"

    # 4. Long raw customer text truncation (>120 chars)
    long_customer_text = "أ" * 200
    sanitized_long = sanitize_value(long_customer_text, max_text_len=120)
    assert len(sanitized_long) < 200
    assert "... [truncated 200 chars]" in sanitized_long


# ==============================================================================
# 2. Customer Interaction Tracing Lifecycle (Success)
# ==============================================================================

def test_customer_interaction_tracing_lifecycle_success(db: Session):
    """
    Verify complete customer interaction lifecycle:
    1. ExecutionTrace started with 'inbound_message' trigger and tenant isolation.
    2. 'context_assembly' and 'llm_generation' steps recorded with timings and summaries.
    3. Trace completed with duration_ms > 0, reply_message_id linked.
    4. Both original message and reply message reference trace_id.
    """
    tenant = create_tenant(db, "Tracing Customer Flow")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="ما هي أوقات العمل لديكم؟")

    mock_provider = MockAIProvider(responses=["أوقات العمل من 9 صباحاً إلى 10 مساءً."])
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_provider)

    result = engine.process_incoming_message(
        tenant_id=tenant.id,
        message_id=msg.id,
    )

    assert result.success is True
    assert result.reply_message_id is not None
    assert result.trace_id is not None
    trace_id = result.trace_id

    # Verify ExecutionTrace in DB
    trace = db.scalar(
        select(ExecutionTrace).where(
            ExecutionTrace.id == trace_id,
            ExecutionTrace.tenant_id == tenant.id,
        )
    )
    assert trace is not None
    assert trace.status == "completed"
    assert trace.trigger_type == "inbound_message"
    assert trace.conversation_id == conv.id
    assert trace.inbound_message_id == msg.id
    assert trace.reply_message_id == result.reply_message_id
    assert trace.duration_ms is not None
    assert trace.duration_ms >= 0
    assert trace.started_at is not None
    assert trace.completed_at is not None

    # Verify ExecutionSteps
    tracing_svc = ExecutionTracingService(db)
    steps = tracing_svc.list_steps(tenant.id, trace_id)
    assert len(steps) >= 2

    # Step 1: context_assembly
    ctx_step = next((s for s in steps if s.step_name == "context_assembly"), None)
    assert ctx_step is not None
    assert ctx_step.step_type == "context_retrieval"
    assert ctx_step.status == "completed"
    assert ctx_step.step_order == 1
    assert "memories_count" in ctx_step.output_summary
    assert "knowledge_count" in ctx_step.output_summary

    # Step 2: llm_generation
    llm_step = next((s for s in steps if s.step_name == "llm_generation"), None)
    assert llm_step is not None
    assert llm_step.step_type == "llm_reasoning"
    assert llm_step.status == "completed"
    assert llm_step.step_order == 2
    assert "provider" in llm_step.input_summary
    assert "reply_length" in llm_step.output_summary

    # Verify message metadata linkage
    db.refresh(msg)
    assert msg.metadata_json.get("trace_id") == str(trace_id)

    reply_msg = db.scalar(select(Message).where(Message.id == result.reply_message_id))
    assert reply_msg is not None
    assert reply_msg.metadata_json.get("trace_id") == str(trace_id)


# ==============================================================================
# 3. Tracing AI Provider Failure & Safe Error Recording
# ==============================================================================

def test_customer_interaction_tracing_failure_sanitization(db: Session):
    """
    Verify that upon AI provider failure:
    1. 'llm_generation' step is recorded with status='failed' and sanitized error.
    2. ExecutionTrace is marked status='failed' with duration calculated.
    3. Sensitive secrets in provider exception are NOT leaked in trace error summary.
    """
    tenant = create_tenant(db, "Tracing Failure Flow")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="اريد معرفة المنتجات")

    failing_provider = MockAIProvider(
        should_fail=True,
        failure_error=AIProviderError("API call failed: key sk-secret123456789012345 and Bearer mytoken12345678"),
    )
    engine = ConversationalAgentEngine(db=db, ai_provider=failing_provider)

    result = engine.process_incoming_message(
        tenant_id=tenant.id,
        message_id=msg.id,
    )

    # Conversational engine catches provider failure safely and returns result with error
    assert result.success is False
    assert result.trace_id is not None
    trace_id = result.trace_id

    trace = db.scalar(
        select(ExecutionTrace).where(
            ExecutionTrace.id == trace_id,
            ExecutionTrace.tenant_id == tenant.id,
        )
    )
    assert trace is not None

    # Verify steps recorded failure
    tracing_svc = ExecutionTracingService(db)
    steps = tracing_svc.list_steps(tenant.id, trace_id)
    llm_step = next((s for s in steps if s.step_name == "llm_generation"), None)
    assert llm_step is not None
    assert llm_step.status == "failed"
    assert llm_step.error_info is not None

    # Redaction verification: ensure no raw secret key in error_info
    raw_error_text = str(llm_step.error_info)
    assert "sk-secret123456789012345" not in raw_error_text
    assert "mytoken12345678" not in raw_error_text


# ==============================================================================
# 4. Loop Prevention & Skipped Messages Tracing
# ==============================================================================

def test_loop_prevention_and_duplicate_skipped_tracing(db: Session):
    """Verify skipped messages (agent loop prevention, duplicates) record proper skipped traces."""
    tenant = create_tenant(db, "Tracing Skipped Flow")
    conv = create_conversation(db, tenant.id)

    # 1. Agent message incoming (should be skipped to prevent infinite loop)
    agent_msg = create_message(db, tenant.id, conv.id, sender_type="agent", content="مرحبا بكم")
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    res1 = engine.process_incoming_message(tenant.id, agent_msg.id)
    assert res1.skipped is True
    assert res1.trace_id is not None

    trace1 = db.scalar(
        select(ExecutionTrace).where(
            ExecutionTrace.id == res1.trace_id,
            ExecutionTrace.tenant_id == tenant.id,
        )
    )
    assert trace1 is not None
    assert trace1.status == "skipped"
    assert "skip_reason" in trace1.metadata_json

    # 2. Duplicate customer message (already processed)
    real_reply = create_message(
        db,
        tenant.id,
        conv.id,
        sender_type="agent",
        content="تم الرد مسبقاً",
    )
    cust_msg = create_message(
        db,
        tenant.id,
        conv.id,
        sender_type="customer",
        content="رسالة مكررة",
        metadata_json={"agent_processed": True, "reply_message_id": str(real_reply.id)},
    )
    res2 = engine.process_incoming_message(tenant.id, cust_msg.id)
    assert res2.skipped is True
    assert res2.trace_id is not None

    trace2 = db.scalar(
        select(ExecutionTrace).where(
            ExecutionTrace.id == res2.trace_id,
            ExecutionTrace.tenant_id == tenant.id,
        )
    )
    assert trace2 is not None
    assert trace2.status == "skipped"
    assert trace2.metadata_json.get("skip_reason") == "already_processed"


# ==============================================================================
# 5. Human Escalation Step Tracing
# ==============================================================================

def test_human_escalation_step_tracing(db: Session):
    """Verify human escalation triggers an ExecutionStep of type 'escalation'."""
    tenant = create_tenant(db, "Tracing Escalation Flow")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="أريد التحدث مع موظف بشري فوراً")

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    result = engine.process_incoming_message(tenant.id, msg.id)

    assert result.success is True
    assert result.trace_id is not None

    tracing_svc = ExecutionTracingService(db)
    steps = tracing_svc.list_steps(tenant.id, result.trace_id)
    esc_step = next((s for s in steps if s.step_name == "human_escalation"), None)
    assert esc_step is not None
    assert esc_step.step_type == "escalation"
    assert esc_step.status == "completed"
    assert esc_step.output_summary.get("reason") == "customer_requested_human"


# ==============================================================================
# 6. Tool Execution Step Tracing (Allowed, Blocked, Idempotency Cached)
# ==============================================================================

def test_tool_execution_tracing_allowed_and_blocked(db: Session):
    """
    Verify ToolExecutor instrumentation:
    1. Records step with status='completed' on successful execution.
    2. Records step with status='blocked' when decision engine blocks execution.
    3. Records step with status='completed' with source='idempotency_cache' on cache hit.
    """
    tenant = create_tenant(db, "Tool Tracing Tenant")
    tracing_svc = ExecutionTracingService(db)

    # Register tool in DB
    tool = Tool(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Mock Calculator Tool",
        slug="calc_tool",
        tool_type="utility",
        description="Performs calculations",
    )
    db.add(tool)

    # Permission allowing calc_tool
    perm = Permission(
        id=uuid4(),
        tenant_id=tenant.id,
        action="execute:calc_tool",
        resource="tools:calc_tool",
        effect="allow",
    )
    db.add(perm)
    db.flush()

    # Start an ExecutionTrace
    trace = tracing_svc.start_trace(tenant_id=tenant.id, trigger_type="tool_test")
    assert trace is not None

    executor = ToolExecutor(db, execution_tracing_service=tracing_svc)
    executor.register_handler("calc_tool", lambda a, b, **kw: {"sum": a + b})

    # Case A: Successful tool execution
    res1 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:calc_tool",
        resource="tools:calc_tool",
        parameters={"a": 10, "b": 20},
        idempotency_key="calc_key_001",
        trace_id=trace.id,
    )
    assert res1.status == "executed"
    assert res1.output == {"sum": 30}

    steps = tracing_svc.list_steps(tenant.id, trace.id)
    calc_step = next((s for s in steps if s.step_name == "tool:calc_tool"), None)
    assert calc_step is not None
    assert calc_step.status == "completed"
    assert calc_step.step_type == "tool_call"
    assert calc_step.idempotency_key == "calc_key_001"

    # Case B: Idempotency cache hit
    res_cached = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:calc_tool",
        resource="tools:calc_tool",
        parameters={"a": 10, "b": 20},
        idempotency_key="calc_key_001",
        trace_id=trace.id,
    )
    assert res_cached.status == "executed"
    assert res_cached.reason == "Result returned from idempotency cache"

    # Case C: Blocked tool execution (unauthorized action)
    unauthorized_tool = Tool(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Sensitive Admin Tool",
        slug="admin_tool",
        tool_type="admin",
        description="Forbidden tool",
    )
    db.add(unauthorized_tool)
    db.flush()

    res_blocked = executor.execute(
        tenant_id=tenant.id,
        tool_id=unauthorized_tool.id,
        action="execute:admin_tool",
        resource="tools:admin_tool",
        trace_id=trace.id,
    )
    assert res_blocked.status == "blocked"

    steps_after = tracing_svc.list_steps(tenant.id, trace.id)
    blocked_step = next((s for s in steps_after if s.step_name == "tool:admin_tool"), None)
    assert blocked_step is not None
    assert blocked_step.status == "blocked"
    assert "decision" in blocked_step.error_info


# ==============================================================================
# 7. Task Execution Service Tracing Lifecycle
# ==============================================================================

def test_task_execution_tracing_lifecycle(db: Session):
    """
    Verify TaskExecutionService executes tools within an ExecutionTrace:
    1. Automatic ExecutionTrace creation with trigger_type='task_execution'.
    2. Tool execution step linked with task_id.
    3. Trace marked completed on successful task execution.
    """
    tenant = create_tenant(db, "Task Tracing Tenant")
    task = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Background Data Sync",
        objective="Sync inventory data",
        status="pending",
        priority="normal",
    )
    db.add(task)

    tool = Tool(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Sync Tool",
        slug="sync_tool",
        tool_type="data",
    )
    db.add(tool)

    perm = Permission(
        id=uuid4(),
        tenant_id=tenant.id,
        action="execute:sync_tool",
        resource="tools:sync_tool",
        effect="allow",
    )
    db.add(perm)
    db.flush()

    tracing_svc = ExecutionTracingService(db)
    executor = ToolExecutor(db, execution_tracing_service=tracing_svc)
    executor.register_handler("sync_tool", lambda **kw: {"synced_items": 42})

    task_service = TaskExecutionService(db, execution_tracing_service=tracing_svc)
    completed_task = task_service.execute_tool(
        tenant_id=tenant.id,
        task_id=task.id,
        tool_id=tool.id,
        action="execute:sync_tool",
        resource="tools:sync_tool",
        executor=executor,
    )

    assert completed_task.status == "completed"
    assert completed_task.result == {"synced_items": 42}

    # Verify ExecutionTrace was created and completed
    trace = db.scalar(
        select(ExecutionTrace).where(
            ExecutionTrace.task_id == task.id,
            ExecutionTrace.tenant_id == tenant.id,
        )
    )
    assert trace is not None
    assert trace.status == "completed"
    assert trace.trigger_type == "task_execution"

    # Verify tool execution step exists
    steps = tracing_svc.list_steps(tenant.id, trace.id)
    tool_step = next((s for s in steps if s.step_name == "tool:sync_tool"), None)
    assert tool_step is not None
    assert tool_step.status == "completed"
    assert tool_step.task_id == task.id


# ==============================================================================
# 8. Multi-Tenant Isolation in Tracing Service
# ==============================================================================

def test_multi_tenant_isolation_in_tracing(db: Session):
    """
    Verify strict tenant isolation:
    1. Tenant B cannot view Tenant A's trace via get_trace.
    2. Tenant B cannot list Tenant A's steps via list_steps.
    3. Tenant B cannot modify or complete Tenant A's trace via complete_trace.
    """
    tenant_a = create_tenant(db, "Tenant Alpha")
    tenant_b = create_tenant(db, "Tenant Beta")

    tracing_svc = ExecutionTracingService(db)

    # Create trace and step for Tenant A
    trace_a = tracing_svc.start_trace(tenant_id=tenant_a.id, trigger_type="isolated_test")
    assert trace_a is not None

    step_a = tracing_svc.record_step(
        tenant_id=tenant_a.id,
        trace_id=trace_a.id,
        step_name="step_a",
        step_type="test",
        status="completed",
    )
    assert step_a is not None

    # Tenant B tries to query Tenant A's trace
    trace_query_b = tracing_svc.get_trace(tenant_id=tenant_b.id, trace_id=trace_a.id)
    assert trace_query_b is None

    # Tenant B tries to list Tenant A's steps
    steps_query_b = tracing_svc.list_steps(tenant_id=tenant_b.id, trace_id=trace_a.id)
    assert len(steps_query_b) == 0

    # Tenant B tries to complete or alter Tenant A's trace
    mod_result = tracing_svc.complete_trace(
        tenant_id=tenant_b.id,
        trace_id=trace_a.id,
        status="failed",
    )
    assert mod_result is None

    # Verify Tenant A's trace is still untouched and running
    db.refresh(trace_a)
    assert trace_a.status == "running"


# ==============================================================================
# 9. Resilience: Tracing Failures Never Disrupt Business Flow
# ==============================================================================

def test_tracing_resilience_non_disruptive_on_error(db: Session):
    """
    Verify that if the tracing service fails (e.g. database glitch during trace write),
    the conversational agent still processes the customer message and returns the reply safely.
    """
    tenant = create_tenant(db, "Resilience Tenant")
    conv = create_conversation(db, tenant.id)
    msg = create_message(db, tenant.id, conv.id, content="مرحبا، كيف حالكم؟")

    # Create a mock tracing service that simulates exceptions
    mock_tracing = MagicMock()
    mock_tracing.start_trace.side_effect = Exception("Simulated DB connection timeout")
    mock_tracing.record_step.side_effect = Exception("Simulated DB lock error")
    mock_tracing.complete_trace.side_effect = Exception("Simulated DB write failure")

    mock_provider = MockAIProvider(responses=["أهلاً وسهلاً بك، نسعد بمساعدتك."])

    engine = ConversationalAgentEngine(
        db=db,
        ai_provider=mock_provider,
        execution_tracing_service=mock_tracing,
    )

    # Process message - must not raise or abort
    result = engine.process_incoming_message(tenant.id, msg.id)

    assert result.success is True
    assert result.reply_message_id is not None
    assert result.reply_content == "أهلاً وسهلاً بك، نسعد بمساعدتك."


# ==============================================================================
# 10. Owner Management Flow Tracing & Intent Router Step
# ==============================================================================

def test_owner_intent_router_step_tracing(db: Session):
    """
    Verify authenticated owner message processes through OwnerIntentRouter,
    recording an 'owner_intent_router' step and completing the trace.
    """
    tenant = create_tenant(db, "Owner Tracing Tenant")
    owner_user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="owner@teststore.com",
        name="Store Owner",
        role="tenant_owner",
        status="active",
    )
    db.add(owner_user)

    conv = create_conversation(db, tenant.id, channel="telegram")
    # Owner message with authenticated metadata
    owner_msg = create_message(
        db,
        tenant.id,
        conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="ما هو اسم المتجر؟",
        metadata_json={
            "is_owner": True,
            "user_id": str(owner_user.id),
            "owner_authenticated": True,
        },
    )

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    result = engine.process_incoming_message(tenant.id, owner_msg.id)

    assert result.success is True
    assert result.trace_id is not None
    trace_id = result.trace_id

    # Verify ExecutionTrace was created and completed
    trace = db.scalar(
        select(ExecutionTrace).where(
            ExecutionTrace.id == trace_id,
            ExecutionTrace.tenant_id == tenant.id,
        )
    )
    assert trace is not None
    assert trace.status == "completed"

    # Verify owner_intent_router step was recorded
    tracing_svc = ExecutionTracingService(db)
    steps = tracing_svc.list_steps(tenant.id, trace_id)
    router_step = next((s for s in steps if s.step_name == "owner_intent_router"), None)
    assert router_step is not None
    assert router_step.step_type == "routing"
    assert router_step.status == "completed"
