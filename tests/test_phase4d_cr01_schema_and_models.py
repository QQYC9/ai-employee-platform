from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.models.tenant import Tenant
from packages.models.domain import (
    Campaign,
    CampaignRecipient,
    Conversation,
    Customer,
    DispatchAttempt,
    DispatchAttemptChunk,
    Message,
    OutboxEvent,
    User,
)


@pytest.fixture
def test_setup_data(test_db_session: Session):
    """Creates isolated tenants, users, campaigns, recipients, and outbox events for testing."""
    # Tenant A
    tenant_a = Tenant(
        id=uuid.uuid4(),
        name="Tenant A CR01",
        slug=f"tenant-a-{uuid.uuid4().hex[:8]}",
    )
    # Tenant B
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Tenant B CR01",
        slug=f"tenant-b-{uuid.uuid4().hex[:8]}",
    )
    test_db_session.add_all([tenant_a, tenant_b])
    test_db_session.flush()

    # User for Tenant A
    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="User A",
        email=f"user-a-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_admin",
    )
    # User for Tenant B
    user_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        name="User B",
        email=f"user-b-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_admin",
    )
    test_db_session.add_all([user_a, user_b])
    test_db_session.flush()

    # Customer for Tenant A
    customer_a = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        phone=f"+1555{uuid.uuid4().hex[:7]}",
        name="Customer A",
    )
    # Customer for Tenant B
    customer_b = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        phone=f"+1555{uuid.uuid4().hex[:7]}",
        name="Customer B",
    )
    test_db_session.add_all([customer_a, customer_b])
    test_db_session.flush()

    # Conversation for Tenant A
    conv_a = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        customer_id=customer_a.id,
    )
    # Conversation for Tenant B
    conv_b = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        customer_id=customer_b.id,
    )
    test_db_session.add_all([conv_a, conv_b])
    test_db_session.flush()

    # Message for Tenant A
    msg_a = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        conversation_id=conv_a.id,
        customer_id=customer_a.id,
        sender_type="user",
        sender_id=user_a.id,
        message_type="text",
        content="Test outbound",
    )
    # Message for Tenant B
    msg_b = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        conversation_id=conv_b.id,
        customer_id=customer_b.id,
        sender_type="user",
        sender_id=user_b.id,
        message_type="text",
        content="Test outbound",
    )
    test_db_session.add_all([msg_a, msg_b])
    test_db_session.flush()

    # Campaign for Tenant A
    campaign_a = Campaign(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Campaign A",
        message_template="Hello from A",
    )
    # Campaign for Tenant B
    campaign_b = Campaign(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        name="Campaign B",
        message_template="Hello from B",
    )
    test_db_session.add_all([campaign_a, campaign_b])
    test_db_session.flush()

    # Recipient for Tenant A
    recipient_a = CampaignRecipient(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        campaign_id=campaign_a.id,
        customer_id=customer_a.id,
        recipient_address=customer_a.phone,
        message_id=msg_a.id,
        status="enqueued",
    )
    # Recipient for Tenant B
    recipient_b = CampaignRecipient(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        campaign_id=campaign_b.id,
        customer_id=customer_b.id,
        recipient_address=customer_b.phone,
        message_id=msg_b.id,
        status="enqueued",
    )
    test_db_session.add_all([recipient_a, recipient_b])
    test_db_session.flush()

    # OutboxEvent for Tenant A
    outbox_a = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        conversation_id=conv_a.id,
        message_id=msg_a.id,
        event_type="campaign_message",
        idempotency_key=f"outbox-{uuid.uuid4()}",
        payload={"campaign_id": str(campaign_a.id)},
        status="processing",
        claim_generation=1,
        dispatch_attempts_count=0,
    )
    # OutboxEvent for Tenant B
    outbox_b = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        conversation_id=conv_b.id,
        message_id=msg_b.id,
        event_type="campaign_message",
        idempotency_key=f"outbox-{uuid.uuid4()}",
        payload={"campaign_id": str(campaign_b.id)},
        status="processing",
        claim_generation=1,
        dispatch_attempts_count=0,
    )
    test_db_session.add_all([outbox_a, outbox_b])
    test_db_session.commit()

    yield {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "campaign_a": campaign_a,
        "campaign_b": campaign_b,
        "recipient_a": recipient_a,
        "recipient_b": recipient_b,
        "outbox_a": outbox_a,
        "outbox_b": outbox_b,
        "msg_a": msg_a,
        "msg_b": msg_b,
    }

    # Teardown: Clean up in reverse dependency order to satisfy ON DELETE RESTRICT
    test_db_session.rollback()
    test_db_session.execute(text("DELETE FROM dispatch_attempt_chunks;"))
    test_db_session.execute(text("DELETE FROM dispatch_attempts;"))
    test_db_session.execute(text("DELETE FROM campaign_recipients;"))
    test_db_session.execute(text("DELETE FROM campaigns;"))
    test_db_session.execute(text("DELETE FROM outbox_events;"))
    test_db_session.execute(text("DELETE FROM messages;"))
    test_db_session.execute(text("DELETE FROM conversations;"))
    test_db_session.execute(text("DELETE FROM customers;"))
    test_db_session.execute(text("DELETE FROM users WHERE email LIKE 'user-%@example.com';"))
    test_db_session.execute(text("DELETE FROM tenants WHERE slug LIKE 'tenant-%';"))
    test_db_session.commit()


