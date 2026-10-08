import uuid

import pytest

from packages.core.database import SessionLocal
from packages.models.domain import Task
from packages.models.tenant import Tenant
from packages.services.agent_runtime import AgentRuntime
from packages.services.task_service import TaskService


@pytest.fixture
def db():
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db):
    tenant = Tenant(
        name="Task Service Tenant",
        slug=f"task-service-{uuid.uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.flush()

    return tenant


def test_create_task(db, tenant):
    service = TaskService(db)

    task = service.create_task(
        tenant_id=tenant.id,
        title="Research competitors",
        objective="Research the main competitors",
    )

    assert task.tenant_id == tenant.id
    assert task.title == "Research competitors"
    assert task.objective == "Research the main competitors"
    assert task.status == "pending"
    assert task.priority == "normal"


def test_get_task_is_tenant_scoped(db, tenant):
    service = TaskService(db)

    task = service.create_task(
        tenant_id=tenant.id,
        title="Private task",
        objective="Private objective",
    )

    other_tenant = Tenant(
        name="Other Tenant",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )

    db.add(other_tenant)
    db.flush()

    assert service.get_task(
        tenant_id=tenant.id,
        task_id=task.id,
    ) is task

    assert service.get_task(
        tenant_id=other_tenant.id,
        task_id=task.id,
    ) is None


def test_list_tasks_can_filter_status(db, tenant):
    service = TaskService(db)

    pending_task = service.create_task(
        tenant_id=tenant.id,
        title="Pending task",
        objective="Pending objective",
    )

    running_task = service.create_task(
        tenant_id=tenant.id,
        title="Running task",
        objective="Running objective",
    )

    running_task.status = "running"
    db.flush()

    pending_tasks = service.list_tasks(
        tenant_id=tenant.id,
        status="pending",
    )

    assert len(pending_tasks) == 1
    assert pending_tasks[0].id == pending_task.id


def test_update_task(db, tenant):
    service = TaskService(db)

    task = service.create_task(
        tenant_id=tenant.id,
        title="Original",
        objective="Original objective",
    )

    updated = service.update_task(
        tenant_id=tenant.id,
        task_id=task.id,
        title="Updated",
        priority="high",
        plan={"steps": ["research", "analyze"]},
    )

    assert updated.title == "Updated"
    assert updated.priority == "high"
    assert updated.plan == {
        "steps": ["research", "analyze"],
    }


def test_agent_runtime_creates_task(db, tenant):
    runtime = AgentRuntime(db)

    task = runtime.receive_request(
        tenant_id=tenant.id,
        request="Research our main competitors and prepare a detailed strategic report for management",
        priority="high",
    )

    assert task.status == "pending"
    assert task.priority == "high"
    assert task.objective == (
        "Research our main competitors and prepare a detailed strategic report for management"
    )
    assert task.title == "Research our main competitors and prepare a detailed..."


def test_agent_runtime_rejects_empty_request(db, tenant):
    runtime = AgentRuntime(db)

    with pytest.raises(ValueError, match="Request cannot be empty"):
        runtime.receive_request(
            tenant_id=tenant.id,
            request="   ",
        )


