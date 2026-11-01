from __future__ import annotations

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import packages.core.database as core_db
from packages.models.tenant import Tenant
from packages.models.domain import Approval, OutboxEvent, User
from packages.services.approval_service import ApprovalService
from packages.services.outbox_worker import OutboxWorker
from packages.tools.executor import ToolExecutor


@pytest.fixture
def approval_exec_test_data(test_db_session: Session):
    """Provisions isolated tenants, users, and session factory for approval execution tests."""
    tenant_a = Tenant(
        id=uuid.uuid4(),
        name="Approval Exec Tenant A",
        slug=f"app-exec-a-{uuid.uuid4().hex[:8]}",
    )
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Approval Exec Tenant B",
        slug=f"app-exec-b-{uuid.uuid4().hex[:8]}",
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
    test_db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
    }


def test_approved_action_executed_through_real_tool_executor(
    test_db_session: Session, approval_exec_test_data: dict
):
    """1 & 7: Verifies approved action is reachable via OutboxWorker dispatch and executed via ToolExecutor."""
    tenant_id = approval_exec_test_data["tenant_a"].id
    user_id = approval_exec_test_data["user_a"].id

    svc = ApprovalService(test_db_session)
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="customer_credit_adjustment",
        description="Adjust customer balance after dispute",
        parameters={"customer_id": "cust-123", "amount": 500, "currency": "SAR"},
    )
    test_db_session.commit()

    # Verify and approve challenge -> enqueues OutboxEvent
    approved_app = svc.verify_and_approve_challenge(
        tenant_id=tenant_id,
        approval_id=app.id,
        submitted_token=raw_code,
        decision_by_user_id=user_id,
        runtime_parameters={"customer_id": "cust-123", "amount": 500, "currency": "SAR"},
    )
    test_db_session.commit()

    outbox_event = test_db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.approval_id == app.id,
            OutboxEvent.event_type == "approval_action_execution",
        )
    )
    assert outbox_event is not None
    assert outbox_event.status == "pending"

    # Set up ToolExecutor with real handler
    executed_calls = []

    def credit_adjustment_handler(**kwargs):
        executed_calls.append(kwargs)
        return {"adjusted": True, "new_balance": 1500}

    executor = ToolExecutor(test_db_session)
    executor.register_handler("customer_credit_adjustment", credit_adjustment_handler)

    # Initialize OutboxWorker with tool_executor
    worker = OutboxWorker(
        tenant_id=tenant_id,
        session_factory=core_db.SessionLocal,
        tool_executor=executor,
    )

    # Dispatch through real worker loop
    processed = worker.run_once()
    assert processed >= 1

    # Verify tool was actually executed
    assert len(executed_calls) == 1
    call_kwargs = executed_calls[0]
    assert call_kwargs["customer_id"] == "cust-123"
    assert call_kwargs["amount"] == 500
    assert call_kwargs["currency"] == "SAR"
    assert "_context" in call_kwargs
    assert call_kwargs["_context"].tenant_id == tenant_id

    # Refresh states from DB
    test_db_session.expire_all()
    refreshed_app = test_db_session.get(Approval, app.id)
    refreshed_event = test_db_session.get(OutboxEvent, outbox_event.id)

    assert refreshed_app.execution_status == "completed"
    assert refreshed_event.status == "completed"


def test_tool_failure_recorded_as_failure_never_success(
    test_db_session: Session, approval_exec_test_data: dict
):
    """2 & 5: Verifies that tool execution failure is recorded as failure and never as success."""
    tenant_id = approval_exec_test_data["tenant_a"].id
    user_id = approval_exec_test_data["user_a"].id

    svc = ApprovalService(test_db_session)
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="failing_gateway_sync",
        description="Sync to external payment gateway",
        parameters={"gateway": "hypothetical_pay", "sync_id": 999},
    )
    test_db_session.commit()

    svc.verify_and_approve_challenge(
        tenant_id=tenant_id,
        approval_id=app.id,
        submitted_token=raw_code,
        decision_by_user_id=user_id,
        runtime_parameters={"gateway": "hypothetical_pay", "sync_id": 999},
    )
    test_db_session.commit()

    outbox_event = test_db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.approval_id == app.id,
            OutboxEvent.event_type == "approval_action_execution",
        )
    )
    assert outbox_event is not None

    def failing_tool_handler(**kwargs):
        raise RuntimeError("Payment gateway returned HTTP 502 Bad Gateway")

    executor = ToolExecutor(test_db_session)
    executor.register_handler("failing_gateway_sync", failing_tool_handler)

    worker = OutboxWorker(
        tenant_id=tenant_id,
        session_factory=core_db.SessionLocal,
        tool_executor=executor,
    )

    worker.run_once()

    test_db_session.expire_all()
    refreshed_app = test_db_session.get(Approval, app.id)
    refreshed_event = test_db_session.get(OutboxEvent, outbox_event.id)

    # Must be recorded as failed, NEVER completed
    assert refreshed_app.execution_status == "failed"
    assert "HTTP 502 Bad Gateway" in (refreshed_app.decision_reason or "")
    assert refreshed_event.status == "failed"
    assert "HTTP 502 Bad Gateway" in (refreshed_event.error_message or "")


