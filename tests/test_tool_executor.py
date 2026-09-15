import uuid

import pytest

from packages.models.domain import AuditEvent, Permission, Tool
from packages.models.tenant import Tenant
from packages.tools.executor import ToolExecutor
from tests.test_action_policy_service import db


@pytest.fixture
def tenant(db):
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Tool Executor Test Tenant",
        slug=f"executor-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def tool(db, tenant):
    tool = Tool(
        tenant_id=tenant.id,
        name="Test Tool",
        slug="test_tool",
        tool_type="function",
        description="Tool executor test tool",
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def test_executor_blocks_denied_action(db, tenant, tool):
    executor = ToolExecutor(db)

    executed = []

    executor.register_handler(
        "test_tool",
        lambda **kwargs: executed.append(kwargs),
    )

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="delete_everything",
        resource="system",
    )

    db.commit()

    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert executed == []

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id)
        .all()
    )

    assert len(events) == 1
    assert events[0].event_type == "tool_execution_blocked"
    assert events[0].action == "delete_everything"
    assert events[0].event_metadata["tool_slug"] == "test_tool"
    assert events[0].event_metadata["status"] == "blocked"


def test_executor_runs_allowed_tool(db, tenant, tool):
    permission = Permission(
        tenant_id=tenant.id,
        action="run_tool",
        resource="test_tool",
        effect="allow",
    )

    db.add(permission)
    db.commit()

    executor = ToolExecutor(db)

    executor.register_handler(
        "test_tool",
        lambda **kwargs: kwargs["message"],
    )

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="run_tool",
        resource="test_tool",
        parameters={"message": "hello"},
    )

    db.commit()

    assert result.status == "executed"
    assert result.decision == "ALLOW"
    assert result.tool_slug == "test_tool"
    assert result.output == "hello"

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id)
        .all()
    )

    assert len(events) == 1
    assert events[0].event_type == "tool_execution"
    assert events[0].action == "run_tool"
    assert events[0].event_metadata["tool_slug"] == "test_tool"
    assert events[0].event_metadata["status"] == "executed"


def test_executor_passes_parameters_to_handler(db, tenant, tool):
    permission = Permission(
        tenant_id=tenant.id,
        action="run_tool",
        resource="test_tool",
        effect="allow",
    )

    db.add(permission)
    db.commit()

    executor = ToolExecutor(db)

    def handler(**kwargs):
        return {
            "received": kwargs,
        }

    executor.register_handler("test_tool", handler)

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="run_tool",
        resource="test_tool",
        parameters={
            "customer_id": "123",
            "message": "Hello customer",
        },
    )

    assert result.status == "executed"
    assert result.output["received"]["customer_id"] == "123"
    assert result.output["received"]["message"] == "Hello customer"


def test_executor_fails_when_handler_is_missing(db, tenant, tool):
    permission = Permission(
        tenant_id=tenant.id,
        action="run_tool",
        resource="test_tool",
        effect="allow",
    )

    db.add(permission)
    db.commit()

    executor = ToolExecutor(db)

    with pytest.raises(
        ValueError,
        match="No execution handler registered",
    ):
        executor.execute(
            tenant_id=tenant.id,
            tool_id=tool.id,
            action="run_tool",
            resource="test_tool",
        )

    db.commit()

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id)
        .all()
    )

    assert len(events) == 1
    assert events[0].event_type == "tool_execution_error"
    assert events[0].action == "run_tool"
    assert events[0].event_metadata["tool_slug"] == "test_tool"
    assert events[0].event_metadata["status"] == "error"


def test_executor_rejects_unknown_tool(db, tenant):
    executor = ToolExecutor(db)

    with pytest.raises(
        ValueError,
        match="Tool not found",
    ):
        executor.execute(
            tenant_id=tenant.id,
            tool_id=uuid.uuid4(),
            action="run_tool",
            resource="test_tool",
        )

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id)
        .all()
    )

    assert events == []
