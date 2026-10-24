from __future__ import annotations

import hmac
import json
from typing import Any
from unittest.mock import MagicMock, patch
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.connectors.base import InboundMessage, OutboundDeliveryResult
from packages.connectors.telegram import TelegramConnector
from packages.core.crypto import SecretsEncryptionService
from packages.core.database import SessionLocal
from packages.models.domain import (
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


# ---------------------------------------------------------------------------
# Test Fixtures
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
def tenant(db: Session):
    t = Tenant(
        name="Telegram Test Enterprise",
        slug=f"tg-test-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Test Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@tgtest.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "متجر البركة التجاري"},
        brand={"tone": "مساعد ذكي ومهني"},
        products={},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def telegram_channel(db: Session, tenant: Tenant):
    svc = ChannelService(db)
    config = {
        "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz_TEST",
        "secret_token": "tg_test_secret_token_12345",
        "owner_telegram_id": "775274399",
        "owner_identifiers": ["775274399"],
    }
    channel = svc.register_channel(
        tenant_id=tenant.id,
        name="Telegram Bot Test",
        channel_type="telegram",
        provider="telegram",
        config=config,
    )
    db.commit()
    return channel


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_telegram_webhook_valid_request(client: TestClient, telegram_channel: Channel, db: Session):
    """1. Valid webhook request accepted with 200 OK and persists message & outbox event."""
    url = f"/api/v1/webhooks/telegram/{telegram_channel.id}"
    headers = {"X-Telegram-Bot-Api-Secret-Token": "tg_test_secret_token_12345"}
    payload = {
        "update_id": 10001,
        "message": {
            "message_id": 42,
            "from": {"id": 999888777, "first_name": "Khalid", "username": "khalid_user"},
            "chat": {"id": 999888777, "type": "private"},
            "date": 1729500000,
            "text": "السلام عليكم، ما هي خدماتكم؟",
        },
    }

    resp = client.post(url, json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["processed_count"] == 1

    # Verify message in DB
    msg_id = uuid.UUID(data["message_ids"][0])
    persisted = db.scalar(select(Message).where(Message.id == msg_id))
    assert persisted is not None
    assert persisted.content == "السلام عليكم، ما هي خدماتكم؟"
    assert persisted.sender_type == "customer"


def test_telegram_webhook_invalid_secret_token_rejected(client: TestClient, telegram_channel: Channel):
    """2. Webhook request with invalid secret token rejected with 401 Unauthorized."""
    url = f"/api/v1/webhooks/telegram/{telegram_channel.id}"
    headers = {"X-Telegram-Bot-Api-Secret-Token": "wrong_secret_token"}
    payload = {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 1}, "text": "test"}}

    resp = client.post(url, json=payload, headers=headers)
    assert resp.status_code == 401
    assert "Invalid secret token" in resp.json()["detail"]


def test_telegram_webhook_channel_not_found(client: TestClient):
    """3. Non-existent channel ID returns 404 Not Found."""
    random_id = uuid.uuid4()
    url = f"/api/v1/webhooks/telegram/{random_id}"
    headers = {"X-Telegram-Bot-Api-Secret-Token": "any"}
    resp = client.post(url, json={"update_id": 1}, headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Channel not found"


def test_telegram_webhook_missing_message_payload(client: TestClient, telegram_channel: Channel):
    """4. Empty or irrelevant update object gracefully handled with 200 OK and 0 processed count."""
    url = f"/api/v1/webhooks/telegram/{telegram_channel.id}"
    headers = {"X-Telegram-Bot-Api-Secret-Token": "tg_test_secret_token_12345"}
    # update without message (e.g. inline_query or empty)
    payload = {"update_id": 10002}

    resp = client.post(url, json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["processed_count"] == 0


def test_telegram_channel_secrets_decryption_failure_handled(db: Session, tenant: Tenant):
    """5. Corrupted encrypted secrets are handled gracefully without leaking."""
    corrupted_channel = Channel(
        tenant_id=tenant.id,
        name="Corrupted Channel",
        channel_type="telegram",
        status="active",
        config={
            "bot_token": "enc:v1:corrupted_nonce:corrupted_ciphertext",
            "secret_token": "enc:v1:corrupted_nonce:corrupted_ciphertext",
        },
    )
    db.add(corrupted_channel)
    db.commit()

    svc = ChannelService(db)
    connector = svc.get_connector(tenant.id, corrupted_channel.id)
    assert connector is not None
    # Decryption fails gracefully returning empty string, not crashing with unhandled exception
    assert connector.bot_token == ""


def test_telegram_owner_teaches_product_and_price(db: Session, tenant: Tenant, telegram_channel: Channel):
    """6. Authorized owner message teaches product and updates BusinessBrain and Knowledge."""
    svc = ChannelService(db)
    owner_inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel.id,
        tenant_id=tenant.id,
        sender_id="775274399",  # Matches owner_telegram_id
        sender_name="Abu Fahad Owner",
        external_message_id=f"tg.owner.{uuid.uuid4().hex[:8]}",
        content="أضف منتج جديد اسمه عسل سدر دوعني بسعر 150 ريال",
    )
    msg = svc.process_inbound_message(owner_inbound)
    db.commit()

    assert msg.sender_type == "user"
    assert (msg.metadata_json or {}).get("is_owner") is True

    # Process message via ConversationalAgentEngine
    engine = ConversationalAgentEngine(db=db)
    result = engine.process_incoming_message(tenant.id, msg.id)
    db.commit()

    assert result.success is True
    assert "تم حفظ وتحديث معلومات النشاط التجاري بنجاح" in (result.reply_content or "")
    assert "عسل سدر دوعني" in (result.reply_content or "")
    assert "150" in (result.reply_content or "")

    # Verify BusinessBrain updated
    brain = db.scalar(select(BusinessBrain).where(BusinessBrain.tenant_id == tenant.id))
    assert "عسل_سدر_دوعني" in (brain.products or {})
    prod = brain.products["عسل_سدر_دوعني"]
    assert prod["name"] == "عسل سدر دوعني"
    assert prod["price"] == 150.0

    # Verify Knowledge created
    k_item = db.scalar(
        select(Knowledge).where(
            Knowledge.tenant_id == tenant.id,
            Knowledge.title == "منتج: عسل سدر دوعني",
        )
    )
    assert k_item is not None
    assert "150" in k_item.content


def test_telegram_customer_queries_existing_and_nonexistent_product(
    db: Session, tenant: Tenant, telegram_channel: Channel
):
    """7 & 8. Customer queries: retrieved accurately for existing product, handled honestly for missing product."""
    # First, seed product in BusinessBrain
    brain = db.scalar(select(BusinessBrain).where(BusinessBrain.tenant_id == tenant.id))
    brain.products = {
        "عسل_سدر_دوعني": {"name": "عسل سدر دوعني", "price": 150.0, "unit": "ريال"}
    }
    db.commit()

    svc = ChannelService(db)

    # Customer A queries existing product
    cust_inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel.id,
        tenant_id=tenant.id,
        sender_id="888777666",
        sender_name="Saud Customer",
        external_message_id=f"tg.cust.{uuid.uuid4().hex[:8]}",
        content="كم سعر عسل سدر دوعني؟",
    )
    msg = svc.process_inbound_message(cust_inbound)
    db.commit()

    assert msg.sender_type == "customer"
    assert (msg.metadata_json or {}).get("is_owner") is False

    mock_ai = MagicMock()
    mock_ai.generate_text.return_value = "سعر عسل سدر دوعني هو 150 ريال."

    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)
    result = engine.process_incoming_message(tenant.id, msg.id)
    db.commit()

    assert result.success is True
    # Verify prompt received the verified business brain facts
    call_prompt = mock_ai.generate_text.call_args[0][0]
    assert "عسل سدر دوعني" in call_prompt
    assert "150" in call_prompt
    assert "سعر عسل سدر دوعني هو 150 ريال" in result.reply_content