def test_unapproved_or_invalid_approval_not_executed(
    test_db_session: Session, approval_exec_test_data: dict
):
    """3: Verifies unapproved (pending) approval cannot be executed via Outbox."""
    tenant_id = approval_exec_test_data["tenant_a"].id

    svc = ApprovalService(test_db_session)
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="unapproved_action",
        description="Dangerous action not yet approved",
        parameters={"danger": True},
    )
    test_db_session.commit()

    # Manually create outbox event while approval is still 'pending'
    outbox_event = OutboxEvent(
        tenant_id=tenant_id,
        approval_id=app.id,
        event_type="approval_action_execution",
        idempotency_key=f"unapproved:{app.id}",
        payload={"approval_id": str(app.id), "action": "unapproved_action"},
        status="pending",
    )
    test_db_session.add(outbox_event)
    test_db_session.commit()

    executed_calls = []
    executor = ToolExecutor(test_db_session)
    executor.register_handler("unapproved_action", lambda **kw: executed_calls.append(kw))

    worker = OutboxWorker(
        tenant_id=tenant_id,
        session_factory=core_db.SessionLocal,
        tool_executor=executor,
    )

    worker.run_once()

    assert len(executed_calls) == 0

    test_db_session.expire_all()
    refreshed_app = test_db_session.get(Approval, app.id)
    refreshed_event = test_db_session.get(OutboxEvent, outbox_event.id)

    assert refreshed_app.status == "pending"
    assert refreshed_app.execution_status == "not_started"
    assert refreshed_event.status == "failed"


def test_wrong_tenant_approval_rejected(
    test_db_session: Session, approval_exec_test_data: dict
):
    """4: Verifies cross-tenant approval execution is rejected."""
    tenant_a_id = approval_exec_test_data["tenant_a"].id
    tenant_b_id = approval_exec_test_data["tenant_b"].id
    user_a_id = approval_exec_test_data["user_a"].id

    svc = ApprovalService(test_db_session)
    app_a, raw_code_a = svc.create_approval_challenge(
        tenant_id=tenant_a_id,
        requested_for="tenant_owner",
        action="tenant_a_secret_op",
        description="Tenant A confidential action",
        parameters={"secret": "confidential_data"},
    )
    test_db_session.commit()

    svc.verify_and_approve_challenge(
        tenant_id=tenant_a_id,
        approval_id=app_a.id,
        submitted_token=raw_code_a,
        decision_by_user_id=user_a_id,
    )
    test_db_session.commit()

    # 1. DB Check Constraint Defense: approval_id cannot be null for approval_action_execution
    null_app_event = OutboxEvent(
        tenant_id=tenant_b_id,
        approval_id=None,
        event_type="approval_action_execution",
        idempotency_key=f"db-check-null:{app_a.id}",
        payload={},
        status="pending",
    )
    test_db_session.add(null_app_event)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    assert "ck_outbox_approval_execution_requires_approval_id" in str(exc_info.value)
    test_db_session.rollback()

    # 2. DB Composite Foreign Key Defense: (tenant_id, approval_id) must belong to same tenant
    invalid_fk_event = OutboxEvent(
        tenant_id=tenant_b_id,
        approval_id=app_a.id,
        event_type="approval_action_execution",
        idempotency_key=f"db-fk-violation:{app_a.id}",
        payload={},
        status="pending",
    )
    test_db_session.add(invalid_fk_event)
    with pytest.raises(IntegrityError) as exc_info:
        test_db_session.flush()
    assert "fk_outbox_events_approval_composite" in str(exc_info.value)
    test_db_session.rollback()

    # 3. Worker-Level Defense: _handle_approval_action_execution rejects foreign approval
    executed_calls = []
    executor = ToolExecutor(test_db_session)
    executor.register_handler("tenant_a_secret_op", lambda **kw: executed_calls.append(kw))

    worker = OutboxWorker(
        tenant_id=tenant_b_id,
        session_factory=core_db.SessionLocal,
        tool_executor=executor,
    )

    simulated_rogue_event = OutboxEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_b_id,
        approval_id=app_a.id,
        event_type="approval_action_execution",
        idempotency_key=f"sim-rogue:{app_a.id}",
        payload={"action": "tenant_a_secret_op"},
        status="pending",
    )

    proceeded = worker._handle_approval_action_execution(test_db_session, simulated_rogue_event)
    assert proceeded is False
    assert len(executed_calls) == 0


