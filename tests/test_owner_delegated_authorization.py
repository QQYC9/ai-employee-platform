from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from sqlalchemy import func, select

from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import (
    User,
    Agent,
    Permission,
    ActionPolicy,
    Approval,
    Task,
    AuditEvent,
    Tool,
)
from packages.services.decision_engine import DecisionEngine
from packages.services.permission_service import PermissionService
from packages.tools.contract import ToolContract, ToolRiskLevel
from packages.tools.executor import ToolExecutor
from packages.tools.registry import ToolRegistry, create_default_registry
from packages.tools.business_tools import TaskCreateTool


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def engine(db):
    return DecisionEngine(db)


@pytest.fixture
def tenant(db):
    t = Tenant(
        id=uuid.uuid4(),
        name="Owner Auth Test Tenant",
        slug=f"owner-auth-{uuid.uuid4().hex[:8]}",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tenant2(db):
    t = Tenant(
        id=uuid.uuid4(),
        name="Foreign Test Tenant",
        slug=f"foreign-auth-{uuid.uuid4().hex[:8]}",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def owner_user(db, tenant):
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Real Tenant Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def admin_user(db, tenant):
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Tenant Admin",
        email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        role="tenant_admin",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def regular_user(db, tenant):
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Regular Staff",
        email=f"staff-{uuid.uuid4().hex[:6]}@example.com",
        role="tenant_user",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def inactive_owner(db, tenant):
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Suspended Owner",
        email=f"suspended-{uuid.uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        status="suspended",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def cross_tenant_owner(db, tenant2):
    u = User(
        id=uuid.uuid4(),
        tenant_id=tenant2.id,
        name="Foreign Owner",
        email=f"foreign-{uuid.uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def agent(db, tenant):
    a = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Autonomous Assistant",
        agent_type="digital_employee",
    )
    db.add(a)
    db.flush()
    return a


# ---------------------------------------------------------------------------
# Test Case 1: Authenticated owner requesting task_create without allow record
# ---------------------------------------------------------------------------
def test_authenticated_owner_can_execute_task_create_and_query_without_allow_record(
    engine, tenant, owner_user, admin_user
):
    """
    Authenticated human owner or admin requesting task_create or task_query
    is permitted directly without requiring a permanent allow record in Permission table.
    """
    # 1. Test owner on execute:task_create
    res1 = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res1.decision == "ALLOW"
    assert res1.requires_approval is False

    # 2. Test owner on task_create (bare slug)
    res2 = engine.decide(
        tenant_id=tenant.id,
        action="task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res2.decision == "ALLOW"

    # 3. Test owner on task_query
    res3 = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_query",
        resource="tools:task_query",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res3.decision == "ALLOW"

    # 4. Test tenant_admin role
    res4 = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=admin_user.id,
        is_owner=True,
    )
    assert res4.decision == "ALLOW"


# ---------------------------------------------------------------------------
# Test Case 2: Authenticated owner blocked when explicit deny exists
# ---------------------------------------------------------------------------
def test_authenticated_owner_blocked_when_explicit_deny_exists(
    db, engine, tenant, owner_user
):
    """
    Explicit deny records in Permission table strictly override owner delegation.
    """
    # Insert explicit deny for task_create
    db.add(
        Permission(
            tenant_id=tenant.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="deny",
        )
    )
    db.flush()

    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res.decision == "DENY"
    assert "explicitly denied" in res.reason


# ---------------------------------------------------------------------------
# Test Case 3: Digital agent blocked without explicit permission
# ---------------------------------------------------------------------------
def test_agent_blocked_without_explicit_permission(
    engine, tenant, agent, owner_user
):
    """
    Digital agents must not inherit owner delegation and remain blocked without explicit allow.
    """
    # Normal agent call
    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent.id,
        is_owner=False,
    )
    assert res.decision == "DENY"

    # Malicious attempt: agent passing is_owner=True with agent_id set
    res_spoof = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent.id,
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res_spoof.decision == "DENY"


# ---------------------------------------------------------------------------
# Test Case 4: Invalid, inactive, or cross-tenant actor_id rejected
# ---------------------------------------------------------------------------
def test_invalid_actor_id_rejected(
    engine, tenant, inactive_owner, cross_tenant_owner
):
    """
    actor_id must exist, be active, and belong to the same tenant.
    """
    # Non-existent user UUID
    fake_id = uuid.uuid4()
    res_fake = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=fake_id,
        is_owner=True,
    )
    assert res_fake.decision == "DENY"

    # Inactive / suspended owner
    res_inactive = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=inactive_owner.id,
        is_owner=True,
    )
    assert res_inactive.decision == "DENY"

    # Cross-tenant owner (belongs to tenant2, requesting action in tenant)
    res_cross = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=cross_tenant_owner.id,
        is_owner=True,
    )
    assert res_cross.decision == "DENY"

    # is_owner=True without actor_id
    res_no_actor = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=None,
        is_owner=True,
    )
    assert res_no_actor.decision == "DENY"


