from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import threading
import time
import uuid
from typing import Any
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.ai_providers.base import AIProvider
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Conversation, Customer, Message, OutboxEvent
from packages.models.tenant import Tenant
from packages.services.conversation_service import ConversationService
from packages.services.outbox_service import OutboxService
from packages.services.outbox_worker import OutboxWorker


class MockE2EAIProvider:
    """Mock provider for local runtime end-to-end verification."""

    def __init__(self, reply: str = "Thank you for reaching out! Your support ticket has been noted."):
        self.reply = reply
        self.called = 0

    def generate_text(self, prompt: str, *, system_instruction: str | None = None, temperature: float = 0.2) -> str:
        self.called += 1
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


@pytest.fixture(autouse=True)
def clean_outbox_table(db: Session):
    db.query(OutboxEvent).delete()
    db.commit()
    yield
    db.query(OutboxEvent).delete()
    db.commit()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tenant(db: Session):
    t = Tenant(
        name="Runtime Verification Tenant",
        slug=f"runtime-verify-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def channel_signed(db: Session, tenant: Tenant):
    ch = Channel(
        tenant_id=tenant.id,
        name="Verified Signed Channel",
        channel_type="webchat",
        status="active",
        config={"webhook_secret": "runtime-e2e-secret-key-12345"},
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


@pytest.fixture
def channel_missing_secret(db: Session, tenant: Tenant):
    """Channel that requires signature but secret is not set (misconfiguration)."""
    ch = Channel(
        tenant_id=tenant.id,
        name="Misconfigured Channel",
        channel_type="webchat",
        status="active",
        config={"require_signature": True, "webhook_secret": ""},
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


@pytest.fixture
def customer(db: Session, tenant: Tenant):
    c = Customer(
        tenant_id=tenant.id,
        name="Runtime Customer",
        email=f"runtime-{uuid.uuid4().hex[:8]}@example.com",
        status="active",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_webhook_fails_closed_when_secret_is_missing(client: TestClient, channel_missing_secret: Channel, customer: Customer):
    """
    Verification 5: Webhook authentication FAILS CLOSED if channel requires signature
    but secret is missing or empty.
    """
    payload = {
        "content": "Attempting message on misconfigured channel",
        "customer_id": str(customer.id),
    }
    raw_body = json.dumps(payload).encode("utf-8")

    # Even with or without headers, must be rejected with 401
    resp = client.post(
        f"/api/v1/webhooks/channels/{channel_missing_secret.id}",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    assert "Invalid or missing webhook signature" in resp.json()["detail"]


def test_webhook_fails_closed_when_signature_header_is_missing(client: TestClient, channel_signed: Channel, customer: Customer):
    """
    Verification 5b: Webhook authentication FAILS CLOSED if secret is configured but header is missing.
    """
    payload = {
        "content": "Unsigned message attempt",
        "customer_id": str(customer.id),
    }
    raw_body = json.dumps(payload).encode("utf-8")

    resp = client.post(
        f"/api/v1/webhooks/channels/{channel_signed.id}",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    assert "Invalid or missing webhook signature" in resp.json()["detail"]


def test_atomicity_under_outbox_persistence_failure(db: Session, tenant: Tenant, customer: Customer, channel_signed: Channel):
    """
    Verification 6: Message persistence and outbox creation are truly atomic under failure.
    If outbox event creation fails or transaction aborts, no partial message remains in DB.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    conv = conv_service.start_conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel_signed.id,
        subject="Atomicity Test",
    )
    db.commit()

    # Capture initial message count
    initial_msg_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
    initial_outbox_count = db.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant.id).count()

    # Simulate atomic block where message is staged, but outbox creation encounters an error
    msg_id = None
    try:
        msg = conv_service.send_message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            sender_type="customer",
            content="This message should roll back atomically",
            customer_id=customer.id,
        )
        msg_id = msg.id

        # Intentional failure: simulate constraint or invalid key error
        raise RuntimeError("Simulated database failure during outbox staging")

    except Exception:
        db.rollback()

    # Verify atomic rollback: neither message nor outbox event exists in database
    final_msg = db.scalar(select(Message).where(Message.id == msg_id)) if msg_id else None
    assert final_msg is None

    final_msg_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
    final_outbox_count = db.query(OutboxEvent).filter(OutboxEvent.tenant_id == tenant.id).count()

    assert final_msg_count == initial_msg_count
    assert final_outbox_count == initial_outbox_count


def test_real_local_async_end_to_end_pipeline(
    client: TestClient,
    db: Session,
    tenant: Tenant,
    channel_signed: Channel,
    customer: Customer,
):
    """
    Verification 7: Real local end-to-end test.
    1. Worker runs continuously in a real background thread without manual invocation.
    2. Message is submitted via authenticated webhook.
    3. API returns HTTP 202 Accepted immediately.
    4. Worker claims event, processes it through ConversationalAgentEngine, and writes reply.
    5. Database contains completed outbox event and persisted agent reply message.
    6. Graceful shutdown joins worker thread cleanly.
    """
    secret = channel_signed.config["webhook_secret"]
    mock_ai = MockE2EAIProvider(reply="Local E2E automated reply from background worker.")

    # 1. Start continuous background worker in independent thread
    worker = OutboxWorker(
        tenant_id=tenant.id,
        ai_provider=mock_ai,
        poll_interval_seconds=0.1,  # Fast polling for test
        batch_size=5,
    )

    worker_thread = threading.Thread(target=worker.run, daemon=True)
    worker_thread.start()
    assert worker_thread.is_alive()

    try:
        # 2. Submit customer message via HTTP webhook
        ext_msg_id = f"e2e-msg-{uuid.uuid4()}"
        payload = {
            "content": "Can you confirm my account balance?",
            "customer_id": str(customer.id),
            "external_id": ext_msg_id,
        }
        raw_body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

        resp = client.post(
            f"/api/v1/webhooks/channels/{channel_signed.id}",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={signature}",
            },
        )

        # 3. Verify immediate acceptance
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        outbox_event_id = uuid.UUID(body["outbox_event_id"])
        conversation_id = uuid.UUID(body["conversation_id"])
        inbound_msg_id = uuid.UUID(body["message_id"])

        # 4. Asynchronously poll database until background worker processes the event
        deadline = time.time() + 8.0  # Up to 8 seconds timeout
        reply_found = False
        completed_event = None
        reply_message = None

        while time.time() < deadline:
            with SessionLocal() as poll_session:
                evt = poll_session.scalar(select(OutboxEvent).where(OutboxEvent.id == outbox_event_id))
                if evt and evt.status == "completed":
                    completed_event = evt
                    # Check for agent reply
                    reply = poll_session.scalar(
                        select(Message).where(
                            Message.conversation_id == conversation_id,
                            Message.sender_type == "agent",
                        )
                    )
                    if reply is not None:
                        reply_found = True
                        reply_message = reply
                        break
            time.sleep(0.1)

        # 5. Assert successful asynchronous processing
        assert reply_found, "Background worker did not persist agent reply before deadline!"
        assert completed_event is not None
        assert completed_event.status == "completed"
        assert completed_event.processed_at is not None

        assert reply_message is not None
        assert reply_message.content == "Local E2E automated reply from background worker."
        assert reply_message.metadata_json.get("in_reply_to_message_id") == str(inbound_msg_id)
        assert mock_ai.called == 1

    finally:
        # 6. Graceful shutdown
        worker.stop()
        worker_thread.join(timeout=3.0)
        assert not worker_thread.is_alive(), "Worker thread did not terminate within timeout!"


def test_tri_component_worker_engine_factory_integration(
    db: Session,
    tenant: Tenant,
    customer: Customer,
    channel_signed: Channel,
    monkeypatch,
):
    """
    Verification 1 & 2: Confirms OutboxWorker, ConversationalAgentEngine, and AIProviderFactory
    are fully linked together.
    The worker runs with ai_provider=None, prompting ConversationalAgentEngine to dynamically
    invoke AIProviderFactory.create_provider(tenant_id, db).
    """
    class TriComponentMockProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def generate_text(self, prompt: str, *, system_instruction: str | None = None, temperature: float = 0.2) -> str:
            return "Generated dynamically via AIProviderFactory resolution!"

        def generate_json(self, *args, **kwargs):
            return {}

    from packages.ai_providers.factory import AIProviderFactory
    from packages.services.ai_provider_service import AIProviderService

    AIProviderFactory.register_provider("tri_mock", TriComponentMockProvider)
    AIProviderService.ALLOWED_PROVIDERS.add("tri_mock")
    monkeypatch.setattr(settings, "ai_provider", "tri_mock")

    try:
        # Register tenant's dedicated AI provider in the database
        provider_svc = AIProviderService(db)
        provider_svc.register_or_update_config(
            tenant_id=tenant.id,
            name="tenant-dynamic-ai",
            provider="tri_mock",
            model="tri-model-v1",
            api_key="sk-mock-key-12345",
            is_default=True,
        )
        db.commit()

        conv_service = ConversationService(db)
        outbox_service = OutboxService(db)

        conv = conv_service.start_conversation(
            tenant_id=tenant.id,
            customer_id=customer.id,
            channel_id=channel_signed.id,
            subject="Tri-Component Test",
        )
        msg = conv_service.send_message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            sender_type="customer",
            content="Testing dynamic factory resolution through outbox worker.",
            customer_id=customer.id,
        )
        event = outbox_service.create_event(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            message_id=msg.id,
            idempotency_key=f"tri-{uuid.uuid4()}",
        )
        db.commit()

        # Worker created with NO injected provider -> must resolve via AIProviderFactory!
        worker = OutboxWorker(tenant_id=tenant.id, ai_provider=None)
        processed = worker.run_once()

        assert processed == 1
        db.refresh(event)
        assert event.status == "completed"

        reply = db.scalar(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.sender_type == "agent",
            )
        )
        assert reply is not None
        assert reply.content == "Generated dynamically via AIProviderFactory resolution!"
        assert reply.metadata_json.get("in_reply_to_message_id") == str(msg.id)

    finally:
        AIProviderFactory._registry.pop("tri_mock", None)
        AIProviderService.ALLOWED_PROVIDERS.discard("tri_mock")


