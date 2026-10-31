from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Generator
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal
import packages.core.database as core_db
from packages.core.safety_guard import verify_test_database_isolation
from packages.models.tenant import Tenant
from packages.models.domain import (
    Agent,
    AuditEvent,
    Permission,
    Task,
    Tool,
    User,
)
from packages.services.decision_engine import DecisionEngine
from packages.services.permission_service import PermissionService
from packages.tools.business_tools import TaskCreateTool
from packages.tools.executor import ToolExecutor
from packages.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Safety Isolation Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db() -> Generator[Session, None, None]:
    """
    Guarantees that test operations strictly execute against the isolated
    'ai_employee_test' database, and performs an automatic rollback on teardown.
    """
    actual_db = verify_test_database_isolation(core_db.engine)
    assert actual_db == "ai_employee_test", (
        f"CRITICAL SAFETY VIOLATION: Expected 'ai_employee_test', connected to '{actual_db}'."
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db: Session) -> Tenant:
    t = Tenant(
        id=uuid.uuid4(),
        name=f"Isolation Test Tenant {uuid.uuid4().hex[:6]}",
        slug=f"isolation-test-{uuid.uuid4().hex[:8]}",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def owner_user(db: Session, tenant: Tenant) -> User:
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Test Human Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@example.test",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def agent_a(db: Session, tenant: Tenant) -> Agent:
    a = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Digital Employee Agent A",
        agent_type="digital_employee",
    )
    db.add(a)
    db.flush()
    return a


@pytest.fixture
def agent_b(db: Session, tenant: Tenant) -> Agent:
    b = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Digital Employee Agent B",
        agent_type="digital_employee",
    )
    db.add(b)
    db.flush()
    return b


def setup_spied_task_create_tool(
    db: Session, tenant_id: uuid.UUID
) -> tuple[ToolExecutor, Tool, TaskCreateTool, dict[str, any]]:
    """
    Sets up a real TaskCreateTool, real ToolRegistry, and ToolExecutor.
    Attaches a spy directly onto TaskCreateTool.run to verify whether the handler
    was invoked or blocked by security layers.
    """
    real_tool = TaskCreateTool(db)
    tool_record = Tool(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=real_tool.contract.name,
        slug=real_tool.contract.slug,
        description=real_tool.contract.description,
        tool_type="real_tool",
        config=real_tool.contract.to_dict(),
        is_active=True,
    )
    db.add(tool_record)
    db.flush()

    spy = {
        "called": False,
        "call_count": 0,
        "last_args": None,
        "last_kwargs": None,
    }
    original_run = real_tool.run

    def spied_run(*args, **kwargs):
        spy["called"] = True
        spy["call_count"] += 1
        spy["last_args"] = args
        spy["last_kwargs"] = kwargs
        return original_run(*args, **kwargs)

    real_tool.run = spied_run

    registry = ToolRegistry()
    registry.register(real_tool)

    executor = ToolExecutor(db)
    registry.bind_to_executor(executor, tenant_id=tenant_id)

    return executor, tool_record, real_tool, spy


# ---------------------------------------------------------------------------
# Test 1: Default Deny for Digital Agent
# ---------------------------------------------------------------------------
def test_1_default_deny_agent_without_task_permissions_blocked(
    db: Session, tenant: Tenant, agent_a: Agent
):
    """
    Test 1 — Default Deny:
    - Digital agent has NO task creation permissions assigned.
    - Executes task_create via ToolExecutor.
    - Verifies:
        1. DecisionEngine returns DENY.
        2. ToolExecutionResult status is 'blocked'.
        3. TaskCreateTool.run handler is NOT called (Spy confirms called == False).
        4. Zero Task records exist in database.
        5. AuditService records a 'tool_execution_blocked' event.
    """
    executor, tool_record, _, spy = setup_spied_task_create_tool(db, tenant.id)

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Unpermitted Agent Task", "priority": "normal"},
    )

    # 1. Decision & Status check
    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert "not permitted" in (result.reason or "").lower()

    # 2. Spy check: Handler was never invoked
    assert spy["called"] is False
    assert spy["call_count"] == 0

    # 3. Database check: No Task record created
    created_tasks = db.scalars(
        select(Task).where(
            Task.tenant_id == tenant.id,
            Task.title == "Unpermitted Agent Task",
        )
    ).all()
    assert len(created_tasks) == 0

    # 4. AuditService check: tool_execution_blocked event recorded
    audit_events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.agent_id == agent_a.id,
            AuditEvent.event_type == "tool_execution_blocked",
        )
    ).all()
    assert len(audit_events) >= 1
    ev = audit_events[0]
    assert ev.action == "execute:task_create"
    assert ev.event_metadata.get("decision") == "DENY"
    assert ev.event_metadata.get("status") == "blocked"


