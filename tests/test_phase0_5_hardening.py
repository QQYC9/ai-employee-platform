from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.connectors.base import OutboundDeliveryResult
from packages.core.database import SessionLocal
from packages.models.domain import (
    AuditEvent,
    BusinessBrain,
    Channel,
    Conversation,
    Customer,
    Knowledge,
    Message,
    OutboxEvent,
    User,
)
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.outbox_worker import OutboxWorker


class MockAIProvider:
    def __init__(self, reply: str = "مرحبا بك"):
        self.reply = reply
        self.called_count = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.called_count += 1
        return self.reply

    def generate_json(self, *args, **kwargs) -> dict[str, Any]:
        return {}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db: Session) -> Tenant:
    t = Tenant(
        name="Phase 0.5 Hardening Enterprise",
        slug=f"p05-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def owner_user(db: Session, tenant: Tenant) -> User:
    u = User(
        tenant_id=tenant.id,
        name="Al-Munther Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@almunther.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def channel(db: Session, tenant: Tenant) -> Channel:
    ch = Channel(
        tenant_id=tenant.id,
        name="Test WhatsApp Channel",
        channel_type="whatsapp",
        status="active",
        config={"webhook_secret": "secret-key-phase05"},
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


@pytest.fixture
def customer(db: Session, tenant: Tenant) -> Customer:
    c = Customer(
        tenant_id=tenant.id,
        name="Customer Ali",
        phone="+967770000001",
        status="active",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Test 1: Guardrail Gap - Empty Brain Blocks Unsupported Products & Features
# ---------------------------------------------------------------------------
def test_guardrail_blocks_unverified_products_and_features_with_empty_brain(
    db: Session, tenant: Tenant, channel: Channel, customer: Customer
):
    """
    Requirement 2:
    - "برنامج ناظم هو نظام لإدارة المهام والمخزون" with an empty brain -> blocked.
    - "نعم، ناظم يدعم الربط مع الضرائب في السعودية" with no such fact -> blocked.
    - "نسخة تجريبية مجانية لمدة 14 يومًا" with no such fact -> blocked.
    All must be replaced with the Arabic handoff reply, logged in audit, and marked in metadata.
    """
    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=customer.id,
        status="active",
        subject="Product query",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Empty brain
    brain = BusinessBrain(tenant_id=tenant.id, version=1)
    db.add(brain)
    db.commit()

    failing_examples = [
        "برنامج ناظم هو نظام لإدارة المهام والمخزون",
        "نعم، ناظم يدعم الربط مع الضرائب في السعودية",
        "نسخة تجريبية مجانية لمدة 14 يومًا",
    ]

    handoff_text = "سأحوّل استفسارك للموظف المختص وسيرد عليك قريبًا."

    for hallucinated_text in failing_examples:
        inbound_msg = Message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            customer_id=customer.id,
            sender_type="customer",
            content="أخبرني عن البرنامج وميزاته؟",
        )
        db.add(inbound_msg)
        db.commit()
        db.refresh(inbound_msg)

        mock_ai = MockAIProvider(reply=hallucinated_text)
        engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

        result = engine.process_incoming_message(tenant.id, inbound_msg.id)
        assert result.success is True
        assert handoff_text in result.reply_content
        assert hallucinated_text not in result.reply_content

        # Inspect DB reply message metadata
        reply_msg = db.scalar(
            select(Message).where(Message.id == result.reply_message_id)
        )
        assert reply_msg is not None
        assert reply_msg.metadata_json.get("guardrail_blocked") is True
        assert "Unverified" in reply_msg.metadata_json.get("guardrail_reason", "")

    # Audit events recorded for blocks
    audit_events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "agent_reply_blocked_by_guardrail",
        )
    ).all()
    assert len(audit_events) == len(failing_examples)


# ---------------------------------------------------------------------------
# Test 2: Guardrail Allows Same Sentences When Matching Facts Exist
# ---------------------------------------------------------------------------
def test_guardrail_allows_same_sentences_when_matching_facts_exist(
    db: Session, tenant: Tenant, channel: Channel, customer: Customer
):
    """
    Requirement 2: The same sentences are ALLOWED when a matching fact exists in the brain.
    """
    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=customer.id,
        status="active",
        subject="Verified Product query",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Populated brain with products, features, and trial policy
    brain = BusinessBrain(
        tenant_id=tenant.id,
        version=1,
        products={
            "ناظم": {
                "name": "برنامج ناظم",
                "description": "هو نظام لإدارة المهام والمخزون",
                "features": ["الربط مع الضرائب في السعودية"],
            }
        },
        policies={
            "trial": "نسخة تجريبية مجانية لمدة 14 يومًا لجميع المشتركين الجدد"
        },
    )
    db.add(brain)
    db.commit()

    allowed_examples = [
        "برنامج ناظم هو نظام لإدارة المهام والمخزون",
        "نعم، ناظم يدعم الربط مع الضرائب في السعودية",
        "نسخة تجريبية مجانية لمدة 14 يومًا",
    ]

    for verified_text in allowed_examples:
        inbound_msg = Message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            customer_id=customer.id,
            sender_type="customer",
            content="استفسار عن الميزات",
        )
        db.add(inbound_msg)
        db.commit()
        db.refresh(inbound_msg)

        mock_ai = MockAIProvider(reply=verified_text)
        engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

        result = engine.process_incoming_message(tenant.id, inbound_msg.id)
        assert result.success is True
        assert result.reply_content == verified_text

        reply_msg = db.scalar(
            select(Message).where(Message.id == result.reply_message_id)
        )
        assert reply_msg is not None
        assert reply_msg.metadata_json.get("guardrail_blocked") is not True


