from __future__ import annotations

import uuid
from typing import Any
import pytest
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProvider, AIProviderError
from packages.context.builder import ContextBuilder
from packages.context.retriever import ContextRetriever
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import BusinessBrain, Customer, Knowledge, Memory, Message, User
from packages.models.tenant import Tenant
from packages.services.conversation_service import ConversationService
from packages.services.conversational_agent_engine import (
    ConversationResponseResult,
    ConversationalAgentEngine,
)


class MockAIProvider:
    """Mock implementation of the AIProvider protocol for fast, offline testing."""

    def __init__(
        self,
        responses: list[str] | None = None,
        should_fail: bool = False,
        failure_error: Exception | None = None,
    ):
        self.responses = responses or ["Hello! I am your AI assistant, happy to help."]
        self.should_fail = should_fail
        self.failure_error = failure_error or AIProviderError(
            "Simulated error with key AIzaSyFakeKey1234567890123456789012 and Bearer secret-auth-token"
        )
        self.calls: list[dict[str, Any]] = []
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

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        return {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant_a(db: Session):
    t = Tenant(
        name="Conversational Tenant A",
        slug=f"conv-tenant-a-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(
        name="Conversational Tenant B",
        slug=f"conv-tenant-b-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def customer_a1(db: Session, tenant_a: Tenant):
    c = Customer(
        tenant_id=tenant_a.id,
        name="Alice Customer",
        email=f"alice-{uuid.uuid4().hex[:8]}@example.com",
        customer_type="individual",
        status="active",
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def customer_a2(db: Session, tenant_a: Tenant):
    c = Customer(
        tenant_id=tenant_a.id,
        name="Bob Customer",
        email=f"bob-{uuid.uuid4().hex[:8]}@example.com",
        customer_type="business",
        status="active",
    )
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_customer_message_generates_and_persists_agent_reply(
    db: Session,
    tenant_a: Tenant,
    customer_a1: Customer,
):
    """Test that an incoming customer message triggers the engine, calls AI, and stores a reply."""
    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a1.id,
        subject="Order Inquiry",
    )

    incoming_msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="What is the status of my order #1042?",
        customer_id=customer_a1.id,
    )
    db.commit()

    mock_ai = MockAIProvider(responses=["Your order #1042 is being prepared for shipping."])
    engine = ConversationalAgentEngine(db, ai_provider=mock_ai)

    result = engine.process_incoming_message(
        tenant_id=tenant_a.id,
        message_id=incoming_msg.id,
    )

    assert result.success is True
    assert result.skipped is False
    assert result.reply_message_id is not None
    assert result.reply_content == "Your order #1042 is being prepared for shipping."
    assert len(mock_ai.calls) == 1

    # Verify persisted message in database
    reply_msg = db.get(Message, result.reply_message_id)
    assert reply_msg is not None
    assert reply_msg.sender_type == "agent"
    assert reply_msg.conversation_id == conv.id
    assert reply_msg.tenant_id == tenant_a.id
    assert reply_msg.customer_id == customer_a1.id
    assert reply_msg.content == "Your order #1042 is being prepared for shipping."
    assert reply_msg.metadata_json.get("in_reply_to_message_id") == str(incoming_msg.id)

    # Verify incoming message metadata updated to processed
    db.refresh(incoming_msg)
    assert incoming_msg.metadata_json.get("agent_processed") is True
    assert incoming_msg.metadata_json.get("reply_message_id") == str(result.reply_message_id)


def test_cross_tenant_isolation_prevents_message_access(
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
    customer_a1: Customer,
):
    """Verify that Tenant B cannot access or process a message from Tenant A."""
    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a1.id,
        subject="Confidential Conversation",
    )
    incoming_msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Tenant A secret information",
    )
    db.commit()

    mock_ai = MockAIProvider()
    engine_b = ConversationalAgentEngine(db, ai_provider=mock_ai)

    with pytest.raises(ValueError, match="not found for tenant"):
        engine_b.process_incoming_message(
            tenant_id=tenant_b.id,
            message_id=incoming_msg.id,
        )

    # Verify AI provider was never invoked
    assert len(mock_ai.calls) == 0


def test_customer_isolation_in_context_memories_and_knowledge(
    db: Session,
    tenant_a: Tenant,
    customer_a1: Customer,
    customer_a2: Customer,
):
    """
    Verify customer data isolation:
    Customer A1's private memories and private knowledge MUST NOT appear in Customer A2's context prompt.
    """
    # 1. Add private memory for Customer A1
    mem_a1 = Memory(
        tenant_id=tenant_a.id,
        content="Customer A1 confidential VIP discount: 40% off",
        importance=90,
        confidence=95,
        status="active",
        metadata_json={"customer_id": str(customer_a1.id)},
    )
    # 2. Add private knowledge for Customer A1
    k_a1 = Knowledge(
        tenant_id=tenant_a.id,
        title="Customer A1 SLA Agreement",
        content="Customer A1 SLA tier is Platinum 1-hour response",
        knowledge_type="customer_agreement",
        status="active",
        metadata_json={"customer_id": str(customer_a1.id)},
    )
    db.add_all([mem_a1, k_a1])
    db.commit()

    # 3. Customer A2 starts a conversation and sends a message
    conv_service = ConversationService(db)
    conv_a2 = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a2.id,
        subject="Inquiry by Customer A2",
    )
    msg_a2 = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv_a2.id,
        sender_type="customer",
        content="What discounts do I qualify for?",
        customer_id=customer_a2.id,
    )
    db.commit()

    mock_ai = MockAIProvider()
    engine = ConversationalAgentEngine(db, ai_provider=mock_ai)

    result = engine.process_incoming_message(
        tenant_id=tenant_a.id,
        message_id=msg_a2.id,
    )

    assert result.success is True
    assert len(mock_ai.calls) == 1

    prompt_received = mock_ai.calls[0]["prompt"]
    # Strictly assert that Customer A1's secrets were completely excluded
    assert "Customer A1 confidential VIP discount" not in prompt_received
    assert "40% off" not in prompt_received
    assert "Platinum 1-hour response" not in prompt_received