def test_outbox_events_cr01_columns(test_db_session: Session, test_setup_data):
    """Verifies that outbox_events has claim_generation and dispatch_attempts_count."""
    outbox = test_setup_data["outbox_a"]
    refetched = test_db_session.get(OutboxEvent, outbox.id)
    assert refetched is not None
    assert refetched.claim_generation == 1
    assert refetched.dispatch_attempts_count == 0

    # Increment them
    refetched.claim_generation += 1
    refetched.dispatch_attempts_count += 1
    test_db_session.commit()

    reloaded = test_db_session.get(OutboxEvent, outbox.id)
    assert reloaded.claim_generation == 2
    assert reloaded.dispatch_attempts_count == 1


def test_dispatch_attempt_and_chunk_creation(test_db_session: Session, test_setup_data):
    """Verifies creating and querying DispatchAttempt and DispatchAttemptChunk."""
    data = test_setup_data
    attempt = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="worker-node-1",
        status="dispatching",
        dispatch_intent_at=datetime.now(timezone.utc),
    )
    test_db_session.add(attempt)
    test_db_session.flush()

    # Create chunk 0
    chunk_0 = DispatchAttemptChunk(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        attempt_id=attempt.id,
        chunk_index=0,
        status="dispatching",
    )
    test_db_session.add(chunk_0)
    test_db_session.commit()

    # Query back
    saved_attempt = test_db_session.get(DispatchAttempt, attempt.id)
    assert saved_attempt is not None
    assert saved_attempt.status == "dispatching"
    assert saved_attempt.worker_id == "worker-node-1"

    saved_chunk = test_db_session.get(DispatchAttemptChunk, chunk_0.id)
    assert saved_chunk is not None
    assert saved_chunk.chunk_index == 0
    assert saved_chunk.status == "dispatching"


def test_composite_foreign_key_cross_tenant_isolation(test_db_session: Session, test_setup_data):
    """Verifies that referencing a campaign/recipient from another tenant is strictly rejected."""
    data = test_setup_data

    # Attempt to create attempt for Tenant A referencing Tenant B's campaign
    cross_attempt = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_b"].id,  # Mismatched tenant!
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="malicious-worker",
        status="dispatching",
    )
    test_db_session.add(cross_attempt)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "fk_attempts_campaign_composite" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()

    # Attempt to create chunk for Tenant A referencing an attempt of Tenant B
    attempt_b = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_b"].id,
        campaign_id=data["campaign_b"].id,
        recipient_id=data["recipient_b"].id,
        outbox_event_id=data["outbox_b"].id,
        claim_generation=1,
        worker_id="worker-b",
        status="dispatching",
    )
    test_db_session.add(attempt_b)
    test_db_session.flush()

    # Cross-tenant chunk
    cross_chunk = DispatchAttemptChunk(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,  # Mismatched tenant!
        attempt_id=attempt_b.id,
        chunk_index=0,
        status="pending",
    )
    test_db_session.add(cross_chunk)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "fk_chunks_attempt_tenant_composite" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()