# ---------------------------------------------------------------------------
# Test Case 5: Regular user passing is_owner=True rejected
# ---------------------------------------------------------------------------
def test_regular_user_passing_is_owner_true_rejected(
    engine, tenant, regular_user
):
    """
    A tenant_user claiming is_owner=True must not receive owner authorization.
    """
    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=regular_user.id,
        is_owner=True,
    )
    assert res.decision == "DENY"


# ---------------------------------------------------------------------------
# Test Case 6: Tool outside allowed whitelist cannot use owner delegation
# ---------------------------------------------------------------------------
def test_tool_outside_whitelist_cannot_use_owner_delegation(
    engine, tenant, owner_user
):
    """
    Only task_create and task_query are whitelisted for owner delegation.
    Other tools (e.g. http_request, customer_create_or_update) are rejected without explicit permission.
    """
    for disallowed_action in ["http_request", "execute:http_request", "customer_create_or_update", "send_email"]:
        res = engine.decide(
            tenant_id=tenant.id,
            action=disallowed_action,
            resource="tools:disallowed",
            actor_id=owner_user.id,
            is_owner=True,
        )
        assert res.decision == "DENY", f"Action '{disallowed_action}' should be DENIED"


# ---------------------------------------------------------------------------
# Test Case 7: Action requiring approval is not executed without approved record
# ---------------------------------------------------------------------------
def test_action_requiring_approval_is_not_executed_without_approved_record(
    db, engine, tenant, owner_user
):
    """
    If ActionPolicyService requires approval, owner authorization does not bypass it.
    It returns APPROVAL_REQUIRED until a valid approved Approval record exists for the task.
    """
    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        requires_approval=True,
        approval_for="platform_admin",
    )
    db.add(policy)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Approval Test Task",
        objective="Verify approval gating",
    )
    db.add(task)
    db.flush()

    task_uuid = task.id

    # 1. Decision before approval -> APPROVAL_REQUIRED
    res_pending = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        task_id=task_uuid,
        is_owner=True,
    )
    assert res_pending.decision == "APPROVAL_REQUIRED"
    assert res_pending.requires_approval is True
    assert res_pending.approval_for == "platform_admin"

    # 2. Add approved Approval record
    appr = Approval(
        tenant_id=tenant.id,
        task_id=task_uuid,
        requested_for="platform_admin",
        action="execute:task_create",
        description="Approved task creation",
        status="approved",
        decision_by_user_id=owner_user.id,
    )
    db.add(appr)
    db.flush()

    # 3. Decision after approval -> ALLOW
    res_approved = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        task_id=task_uuid,
        is_owner=True,
    )
    assert res_approved.decision == "ALLOW"


# ---------------------------------------------------------------------------
# Test Case 8: Legacy calls without actor context preserved
# ---------------------------------------------------------------------------
def test_legacy_calls_without_actor_context_preserved(
    db, engine, tenant
):
    """
    Legacy callers calling decide() without actor_id or is_owner continue to function
    with the exact historical behavior.
    """
    # Without permission -> DENY
    res_no_perm = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
    )
    assert res_no_perm.decision == "DENY"

    # With allow permission -> ALLOW
    db.add(
        Permission(
            tenant_id=tenant.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
    )
    db.flush()

    res_allowed = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
    )
    assert res_allowed.decision == "ALLOW"


# ---------------------------------------------------------------------------
# Phase 1-A Tests: Edge cases for explicit deny, agent isolation, and action formatting
# ---------------------------------------------------------------------------
def test_generic_explicit_deny_with_null_resource_blocks_owner(
    db, engine, tenant, owner_user
):
    """
    A generic tenant-level deny rule with resource=None blocks owner execution
    even when a specific resource is requested.
    """
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="execute:task_create",
            resource=None,
            effect="deny",
        )
    )
    db.flush()

    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res.decision == "DENY"
    assert "explicitly denied" in res.reason


def test_generic_explicit_deny_with_empty_resource_blocks_owner(
    db, engine, tenant, owner_user
):
    """
    A generic tenant-level deny rule with resource='' blocks owner execution
    even when a specific resource is requested.
    """
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="execute:task_create",
            resource="",
            effect="deny",
        )
    )
    db.flush()

    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res.decision == "DENY"
    assert "explicitly denied" in res.reason


def test_agent_specific_deny_does_not_block_human_owner(
    db, engine, tenant, owner_user, agent
):
    """
    An explicit deny rule targeted at a specific digital agent (agent_id set)
    must NOT block the human owner in direct execution.
    """
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="deny",
        )
    )
    db.flush()

    # Human owner direct execution
    res_owner = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
        agent_id=None,
    )
    assert res_owner.decision == "ALLOW"


