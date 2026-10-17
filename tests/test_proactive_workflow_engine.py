from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import (
    Agent,
    DailyReport,
    OutboxEvent,
    ProactiveWorkflow,
    Task,
    User,
    WorkflowRun,
    WorkflowTriggerEvent,
)
from packages.models.tenant import Tenant
from packages.services.outbox_worker import OutboxWorker
from packages.services.proactive_workflow_service import ProactiveWorkflowService, calculate_next_run


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def clean_workflow_tables(db: Session):
    """Ensure clean slate for workflow and outbox tables."""
    db.query(WorkflowRun).delete()
    db.query(WorkflowTriggerEvent).delete()
    db.query(ProactiveWorkflow).delete()
    db.query(OutboxEvent).delete()
    db.commit()
    yield
    db.query(WorkflowRun).delete()
    db.query(WorkflowTriggerEvent).delete()
    db.query(ProactiveWorkflow).delete()
    db.query(OutboxEvent).delete()
    db.commit()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def tenant_a(db: Session):
    t = Tenant(name="Proactive Tenant A", slug=f"proact-a-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(name="Proactive Tenant B", slug=f"proact-b-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def agent_a(db: Session, tenant_a: Tenant):
    a = Agent(
        tenant_id=tenant_a.id,
        name="Sales Followup Bot",
        agent_type="main",
        status="active",
        system_config={"persona": "Sales Executive"},
    )
    db.add(a)
    db.commit()
    return a


@pytest.fixture
def user_a(db: Session, tenant_a: Tenant):
    u = User(
        tenant_id=tenant_a.id,
        name="Alice Admin",
        email=f"alice-{uuid.uuid4().hex[:6]}@proactive.com",
        role="tenant_admin",
        status="active",
    )
    db.add(u)
    db.commit()
    return u


def test_create_workflow_schedule_and_validation(db: Session, tenant_a: Tenant, agent_a: Agent):
    service = ProactiveWorkflowService(db)

    # 1. Valid interval workflow
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        agent_id=agent_a.id,
        name="Hourly Pipeline Monitor",
        action_type="run_task",
        trigger_type="interval",
        schedule_type="interval",
        interval_seconds=3600,
        timezone_name="Asia/Riyadh",
    )
    assert wf.id is not None
    assert wf.status == "active"
    assert wf.next_run_at is not None
    assert wf.timezone == "Asia/Riyadh"

    # 2. Rejection of invalid types
    with pytest.raises(ValueError, match="Invalid trigger_type"):
        service.create_workflow(tenant_id=tenant_a.id, name="Bad", trigger_type="unsupported")

    with pytest.raises(ValueError, match="Invalid action_type"):
        service.create_workflow(tenant_id=tenant_a.id, name="Bad", action_type="hack_system")


def test_recurring_workflow_next_run_calculation():
    now = datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc)

    # Interval 1800s (30m)
    next_time = calculate_next_run("interval", interval_seconds=1800, from_time=now)
    assert next_time == now + timedelta(seconds=1800)

    # Daily cron at 09:00
    cron_next = calculate_next_run("cron", cron_expression="0 9 * * *", tz_name="UTC", from_time=now)
    assert cron_next == datetime(2026, 10, 18, 9, 0, 0, tzinfo=timezone.utc)


def test_spawn_due_workflow_runs(db: Session, tenant_a: Tenant, agent_a: Agent):
    service = ProactiveWorkflowService(db)
    now = datetime.now(timezone.utc)

    # Workflow due right now
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        agent_id=agent_a.id,
        name="Due Workflow",
        interval_seconds=60,
        start_immediately=True,
    )
    assert wf.next_run_at <= datetime.now(timezone.utc) + timedelta(seconds=2)

    spawned = service.spawn_due_workflow_runs(limit=10)
    assert spawned == 1

    runs = service.list_runs(tenant_a.id, workflow_id=wf.id)
    assert len(runs) == 1
    assert runs[0].status == "pending"

    # Workflow next_run_at was advanced
    db.refresh(wf)
    assert wf.next_run_at > now


def test_duplicate_run_prevention_and_idempotency(db: Session, tenant_a: Tenant):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(tenant_id=tenant_a.id, name="Idempotent WF")

    fixed_time = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    idemp_key = f"fixed-key-{wf.id}"

    run1 = service.enqueue_run(
        tenant_id=tenant_a.id,
        workflow_id=wf.id,
        scheduled_at=fixed_time,
        idempotency_key=idemp_key,
    )
    db.commit()

    # Second enqueue with identical key must return existing run
    run2 = service.enqueue_run(
        tenant_id=tenant_a.id,
        workflow_id=wf.id,
        scheduled_at=fixed_time,
        idempotency_key=idemp_key,
    )
    assert run1.id == run2.id

    runs = service.list_runs(tenant_a.id, workflow_id=wf.id)
    assert len(runs) == 1