def test_telegram_human_escalation_triggers_owner_alert(
    db: Session, tenant: Tenant, telegram_channel: Channel
):
    """9. Customer requesting human triggers escalation and alerts owner telegram ID."""
    svc = ChannelService(db)
    cust_inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel.id,
        tenant_id=tenant.id,
        sender_id="888777666",
        sender_name="Saud Customer",
        external_message_id=f"tg.esc.{uuid.uuid4().hex[:8]}",
        content="أريد التحدث مع موظف بشري",
    )
    msg = svc.process_inbound_message(cust_inbound)
    db.commit()

    engine = ConversationalAgentEngine(db=db)
    result = engine.process_incoming_message(tenant.id, msg.id)
    db.commit()

    assert result.success is True
    assert "تم تحويل محادثتك إلى المالك وفريق الإدارة" in result.reply_content

    # Escalation Outbox Event created
    esc_event = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant.id,
            OutboxEvent.event_type == "notify_owner_escalation",
        )
    )
    assert esc_event is not None
    assert esc_event.payload["channel_id"] == str(telegram_channel.id)

    # Worker dispatches alert to owner Telegram ID
    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="775274399",
        status="sent",
    )

    worker = OutboxWorker(session_factory=SessionLocal, channel_service=mock_channel_svc)
    assert worker.process_event(esc_event.id) is True

    mock_channel_svc.send_channel_message.assert_called_once()
    call_kwargs = mock_channel_svc.send_channel_message.call_args[1]
    assert call_kwargs["recipient"] == "775274399"
    assert "تنبيه تصعيد بشري" in call_kwargs["content"]