# ---------------------------------------------------------------------------
# Test 3: Guardrail Applied to Owner Path When Asking About Business
# ---------------------------------------------------------------------------
def test_guardrail_applied_to_owner_path_when_asking_about_business(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    """
    Requirement 3: Apply the same guardrail to the owner path when the owner asks
    about the business itself (identity, products, prices, features).
    """
    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="active",
        subject="Owner dialogue",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Empty brain for tenant
    brain = BusinessBrain(tenant_id=tenant.id, version=1)
    db.add(brain)
    db.commit()

    # Owner asks about a product not recorded in the brain
    owner_msg = Message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="owner",
        content="ما هو برنامج ناظم وما هي مميزاته؟",
    )
    db.add(owner_msg)
    db.commit()
    db.refresh(owner_msg)

    # Mock provider tries to hallucinate an invented description
    mock_ai = MockAIProvider(reply="برنامج ناظم هو نظام لإدارة المهام والمخزون ويدعم الربط مع الضرائب في السعودية")
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    result = engine.process_incoming_message(tenant.id, owner_msg.id)
    assert result.success is True

    # Intercepted by owner guardrail
    assert "غير مسجلة حالياً في قاعدة بيانات المنشأة" in result.reply_content
    assert "إدارة المهام والمخزون" not in result.reply_content

    # Inspect persisted reply
    reply_msg = db.scalar(select(Message).where(Message.id == result.reply_message_id))
    assert reply_msg is not None
    assert reply_msg.metadata_json.get("guardrail_blocked") is True

    # Audit event logged for owner block
    audit_evt = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "owner_reply_blocked_by_guardrail",
        )
    )
    assert audit_evt is not None
    assert "Blocked unverified claim" in audit_evt.description