def test_agent_specific_deny_is_enforced_when_agent_requests(
    db, engine, tenant, agent
):
    """
    An explicit deny rule targeted at a specific digital agent MUST be enforced
    when that digital agent makes the request, overriding an applicable allow rule.
    A second agent without the deny rule continues to be allowed by the general rule.
    """
    # 1. Base allow rule applicable to the tenant
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
    )
    # 2. Agent-specific deny on the first agent
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="deny",
        )
    )
    # 3. Create second agent without specific deny
    agent_b = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Second Agent",
        agent_type="digital_employee",
    )
    db.add(agent_b)
    db.flush()

    # 4. First agent request -> DENIED due to agent-specific deny overriding tenant allow
    res_agent = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent.id,
        is_owner=False,
    )
    assert res_agent.decision == "DENY"

    # 5. Second agent request -> ALLOWED due to general tenant allow
    res_agent_b = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_b.id,
        is_owner=False,
    )
    assert res_agent_b.decision == "ALLOW"


def test_resource_mismatch_does_not_block_owner(
    db, engine, tenant, owner_user
):
    """
    A specific deny rule on resource='tools:task_query' does not block
    the owner from executing on resource='tools:task_create'.
    """
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="execute:task_create",
            resource="tools:other_resource",
            effect="deny",
        )
    )
    db.flush()

    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res.decision == "ALLOW"


def test_action_name_format_cross_denial(
    db, engine, tenant, owner_user
):
    """
    Cross-format action name matching:
    - Deny registered as 'task_create' blocks incoming 'execute:task_create'.
    - Deny registered as 'execute:task_create' blocks incoming 'task_create'.
    - Deny on 'task_query' does NOT block incoming 'execute:task_create' (cross-tool isolation).
    """
    # 1. Deny on bare 'task_create'
    p1 = Permission(
        tenant_id=tenant.id,
        agent_id=None,
        action="task_create",
        resource="tools:task_create",
        effect="deny",
    )
    db.add(p1)
    db.flush()

    res1 = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res1.decision == "DENY"
    assert "explicitly denied" in res1.reason

    # Clean up p1 for next sub-test
    db.delete(p1)
    db.flush()

    # 2. Deny on 'execute:task_create' blocks incoming bare 'task_create'
    p2 = Permission(
        tenant_id=tenant.id,
        agent_id=None,
        action="execute:task_create",
        resource="tools:task_create",
        effect="deny",
    )
    db.add(p2)
    db.flush()

    res2 = engine.decide(
        tenant_id=tenant.id,
        action="task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res2.decision == "DENY"
    assert "explicitly denied" in res2.reason

    # Clean up p2 for next sub-test
    db.delete(p2)
    db.flush()

    # 3. Cross-tool isolation: Deny on 'execute:task_query' does NOT block 'execute:task_create'
    p3 = Permission(
        tenant_id=tenant.id,
        agent_id=None,
        action="execute:task_query",
        resource="tools:task_query",
        effect="deny",
    )
    db.add(p3)
    db.flush()

    res3 = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
    )
    assert res3.decision == "ALLOW"


def test_action_requiring_approval_rejected_returns_deny_for_owner(
    db, engine, tenant, owner_user
):
    """
    If an ActionPolicy requires approval and the task's approval was rejected,
    the owner request must be DENIED with explicit rejection reason.
    """
    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        requires_approval=True,
        approval_for="platform_admin",
    )
    task = Task(
        tenant_id=tenant.id,
        title="Rejected Approval Task",
        objective="Verify rejection gating",
    )
    db.add(policy)
    db.add(task)
    db.flush()

    # Insert rejected Approval
    appr = Approval(
        tenant_id=tenant.id,
        task_id=task.id,
        requested_for="platform_admin",
        action="execute:task_create",
        description="Rejected task creation",
        status="rejected",
        decision_by_user_id=owner_user.id,
        decision_reason="Security policy violation",
    )
    db.add(appr)
    db.flush()

    res = engine.decide(
        tenant_id=tenant.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        task_id=task.id,
        is_owner=True,
    )
    assert res.decision == "DENY"
    assert "rejected" in res.reason


# ---------------------------------------------------------------------------
# Phase 1-D Tests: ToolContract Permission Enforcement Gate in ToolExecutor
# ---------------------------------------------------------------------------