def test_retrying_completed_approval_does_not_duplicate_tool_execution(
    test_db_session: Session, approval_exec_test_data: dict
):
    """6: Verifies retrying the same Outbox event does not cause duplicate execution."""
    tenant_id = approval_exec_test_data["tenant_a"].id
    user_id = approval_exec_test_data["user_a"].id

    svc = ApprovalService(test_db_session)
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="idempotent_billing_charge",
        description="Charge one-time enterprise fee",
        parameters={"charge_id": "chg-101", "cents": 25000},
    )
    test_db_session.commit()

    svc.verify_and_approve_challenge(
        tenant_id=tenant_id,
        approval_id=app.id,
        submitted_token=raw_code,
        decision_by_user_id=user_id,
        runtime_parameters={"charge_id": "chg-101", "cents": 25000},
    )
    test_db_session.commit()

    outbox_event = test_db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.approval_id == app.id,
            OutboxEvent.event_type == "approval_action_execution",
        )
    )

    call_count = [0]

    def billing_handler(**kwargs):
        call_count[0] += 1
        return {"charged": True, "tx_id": "tx-999"}

    executor = ToolExecutor(test_db_session)
    executor.register_handler("idempotent_billing_charge", billing_handler)

    worker = OutboxWorker(
        tenant_id=tenant_id,
        session_factory=core_db.SessionLocal,
        tool_executor=executor,
    )

    # First run -> executes tool
    worker.run_once()
    assert call_count[0] == 1

    test_db_session.expire_all()
    refreshed_app = test_db_session.get(Approval, app.id)
    refreshed_event = test_db_session.get(OutboxEvent, outbox_event.id)
    assert refreshed_app.execution_status == "completed"
    assert refreshed_event.status == "completed"

    # Simulate worker crash / retry: reset outbox event back to pending
    refreshed_event.status = "pending"
    test_db_session.commit()

    # Second run -> should detect already-completed approval and NOT re-run tool!
    worker.run_once()

    # Tool must NOT be called a second time
    assert call_count[0] == 1

    test_db_session.expire_all()
    re_refreshed_event = test_db_session.get(OutboxEvent, outbox_event.id)
    assert re_refreshed_event.status == "completed"


def test_missing_action_handler_fails_and_records_failure(
    test_db_session: Session, approval_exec_test_data: dict
):
    """Verifies that an approved action with no registered handler fails safely."""
    tenant_id = approval_exec_test_data["tenant_a"].id
    user_id = approval_exec_test_data["user_a"].id

    svc = ApprovalService(test_db_session)
    app, raw_code = svc.create_approval_challenge(
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="non_existent_tool_action",
        description="Action that has no registered handler",
    )
    test_db_session.commit()

    svc.verify_and_approve_challenge(
        tenant_id=tenant_id,
        approval_id=app.id,
        submitted_token=raw_code,
        decision_by_user_id=user_id,
    )
    test_db_session.commit()

    outbox_event = test_db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.approval_id == app.id,
            OutboxEvent.event_type == "approval_action_execution",
        )
    )

    # Executor with NO handler registered for non_existent_tool_action
    executor = ToolExecutor(test_db_session)

    worker = OutboxWorker(
        tenant_id=tenant_id,
        session_factory=core_db.SessionLocal,
        tool_executor=executor,
    )

    worker.run_once()

    test_db_session.expire_all()
    refreshed_app = test_db_session.get(Approval, app.id)
    refreshed_event = test_db_session.get(OutboxEvent, outbox_event.id)

    assert refreshed_app.execution_status == "failed"
    assert "No execution handler registered" in (refreshed_app.decision_reason or "")
    assert refreshed_event.status == "failed"