# ---------------------------------------------------------------------------
# Test 4: Real Message Flow (Webhook Payload -> Inbound -> Outbox -> Engine -> Send)
# ---------------------------------------------------------------------------
def test_real_message_flow_webhook_inbound_outbox_engine_send(
    db: Session, tenant: Tenant, channel: Channel, customer: Customer
):
    """
    Requirement 4: Integration test that goes through the real message flow:
    webhook payload -> process_inbound_message -> outbox -> engine -> send
    with only the AI provider mocked, and prints/verifies stored conversation_id and reply.
    """
    client = TestClient(app)
    secret = channel.config["webhook_secret"]

    # 1. Prepare incoming webhook payload
    ext_id = f"ext-{uuid.uuid4().hex[:8]}"
    payload = {
        "content": "مرحبا، ما هي ساعات العمل لديكم؟",
        "customer_id": str(customer.id),
        "external_id": ext_id,
        "metadata_json": {
            "sender_id": "+967770000001",
            "channel_type": "whatsapp",
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # 2. Step 1: Webhook payload arrives via HTTP
    resp = client.post(
        f"/api/v1/webhooks/channels/{channel.id}",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={sig}",
        },
    )
    assert resp.status_code in (200, 202), resp.text
    data = resp.json()
    assert data["status"] == "accepted"
    stored_conv_id = uuid.UUID(data["conversation_id"])
    stored_msg_id = uuid.UUID(data["message_id"])
    stored_outbox_id = uuid.UUID(data["outbox_event_id"])

    # Verify atomic DB persistence of incoming message and outbox event
    inbound_msg = db.scalar(select(Message).where(Message.id == stored_msg_id))
    assert inbound_msg is not None
    assert inbound_msg.content == "مرحبا، ما هي ساعات العمل لديكم؟"
    assert inbound_msg.conversation_id == stored_conv_id

    outbox_evt = db.scalar(select(OutboxEvent).where(OutboxEvent.id == stored_outbox_id))
    assert outbox_evt is not None
    assert outbox_evt.event_type == "process_incoming_message"
    assert outbox_evt.status == "pending"

    # 3. Step 2 & 3: OutboxWorker claims and executes the event
    expected_reply_text = "أهلاً بك! ساعات العمل لدينا من السبت إلى الخميس من 9 صباحاً حتى 6 مساءً."
    mock_ai = MockAIProvider(reply=expected_reply_text)

    # Set up brain with operations working hours so guardrail allows it
    brain = BusinessBrain(
        tenant_id=tenant.id,
        version=1,
        operations={"working_hours": "من السبت إلى الخميس 9 صباحاً حتى 6 مساءً"},
    )
    db.add(brain)
    db.commit()

    # Mock channel delivery service for outbound connector dispatch
    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="whatsapp",
        recipient_id="+967770000001",
        status="sent",
        external_message_id="wa-msg-12345",
    )

    worker = OutboxWorker(
        session_factory=SessionLocal,
        ai_provider=mock_ai,
        channel_service=mock_channel_svc,
        worker_id="test-p05-worker",
    )

    # Process the single outbox event
    success = worker.process_event(outbox_evt.id)
    assert success is True

    # 4. Verify completed outbox event
    db.expire_all()
    outbox_completed = db.scalar(select(OutboxEvent).where(OutboxEvent.id == stored_outbox_id))
    assert outbox_completed.status == "completed"

    # 5. Verify stored reply in PostgreSQL
    reply_msg = db.scalar(
        select(Message).where(
            Message.conversation_id == stored_conv_id,
            Message.sender_type == "agent",
        )
    )
    assert reply_msg is not None
    assert reply_msg.content == expected_reply_text
    assert reply_msg.metadata_json.get("in_reply_to_message_id") == str(stored_msg_id)

    # 6. Verify channel send was called with the reply
    mock_channel_svc.send_channel_message.assert_called_once()
    send_args = mock_channel_svc.send_channel_message.call_args[1]
    assert send_args["content"] == expected_reply_text

    # Show stored conversation_id and reply as requested
    import sys
    output_lines = [
        "",
        "[REAL MESSAGE FLOW VERIFIED]",
        f"  Conversation ID : {stored_conv_id}",
        f"  Inbound Message : {inbound_msg.content} (ID: {stored_msg_id})",
        f"  Persisted Reply : {reply_msg.content} (ID: {reply_msg.id})",
        f"  Outbox Event ID : {outbox_completed.id} (Status: {outbox_completed.status})",
    ]
    try:
        print("\n".join(output_lines))
    except UnicodeEncodeError:
        # Fallback for Windows consoles lacking UTF-8 encoding
        safe_output = "\n".join(output_lines).encode("ascii", errors="backslashreplace").decode("ascii")
        print(safe_output)
