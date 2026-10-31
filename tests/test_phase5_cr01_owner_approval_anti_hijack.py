from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.models.tenant import Tenant
from packages.models.domain import (
    Approval,
    Conversation,
    Customer,
    Message,
    OutboxEvent,
    User,
)
from packages.services.approval_service import (
    ApprovalCancelledError,
    ApprovalExhaustedError,
    ApprovalExpiredError,
    ApprovalPayloadMismatchError,
    ApprovalService,
    ApprovalStateConflictError,
    ApprovalTokenMismatchError,
    FencingOwnershipLostError,
)
from packages.services.owner_intent_router import OwnerIntentRouter


@pytest.fixture
def cr01_test_data(test_db_session: Session):
    """Provisions isolated tenants, users, conversations, and messages for testing."""
    tenant_a = Tenant(
        id=uuid.uuid4(),
        name="Tenant CR05-01 A",
        slug=f"tenant-a-{uuid.uuid4().hex[:8]}",
    )
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Tenant CR05-01 B",
        slug=f"tenant-b-{uuid.uuid4().hex[:8]}",
    )
    test_db_session.add_all([tenant_a, tenant_b])
    test_db_session.flush()

    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Owner A",
        email=f"owner-a-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
    )
    user_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        name="Owner B",
        email=f"owner-b-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
    )
    test_db_session.add_all([user_a, user_b])
    test_db_session.flush()

    customer_a = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        phone=f"+1555{uuid.uuid4().hex[:7]}",
        name="Customer A",
    )
    test_db_session.add(customer_a)
    test_db_session.flush()

    conv_a = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        customer_id=customer_a.id,
    )
    test_db_session.add(conv_a)
    test_db_session.flush()

    msg_a = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        conversation_id=conv_a.id,
        customer_id=customer_a.id,
        sender_type="user",
        sender_id=user_a.id,
        content="Test incoming message",
    )
    test_db_session.add(msg_a)
    test_db_session.flush()

    yield {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "conv_a": conv_a,
        "msg_a": msg_a,
    }

    # Teardown
    test_db_session.rollback()
    test_db_session.query(OutboxEvent).delete()
    test_db_session.query(Approval).delete()
    test_db_session.query(Message).delete()
    test_db_session.query(Conversation).delete()
    test_db_session.query(Customer).delete()
    test_db_session.query(User).delete()
    test_db_session.query(Tenant).delete()
    test_db_session.commit()


# ===========================================================================
# 1. Challenge Security & Verification Tests
# ===========================================================================

def test_challenge_creation_and_hmac_storage(test_db_session: Session, cr01_test_data: dict):
    """Verifies that raw token is returned in memory and only HMAC-SHA256 is stored in DB."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="broadcast_campaign",
        description="Launch marketing campaign to 500 recipients",
        parameters={"campaign_id": "c1", "count": 500},
    )

    # 1. Raw code properties
    assert len(raw_code) == 6
    assert ApprovalService.CHALLENGE_REGEX.match(raw_code) is not None
    for char in raw_code:
        assert char in ApprovalService.CHALLENGE_ALPHABET

    # 2. Database storage verification: raw_code must NEVER be stored plaintext!
    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app is not None
    assert db_app.token != raw_code
    assert len(db_app.token) == 64  # SHA256 hex digest length
    assert ApprovalService.verify_token(raw_code, db_app.token, tenant_id) is True
    assert db_app.failed_attempts == 0
    assert db_app.max_attempts == 3
    assert db_app.status == "pending"
    assert db_app.execution_status == "not_started"


def test_challenge_successful_verification_and_atomic_outbox(test_db_session: Session, cr01_test_data: dict):
    """Verifies valid token transitions approval to 'approved' and enqueues Outbox atomically."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    params = {"target": "customers", "action": "notify"}
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="customer_notify",
        description="Notify customers",
        parameters=params,
    )

    approved_app = svc.verify_and_approve_challenge(
        tenant_id=tenant_id,
        approval_id=app.id,
        submitted_token=raw_code,
        decision_by_user_id=user_id,
        runtime_parameters=params,
    )

    assert approved_app.status == "approved"
    assert approved_app.execution_status == "queued"
    assert approved_app.decided_at is not None

    # Check atomic outbox event
    outbox_event = test_db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.approval_id == app.id,
            OutboxEvent.event_type == "approval_action_execution",
        )
    )
    assert outbox_event is not None
    assert outbox_event.idempotency_key == f"approval_exec:{app.id}"
    assert outbox_event.status == "pending"
    assert outbox_event.payload["payload_hash"] == app.payload_hash