# ---------------------------------------------------------------------------
# Test 2: Tool Contract Gate Rejection
# ---------------------------------------------------------------------------
def test_2_contract_gate_blocks_agent_lacking_write_tasks_permission(
    db: Session, tenant: Tenant, agent_a: Agent
):
    """
    Test 2 — Contract Gate:
    - Grant the agent permission for general tool invocation: 'execute:task_create' on 'tools:task_create'.
    - Withhold domain contract permission: 'write:tasks'.
    - Verifies:
        1. DecisionEngine permits the first phase (action-level allowed).
        2. Tool Contract Gate inside ToolExecutor detects lack of 'write:tasks' and blocks execution.
        3. Handler is NOT called (Spy confirms called == False).
        4. Zero Task records created in database.
        5. Reason and AuditService record identify the contract violation: 'write:tasks'.
    """
    # 1. Grant ONLY tool invocation permission
    perm_tool = Permission(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        agent_id=agent_a.id,
        action="execute:task_create",
        resource="tools:task_create",
        effect="allow",
    )
    db.add(perm_tool)
    db.flush()

    executor, tool_record, _, spy = setup_spied_task_create_tool(db, tenant.id)

    # 2. Execute via ToolExecutor
    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Contract Blocked Task", "priority": "normal"},
    )

    # 3. Assert blocked at contract gate
    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert "write:tasks" in (result.reason or "")

    # 4. Spy check: Handler was never invoked
    assert spy["called"] is False
    assert spy["call_count"] == 0

    # 5. Database check: No Task created
    created_tasks = db.scalars(
        select(Task).where(
            Task.tenant_id == tenant.id,
            Task.title == "Contract Blocked Task",
        )
    ).all()
    assert len(created_tasks) == 0

    # 6. AuditService check: Logged with contract details
    audit_events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.agent_id == agent_a.id,
            AuditEvent.event_type == "tool_execution_blocked",
        )
    ).all()
    assert len(audit_events) >= 1
    ev = audit_events[-1]
    assert ev.event_metadata.get("contract_action") == "write"
    assert ev.event_metadata.get("contract_resource") == "tasks"