def test_contract_deny_on_write_tasks_blocks_task_create(
    db, tenant, owner_user
):
    """
    1) Verify that an explicit deny on the contract permission ('write:tasks') blocks
       task_create execution in ToolExecutor even for the authenticated owner.
    2) Verify that the handler is NEVER called and the row count in 'tasks' does NOT increase.
    3) Verify an AuditEvent is recorded with contract-level denial details.
    """
    # 1. Register Tool model in DB
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)

    # 2. Add tenant-level explicit deny on the contract domain permission
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="write",
            resource="tasks",
            effect="deny",
        )
    )
    db.flush()

    # 3. Record task count before execution
    count_before = db.scalar(
        select(func.count(Task.id)).where(Task.tenant_id == tenant.id)
    ) or 0

    # 4. Set up ToolExecutor with real TaskCreateTool handler via ToolRegistry
    executor = ToolExecutor(db)
    registry = ToolRegistry()
    registry.register(TaskCreateTool(db))
    registry.bind_to_executor(executor, tenant_id=tenant.id)

    # 5. Owner attempts to execute task_create
    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
        parameters={"title": "Unauthorized Owner Task", "priority": "high"},
    )

    # 6. Assert execution was blocked at the contract gate
    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert "write:tasks" in result.reason
    assert "Explicit deny on contract permission" in result.reason

    # 7. CRITICAL: Assert handler was NOT called and DB row count did not increase
    count_after = db.scalar(
        select(func.count(Task.id)).where(Task.tenant_id == tenant.id)
    ) or 0
    assert count_after == count_before

    # 8. Assert audit event was recorded with actor and contract details
    audit = (
        db.query(AuditEvent)
        .filter(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "tool_execution_blocked",
        )
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit is not None
    assert audit.user_id == owner_user.id
    assert audit.event_metadata["contract_action"] == "write"
    assert audit.event_metadata["contract_resource"] == "tasks"
    assert audit.event_metadata["is_owner"] is True


def test_contract_allowed_permissions_allows_execution(
    db, tenant, owner_user
):
    """
    Verify that when no explicit deny exists on the contract permission,
    the authenticated owner executes task_create successfully, the handler runs,
    and a Task row is created in the database.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)
    db.flush()

    count_before = db.scalar(
        select(func.count(Task.id)).where(Task.tenant_id == tenant.id)
    ) or 0

    executor = ToolExecutor(db)
    registry = ToolRegistry()
    registry.register(TaskCreateTool(db))
    registry.bind_to_executor(executor, tenant_id=tenant.id)

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
        parameters={"title": "Authorized Owner Task", "priority": "normal"},
    )

    assert result.status == "executed"
    assert result.decision == "ALLOW"
    assert result.output is not None
    assert "task_id" in result.output

    count_after = db.scalar(
        select(func.count(Task.id)).where(Task.tenant_id == tenant.id)
    ) or 0
    assert count_after == count_before + 1

    created_task = db.get(Task, uuid.UUID(result.output["task_id"]))
    assert created_task is not None
    assert created_task.title == "Authorized Owner Task"
    assert created_task.tenant_id == tenant.id


def test_multi_permission_contract_fails_if_any_single_permission_fails(
    db, tenant, agent
):
    """
    Verify that for a tool requiring multiple contract permissions (e.g. read:conversations AND read:messages),
    execution is blocked if any single permission is not granted to an agent.
    Once all required permissions are granted, execution succeeds.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Multi Permission Tool",
        slug="multi_perm_tool",
        tool_type="function",
        description="Tool requiring multiple permissions",
    )
    db.add(tool)

    # 1. Allow tool execution at the decision engine level
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:multi_perm_tool",
            resource="tools:multi_perm_tool",
            effect="allow",
        )
    )
    # 2. Allow first contract permission ONLY
    p_conv = Permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="read",
        resource="conversations",
        effect="allow",
    )
    db.add(p_conv)
    db.flush()

    executor = ToolExecutor(db)
    executed_flags = []

    def multi_handler(**kwargs):
        executed_flags.append(True)
        return {"status": "ok"}

    # Attach contract with 2 required permissions
    multi_handler.contract = ToolContract(
        slug="multi_perm_tool",
        name="Multi Perm Tool",
        version="1.0.0",
        description="Multi permission test tool",
        risk_level=ToolRiskLevel.LOW,
        requires_approval=False,
        required_permissions=[("read", "conversations"), ("read", "messages")],
    )
    executor.register_handler("multi_perm_tool", multi_handler)

    # 3. Execute: agent has read:conversations but lacks read:messages -> BLOCKED
    result1 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:multi_perm_tool",
        resource="tools:multi_perm_tool",
        agent_id=agent.id,
        is_owner=False,
    )
    assert result1.status == "blocked"
    assert result1.decision == "DENY"
    assert "read:messages" in result1.reason
    assert len(executed_flags) == 0  # Handler was never called

    # 4. Grant missing permission: read:messages
    p_msg = Permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="read",
        resource="messages",
        effect="allow",
    )
    db.add(p_msg)
    db.flush()

    # 5. Execute again -> SUCCEEDS
    result2 = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:multi_perm_tool",
        resource="tools:multi_perm_tool",
        agent_id=agent.id,
        is_owner=False,
    )
    assert result2.status == "executed"
    assert result2.decision == "ALLOW"
    assert len(executed_flags) == 1


