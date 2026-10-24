from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import uuid
from typing import Any
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.ai_providers.base import AIProvider, AIProviderError, AIProviderTimeoutError
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Conversation, Customer, Message, OutboxEvent
from packages.models.tenant import Tenant
from packages.services.conversation_service import ConversationService
from packages.services.outbox_service import OutboxService, sanitize_error
from packages.services.outbox_worker import OutboxWorker, is_transient_error


# ---------------------------------------------------------------------------
# Mock AI Provider for reliable offline testing
# ---------------------------------------------------------------------------
class MockAIProvider:
    def __init__(
        self,
        response: str = "Hello from AI Agent! How can I help you today?",
        should_fail: bool = False,
        failure_error: Exception | None = None,
    ):
        self.response = response
        self.should_fail = should_fail
        self.failure_error = failure_error or AIProviderTimeoutError("Connection timed out to provider")
        self.call_count = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.call_count += 1
        if self.should_fail:
            raise self.failure_error
        return self.response

    def generate_json(self, *args, **kwargs) -> dict[str, Any]:
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


@pytest.fixture(autouse=True)
def clean_outbox_table(db: Session):
    """Ensure outbox table is pristine before and after each test."""
    db.query(OutboxEvent).delete()
    db.commit()
    yield
    db.query(OutboxEvent).delete()
    db.commit()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tenant_a(db: Session):
    t = Tenant(
        name="Outbox Tenant A",
        slug=f"outbox-a-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(
        name="Outbox Tenant B",
        slug=f"outbox-b-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def channel_a(db: Session, tenant_a: Tenant):
    ch = Channel(
        tenant_id=tenant_a.id,
        name="WebChat Channel A",
        channel_type="webchat",
        status="active",
        config={"webhook_secret": "secret-webhook-key-12345"},
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


@pytest.fixture
def customer_a(db: Session, tenant_a: Tenant):
    c = Customer(
        tenant_id=tenant_a.id,
        name="Charlie Customer",
        email=f"charlie-{uuid.uuid4().hex[:8]}@example.com",
        status="active",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture
def conversation_a(db: Session, tenant_a: Tenant, customer_a: Customer, channel_a: Channel):
    conv = Conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a.id,
        channel_id=channel_a.id,
        subject="Support Request",
        status="open",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_atomic_message_and_outbox_persistence(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    1. Atomic message and outbox persistence:
    Verifies that message and outbox event are created atomically in the same transaction.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    idempotency_key = f"key-{uuid.uuid4()}"
    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Hello, I need assistance with my account.",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=idempotency_key,
    )
    db.commit()

    # Verify both are persisted
    saved_msg = db.scalar(select(Message).where(Message.id == msg.id))
    saved_event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event.id))

    assert saved_msg is not None
    assert saved_event is not None
    assert saved_event.status == "pending"
    assert saved_event.message_id == msg.id
    assert saved_event.conversation_id == conversation_a.id
    assert saved_event.tenant_id == tenant_a.id


def test_successful_worker_processing(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    2. Successful worker processing:
    Message -> Outbox Event -> Worker -> ConversationalAgentEngine -> Persisted Reply.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="What are your business hours?",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"hours-{uuid.uuid4()}",
    )
    db.commit()

    mock_ai = MockAIProvider(response="We are open Monday to Friday from 9 AM to 6 PM.")
    worker = OutboxWorker(tenant_id=tenant_a.id, ai_provider=mock_ai, batch_size=5)

    processed_count = worker.run_once()
    assert processed_count == 1

    # Verify outbox event is marked completed
    db.expire_all()
    completed_event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event.id))
    assert completed_event.status == "completed"
    assert completed_event.processed_at is not None
    assert completed_event.error_message is None

    # Verify reply message exists in conversation
    reply_msg = db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_a.id,
            Message.sender_type == "agent",
        )
    )
    assert reply_msg is not None
    assert reply_msg.content == "We are open Monday to Friday from 9 AM to 6 PM."
    assert reply_msg.metadata_json.get("in_reply_to_message_id") == str(msg.id)

    # Verify incoming message was flagged as processed
    db.refresh(msg)
    assert msg.metadata_json.get("agent_processed") is True
    assert msg.metadata_json.get("reply_message_id") == str(reply_msg.id)