def test_claim_due_runs_with_concurrency_locks(db: Session, tenant_a: Tenant):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(tenant_id=tenant_a.id, name="Claim Test")

    now = datetime.now(timezone.utc)
    service.enqueue_run(tenant_id=tenant_a.id, workflow_id=wf.id, scheduled_at=now)
    db.commit()

    claimed = service.claim_due_runs(worker_id="worker-node-1", batch_size=5)
    assert len(claimed) == 1
    assert claimed[0].status == "running"
    assert claimed[0].locked_by == "worker-node-1"
    assert claimed[0].lock_expires_at is not None

    # A second worker cannot claim the already locked run
    claimed2 = service.claim_due_runs(worker_id="worker-node-2", batch_size=5)
    assert len(claimed2) == 0


def test_execute_run_run_task_action(db: Session, tenant_a: Tenant, agent_a: Agent):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        agent_id=agent_a.id,
        name="Auto Task WF",
        action_type="run_task",
        action_payload={"title": "Automated Quote Checkup", "objective": "Review pending quotes"},
        start_immediately=True,
    )
    service.spawn_due_workflow_runs()
    claimed = service.claim_due_runs(worker_id="w1")
    assert len(claimed) == 1

    success = service.execute_run(claimed[0].id)
    assert success is True

    db.refresh(claimed[0])
    assert claimed[0].status == "completed"
    assert claimed[0].task_id is not None
    assert claimed[0].result.get("task_id") == str(claimed[0].task_id)


def test_execute_run_generate_daily_report_action(db: Session, tenant_a: Tenant, agent_a: Agent):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        agent_id=agent_a.id,
        name="Daily Briefing",
        action_type="generate_daily_report",
        start_immediately=True,
    )
    service.spawn_due_workflow_runs()
    claimed = service.claim_due_runs(worker_id="w1")
    assert len(claimed) == 1

    success = service.execute_run(claimed[0].id)
    assert success is True

    db.refresh(claimed[0])
    assert claimed[0].status == "completed"
    report_id = claimed[0].result.get("report_id")
    assert report_id is not None

    report = db.scalar(select(DailyReport).where(DailyReport.id == uuid.UUID(report_id)))
    assert report is not None
    assert report.tenant_id == tenant_a.id


def test_execute_run_check_overdue_tasks_action(db: Session, tenant_a: Tenant):
    # Create an existing pending task
    task = Task(
        tenant_id=tenant_a.id,
        title="Existing Task",
        objective="Follow up",
        status="pending",
    )
    db.add(task)
    db.commit()

    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        name="Overdue Monitor",
        action_type="check_overdue_tasks",
        start_immediately=True,
    )
    service.spawn_due_workflow_runs()
    claimed = service.claim_due_runs(worker_id="w1")
    assert len(claimed) == 1

    success = service.execute_run(claimed[0].id)
    assert success is True
    assert claimed[0].result.get("overdue_count") >= 1


def test_stale_run_recovery_after_worker_crash(db: Session, tenant_a: Tenant):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(tenant_id=tenant_a.id, name="Crash Test")

    run = service.enqueue_run(tenant_id=tenant_a.id, workflow_id=wf.id)
    run.status = "running"
    run.locked_by = "crashed-worker"
    # Set lock expired 10 minutes ago
    run.locked_at = datetime.now(timezone.utc) - timedelta(minutes=15)
    run.lock_expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()

    recovered = service.recover_stale_runs(stale_threshold_seconds=60)
    assert recovered == 1

    db.refresh(run)
    assert run.status == "pending"
    assert run.locked_by is None
    assert run.attempt_count == 1


def test_bounded_retries_and_terminal_failure(db: Session, tenant_a: Tenant):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        name="Fail Test",
        max_retries=2,
        action_payload={"force_failure": True},
    )

    run = service.enqueue_run(tenant_id=tenant_a.id, workflow_id=wf.id)
    run.status = "running"
    run.max_attempts = 2
    run.attempt_count = 1  # Next fail hits 2 (terminal)
    db.commit()

    success = service.execute_run(run.id)
    assert success is False

    db.refresh(run)
    assert run.status == "failed"
    assert "Forced execution failure" in run.error_message