def test_contract_agent_specific_deny_overrides_general_allow(
    db, tenant, agent
):
    """
    Verify that an agent-specific deny on a contract permission ('write:tasks')
    blocks the specific agent even when a general tenant allow for 'write:tasks' exists,
    while a second agent without the deny rule is allowed to execute.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)

    agent_b = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Second Agent B",
        agent_type="digital_employee",
    )
    db.add(agent_b)

    # General allow for tool execution
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
    )
    # General allow for domain contract permission
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="write",
            resource="tasks",
            effect="allow",
        )
    )
    # Agent-specific DENY on contract permission for agent
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="write",
            resource="tasks",
            effect="deny",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    registry = ToolRegistry()
    registry.register(TaskCreateTool(db))
    registry.bind_to_executor(executor, tenant_id=tenant.id)

    # 1. Agent A execution -> BLOCKED at contract gate
    res_a = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent.id,
        is_owner=False,
        parameters={"title": "Agent A Task", "priority": "normal"},
    )
    assert res_a.status == "blocked"
    assert res_a.decision == "DENY"
    assert "write:tasks" in res_a.reason

    # 2. Agent B execution -> EXECUTED successfully
    res_b = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent_b.id,
        is_owner=False,
        parameters={"title": "Agent B Task", "priority": "normal"},
    )
    assert res_b.status == "executed"
    assert res_b.decision == "ALLOW"
    assert "task_id" in res_b.output


def test_contract_agent_specific_deny_does_not_block_human_owner(
    db, tenant, owner_user, agent
):
    """
    Verify that an agent-specific deny on a contract permission ('write:tasks')
    does NOT block the human owner in direct execution.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)

    # Agent-specific deny on contract permission
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="write",
            resource="tasks",
            effect="deny",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    registry = ToolRegistry()
    registry.register(TaskCreateTool(db))
    registry.bind_to_executor(executor, tenant_id=tenant.id)

    # Owner executes task_create directly (agent_id=None)
    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
        parameters={"title": "Owner Direct Task", "priority": "normal"},
    )
    assert result.status == "executed"
    assert result.decision == "ALLOW"
    assert "task_id" in result.output


def test_tool_without_contract_permissions_maintains_legacy_behavior(
    db, tenant, owner_user, agent
):
    """
    Verify that tools with empty required_permissions (or no contract attached)
    maintain their exact historical execution behavior without any contract-level blocking.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Legacy Function Tool",
        slug="legacy_tool",
        tool_type="function",
        description="Legacy tool without contract",
    )
    db.add(tool)

    # Allow tool execution
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="run_tool",
            resource="legacy_tool",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    invoked = []

    def legacy_handler(**kwargs):
        invoked.append(kwargs)
        return {"output": "legacy_success"}

    # No contract attached to handler
    executor.register_handler("legacy_tool", legacy_handler)

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="run_tool",
        resource="legacy_tool",
        agent_id=agent.id,
        parameters={"data": "test_legacy"},
    )
    assert result.status == "executed"
    assert result.decision == "ALLOW"
    assert result.output == {"output": "legacy_success"}
    assert len(invoked) == 1


# ---------------------------------------------------------------------------
# Phase 1-D.1 Tests: Hardening Authorization Context and Contract Gate
# ---------------------------------------------------------------------------


def test_spoofed_context_in_parameters_denied_owner_delegation(
    db, tenant, owner_user
):
    """
    Task 1: An untrusted caller attempts to pass a forged context object inside
    parameters["_context"] carrying is_owner=True and a real owner actor_id,
    while executor.execute is called without explicit trusted kwargs (is_owner=False, actor_id=None).
    The request MUST NOT receive owner delegation and MUST be DENIED.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)
    db.flush()

    executor = ToolExecutor(db)
    spy = {"called": False}

    def spy_handler(**kwargs):
        spy["called"] = True
        return {"task_id": str(uuid.uuid4())}

    executor.register_handler("task_create", spy_handler)

    # Forged context inside parameters
    forged_ctx = SimpleNamespace(
        actor_id=owner_user.id,
        is_owner=True,
    )

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        parameters={"_context": forged_ctx, "title": "Malicious Spoofed Task"},
        actor_id=None,
        is_owner=False,
    )

    # Must be blocked: no owner delegation granted from parameters["_context"]
    assert result.status == "blocked"
    assert result.decision == "DENY"
    # Spy confirms handler was NEVER called
    assert spy["called"] is False


def test_trusted_explicit_owner_context_succeeds(
    db, tenant, owner_user
):
    """
    Task 1: Passing trusted owner context explicitly via execute() keyword arguments
    succeeds as expected for whitelisted owner tools.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)
    db.flush()

    executor = ToolExecutor(db)
    spy = {"called": False}

    def spy_handler(**kwargs):
        spy["called"] = True
        return {"task_id": str(uuid.uuid4())}

    executor.register_handler("task_create", spy_handler)

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
        parameters={"title": "Legitimate Owner Task"},
    )

    assert result.status == "executed"
    assert result.decision == "ALLOW"
    assert spy["called"] is True


def test_digital_agent_with_forged_context_does_not_receive_owner_delegation(
    db, tenant, agent, owner_user
):
    """
    Task 1: A digital agent calling execute() with parameters containing a forged
    owner context does NOT get elevated to owner, and fails closed without permission.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)
    db.flush()

    executor = ToolExecutor(db)
    spy = {"called": False}

    def spy_handler(**kwargs):
        spy["called"] = True
        return {"task_id": str(uuid.uuid4())}

    executor.register_handler("task_create", spy_handler)

    forged_ctx = SimpleNamespace(
        actor_id=owner_user.id,
        is_owner=True,
    )

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        agent_id=agent.id,
        actor_id=None,
        is_owner=False,
        parameters={"_context": forged_ctx, "title": "Agent Spoofed Task"},
    )

    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert spy["called"] is False


