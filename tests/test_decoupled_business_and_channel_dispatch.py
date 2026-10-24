from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProviderError
from packages.connectors.base import InboundMessage, OutboundDeliveryResult
from packages.core.database import SessionLocal
from packages.models.domain import (
    BusinessBrain,
    Channel,
    Conversation,
    Customer,
    Message,
    OutboxEvent,
    User,
)
from packages.models.tenant import Tenant
from packages.services.business_brain_service import BusinessBrainService
from packages.services.channel_service import ChannelService
from packages.services.outbox_service import OutboxService
from packages.services.outbox_worker import OutboxWorker


# ===========================================================================
# Fixtures
# ===========================================================================

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
        name="Enterprise Alpha",
        slug=f"ent-a-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner Alpha",
        email=f"owner-{uuid.uuid4().hex[:6]}@alpha.local",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "متجر ألفا للعسل"},
        brand={"tone": "مهني ومساعد"},
        products={},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(
        name="Enterprise Beta",
        slug=f"ent-b-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner Beta",
        email=f"owner-{uuid.uuid4().hex[:6]}@beta.local",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "متجر بيتا للعود"},
        brand={"tone": "فاخر"},
        products={},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def telegram_channel_a(db: Session, tenant_a: Tenant):
    svc = ChannelService(db)
    config = {
        "bot_token": "123456789:ABC_ALPHA_TOKEN",
        "secret_token": "secret_alpha_token",
        "owner_telegram_id": "111222333",
        "owner_identifiers": ["111222333"],
    }
    channel = svc.register_channel(
        tenant_id=tenant_a.id,
        name="Telegram Alpha Channel",
        channel_type="telegram",
        provider="telegram",
        config=config,
    )
    db.commit()
    return channel


@pytest.fixture
def telegram_channel_b(db: Session, tenant_b: Tenant):
    svc = ChannelService(db)
    config = {
        "bot_token": "987654321:XYZ_BETA_TOKEN",
        "secret_token": "secret_beta_token",
        "owner_telegram_id": "444555666",
        "owner_identifiers": ["444555666"],
    }
    channel = svc.register_channel(
        tenant_id=tenant_b.id,
        name="Telegram Beta Channel",
        channel_type="telegram",
        provider="telegram",
        config=config,
    )
    db.commit()
    return channel


# ===========================================================================
# 1. Success of business operation execution, persistence, and reply delivery
# ===========================================================================