def test_pause_resume_and_cancellation(db: Session, tenant_a: Tenant):
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(tenant_id=tenant_a.id, name="Lifecycle Test")

    # Pause
    paused = service.pause_workflow(tenant_a.id, wf.id)
    assert paused.status == "paused"
    assert paused.is_active is False

    # Resume
    resumed = service.resume_workflow(tenant_a.id, wf.id)
    assert resumed.status == "active"
    assert resumed.is_active is True

    # Cancel
    cancelled = service.cancel_workflow(tenant_a.id, wf.id)
    assert cancelled.status == "cancelled"
    assert cancelled.next_run_at is None


def test_triggers_layer_event_ingestion_and_idempotency(db: Session, tenant_a: Tenant):
    service = ProactiveWorkflowService(db)

    # Workflow listening to event
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        name="Quote Notification Workflow",
        trigger_type="event",
        action_payload={"event_type": "quote_sent"},
    )

    # Fire trigger event
    event = service.fire_trigger_event(
        tenant_id=tenant_a.id,
        event_type="quote_sent",
        source_id="quote-12345",
        payload={"amount": 25000, "customer": "Acme Corp"},
        idempotency_key="quote-event-unique-123",
    )
    assert event.status == "processed"

    # Verify a run was generated for the matching workflow
    runs = service.list_runs(tenant_a.id, workflow_id=wf.id)
    assert len(runs) == 1
    assert runs[0].trigger_source == "event"

    # Repeated event with same key returns existing without spawning new run
    event2 = service.fire_trigger_event(
        tenant_id=tenant_a.id,
        event_type="quote_sent",
        source_id="quote-12345",
        idempotency_key="quote-event-unique-123",
    )
    assert event.id == event2.id
    runs_after = service.list_runs(tenant_a.id, workflow_id=wf.id)
    assert len(runs_after) == 1


def test_tenant_isolation_on_workflows_and_runs(db: Session, tenant_a: Tenant, tenant_b: Tenant):
    service = ProactiveWorkflowService(db)

    wf_a = service.create_workflow(tenant_id=tenant_a.id, name="Tenant A WF")
    wf_b = service.create_workflow(tenant_id=tenant_b.id, name="Tenant B WF")

    # Tenant A cannot see Tenant B's workflow
    assert service.get_workflow(tenant_a.id, wf_b.id) is None
    assert service.get_workflow(tenant_b.id, wf_a.id) is None

    # Cross-tenant pause is rejected
    with pytest.raises(ValueError):
        service.pause_workflow(tenant_a.id, wf_b.id)


def test_outbox_worker_unification_processes_both_messages_and_workflows(
    db: Session, tenant_a: Tenant, agent_a: Agent
):
    """
    Verify that OutboxWorker.run_once seamlessly processes both outbox customer messages
    AND proactive workflow runs in a unified poll iteration.
    """
    service = ProactiveWorkflowService(db)
    wf = service.create_workflow(
        tenant_id=tenant_a.id,
        agent_id=agent_a.id,
        name="Worker Unified Test",
        action_type="check_overdue_tasks",
        start_immediately=True,
    )
    db.commit()

    worker = OutboxWorker(worker_id="test-unified-worker")
    processed = worker.run_once()
    assert processed >= 1

    runs = service.list_runs(tenant_a.id, workflow_id=wf.id)
    assert len(runs) == 1
    assert runs[0].status == "completed"


def test_proactive_workflow_api_crud_and_trigger(client: TestClient, user_a: User, tenant_a: Tenant):
    from packages.auth.jwt_service import create_access_token
    token = create_access_token(user_id=user_a.id, tenant_id=tenant_a.id, role=user_a.role)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Workflow via API
    resp = client.post(
        "/api/v1/workflows",
        headers=headers,
        json={
            "name": "API Created Workflow",
            "trigger_type": "interval",
            "schedule_type": "interval",
            "interval_seconds": 600,
            "action_type": "check_overdue_tasks",
        },
    )
    assert resp.status_code == 201
    wf_id = resp.json()["id"]

    # 2. List Workflows
    list_resp = client.get("/api/v1/workflows", headers=headers)
    assert list_resp.status_code == 200
    assert any(w["id"] == wf_id for w in list_resp.json())

    # 3. Trigger manual run via API
    trig_resp = client.post(f"/api/v1/workflows/{wf_id}/trigger", headers=headers)
    assert trig_resp.status_code == 200
    assert trig_resp.json()["workflow_id"] == wf_id

    # 4. Ingest Event via API
    evt_resp = client.post(
        "/api/v1/workflows/events",
        headers=headers,
        json={
            "event_type": "customer_signed_contract",
            "source_id": "contract-99",
            "payload": {"contract_id": 99},
        },
    )
    assert evt_resp.status_code == 200
    assert evt_resp.json()["status"] == "processed"