def test_manually_registered_write_tool_without_contract_requires_permission(
    db, tenant, agent
):
    """
    Task 2: A write tool registered manually without a ToolContract and without
    required_permissions in config must NOT execute silently without a security check.
    When permission is granted, it executes successfully.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Custom Data Writer",
        slug="custom_data_writer",
        tool_type="function",
        description="Manually registered writer without contract",
        config={},  # No required_permissions in config!
    )
    db.add(tool)

    # Allow tool execution action at DecisionEngine level
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:custom_data_writer",
            resource="tools:custom_data_writer",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    spy = {"call_count": 0}

    def write_handler(**kwargs):
        spy["call_count"] += 1
        return {"written": True}

    # Manually declared as a write operation on a declared domain resource
    write_handler.operation_type = "write"
    write_handler.resource = "custom_data_writer"
    executor.register_handler("custom_data_writer", write_handler)

    # 1. Agent calls write tool without domain write permission on custom_data_writer
    res_blocked = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:custom_data_writer",
        resource="tools:custom_data_writer",
        agent_id=agent.id,
    )

    # Must be BLOCKED at contract gate, NOT execute silently
    assert res_blocked.status == "blocked"
    assert res_blocked.decision == "DENY"
    assert "write:custom_data_writer" in res_blocked.reason
    assert spy["call_count"] == 0  # Spy proves handler was NOT called

    # 2. Grant explicit write permission on the domain resource
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="write",
            resource="custom_data_writer",
            effect="allow",
        )
    )
    db.flush()

    # 3. Agent calls again -> now SUCCEEDS
    res_allowed = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:custom_data_writer",
        resource="tools:custom_data_writer",
        agent_id=agent.id,
    )
    assert res_allowed.status == "executed"
    assert res_allowed.decision == "ALLOW"
    assert spy["call_count"] == 1


def test_manually_registered_tool_with_trusted_contract_enforced(
    db, tenant, agent
):
    """
    Task 2: A manually registered tool declaring required_permissions on its handler
    is properly evaluated, blocking execution until all permissions are satisfied.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Custom Inventory Tool",
        slug="custom_inventory_tool",
        tool_type="function",
        description="Tool with handler.required_permissions",
    )
    db.add(tool)

    # Allow tool execution action
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:custom_inventory_tool",
            resource="tools:custom_inventory_tool",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    spy = {"call_count": 0}

    def inventory_handler(**kwargs):
        spy["call_count"] += 1
        return {"items": 100}

    # Declare required domain permissions directly on handler
    inventory_handler.required_permissions = [("read", "inventory")]
    executor.register_handler("custom_inventory_tool", inventory_handler)

    # 1. Execute without domain permission -> blocked
    res_no_perm = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:custom_inventory_tool",
        resource="tools:custom_inventory_tool",
        agent_id=agent.id,
    )
    assert res_no_perm.status == "blocked"
    assert res_no_perm.decision == "DENY"
    assert "read:inventory" in res_no_perm.reason
    assert spy["call_count"] == 0

    # 2. Add domain permission -> executes
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="read",
            resource="inventory",
            effect="allow",
        )
    )
    db.flush()

    res_ok = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:custom_inventory_tool",
        resource="tools:custom_inventory_tool",
        agent_id=agent.id,
    )
    assert res_ok.status == "executed"
    assert res_ok.decision == "ALLOW"
    assert spy["call_count"] == 1