def test_loop_prevention_skips_agent_and_system_messages(
    db: Session,
    tenant_a: Tenant,
    customer_a1: Customer,
):
    """Verify that messages from 'agent' or 'system' are ignored to prevent infinite response loops."""
    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a1.id,
    )

    # 1. Test agent message
    agent_msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="agent",
        content="I am the assistant answering.",
    )
    db.commit()

    mock_ai = MockAIProvider()
    engine = ConversationalAgentEngine(db, ai_provider=mock_ai)

    res_agent = engine.process_incoming_message(
        tenant_id=tenant_a.id,
        message_id=agent_msg.id,
    )
    assert res_agent.skipped is True
    assert "feedback loops" in res_agent.skip_reason
    assert len(mock_ai.calls) == 0

    # 2. Test system message
    sys_msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="system",
        content="System event: ticket assigned.",
    )
    db.commit()

    res_sys = engine.process_incoming_message(
        tenant_id=tenant_a.id,
        message_id=sys_msg.id,
    )
    assert res_sys.skipped is True
    assert len(mock_ai.calls) == 0


def test_idempotency_prevents_duplicate_replies(
    db: Session,
    tenant_a: Tenant,
    customer_a1: Customer,
):
    """Verify that re-processing the same message does not call the AI provider again or duplicate replies."""
    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a1.id,
    )
    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="First time greeting",
    )
    db.commit()

    mock_ai = MockAIProvider(responses=["First response only."])
    engine = ConversationalAgentEngine(db, ai_provider=mock_ai)

    # First execution
    res1 = engine.process_incoming_message(tenant_id=tenant_a.id, message_id=msg.id)
    assert res1.success is True
    assert res1.skipped is False
    assert len(mock_ai.calls) == 1
    first_reply_id = res1.reply_message_id

    # Second execution (retry or duplicate call)
    res2 = engine.process_incoming_message(tenant_id=tenant_a.id, message_id=msg.id)
    assert res2.success is True
    assert res2.skipped is True
    assert res2.reply_message_id == first_reply_id
    assert len(mock_ai.calls) == 1  # No additional AI call

    # Verify conversation only has 2 messages: incoming + single reply
    all_msgs = conv_service.list_messages(tenant_a.id, conv.id)
    assert len(all_msgs) == 2


def test_ai_provider_failure_handled_safely_without_leaking_secrets(
    db: Session,
    tenant_a: Tenant,
    customer_a1: Customer,
):
    """Verify that AIProvider errors are handled safely, returning failure and sanitizing any leaked keys."""
    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a1.id,
    )
    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Trigger error test",
    )
    db.commit()

    mock_ai = MockAIProvider(
        should_fail=True,
        failure_error=AIProviderError(
            "Service failed with key AIzaSyDfakeKey1234567890123456789012 and Bearer sk-supersecrettoken"
        ),
    )
    engine = ConversationalAgentEngine(db, ai_provider=mock_ai)

    result = engine.process_incoming_message(tenant_id=tenant_a.id, message_id=msg.id)

    assert result.success is False
    assert result.reply_message_id is None
    assert result.error is not None
    # Strictly ensure credentials were redacted
    assert "AIzaSyDfakeKey1234567890123456789012" not in result.error
    assert "[REDACTED_KEY]" in result.error
    assert "sk-supersecrettoken" not in result.error
    assert "[REDACTED_TOKEN]" in result.error


def test_blocked_customer_message_is_skipped(
    db: Session,
    tenant_a: Tenant,
):
    """Verify that messages from a blocked customer are skipped without calling AI."""
    blocked_customer = Customer(
        tenant_id=tenant_a.id,
        name="Blocked Spammer",
        email=f"spammer-{uuid.uuid4().hex[:8]}@example.com",
        customer_type="individual",
        status="blocked",
    )
    db.add(blocked_customer)
    db.flush()

    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=None,
    )
    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        customer_id=blocked_customer.id,
        content="Spam message attempt",
    )
    db.commit()

    mock_ai = MockAIProvider()
    engine = ConversationalAgentEngine(db, ai_provider=mock_ai)

    result = engine.process_incoming_message(tenant_id=tenant_a.id, message_id=msg.id)

    assert result.success is True
    assert result.skipped is True
    assert "blocked" in result.skip_reason
    assert len(mock_ai.calls) == 0


def test_ai_provider_settings_exist_without_revealing_secret_keys():
    """Verify that settings are configured properly without revealing or printing secrets."""
    assert isinstance(settings.ai_provider, str)
    assert settings.ai_provider != ""
    assert isinstance(settings.gemini_model, str)
    assert settings.gemini_model != ""
    assert isinstance(settings.gemini_api_key, str)
    # Never print or assert the content of the key