def test_challenge_invalid_token_increments_attempts(test_db_session: Session, cr01_test_data: dict):
    """Verifies invalid token increments failed_attempts and does not approve."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="delete_records",
        description="Delete inactive records",
    )

    with pytest.raises(ApprovalTokenMismatchError) as exc_info:
        svc.verify_and_approve_challenge(
            tenant_id=tenant_id,
            approval_id=app.id,
            submitted_token="222222",  # Wrong token
            decision_by_user_id=user_id,
        )
    assert "2 attempt(s) remaining" in str(exc_info.value)

    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app.failed_attempts == 1
    assert db_app.status == "pending"


def test_challenge_exhaustion_after_three_failed_attempts(test_db_session: Session, cr01_test_data: dict):
    """Verifies that 3 failed attempts transition approval status to 'exhausted'."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="modify_pricing",
        description="Modify base price list",
    )

    # Attempt 1
    with pytest.raises(ApprovalTokenMismatchError):
        svc.verify_and_approve_challenge(tenant_id, app.id, "333333", user_id)
    # Attempt 2
    with pytest.raises(ApprovalTokenMismatchError):
        svc.verify_and_approve_challenge(tenant_id, app.id, "444444", user_id)
    # Attempt 3 -> Exhausted!
    with pytest.raises(ApprovalExhaustedError):
        svc.verify_and_approve_challenge(tenant_id, app.id, "555555", user_id)

    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app.failed_attempts == 3
    assert db_app.status == "exhausted"

    # Attempt 4 (even with correct code) must be rejected
    with pytest.raises(ApprovalExhaustedError):
        svc.verify_and_approve_challenge(tenant_id, app.id, raw_code, user_id)


def test_challenge_expired_token_rejected(test_db_session: Session, cr01_test_data: dict):
    """Verifies that an expired challenge transitions to 'expired' and rejects verification."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="billing_update",
        description="Update subscription",
        expires_in_minutes=-1,  # Already expired
    )

    with pytest.raises(ApprovalExpiredError):
        svc.verify_and_approve_challenge(tenant_id, app.id, raw_code, user_id)

    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app.status == "expired"


def test_challenge_cancelled_rejected(test_db_session: Session, cr01_test_data: dict):
    """Verifies that cancelled approval rejects verification."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="export_data",
        description="Export customer database",
    )
    svc.cancel(tenant_id, app.id, user_id=user_id, user_role="tenant_owner")

    with pytest.raises(ApprovalCancelledError):
        svc.verify_and_approve_challenge(tenant_id, app.id, raw_code, user_id)


# ===========================================================================
# 2. Payload Binding & Tampering Prevention Tests
# ===========================================================================