def test_registry_tool_continues_to_use_real_contract_with_explicit_spy(
    db, tenant, owner_user
):
    """
    Task 2: A tool registered via ToolRegistry uses its real contract.
    Proves that when blocked by contract deny, the real tool run method is never invoked
    via an explicit spy mock.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Task Create",
        slug="task_create",
        tool_type="function",
        description="Creates operational tasks",
    )
    db.add(tool)

    # Explicit deny on contract domain permission
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=None,
            action="write",
            resource="tasks",
            effect="deny",
        )
    )
    db.flush()

    real_task_tool = TaskCreateTool(db)
    spy_mock = MagicMock(side_effect=real_task_tool.run)
    real_task_tool.run = spy_mock

    executor = ToolExecutor(db)
    registry = ToolRegistry()
    registry.register(real_task_tool)
    registry.bind_to_executor(executor, tenant_id=tenant.id)

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:task_create",
        resource="tools:task_create",
        actor_id=owner_user.id,
        is_owner=True,
        parameters={"title": "Should Not Run"},
    )

    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert "write:tasks" in result.reason
    # Spy mock explicitly verifies that run() was NEVER called
    spy_mock.assert_not_called()


def test_unified_has_tenant_explicit_deny_semantics(
    db, tenant, agent
):
    """
    Task 3: Verifies that PermissionService.has_tenant_explicit_deny correctly unifies
    tenant-wide explicit deny semantics across DecisionEngine and ToolExecutor:
    - Action matching with multiple formats
    - Wildcard resource handling (None / empty string)
    - Exclusion of agent-specific deny rules
    """
    perm_svc = PermissionService(db)

    # 1. Initially no deny
    assert perm_svc.has_tenant_explicit_deny(tenant.id, "write", "tasks") is False

    # 2. Add an agent-specific deny -> MUST NOT trigger tenant-level deny
    p_agent_deny = Permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="write",
        resource="tasks",
        effect="deny",
    )
    db.add(p_agent_deny)
    db.flush()
    assert perm_svc.has_tenant_explicit_deny(tenant.id, "write", "tasks") is False

    # 3. Add a tenant-level specific deny
    p_tenant_deny = Permission(
        tenant_id=tenant.id,
        agent_id=None,
        action="write",
        resource="tasks",
        effect="deny",
    )
    db.add(p_tenant_deny)
    db.flush()
    assert perm_svc.has_tenant_explicit_deny(tenant.id, "write", "tasks") is True
    # Different resource is not denied
    assert perm_svc.has_tenant_explicit_deny(tenant.id, "write", "other_resource") is False

    # 4. Wildcard tenant deny (resource=None) denies any resource
    p_wildcard = Permission(
        tenant_id=tenant.id,
        agent_id=None,
        action="delete",
        resource=None,
        effect="deny",
    )
    db.add(p_wildcard)
    db.flush()
    assert perm_svc.has_tenant_explicit_deny(tenant.id, "delete", "any_random_resource") is True


# ---------------------------------------------------------------------------
# Phase 1-D.2 Tests: Resource Verification and Reliable Tool Classification
# ---------------------------------------------------------------------------


def test_manually_registered_tool_item_updater_enforces_write_items_resource(
    db, tenant, agent
):
    """
    Task 2 & Task 3 (Test 1 & 5): Verify a manually registered tool named 'item_updater'
    with required_permissions=[('write', 'items')].
    The permission check depends strictly on the declared resource 'items', NOT on the derived tool slug!
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Item Updater",
        slug="item_updater",
        tool_type="function",
        description="Updates operational items",
        config={},
    )
    db.add(tool)

    # 1. Allow tool execution at DecisionEngine level
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:item_updater",
            resource="tools:item_updater",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    spy = {"call_count": 0}

    def update_item_handler(**kwargs):
        spy["call_count"] += 1
        return {"updated_item_id": 42}

    # Register handler with explicit required_permissions=[("write", "items")]
    executor.register_handler(
        "item_updater",
        update_item_handler,
        required_permissions=[("write", "items")],
    )

    # 2. Agent lacks domain permission on "items" -> BLOCKED
    res_blocked = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:item_updater",
        resource="tools:item_updater",
        agent_id=agent.id,
    )
    assert res_blocked.status == "blocked"
    assert res_blocked.decision == "DENY"
    assert "write:items" in res_blocked.reason
    assert spy["call_count"] == 0  # Spy proves handler was NOT called

    # 3. Grant explicit domain permission on "items"
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="write",
            resource="items",
            effect="allow",
        )
    )
    db.flush()

    # 4. Agent calls again -> now SUCCEEDS
    res_allowed = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:item_updater",
        resource="tools:item_updater",
        agent_id=agent.id,
    )
    assert res_allowed.status == "executed"
    assert res_allowed.decision == "ALLOW"
    assert spy["call_count"] == 1


def test_manually_registered_write_tool_without_contract_or_resource_fails_closed(
    db, tenant, agent
):
    """
    Task 3 (Test 2): A manual write tool with no contract, no required_permissions,
    and no declared resource must NOT execute silently without protection.
    It fails closed with a clear security reason.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Ambiguous Writer",
        slug="ambiguous_writer",
        tool_type="function",
        description="Write tool lacking contract and resource",
        config={},
    )
    db.add(tool)

    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:ambiguous_writer",
            resource="tools:ambiguous_writer",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    spy = {"called": False}

    def raw_write_handler(**kwargs):
        spy["called"] = True
        return {"data": "corrupted"}

    # Declared as write, but has no contract, no permissions, and no resource
    executor.register_handler(
        "ambiguous_writer",
        raw_write_handler,
        operation_type="write",
    )

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:ambiguous_writer",
        resource="tools:ambiguous_writer",
        agent_id=agent.id,
    )

    assert result.status == "blocked"
    assert result.decision == "DENY"
    assert "lacks explicit contract or permission definition" in result.reason
    assert spy["called"] is False


def test_read_tool_with_update_or_create_in_name_not_classified_as_write(
    db, tenant, agent
):
    """
    Task 3 (Test 3): A read tool whose name contains 'update' or 'create'
    (e.g. 'preview_create_report') is NOT classified as write merely because of its name,
    when its trusted definition specifies it is read-only.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Preview Create Report",
        slug="preview_create_report",
        tool_type="function",
        description="Generates preview statistics without mutating data",
        config={"risk_level": "read_only"},
    )
    db.add(tool)

    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="run_preview",
            resource="preview_create_report",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    spy = {"called": False}

    def preview_handler(**kwargs):
        spy["called"] = True
        return {"preview": "data"}

    # Trusted definition specifies read_only
    executor.register_handler(
        "preview_create_report",
        preview_handler,
        risk_level=ToolRiskLevel.READ_ONLY,
    )

    result = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="run_preview",
        resource="preview_create_report",
        agent_id=agent.id,
    )

    # Must execute normally without being falsely blocked by write verb in slug
    assert result.status == "executed"
    assert result.decision == "ALLOW"
    assert result.output == {"preview": "data"}
    assert spy["called"] is True