def test_1_successful_business_operation_and_reply_delivery(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 1:
    Owner sends command to add a product via Telegram.
    Business operation succeeds and is saved, reply is generated,
    and Telegram delivery succeeds.
    """
    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel_a.id,
        tenant_id=tenant_a.id,
        sender_id="111222333",  # Owner
        sender_name="Owner Alpha",
        external_message_id=f"tg.add.{uuid.uuid4().hex[:8]}",
        content="أضف منتج: عسل سدر فاخر بسعر 180 ريال",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    event = db.scalar(select(OutboxEvent).where(OutboxEvent.message_id == msg.id))
    assert event is not None
    assert event.status == "pending"

    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="111222333",
        external_message_id="tg.out.101",
        status="sent",
    )

    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )
    success = worker.process_event(event.id)
    assert success is True

    # DB Verification: Business Brain was updated with the product
    brain = BusinessBrainService(db).get_brain(tenant_a.id)
    assert brain is not None
    assert "عسل_سدر_فاخر" in (brain.products or {})
    assert brain.products["عسل_سدر_فاخر"]["price"] == 180.0

    # DB Verification: Reply Message exists with delivery confirmation
    reply_msg = db.scalar(
        select(Message).where(
            Message.conversation_id == msg.conversation_id,
            Message.sender_type == "agent",
        )
    )
    assert reply_msg is not None
    assert "عسل سدر فاخر" in reply_msg.content
    assert (reply_msg.metadata_json or {}).get("delivery_status") == "delivered"
    assert (reply_msg.metadata_json or {}).get("external_message_id") == "tg.out.101"

    # DB Verification: Outbox Event is marked completed
    db.refresh(event)
    assert event.status == "completed"


# ===========================================================================
# 2. Business operation succeeds, but Telegram delivery fails (Network Glitch)
# ===========================================================================

def test_2_business_operation_persists_when_telegram_delivery_fails(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 2:
    Owner adds a product, but Telegram delivery encounters a 503 error.
    CRITICAL REQUIREMENT:
    The business operation MUST NOT be rolled back!
    The product MUST remain committed in BusinessBrain.
    The reply message must be saved with delivery_status="pending".
    The outbox event must be scheduled for retry with backoff.
    """
    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel_a.id,
        tenant_id=tenant_a.id,
        sender_id="111222333",
        sender_name="Owner Alpha",
        external_message_id=f"tg.add2.{uuid.uuid4().hex[:8]}",
        content="أضف منتج: عسل جبلي حضرمي بسعر 220 ريال",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    event = db.scalar(select(OutboxEvent).where(OutboxEvent.message_id == msg.id))

    # Mock Telegram network failure
    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=False,
        channel_type="telegram",
        recipient_id="111222333",
        status="failed",
        error="Telegram 503 Service Unavailable / Network Timeout",
    )

    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )
    count = worker.run_once()
    assert count == 0

    # CRITICAL CHECK: Business Brain MUST have the new product committed!
    db.expire_all()
    brain = BusinessBrainService(db).get_brain(tenant_a.id)
    assert "عسل_جبلي_حضرمي" in (brain.products or {})
    assert brain.products["عسل_جبلي_حضرمي"]["price"] == 220.0

    # CRITICAL CHECK: Reply message MUST be committed in database
    reply_msg = db.scalar(
        select(Message).where(
            Message.conversation_id == msg.conversation_id,
            Message.sender_type == "agent",
        )
    )
    assert reply_msg is not None
    assert "عسل جبلي حضرمي" in reply_msg.content
    assert (reply_msg.metadata_json or {}).get("delivery_status") != "delivered"

    # CRITICAL CHECK: Outbox event status is pending for retry
    db.refresh(event)
    assert event.status == "pending"
    assert event.attempt_count == 1
    assert "Telegram 503" in (event.error_message or "")


# ===========================================================================
# 3. Retrying reply delivery does NOT re-execute the business operation
# ===========================================================================