def test_payload_tampering_cancels_approval(test_db_session: Session, cr01_test_data: dict):
    """Verifies that modifying payload parameters invalidates the approval."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    original_params = {"action": "delete_inactive", "days": 90}
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="delete_inactive_users",
        description="Delete users inactive for 90 days",
        parameters=original_params,
    )

    # Attempt verification with altered parameters (e.g. days changed to 30)
    tampered_params = {"action": "delete_inactive", "days": 30}
    with pytest.raises(ApprovalPayloadMismatchError):
        svc.verify_and_approve_challenge(
            tenant_id=tenant_id,
            approval_id=app.id,
            submitted_token=raw_code,
            decision_by_user_id=user_id,
            runtime_parameters=tampered_params,
        )

    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app.status == "cancelled"
    assert "Payload mismatch" in (db_app.decision_reason or "")


def test_cross_tenant_approval_isolation(test_db_session: Session, cr01_test_data: dict):
    """Verifies tenant B cannot verify or approve tenant A's challenge."""
    svc = ApprovalService(test_db_session)
    tenant_a_id = cr01_test_data["tenant_a"].id
    tenant_b_id = cr01_test_data["tenant_b"].id
    user_b_id = cr01_test_data["user_b"].id

    app_a, raw_code_a = svc.create_approval_challenge(
        tenant_id=tenant_a_id,
        requested_for="tenant_owner",
        action="sensitive_op",
        description="Tenant A sensitive op",
    )

    with pytest.raises(PermissionError) as exc_info:
        svc.verify_and_approve_challenge(
            tenant_id=tenant_b_id,  # Tenant B trying to approve Tenant A's approval
            approval_id=app_a.id,
            submitted_token=raw_code_a,
            decision_by_user_id=user_b_id,
        )
    assert "Cross-tenant access prohibited" in str(exc_info.value)


# ===========================================================================
# 3. Router Intent & Bare Affirmation Non-Disclosure Tests
# ===========================================================================

def test_bare_affirmation_does_not_reveal_token(test_db_session: Session, cr01_test_data: dict):
    """Verifies that sending bare 'نعم' when approval is pending NEVER discloses the challenge code."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="bulk_delete",
        description="Delete all test data",
    )

    router = OwnerIntentRouter(test_db_session)
    contract = router.parse_intent("نعم", tenant_id=tenant_id, actor_id=user_id)

    # 1. Must be classified as bare_affirmation_blocked
    assert contract.intent == "bare_affirmation_blocked"
    assert contract.clarification_required is True

    # 2. Must NEVER disclose the raw token in clarification question!
    question = contract.clarification_question or ""
    assert raw_code not in question
    assert str(app.id) in question
    assert "نعم XXXXXX" in question


def test_challenge_command_routing_and_approval(test_db_session: Session, cr01_test_data: dict):
    """Verifies that sending 'نعم <CODE>' routes correctly and approves the challenge."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="confirm_campaign",
        description="Confirm marketing broadcast",
    )

    router = OwnerIntentRouter(test_db_session)
    # Owner sends: "نعم 4A7F2K"
    contract = router.parse_intent(f"نعم {raw_code}", tenant_id=tenant_id, actor_id=user_id)

    assert contract.intent == "challenge_response"
    assert contract.entities.get("token") == raw_code
    assert contract.entities.get("action") == "approve"

    # Execute plan
    res = router.execute_plan(contract, conversation_id=uuid.uuid4(), message_id=uuid.uuid4(), engine=None)
    assert res.success is True
    assert "تم التحقق من رمز التأكيد بنجاح" in res.reply_text

    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app.status == "approved"
    assert db_app.execution_status == "queued"


# ===========================================================================
# 4. Atomicity, Fencing & Concurrency Tests
# ===========================================================================