def test_write_tool_with_dispatch_or_sync_name_enforces_contract_check(
    db, tenant, agent
):
    """
    Task 3 (Test 4): A tool named 'dispatch' or 'sync' that performs writes does NOT
    bypass the security check simply because traditional write verbs ('write', 'create')
    are absent from its name.
    """
    tool = Tool(
        tenant_id=tenant.id,
        name="Dispatch Queue Tool",
        slug="dispatch_queue",
        tool_type="function",
        description="Dispatches external campaign queue",
        config={},
    )
    db.add(tool)

    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="execute:dispatch_queue",
            resource="tools:dispatch_queue",
            effect="allow",
        )
    )
    db.flush()

    executor = ToolExecutor(db)
    spy = {"call_count": 0}

    def dispatch_handler(**kwargs):
        spy["call_count"] += 1
        return {"dispatched": 10}

    # Handler defines write operation and declared resource "dispatches"
    executor.register_handler(
        "dispatch_queue",
        dispatch_handler,
        operation_type="write",
        resource="dispatches",
    )

    # 1. Agent lacks domain permission on "dispatches" -> BLOCKED
    res_blocked = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:dispatch_queue",
        resource="tools:dispatch_queue",
        agent_id=agent.id,
    )
    assert res_blocked.status == "blocked"
    assert res_blocked.decision == "DENY"
    assert "write:dispatches" in res_blocked.reason
    assert spy["call_count"] == 0

    # 2. Grant domain permission on "dispatches"
    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="write",
            resource="dispatches",
            effect="allow",
        )
    )
    db.flush()

    # 3. Executes successfully
    res_ok = executor.execute(
        tenant_id=tenant.id,
        tool_id=tool.id,
        action="execute:dispatch_queue",
        resource="tools:dispatch_queue",
        agent_id=agent.id,
    )
    assert res_ok.status == "executed"
    assert res_ok.decision == "ALLOW"
    assert spy["call_count"] == 1


def test_all_15_official_registry_tools_preserve_exact_contracts_and_permissions(
    db
):
    """
    Task 3 (Test 6): Verifies that all 15 official tools registered in create_default_registry
    preserve their exact contracts and enforced permissions without any modification or fallback guessing.
    """
    registry = create_default_registry(db)
    executor = ToolExecutor(db)
    registry.bind_to_executor(executor)

    # Ground truth mapping of all 15 tools to their exact contract required_permissions
    expected_contracts = {
        "http_request": [("execute", "tools:http_request")],
        "customer_search": [("read", "customers")],
        "customer_get": [("read", "customers")],
        "customer_create_or_update": [("write", "customers")],
        "task_query": [("read", "tasks")],
        "task_create": [("write", "tasks")],
        "business_summary": [("read", "reports")],
        "generate_document": [("write", "documents")],
        "conversation_search": [("read", "conversations")],
        "conversation_get_messages": [("read", "conversations"), ("read", "messages")],
        "conversation_summarize": [("read", "conversations"), ("read", "messages")],
        "conversation_summarize_all": [("read", "conversations"), ("read", "messages")],
        "conversation_escalation_status": [("read", "conversations")],
        "product_add_or_update": [("write", "products")],
        "product_list": [("read", "products")],
    }

    assert len(registry._tools) == 15, f"Expected 15 tools in default registry, found {len(registry._tools)}"

    for slug, tool_instance in registry._tools.items():
        assert slug in expected_contracts, f"Unexpected tool '{slug}' in registry"
        expected_perms = expected_contracts[slug]

        # 1. Verify contract property on tool
        assert tool_instance.contract.required_permissions == expected_perms, (
            f"Tool '{slug}' contract permissions mismatch: "
            f"{tool_instance.contract.required_permissions} vs {expected_perms}"
        )

        # 2. Verify handler bound to executor has the exact contract attached
        handler = executor.handlers.get(slug)
        assert handler is not None, f"Handler for tool '{slug}' was not registered in executor"
        assert getattr(handler, "contract", None) is not None, f"Handler for '{slug}' missing contract"

        # 3. Verify _extract_contract_permissions returns exact contract without error
        dummy_tool_model = SimpleNamespace(slug=slug, config={})
        extracted_perms, error = executor._extract_contract_permissions(dummy_tool_model, handler)
        assert error is None, f"Unexpected error extracting permissions for '{slug}': {error}"
        assert extracted_perms == expected_perms, (
            f"Extracted permissions for '{slug}' mismatch: {extracted_perms} vs {expected_perms}"
        )