def test_unique_event_generation_constraint(test_db_session: Session, test_setup_data):
    """Verifies that an outbox event cannot have two attempts with the same claim_generation."""
    data = test_setup_data
    attempt_1 = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="worker-1",
        status="dispatching",
    )
    test_db_session.add(attempt_1)
    test_db_session.flush()

    # Duplicate attempt with same generation
    attempt_duplicate = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,  # Duplicate generation!
        worker_id="worker-2",
        status="dispatching",
    )
    test_db_session.add(attempt_duplicate)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "uq_dispatch_attempts_event_generation" in str(exc_info.value).lower() or "uniqueviolation" in str(exc_info.value).lower()


def test_unique_chunk_index_constraint(test_db_session: Session, test_setup_data):
    """Verifies that an attempt cannot have duplicate chunk indexes."""
    data = test_setup_data
    attempt = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="worker-1",
        status="dispatching",
    )
    test_db_session.add(attempt)
    test_db_session.flush()

    chunk_0a = DispatchAttemptChunk(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        attempt_id=attempt.id,
        chunk_index=0,
        status="pending",
    )
    test_db_session.add(chunk_0a)
    test_db_session.flush()

    chunk_0b = DispatchAttemptChunk(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        attempt_id=attempt.id,
        chunk_index=0,  # Duplicate chunk_index!
        status="pending",
    )
    test_db_session.add(chunk_0b)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "uq_chunk_attempt_index" in str(exc_info.value).lower() or "uniqueviolation" in str(exc_info.value).lower()


def test_check_constraints_enforcement(test_db_session: Session, test_setup_data):
    """Verifies CHECK constraints on status, outcome, and chunk_index."""
    data = test_setup_data

    # Invalid attempt status
    invalid_status_attempt = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="worker-1",
        status="illegal_status_value",  # CheckConstraint violation!
    )
    test_db_session.add(invalid_status_attempt)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "chk_attempt_status" in str(exc_info.value).lower() or "checkviolation" in str(exc_info.value).lower()

    # Valid attempt
    attempt = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="worker-1",
        status="dispatching",
    )
    test_db_session.add(attempt)
    test_db_session.flush()

    # Negative chunk_index
    negative_chunk = DispatchAttemptChunk(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        attempt_id=attempt.id,
        chunk_index=-1,  # CheckConstraint violation!
        status="pending",
    )
    test_db_session.add(negative_chunk)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "chk_chunk_index_positive" in str(exc_info.value).lower() or "checkviolation" in str(exc_info.value).lower()


def test_on_delete_restrict_preserves_audit_trail(test_db_session: Session, test_setup_data):
    """Verifies that an attempt cannot be deleted while child chunks exist (ON DELETE RESTRICT)."""
    data = test_setup_data
    attempt = DispatchAttempt(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        campaign_id=data["campaign_a"].id,
        recipient_id=data["recipient_a"].id,
        outbox_event_id=data["outbox_a"].id,
        claim_generation=1,
        worker_id="worker-1",
        status="accepted",
    )
    test_db_session.add(attempt)
    test_db_session.flush()

    chunk = DispatchAttemptChunk(
        id=uuid.uuid4(),
        tenant_id=data["tenant_a"].id,
        attempt_id=attempt.id,
        chunk_index=0,
        status="accepted",
    )
    test_db_session.add(chunk)
    test_db_session.commit()

    # Attempt to delete the parent attempt
    test_db_session.delete(attempt)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    test_db_session.rollback()
    assert "fk_chunks_attempt_tenant_composite" in str(exc_info.value).lower() or "foreignkeyviolation" in str(exc_info.value).lower()