def test_3_retry_delivers_reply_without_reexecuting_business_operation(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 3:
    Continuing from Scenario 2:
    When the worker retries the failed event, Telegram is now online.
    CRITICAL REQUIREMENT:
    The worker must ONLY deliver the reply.
    It MUST NOT re-run ConversationalAgentEngine or re-add the product!
    """
    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel_a.id,
        tenant_id=tenant_a.id,
        sender_id="111222333",
        external_message_id=f"tg.retry.{uuid.uuid4().hex[:8]}",
        content="أضف منتج: عسل الطلح الملكي بسعر 250 ريال",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    event = db.scalar(select(OutboxEvent).where(OutboxEvent.message_id == msg.id))

    # Attempt 1: Delivery fails
    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=False,
        channel_type="telegram",
        recipient_id="111222333",
        status="failed",
        error="Temporary connection timeout",
    )
    worker1 = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )
    res1 = worker1.process_event(event.id)
    assert res1 is False

    # Get the committed reply message
    db.expire_all()
    first_reply = db.scalar(
        select(Message).where(
            Message.conversation_id == msg.conversation_id,
            Message.sender_type == "agent",
        )
    )
    assert first_reply is not None
    first_reply_id = first_reply.id
    first_content = first_reply.content

    # Attempt 2: Worker retries after backoff, Telegram succeeds
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="111222333",
        external_message_id="tg.out.retry.202",
        status="sent",
    )

    worker2 = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )
    res2 = worker2.process_event(event.id)
    assert res2 is True

    # VERIFY: Exactly 1 reply message exists in the conversation (NO duplicate reply created!)
    db.expire_all()
    all_replies = db.scalars(
        select(Message).where(
            Message.conversation_id == msg.conversation_id,
            Message.sender_type == "agent",
        )
    ).all()
    assert len(all_replies) == 1
    assert all_replies[0].id == first_reply_id
    assert all_replies[0].content == first_content
    assert (all_replies[0].metadata_json or {}).get("delivery_status") == "delivered"

    # VERIFY: Outbox event is now completed
    db.refresh(event)
    assert event.status == "completed"


# ===========================================================================
# 4. Redelivery of outbox event after worker crash / stale lock recovery
# ===========================================================================

def test_4_stale_event_recovered_and_delivered_without_duplication(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 4:
    Worker crashes mid-flight after committing the business operation.
    Event has a stale lock.
    Worker recovers stale events and safely finishes delivery without re-executing business logic.
    """
    conv = Conversation(
        tenant_id=tenant_a.id,
        channel_id=telegram_channel_a.id,
        status="open",
        subject="Owner Chat",
    )
    db.add(conv)
    db.flush()

    orig_msg = Message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="user",
        content="أضف منتج: غذاء ملكات النحل بسعر 300 ريال",
        metadata_json={"is_owner": True, "agent_processed": True},
    )
    db.add(orig_msg)
    db.flush()

    reply_msg = Message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="agent",
        content="✅ تم حفظ المنتج غذاء ملكات النحل بسعر 300 ريال",
        metadata_json={
            "in_reply_to_message_id": str(orig_msg.id),
            "delivery_status": "pending",
        },
    )
    db.add(reply_msg)
    db.flush()

    # Create stale outbox event simulating crashed worker 10 minutes ago
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    event = OutboxEvent(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        message_id=orig_msg.id,
        event_type="process_incoming_message",
        idempotency_key=f"stale-{uuid.uuid4()}",
        status="processing",
        attempt_count=1,
        locked_at=past_time,
        locked_by="crashed-worker-99",
        lock_expires_at=past_time + timedelta(minutes=5),  # Expired 5 mins ago
        payload={
            "channel_id": str(telegram_channel_a.id),
            "sender_id": "111222333",
            "reply_message_id": str(reply_msg.id),
        },
    )
    db.add(event)
    db.commit()

    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="111222333",
        external_message_id="tg.recovered.505",
        status="sent",
    )

    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )

    # run_once should recover the stale event and process it
    processed_count = worker.run_once()
    assert processed_count == 1

    # VERIFY: Event is completed, reply delivered
    db.expire_all()
    db.refresh(event)
    assert event.status == "completed"
    db.refresh(reply_msg)
    assert (reply_msg.metadata_json or {}).get("delivery_status") == "delivered"
    mock_channel_svc.send_channel_message.assert_called_once()


# ===========================================================================
# 5. Business operation failure: NO success reply sent to channel
# ===========================================================================