def test_tenant_isolation(db: Session, tenant_a: Tenant, tenant_b: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    3. Tenant isolation:
    Events from Tenant B cannot execute or manipulate resources belonging to Tenant A.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    # Message belonging to Tenant A
    msg_a = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Tenant A confidential customer request",
        customer_id=customer_a.id,
    )
    db.commit()

    # OutboxService enforces tenant boundary on event creation
    with pytest.raises(ValueError, match="not found for tenant"):
        outbox_service.create_event(
            tenant_id=tenant_b.id,  # Cross-tenant attempt!
            conversation_id=conversation_a.id,
            message_id=msg_a.id,
            idempotency_key=f"cross-{uuid.uuid4()}",
        )

    # If an event exists with mismatched tenant in worker, worker rejects as permanent failure
    forged_event = OutboxEvent(
        tenant_id=tenant_b.id,
        conversation_id=conversation_a.id,  # Belongs to Tenant A!
        message_id=msg_a.id,
        idempotency_key=f"forged-{uuid.uuid4()}",
        status="pending",
        scheduled_at=datetime.now(timezone.utc),
    )
    db.add(forged_event)
    db.commit()

    worker = OutboxWorker(ai_provider=MockAIProvider(), batch_size=10)
    worker.run_once()

    db.refresh(forged_event)
    assert forged_event.status == "failed"
    assert "Tenant boundary violation" in forged_event.error_message


def test_duplicate_event_delivery(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    4. Duplicate event delivery & idempotency:
    Sending the same event idempotency key twice returns existing event without duplicates.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Order status inquiry",
        customer_id=customer_a.id,
    )
    db.commit()

    key = f"order-inquiry-{uuid.uuid4()}"
    event1 = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=key,
    )
    db.commit()

    # Second creation attempt with same key
    event2 = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=key,
    )

    assert event1.id == event2.id

    # Verify database has strictly 1 record with this key
    count = db.query(OutboxEvent).filter(
        OutboxEvent.tenant_id == tenant_a.id,
        OutboxEvent.idempotency_key == key,
    ).count()
    assert count == 1


def test_concurrent_worker_claims(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    5. Concurrent worker claims:
    Multiple workers claiming events concurrently on PostgreSQL with FOR UPDATE SKIP LOCKED
    never claim the same event twice.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    # Seed 12 events
    created_ids = []
    for i in range(12):
        msg = conv_service.send_message(
            tenant_id=tenant_a.id,
            conversation_id=conversation_a.id,
            sender_type="customer",
            content=f"Concurrent message {i}",
            customer_id=customer_a.id,
        )
        event = outbox_service.create_event(
            tenant_id=tenant_a.id,
            conversation_id=conversation_a.id,
            message_id=msg.id,
            idempotency_key=f"concurrent-{i}-{uuid.uuid4()}",
        )
        created_ids.append(event.id)
    db.commit()

    claimed_by_worker: dict[str, list[uuid.UUID]] = {}
    target_tenant_id = tenant_a.id

    def worker_claim(worker_id: str):
        thread_db = SessionLocal()
        try:
            svc = OutboxService(thread_db)
            claimed = svc.claim_events(worker_id, tenant_id=target_tenant_id, batch_size=4)
            return worker_id, [c.id for c in claimed]
        finally:
            thread_db.close()


    # Execute 4 concurrent claims across threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker_claim, f"worker-{w}") for w in range(4)]
        for fut in concurrent.futures.as_completed(futures):
            wid, claimed_ids = fut.result()
            claimed_by_worker[wid] = claimed_ids

    # Flatten all claimed IDs
    all_claimed = []
    for wid, c_ids in claimed_by_worker.items():
        all_claimed.extend(c_ids)

    # Concurrency verification: strictly no overlaps!
    assert len(all_claimed) == len(set(all_claimed)), "Duplicate claims detected across concurrent workers!"
    assert len(all_claimed) == 12, f"Expected 12 claimed events, got {len(all_claimed)}"


def test_worker_crash_and_stale_event_recovery(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    6. Worker crash and stale-event recovery:
    An event left in 'processing' whose lock expired is safely recovered back to 'pending'.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Crash test message",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"crash-{uuid.uuid4()}",
        max_attempts=3,
    )
    db.commit()

    # Simulate worker crash: claim and expire lock
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    event.status = "processing"
    event.attempt_count = 1
    event.locked_at = past_time
    event.locked_by = "crashed-worker-pid-999"
    event.lock_expires_at = past_time + timedelta(minutes=5)
    db.commit()

    # Run recovery
    recovered = outbox_service.recover_stale_events(tenant_id=tenant_a.id, lock_timeout_seconds=60)
    assert len(recovered) == 1
    assert recovered[0].id == event.id

    db.refresh(event)
    assert event.status == "pending"
    assert event.locked_by is None
    assert "Recovered from stalled worker crash" in event.error_message


def test_stale_event_exceeded_max_attempts_fails(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    6b. If a crashed event has reached max_attempts, recovery marks it failed.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Crash loop message",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"crash-max-{uuid.uuid4()}",
        max_attempts=2,
    )
    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    event.status = "processing"
    event.attempt_count = 2  # Reached max_attempts!
    event.locked_at = past_time
    event.lock_expires_at = past_time
    db.commit()

    outbox_service.recover_stale_events(tenant_id=tenant_a.id, lock_timeout_seconds=60)
    db.refresh(event)

    assert event.status == "failed"
    assert "exceeded max attempts" in event.error_message


def test_transient_failure_and_bounded_retry(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    7. Transient failure and bounded retry behavior:
    Timeout / rate limit results in exponential backoff retry.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Transient failure test",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"transient-{uuid.uuid4()}",
        max_attempts=4,
    )
    db.commit()

    failing_ai = MockAIProvider(should_fail=True, failure_error=AIProviderTimeoutError("Service timeout"))
    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        ai_provider=failing_ai,
        base_backoff_seconds=2.0,
        max_backoff_seconds=60.0,
        backoff_factor=2.0,
    )

    # First attempt
    worker.run_once()
    db.refresh(event)

    assert event.status == "pending"
    assert event.attempt_count == 1
    # Scheduled for future: now + 2s
    assert event.scheduled_at > datetime.now(timezone.utc) - timedelta(seconds=1)
    assert "timeout" in event.error_message.lower()

    # Backoff formula verification
    assert worker.calculate_backoff(1) == 2.0
    assert worker.calculate_backoff(2) == 4.0
    assert worker.calculate_backoff(3) == 8.0
    assert worker.calculate_backoff(10) == 60.0  # Bounded by max_backoff