def test_atomic_result_recording_checks_both_rowcounts(test_db_session: Session, cr01_test_data: dict):
    """Verifies record_execution_result verifies rowcount == 1 on both outbox and approvals."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="atomic_test_action",
        description="Testing atomic result update",
    )
    svc.verify_and_approve_challenge(tenant_id, app.id, raw_code, user_id)

    outbox = test_db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.approval_id == app.id)
    )
    assert outbox is not None

    # Transition approval to executing
    app.execution_status = "executing"
    test_db_session.flush()

    # 1. Normal success: both rowcounts == 1
    svc.record_execution_result(
        tenant_id=tenant_id,
        approval_id=app.id,
        outbox_event_id=outbox.id,
        claim_generation=outbox.claim_generation,
        is_success=True,
    )
    test_db_session.flush()

    assert outbox.status == "completed"
    assert app.execution_status == "completed"


def test_stale_worker_fencing_aborts_result_recording(test_db_session: Session, cr01_test_data: dict):
    """Verifies that a stale worker with outdated claim_generation fails with FencingOwnershipLostError."""
    svc = ApprovalService(test_db_session)
    tenant_id = cr01_test_data["tenant_a"].id
    user_id = cr01_test_data["user_a"].id

    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="fencing_test",
        description="Testing stale worker fencing",
    )
    svc.verify_and_approve_challenge(tenant_id, app.id, raw_code, user_id)

    outbox = test_db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.approval_id == app.id)
    )
    assert outbox is not None

    app.execution_status = "executing"
    test_db_session.flush()

    # Worker A claimed generation 0, but another worker incremented it to 1!
    outbox.claim_generation = 1
    test_db_session.flush()

    # Stale Worker A attempts to record result with expected gen 0 -> must raise FencingOwnershipLostError!
    with pytest.raises(FencingOwnershipLostError):
        svc.record_execution_result(
            tenant_id=tenant_id,
            approval_id=app.id,
            outbox_event_id=outbox.id,
            claim_generation=0,  # Outdated generation!
            is_success=True,
        )

    # State must not be updated by stale worker
    assert outbox.status == "pending"
    assert app.execution_status == "executing"


def test_outbox_unique_execution_event_per_approval(test_db_session: Session, cr01_test_data: dict):
    """Verifies partial unique index uq_outbox_tenant_approval_execution prevents duplicate execution events."""
    tenant_id = cr01_test_data["tenant_a"].id

    app = Approval(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="unique_test",
        description="Testing partial unique index",
        status="approved",
    )
    test_db_session.add(app)
    test_db_session.flush()

    event1 = OutboxEvent(
        tenant_id=tenant_id,
        approval_id=app.id,
        event_type="approval_action_execution",
        idempotency_key=f"exec:1:{app.id}",
        payload={},
    )
    test_db_session.add(event1)
    test_db_session.flush()

    # Second event for same (tenant_id, approval_id) must fail with IntegrityError (UniqueViolation)
    event2 = OutboxEvent(
        tenant_id=tenant_id,
        approval_id=app.id,
        event_type="approval_action_execution",
        idempotency_key=f"exec:2:{app.id}",
        payload={},
    )
    test_db_session.add(event2)
    with pytest.raises(IntegrityError):
        test_db_session.flush()

    test_db_session.rollback()


# ===========================================================================
# 5. Idempotency Window & Ambiguity Evaluation Tests
# ===========================================================================

def test_evaluate_retry_eligibility():
    """Verifies safe retry evaluation rules and fallback to reconciliation_required."""
    now = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    first_attempt = now - timedelta(hours=1)
    retention_24h = timedelta(hours=24)

    # 1. Confirmed processed -> never retry, mark completed
    can_retry, status = ApprovalService.evaluate_retry_eligibility(
        first_attempt, retention_24h, "confirmed_processed", now=now
    )
    assert can_retry is False
    assert status == "completed"

    # 2. Confirmed not processed within 24h window -> retry allowed
    can_retry, status = ApprovalService.evaluate_retry_eligibility(
        first_attempt, retention_24h, "confirmed_not_processed", now=now
    )
    assert can_retry is True
    assert status == "queued"

    # 3. Outcome unknown (timeout/socket drop) -> halt and reconcile
    can_retry, status = ApprovalService.evaluate_retry_eligibility(
        first_attempt, retention_24h, "outcome_unknown", now=now
    )
    assert can_retry is False
    assert status == "reconciliation_required"

    # 4. Retention deadline expired (e.g. 25 hours later) -> halt and reconcile
    expired_attempt = now - timedelta(hours=25)
    can_retry, status = ApprovalService.evaluate_retry_eligibility(
        expired_attempt, retention_24h, "confirmed_not_processed", now=now
    )
    assert can_retry is False
    assert status == "reconciliation_required"

    # 5. Missing first_external_attempt_at -> halt and reconcile
    can_retry, status = ApprovalService.evaluate_retry_eligibility(
        None, retention_24h, "confirmed_not_processed", now=now
    )
    assert can_retry is False
    assert status == "reconciliation_required"