def test_5_failed_business_operation_never_sends_success_reply(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 5:
    If processing fails (e.g. AI provider throws error for customer inquiry),
    NO success reply must be sent to Telegram, and the event must be marked failed/pending backoff.
    """
    cust = Customer(
        tenant_id=tenant_a.id,
        name="Test Cust",
        status="active",
    )
    db.add(cust)
    db.flush()

    conv = Conversation(
        tenant_id=tenant_a.id,
        customer_id=cust.id,
        channel_id=telegram_channel_a.id,
        status="open",
    )
    db.add(conv)
    db.flush()

    msg = Message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        customer_id=cust.id,
        sender_type="customer",
        content="هل يمكنكم شحن العسل إلى الرياض؟",
    )
    db.add(msg)
    db.flush()

    event = OutboxEvent(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        message_id=msg.id,
        event_type="process_incoming_message",
        idempotency_key=f"fail-{uuid.uuid4()}",
        status="pending",
        payload={
            "channel_id": str(telegram_channel_a.id),
            "sender_id": "888777666",
        },
    )
    db.add(event)
    db.commit()

    mock_channel_svc = MagicMock(spec=ChannelService)

    # Mock AI provider that fails
    mock_ai = MagicMock()
    mock_ai.generate_text.side_effect = AIProviderError("Provider unavailable")

    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        ai_provider=mock_ai,
        channel_service=mock_channel_svc,
    )

    success = worker.process_event(event.id)
    assert success is False

    # MOST IMPORTANTLY: mock_channel_svc.send_channel_message MUST NEVER BE CALLED!
    mock_channel_svc.send_channel_message.assert_not_called()

    # No spurious reply message was committed
    db.expire_all()
    replies = db.scalars(
        select(Message).where(
            Message.conversation_id == conv.id,
            Message.sender_type == "agent",
        )
    ).all()
    assert len(replies) == 0


# ===========================================================================
# 6. Duplicate arrival of the same event is cleanly handled (Idempotency)
# ===========================================================================

def test_6_duplicate_event_arrival_cleanly_short_circuited(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 6:
    An event whose reply has already been delivered is processed again.
    It must complete immediately without making another network call to Telegram.
    """
    conv = Conversation(
        tenant_id=tenant_a.id,
        channel_id=telegram_channel_a.id,
        status="open",
    )
    db.add(conv)
    db.flush()

    orig_msg = Message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="user",
        content="أهلاً",
        metadata_json={"agent_processed": True},
    )
    db.add(orig_msg)
    db.flush()

    delivered_reply = Message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="agent",
        content="مرحباً بك يا صاحب المنشأة",
        metadata_json={
            "in_reply_to_message_id": str(orig_msg.id),
            "delivery_status": "delivered",
            "external_message_id": "tg.already.sent.777",
        },
    )
    db.add(delivered_reply)
    db.flush()

    event = OutboxEvent(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        message_id=orig_msg.id,
        event_type="process_incoming_message",
        idempotency_key=f"dup-{uuid.uuid4()}",
        status="pending",
        payload={
            "channel_id": str(telegram_channel_a.id),
            "sender_id": "111222333",
            "reply_message_id": str(delivered_reply.id),
        },
    )
    db.add(event)
    db.commit()

    mock_channel_svc = MagicMock(spec=ChannelService)
    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )

    success = worker.process_event(event.id)
    assert success is True

    # Telegram send must NOT have been called!
    mock_channel_svc.send_channel_message.assert_not_called()

    # Event must be completed
    db.refresh(event)
    assert event.status == "completed"


# ===========================================================================
# 7. End-to-end: Delivery fails, worker recovers on next poll, completes
# ===========================================================================

def test_7_e2e_delivery_failure_followed_by_successful_recovery(
    db: Session, tenant_a: Tenant, telegram_channel_a: Channel
):
    """
    Scenario 7:
    End-to-end run_once lifecycle:
    Poll 1: Delivery fails due to network outage -> Business operation saved, event scheduled.
    Time passes: event becomes due.
    Poll 2: Delivery succeeds -> Event completed.
    """
    # Ensure no lingering events from earlier tests interfere with run_once
    db.query(OutboxEvent).filter(
        OutboxEvent.tenant_id == tenant_a.id,
        OutboxEvent.status.in_(["pending", "processing"]),
    ).update({"status": "completed"})
    db.commit()

    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel_a.id,
        tenant_id=tenant_a.id,
        sender_id="111222333",
        external_message_id=f"tg.e2e.{uuid.uuid4().hex[:8]}",
        content="أضف منتج: حبوب اللقاح بسعر 95 ريال",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    event = db.scalar(select(OutboxEvent).where(OutboxEvent.message_id == msg.id))

    # Phase 1: Delivery fails
    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=False,
        channel_type="telegram",
        recipient_id="111222333",
        status="failed",
        error="Temporary connection reset",
    )
    worker1 = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )
    count1 = worker1.run_once()
    assert count1 == 0  # Failed item not counted as success

    # Verify BusinessBrain already has the product!
    db.expire_all()
    brain = BusinessBrainService(db).get_brain(tenant_a.id)
    assert "حبوب_اللقاح" in (brain.products or {})

    # Force event to be due immediately for Poll 2
    db.refresh(event)
    event.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    # Phase 2: Next poll iteration, network is restored
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="111222333",
        external_message_id="tg.restored.888",
        status="sent",
    )
    worker2 = OutboxWorker(
        tenant_id=tenant_a.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )
    count2 = worker2.run_once()
    assert count2 == 1

    db.refresh(event)
    assert event.status == "completed"