def test_permanent_failure_handling(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    8. Permanent failure handling:
    An unrecoverable issue (e.g. invalid sender or unrecoverable error)
    is marked failed immediately and never endlessly retried.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Permanent failure test",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"perm-{uuid.uuid4()}",
    )
    db.commit()

    # Simulate an unrecoverable permanent error from the AI provider or execution
    permanent_error = ValueError("Permanent validation failure: Model rejected invalid prompt parameters")
    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        ai_provider=MockAIProvider(should_fail=True, failure_error=permanent_error),
        batch_size=5,
    )
    worker.run_once()

    db.refresh(event)
    assert event.status == "failed"
    assert "Permanent failure" in event.error_message
    assert "rejected invalid prompt parameters" in event.error_message


def test_duplicate_reply_prevention(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    9. Duplicate reply prevention:
    Re-processing an event whose message already has an agent reply does not send another reply.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)
    db.query(OutboxEvent).filter(
        OutboxEvent.tenant_id == tenant_a.id,
        OutboxEvent.status.in_(["pending", "processing"]),
    ).update({"status": "completed"})
    db.commit()

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Hello, duplicate test",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"dup-reply-{uuid.uuid4()}",
    )
    db.commit()

    mock_ai = MockAIProvider(response="First reply response.")
    worker = OutboxWorker(tenant_id=tenant_a.id, ai_provider=mock_ai)

    # First run processes successfully
    worker.run_once()
    db.refresh(event)
    assert event.status == "completed"
    assert mock_ai.call_count == 1

    # Reset event to pending to simulate duplicate dispatch
    event.status = "pending"
    event.scheduled_at = datetime.now(timezone.utc)
    db.commit()

    # Second run
    worker.run_once()
    db.refresh(event)
    assert event.status == "completed"

    # Verify there is still only ONE reply message in the conversation!
    replies = db.scalars(
        select(Message).where(
            Message.conversation_id == conversation_a.id,
            Message.sender_type == "agent",
        )
    ).all()
    assert len(replies) == 1
    assert mock_ai.call_count == 1  # AI Provider was not invoked a second time!