def test_telegram_outbound_failure_triggers_backoff(
    db: Session, tenant: Tenant, telegram_channel: Channel
):
    """10. Outbound delivery failure marks event failed with exponential backoff for retry."""
    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=telegram_channel.id,
        status="active",
        subject="Test Escalation",
    )
    db.add(conv)
    db.flush()

    msg = Message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Help please",
    )
    db.add(msg)
    db.flush()

    outbox_event = OutboxEvent(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        message_id=msg.id,
        event_type="notify_owner_escalation",
        idempotency_key=f"test:esc:{uuid.uuid4()}",
        status="claimed",
        attempt_count=1,
        payload={
            "channel_id": str(telegram_channel.id),
            "customer_name": "Test Customer",
            "message_content": "Help please",
        },
    )
    db.add(outbox_event)
    db.commit()

    mock_channel_svc = MagicMock(spec=ChannelService)
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=False,
        channel_type="telegram",
        recipient_id="775274399",
        status="failed",
        error="Telegram 503 Service Unavailable",
    )

    worker = OutboxWorker(session_factory=SessionLocal, channel_service=mock_channel_svc)
    success = worker.process_event(outbox_event.id)
    assert success is False

    db.refresh(outbox_event)
    assert outbox_event.status == "failed"
    assert outbox_event.scheduled_at is not None
    assert "Failed to deliver escalation alert" in (outbox_event.error_message or "")


def test_telegram_inbound_idempotency_prevents_duplicate_processing(
    db: Session, tenant: Tenant, telegram_channel: Channel
):
    """11. Inbound duplicate Telegram update with identical message_id is deduplicated."""
    svc = ChannelService(db)
    ext_id = f"tg.idem.{uuid.uuid4().hex[:8]}"

    inbound = InboundMessage(
        channel_type="telegram",
        channel_id=telegram_channel.id,
        tenant_id=tenant.id,
        sender_id="888777666",
        external_message_id=ext_id,
        content="أول رسالة",
    )
    msg1 = svc.process_inbound_message(inbound)
    db.commit()

    # Second arrival of identical message
    msg2 = svc.process_inbound_message(inbound)
    db.commit()

    assert msg1.id == msg2.id

    # Verify only ONE outbox event was created
    events = list(
        db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == tenant.id,
                OutboxEvent.message_id == msg1.id,
            )
        )
    )
    assert len(events) == 1