# ===========================================================================
# 8. Cross-Tenant Isolation: Tenant A's delivery failure does not affect Tenant B
# ===========================================================================

def test_8_cross_tenant_isolation_during_dispatch_failure(
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
    telegram_channel_a: Channel,
    telegram_channel_b: Channel,
):
    """
    Scenario 8:
    Tenant A's delivery fails, while Tenant B's message is processed concurrently.
    Tenant B's message and delivery must succeed without any cross-tenant leakage or block.
    """
    chan_svc = ChannelService(db)

    # Inbound for Tenant A
    inbound_a = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel_a.id,
        tenant_id=tenant_a.id,
        sender_id="111222333",
        external_message_id=f"tg.a.{uuid.uuid4().hex[:8]}",
        content="أضف منتج: عسل ألفا بسعر 100 ريال",
    )
    msg_a = chan_svc.process_inbound_message(inbound_a)

    # Inbound for Tenant B
    inbound_b = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel_b.id,
        tenant_id=tenant_b.id,
        sender_id="444555666",
        external_message_id=f"tg.b.{uuid.uuid4().hex[:8]}",
        content="أضف منتج: عود بيتا بسعر 400 ريال",
    )
    msg_b = chan_svc.process_inbound_message(inbound_b)
    db.commit()

    event_a = db.scalar(select(OutboxEvent).where(OutboxEvent.message_id == msg_a.id))
    event_b = db.scalar(select(OutboxEvent).where(OutboxEvent.message_id == msg_b.id))

    def mock_send(tenant_id, channel_id, recipient, content, **kwargs):
        if tenant_id == tenant_a.id:
            return OutboundDeliveryResult(
                success=False,
                channel_type="telegram",
                recipient_id=recipient,
                status="failed",
                error="Tenant A Telegram 503 Service Unavailable / Timeout",
            )
        return OutboundDeliveryResult(
            success=True,
            channel_type="telegram",
            recipient_id=recipient,
            external_message_id="tg.b.ok",
            status="sent",
        )

    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.side_effect = mock_send

    worker = OutboxWorker(
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )

    res_a = worker.process_event(event_a.id)
    assert res_a is False

    res_b = worker.process_event(event_b.id)
    assert res_b is True

    # VERIFY: Tenant A's business data is saved, event is pending retry
    db.expire_all()
    brain_a = BusinessBrainService(db).get_brain(tenant_a.id)
    assert "عسل_ألفا" in (brain_a.products or {})
    db.refresh(event_a)
    assert event_a.status == "pending"

    # VERIFY: Tenant B's business data is saved, event is completed
    brain_b = BusinessBrainService(db).get_brain(tenant_b.id)
    assert "عود_بيتا" in (brain_b.products or {})
    db.refresh(event_b)
    assert event_b.status == "completed"

    # Strict boundary check: Tenant A does NOT have Tenant B's products
    assert "عود_بيتا" not in (brain_a.products or {})
    assert "عسل_ألفا" not in (brain_b.products or {})
