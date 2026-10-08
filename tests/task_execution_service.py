import uuid

import pytest

from packages.core.database import SessionLocal
from packages.models.domain import Approval, Permission, Task, Tool
from packages.models.tenant import Tenant
from packages.services.approval_service import ApprovalService
from packages.services.task_execution_service import TaskExecutionService
from packages.tools.executor import ToolExecutor


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


def test_complete_running_task(db):
    tenant = Tenant(
        name="Completion Tenant",
        slug=f"completion-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Complete task",
        objective="Complete test task",
        status="running",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    result = service.complete_task(
        tenant_id=tenant.id,
        task_id=task.id,
        result={"message": "Task completed successfully"},
    )

    assert result.status == "completed"
    assert result.result == {"message": "Task completed successfully"}


def test_fail_running_task(db):
    tenant = Tenant(
        name="Failure Tenant",
        slug=f"failure-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Fail task",
        objective="Fail test task",
        status="running",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    result = service.fail_task(
        tenant_id=tenant.id,
        task_id=task.id,
        error="Tool execution failed",
    )

    assert result.status == "failed"
    assert result.error == "Tool execution failed"


def test_cannot_complete_pending_task(db):
    tenant = Tenant(
        name="Invalid Completion Tenant",
        slug=f"invalid-completion-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Invalid completion",
        objective="Should not complete",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    with pytest.raises(ValueError, match="cannot be completed"):
        service.complete_task(
            tenant_id=tenant.id,
            task_id=task.id,
            result={"message": "invalid"},
        )


def test_cannot_fail_pending_task(db):
    tenant = Tenant(
        name="Invalid Failure Tenant",
        slug=f"invalid-failure-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Invalid failure",
        objective="Should not fail",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    with pytest.raises(ValueError, match="cannot be failed"):
        service.fail_task(
            tenant_id=tenant.id,
            task_id=task.id,
            error="invalid failure",
        )


def test_execute_tool_for_task(db):
    tenant = Tenant(
        name="Task Tool Tenant",
        slug=f"task-tool-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    tool = Tool(
        tenant_id=tenant.id,
        name="Task Test Tool",
        slug=f"task_test_tool_{uuid.uuid4().hex[:8]}",
        tool_type="function",
        description="Task execution test tool",
    )
    db.add(tool)
    db.flush()

    permission = Permission(
        tenant_id=tenant.id,
        action="run_tool",
        resource=tool.slug,
        effect="allow",
    )
    db.add(permission)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Execute tool task",
        objective="Run the test tool",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    executor = ToolExecutor(db)

    executor.register_handler(
        tool.slug,
        lambda **kwargs: {
            "message": kwargs["message"],
            "success": True,
        },
    )

    service = TaskExecutionService(db)

    result = service.execute_tool(
        tenant_id=tenant.id,
        task_id=task.id,
        tool_id=tool.id,
        action="run_tool",
        resource=tool.slug,
        parameters={"message": "Hello from task"},
        executor=executor,
    )

    assert result.status == "completed"
    assert result.result == {
        "message": "Hello from task",
        "success": True,
    }

def test_request_approval_for_running_task(db):
    tenant = Tenant(
        name="Approval Task Tenant",
        slug=f"approval-task-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Approval task",
        objective="Task requires approval",
        status="running",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    result = service.request_approval(
        tenant_id=tenant.id,
        task_id=task.id,
        action="send_message",
        description="Send message to customer",
    )

    assert result.status == "waiting_approval"
def test_request_approval_for_running_task(db):
    tenant = Tenant(
        name="Approval Task Tenant",
        slug=f"approval-task-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Approval task",
        objective="Task requires approval",
        status="running",
        priority="normal",
    )
    db.add(task)
    db.flush()

    service = TaskExecutionService(db)

    result = service.request_approval(
        tenant_id=tenant.id,
        task_id=task.id,
        action="send_message",
        description="Send message to customer",
    )

    assert result.status == "waiting_approval"

    approval = (
        db.query(Approval)
        .filter(
            Approval.tenant_id == tenant.id,
            Approval.task_id == task.id,
        )
        .first()
    )

    assert approval is not None
    assert approval.status == "pending"
    assert approval.action == "send_message"
    assert approval.description == "Send message to customer"

def test_resume_approved_task(db):
    tenant = Tenant(
        name="Resume Approval Tenant",
        slug=f"resume-approval-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Resume approved task",
        objective="Resume after approval",
        status="waiting_approval",
        priority="normal",
    )
    db.add(task)
    db.flush()

    approval_service = ApprovalService(db)

    approval = approval_service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="send_message",
        description="Send message to customer",
        task_id=task.id,
    )

    approval.status = "approved"
    db.flush()

    service = TaskExecutionService(db)

    result = service.resume_approved_task(
        tenant_id=tenant.id,
        task_id=task.id,
        approval_id=approval.id,
    )

    assert result.status == "running"
