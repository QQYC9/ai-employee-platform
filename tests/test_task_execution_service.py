import uuid

import pytest

from packages.core.database import SessionLocal
from packages.models.domain import Task
from packages.models.tenant import Tenant
from packages.services.task_execution_service import TaskExecutionService


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_start_pending_task(db):
    tenant = Tenant(
        name="Execution Tenant",
        slug=f"execution-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Test task",
        objective="Execute test task",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    result = service.start_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert result.status == "running"