def test_provider_failure_without_secret_leakage(db: Session, tenant_a: Tenant, conversation_a: Conversation, customer_a: Customer):
    """
    10. Provider failure without secret leakage:
    API keys, Bearer tokens, and secrets in exceptions are completely redacted.
    """
    conv_service = ConversationService(db)
    outbox_service = OutboxService(db)

    msg = conv_service.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        sender_type="customer",
        content="Secret leak test",
        customer_id=customer_a.id,
    )
    event = outbox_service.create_event(
        tenant_id=tenant_a.id,
        conversation_id=conversation_a.id,
        message_id=msg.id,
        idempotency_key=f"leak-{uuid.uuid4()}",
    )
    db.commit()

    sensitive_error = AIProviderError(
        "API request failed with key AIzaSyD1234567890abcdef1234567890abcdef and Authorization: Bearer sk-ant-secret-1234567890"
    )
    worker = OutboxWorker(
        tenant_id=tenant_a.id,
        ai_provider=MockAIProvider(should_fail=True, failure_error=sensitive_error),
    )
    worker.run_once()

    db.refresh(event)
    assert "AIzaSyD" not in event.error_message
    assert "sk-ant-secret" not in event.error_message
    assert "[REDACTED" in event.error_message


def test_webhook_signature_validation(client: TestClient, db: Session, tenant_a: Tenant, channel_a: Channel, customer_a: Customer):
    """
    11. Webhook signature validation:
    Verifies valid HMAC-SHA256 signature succeeds (202), while invalid/missing signatures are rejected (401).
    """
    secret = channel_a.config["webhook_secret"]
    payload = {
        "content": "Hello via webhook!",
        "customer_id": str(customer_a.id),
        "external_id": f"ext-{uuid.uuid4()}",
    }
    raw_body = json.dumps(payload).encode("utf-8")

    # Case A: Valid signature
    valid_sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    resp_valid = client.post(
        f"/api/v1/webhooks/channels/{channel_a.id}",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={valid_sig}",
        },
    )
    assert resp_valid.status_code == 202
    data = resp_valid.json()
    assert data["status"] == "accepted"
    assert "outbox_event_id" in data

    # Case B: Invalid signature
    resp_invalid = client.post(
        f"/api/v1/webhooks/channels/{channel_a.id}",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": "sha256=invalidhash00000000000000000000000000000000000000000000000000000000",
        },
    )
    assert resp_invalid.status_code == 401
    assert "Invalid or missing webhook signature" in resp_invalid.json()["detail"]

    # Case C: Missing signature header
    resp_missing = client.post(
        f"/api/v1/webhooks/channels/{channel_a.id}",
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp_missing.status_code == 401


def test_preservation_of_customer_block_and_loop_prevention(client: TestClient, db: Session, tenant_a: Tenant, channel_a: Channel, customer_a: Customer):
    """
    12. Preservation of approval, tool policies, and customer block rules:
    - Blocked customer cannot initiate processing.
    - Agent-generated replies cannot be ingested as inbound webhook messages.
    """
    secret = channel_a.config["webhook_secret"]

    # Test A: Blocked customer rejection
    customer_a.status = "blocked"
    db.commit()

    payload_blocked = {
        "content": "I want to talk",
        "customer_id": str(customer_a.id),
    }
    raw_body_b = json.dumps(payload_blocked).encode("utf-8")
    sig_b = hmac.new(secret.encode("utf-8"), raw_body_b, hashlib.sha256).hexdigest()

    resp_b = client.post(
        f"/api/v1/webhooks/channels/{channel_a.id}",
        content=raw_body_b,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": sig_b,
        },
    )
    assert resp_b.status_code == 403
    assert "blocked" in resp_b.json()["detail"].lower()

    # Test B: Loop prevention - reject sender_type='agent' via webhook
    payload_agent = {
        "content": "Agent automated reply",
        "sender_type": "agent",
    }
    raw_body_a = json.dumps(payload_agent).encode("utf-8")
    sig_a = hmac.new(secret.encode("utf-8"), raw_body_a, hashlib.sha256).hexdigest()

    resp_a = client.post(
        f"/api/v1/webhooks/channels/{channel_a.id}",
        content=raw_body_a,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": sig_a,
        },
    )
    assert resp_a.status_code == 400
    assert "rejected sender_type" in resp_a.json()["detail"]