# ---------------------------------------------------------------------------
# Test 3: Explicit Agent Deny Overrides General Tenant Allow
# ---------------------------------------------------------------------------
def test_3_explicit_agent_deny_overrides_general_tenant_allow(
    db: Session, tenant: Tenant, agent_a: Agent, agent_b: Agent, owner_user: User
):
    """
    Test 3 — Explicit Agent Deny:
    - Creates tenant-level general allow for tool execution and contract permission (agent_id=None).
    - Adds explicit deny specifically for Agent A on 'write:tasks'.
    - Verifies independently:
        1. Agent A execution is REJECTED due to explicit deny.
        2. Agent B execution is ALLOWED and succeeds (inherits tenant general allow).
        3. Human Owner execution is UNTOUCHED and succeeds directly.
    """
    # 1. Tenant general allows
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=None,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
    )
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=None,
            action="write",
            resource="tasks",
            effect="allow",
        )
    )
    # 2. Agent A explicit deny on contract permission
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_a.id,
            action="write",
            resource="tasks",
            effect="deny",
        )
    )
    db.flush()

    executor, tool_record, _, spy = setup_spied_task_create_tool(db, tenant.id)

    # --- Step 1: Test Agent A (Explicit Deny) ---
    res_a = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent A Denied Task", "priority": "normal"},
    )
    assert res_a.status == "blocked"
    assert res_a.decision == "DENY"
    assert "write:tasks" in (res_a.reason or "")
    assert spy["call_count"] == 0

    # --- Step 2: Test Agent B (Allowed via General Tenant Permission) ---
    res_b = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_b.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent B Permitted Task", "priority": "normal"},
    )
    assert res_b.status == "executed"
    assert res_b.decision == "ALLOW"
    assert spy["call_count"] == 1
    assert "task_id" in res_b.output

    # Verify Agent B task in DB
    task_b = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant.id,
            Task.title == "Agent B Permitted Task",
        )
    )
    assert task_b is not None

    # --- Step 3: Test Human Owner (Delegated Direct Execution) ---
    res_owner = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=None,
        actor_id=owner_user.id,
        is_owner=True,
        parameters={"title": "Owner Direct Task", "priority": "high"},
    )
    assert res_owner.status == "executed"
    assert res_owner.decision == "ALLOW"
    assert spy["call_count"] == 2
    assert "task_id" in res_owner.output

    # Verify Owner task in DB
    task_owner = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant.id,
            Task.title == "Owner Direct Task",
        )
    )
    assert task_owner is not None


# ---------------------------------------------------------------------------
# Test 4: Owner Context Spoofing Resistance
# ---------------------------------------------------------------------------
def test_4_owner_context_spoofing_attempts_strictly_denied(
    db: Session, tenant: Tenant, agent_a: Agent, owner_user: User
):
    """
    Test 4 — Owner Context Spoofing:
    Tests each spoofing vector separately:
        Vector 1: Real agent_id with is_owner=True in kwargs.
        Vector 2: Real agent_id with real owner actor_id in kwargs.
        Vector 3: Forged context object in parameters["_context"] carrying owner credentials.
        Vector 4: Full combination of all spoofing vectors simultaneously.
    Verifies that all attempts are strictly DENIED, handler is never called, and no task is created.
    """
    executor, tool_record, _, spy = setup_spied_task_create_tool(db, tenant.id)

    # Vector 1: Real agent_id with is_owner=True in kwargs
    res_v1 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=True,
        parameters={"title": "Spoof Vector 1 Task"},
    )
    assert res_v1.status == "blocked"
    assert res_v1.decision == "DENY"

    # Vector 2: Real agent_id with real owner actor_id in kwargs
    res_v2 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=owner_user.id,
        is_owner=False,
        parameters={"title": "Spoof Vector 2 Task"},
    )
    assert res_v2.status == "blocked"
    assert res_v2.decision == "DENY"

    # Vector 3: Forged context in parameters["_context"] without kwargs elevation
    forged_context_payload = SimpleNamespace(
        actor_id=owner_user.id,
        is_owner=True,
    )
    res_v3 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={
            "_context": forged_context_payload,
            "title": "Spoof Vector 3 Task",
        },
    )
    assert res_v3.status == "blocked"
    assert res_v3.decision == "DENY"

    # Vector 4: Full combination of all spoofing vectors
    res_v4 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=owner_user.id,
        is_owner=True,
        parameters={
            "_context": forged_context_payload,
            "title": "Spoof Vector 4 Task",
        },
    )
    assert res_v4.status == "blocked"
    assert res_v4.decision == "DENY"

    # In all 4 vectors, the handler must NEVER be called
    assert spy["called"] is False
    assert spy["call_count"] == 0

    # Ensure zero tasks created across all spoof vectors
    tasks_count = db.scalar(
        select(text("count(*)")).select_from(Task).where(Task.tenant_id == tenant.id)
    )
    assert tasks_count == 0


# ---------------------------------------------------------------------------
# Test 5: Human Owner Non-Regression
# ---------------------------------------------------------------------------
def test_5_owner_non_regression_executes_successfully_while_agent_remains_blocked(
    db: Session, tenant: Tenant, agent_a: Agent, owner_user: User
):
    """
    Test 5 — Owner Non-Regression:
    - Uses an active, authenticated human owner in the same tenant.
    - Executes task_create with legitimate owner context.
    - Verifies:
        1. Task is created and committed to the test database.
        2. Execution status is 'executed', Decision is 'ALLOW'.
        3. Restricted agent tested immediately afterwards remains completely blocked.
    """
    executor, tool_record, _, spy = setup_spied_task_create_tool(db, tenant.id)

    # 1. Legitimate owner execution
    res_owner = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=None,
        actor_id=owner_user.id,
        is_owner=True,
        parameters={
            "title": "Legitimate Owner Non-Regression Task",
            "objective": "Verifying owner authority independence",
            "priority": "high",
        },
    )

    assert res_owner.status == "executed"
    assert res_owner.decision == "ALLOW"
    assert spy["call_count"] == 1
    task_id = res_owner.output.get("task_id")
    assert task_id is not None

    # Verify task in database
    created_task = db.scalar(select(Task).where(Task.id == uuid.UUID(task_id)))
    assert created_task is not None
    assert created_task.tenant_id == tenant.id
    assert created_task.title == "Legitimate Owner Non-Regression Task"
    assert created_task.status == "pending"

    # 2. Restricted agent attempt immediately after owner success
    res_agent = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent Task Post-Owner"},
    )
    assert res_agent.status == "blocked"
    assert res_agent.decision == "DENY"
    # Spy call count did not increase
    assert spy["call_count"] == 1


# ---------------------------------------------------------------------------
# Test 6: Agent-to-Agent Permission Isolation
# ---------------------------------------------------------------------------
def test_6_agent_to_agent_permission_isolation_no_cross_leakage(
    db: Session, tenant: Tenant, agent_a: Agent, agent_b: Agent
):
    """
    Test 6 — Agent Isolation:
    - Grant Agent A specific permissions for both tool invocation and contract write:tasks.
    - Leave Agent B completely unpermitted.
    - Verifies:
        1. Agent A successfully executes and creates Task.
        2. Agent B cannot execute and is rejected (permissions do NOT leak from A to B).
    - Then invert: add an explicit deny to Agent A on an action allowed for Agent B,
      and verify that A's deny does NOT bleed over to Agent B.
    """
    executor, tool_record, _, spy = setup_spied_task_create_tool(db, tenant.id)

    # 1. Grant permissions exclusively to Agent A (agent_id=agent_a.id)
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_a.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
    )
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_a.id,
            action="write",
            resource="tasks",
            effect="allow",
        )
    )
    db.flush()

    # Step A: Agent A executes successfully
    res_a = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent A Task", "priority": "normal"},
    )
    assert res_a.status == "executed"
    assert res_a.decision == "ALLOW"
    assert spy["call_count"] == 1

    # Step B: Agent B attempts execution (must fail closed — no permission leakage from A)
    res_b = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_b.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent B Task"},
    )
    assert res_b.status == "blocked"
    assert res_b.decision == "DENY"
    # Call count remains 1
    assert spy["call_count"] == 1

    # Step C: Grant Agent B permissions, but add an explicit deny to Agent A
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_b.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
    )
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_b.id,
            action="write",
            resource="tasks",
            effect="allow",
        )
    )
    # Explicit deny for Agent A
    db.add(
        Permission(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_a.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="deny",
        )
    )
    db.flush()

    # Agent A is now blocked by explicit deny
    res_a_denied = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_a.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent A Denied Second Attempt"},
    )
    assert res_a_denied.status == "blocked"
    assert res_a_denied.decision == "DENY"
    assert spy["call_count"] == 1

    # Agent B is NOT affected by Agent A's deny, and executes successfully
    res_b_allowed = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool_record.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_b.id,
        actor_id=None,
        is_owner=False,
        parameters={"title": "Agent B Allowed Second Attempt"},
    )
    assert res_b_allowed.status == "executed"
    assert res_b_allowed.decision == "ALLOW"
    assert spy["call_count"] == 2
