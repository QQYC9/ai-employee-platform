import uuid
import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.core.database import SessionLocal
from packages.models.domain import (
    ActionPolicy,
    Agent,
    AgentCapability,
    Approval,
    Capability,
    CapabilityTool,
    Permission,
    Task,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.approval_service import ApprovalService
from packages.services.audit_service import AuditService
from packages.services.idempotency_service import (
    ConcurrencyConflictError,
    IdempotencyService,
    ReconciliationRequiredError,
)
from packages.services.task_execution_service import TaskExecutionService
from packages.services.task_lifecycle import (
    TaskStatus,
    InvalidStateTransitionError,
    can_transition,
    validate_transition,
)
from packages.services.task_planner import PlanStep
from packages.services.task_verification_service import TaskVerificationService
from packages.tools.executor import ToolExecutor


client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    t = Tenant(
        name="Phase 9 Tenant",
        slug=f"p9-tenant-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tenant_b(db):
    t = Tenant(
        name="Phase 9 Tenant B",
        slug=f"p9-tenant-b-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def agent(db, tenant):
    ag = Agent(
        tenant_id=tenant.id,
        name="Phase 9 Agent",
        agent_type="worker",
        status="active",
        system_config={},
    )
    db.add(ag)
    db.flush()
    return ag


@pytest.fixture
def user(db, tenant):
    u = User(
        tenant_id=tenant.id,
        name="Phase 9 Owner",
        email=f"p9-owner-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


def _create_tool(db, tenant, agent, slug, name="Test Tool"):
    tool = Tool(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        tool_type="function",
        description="Phase 9 test tool",
        is_active=True,
    )
    db.add(tool)
    db.flush()

    capability = Capability(
        tenant_id=tenant.id,
        name=f"Cap {slug}",
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db.add(capability)
    db.flush()

    ct = CapabilityTool(
        tenant_id=tenant.id,
        capability_id=capability.id,
        tool_id=tool.id,
    )
    db.add(ct)
    db.flush()

    ac = AgentCapability(
        tenant_id=tenant.id,
        agent_id=agent.id,
        capability_id=capability.id,
    )
    db.add(ac)
    db.flush()

    perm = Permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="execute",
        resource=tool.slug,
        effect="allow",
    )
    db.add(perm)
    db.flush()
    return tool


# ---------------------------------------------------------------------------
# Workstream 1: Lifecycle State Transitions
# ---------------------------------------------------------------------------

def test_valid_lifecycle_transitions():
    """Verify standard legal state transitions across the full lifecycle."""
    assert can_transition(TaskStatus.PENDING, TaskStatus.PLANNING)
    assert can_transition(TaskStatus.PLANNING, TaskStatus.PLANNED)
    assert can_transition(TaskStatus.PLANNED, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.COMPLETED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.FAILED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL)
    assert can_transition(TaskStatus.WAITING_APPROVAL, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.WAITING_APPROVAL, TaskStatus.FAILED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.CANCELLED)
    assert can_transition(TaskStatus.FAILED, TaskStatus.RUNNING, is_recovery=True)  # Retry
    assert can_transition(TaskStatus.FAILED, TaskStatus.PLANNED, is_recovery=True)  # Retry


def test_terminal_states_cannot_transition_illegally():
    """Terminal states (completed, cancelled) cannot transition to running without explicit recovery."""
    with pytest.raises(InvalidStateTransitionError, match="Cannot transition|Invalid task lifecycle transition"):
        validate_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING)

    with pytest.raises(InvalidStateTransitionError, match="Cannot transition|Invalid task lifecycle transition"):
        validate_transition(TaskStatus.CANCELLED, TaskStatus.RUNNING)

    with pytest.raises(InvalidStateTransitionError, match="Cannot transition|Invalid task lifecycle transition"):
        validate_transition(TaskStatus.COMPLETED, TaskStatus.CANCELLED)

    with pytest.raises(InvalidStateTransitionError, match="Cannot transition|Invalid task lifecycle transition"):
        validate_transition(TaskStatus.PENDING, TaskStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Workstream 2: Reliable Sequential Multi-Step Execution & Evidence Verification
# ---------------------------------------------------------------------------

def test_successful_multistep_execution_and_evidence_verification(db, tenant, agent):
    """Multi-step plan executes sequentially, records results, and verifies completion with evidence."""
    tool1 = _create_tool(db, tenant, agent, f"tool1_{uuid.uuid4().hex[:6]}")
    tool2 = _create_tool(db, tenant, agent, f"tool2_{uuid.uuid4().hex[:6]}")

    execution_order = []

    def handler1(**kw):
        execution_order.append("step1")
        return {"fetched_data": [1, 2, 3]}

    def handler2(**kw):
        execution_order.append("step2")
        return {"processed_items": 3, "summary": "Done"}

    tool_executor = ToolExecutor(db, handlers={tool1.slug: handler1, tool2.slug: handler2})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Multi-Step Verified Task",
        objective="Fetch data and process it",
        status=TaskStatus.PENDING,
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Fetch", action="execute", resource=tool1.slug, tool_id=tool1.id),
            PlanStep(step_id="step2", step_type="tool", description="Process", action="execute", resource=tool2.slug, tool_id=tool2.id),
        ],
    )

    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    db.refresh(task)
    assert task.status == TaskStatus.COMPLETED
    assert execution_order == ["step1", "step2"]

    # Verify task result evidence contract
    assert result.status == TaskStatus.COMPLETED
    verification = task.result.get("verification")
    assert verification is not None
    assert verification["verified"] is True
    assert verification["details"]["steps_evaluated"] == 2
    assert len(verification["unresolved"]) == 0
    assert len(verification["evidence"]["steps"]) == 2


# ---------------------------------------------------------------------------
# Workstream 3: Stop-on-Failure and Resumption
# ---------------------------------------------------------------------------

def test_stop_on_failure_prevents_dependent_steps_and_records_sanitized_error(db, tenant, agent):
    """When a step fails, subsequent steps MUST NOT run, and sanitized error is recorded."""
    tool1 = _create_tool(db, tenant, agent, f"tool1_{uuid.uuid4().hex[:6]}")
    tool2 = _create_tool(db, tenant, agent, f"tool2_{uuid.uuid4().hex[:6]}")
    tool3 = _create_tool(db, tenant, agent, f"tool3_{uuid.uuid4().hex[:6]}")

    tool1_calls = []
    tool3_calls = []

    def handler1(**kw):
        tool1_calls.append(kw)
        return {"ok": True}

    def handler2(**kw):
        raise RuntimeError("External DB connection timeout")

    def handler3(**kw):
        tool3_calls.append(kw)
        return {"ok": True}

    tool_executor = ToolExecutor(db, handlers={
        tool1.slug: handler1,
        tool2.slug: handler2,
        tool3.slug: handler3,
    })
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Stop on Failure Task",
        objective="Run 3 steps where step 2 fails",
        status=TaskStatus.PENDING,
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Step 1", action="execute", resource=tool1.slug, tool_id=tool1.id),
            PlanStep(step_id="step2", step_type="tool", description="Step 2 fails", action="execute", resource=tool2.slug, tool_id=tool2.id),
            PlanStep(step_id="step3", step_type="tool", description="Step 3 dependent", action="execute", resource=tool3.slug, tool_id=tool3.id),
        ],
    )

    with pytest.raises(RuntimeError, match="External DB connection timeout"):
        orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    db.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "External DB connection timeout" in (task.error or "")
    assert len(tool1_calls) == 1
    assert len(tool3_calls) == 0  # Dependent step 3 must NEVER have run


def test_resumption_never_repeats_completed_steps(db, tenant, agent, user):
    """On resuming an interrupted/approved task, already completed steps are skipped."""
    tool1 = _create_tool(db, tenant, agent, f"tool1_{uuid.uuid4().hex[:6]}")
    tool2 = _create_tool(db, tenant, agent, f"tool2_{uuid.uuid4().hex[:6]}")

    step1_calls = []
    step2_calls = []

    def handler1(**kw):
        step1_calls.append(kw)
        return {"step1": "completed"}

    def handler2(**kw):
        step2_calls.append(kw)
        return {"step2": "completed"}

    # Guard tool2 with an ActionPolicy requiring approval
    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="execute",
        resource=tool2.slug,
        requires_approval=True,
        approval_for="tenant_owner",
        is_active=True,
    )
    db.add(policy)
    db.flush()

    tool_executor = ToolExecutor(db, handlers={tool1.slug: handler1, tool2.slug: handler2})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Resume Safe Task",
        objective="Run step1, wait on step2, resume",
        status=TaskStatus.PENDING,
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Autonomous step", action="execute", resource=tool1.slug, tool_id=tool1.id),
            PlanStep(step_id="step2", step_type="tool", description="Guarded step", action="execute", resource=tool2.slug, tool_id=tool2.id),
        ],
    )

    # First execution pauses at step 2
    res1 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res1.status == TaskStatus.WAITING_APPROVAL
    assert len(step1_calls) == 1
    assert len(step2_calls) == 0

    # Locate and approve the approval
    approval_svc = ApprovalService(db)
    pending_approvals = approval_svc.list_approvals(tenant.id, status="pending", task_id=task.id)
    assert len(pending_approvals) >= 1
    target_approval = pending_approvals[0]
    approval_svc.approve(tenant.id, target_approval.id, user.id)

    # Resume the task
    res2 = orchestrator.resume_approved_task(tenant.id, task.id, target_approval.id)
    assert res2.status == TaskStatus.COMPLETED

    # Step 1 MUST NOT have been executed again
    assert len(step1_calls) == 1
    assert len(step2_calls) == 1


# ---------------------------------------------------------------------------
# Workstream 4: Completion Verification Contract
# ---------------------------------------------------------------------------

def test_completion_verification_fails_when_tool_output_indicates_error(tenant):
    """TaskVerificationService catches failure evidence and rejects false success."""
    verifier = TaskVerificationService()
    task = Task(
        tenant_id=tenant.id,
        title="Verification Test",
        objective="Charge customer",
        status=TaskStatus.RUNNING,
    )
    
    plan_steps = [
        {"step_id": "s1", "status": "completed", "tool_id": str(uuid.uuid4()), "result": {"error": "Downstream rejected request"}}
    ]
    
    res = verifier.verify_completion(
        task=task,
        plan=None,
        execution_results=plan_steps,
    )
    assert res.verified is False
    assert len(res.unresolved) >= 1
    assert "error" in res.unresolved[0].lower() or "failure" in res.unresolved[0].lower()


def test_completion_verification_fails_when_steps_uncompleted(tenant):
    """TaskVerificationService fails if any step is not in completed state."""
    verifier = TaskVerificationService()
    task = Task(
        tenant_id=tenant.id,
        title="Verification Test",
        objective="Multi-step workflow",
        status=TaskStatus.RUNNING,
    )
    plan_steps = [
        {"step_id": "s1", "status": "completed", "tool_id": str(uuid.uuid4()), "result": {"ok": True}},
        {"step_id": "s2", "status": "pending", "tool_id": str(uuid.uuid4()), "result": None},
    ]
    res = verifier.verify_completion(
        task=task,
        plan=None,
        execution_results=plan_steps,
    )
    assert res.verified is False
    assert len(res.unresolved) >= 1


# ---------------------------------------------------------------------------
# Workstream 5: Approval Rejection Fails Task Safely
# ---------------------------------------------------------------------------

def test_rejected_approval_fails_task_and_prevents_tool_execution(db, tenant, agent, user):
    """Rejecting an approval immediately marks task as failed and prevents execution."""
    tool = _create_tool(db, tenant, agent, f"guarded_{uuid.uuid4().hex[:6]}")
    tool_calls = []

    def handler(**kw):
        tool_calls.append(kw)
        return {"transferred": 1000}

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="execute",
        resource=tool.slug,
        requires_approval=True,
        approval_for="tenant_owner",
        is_active=True,
    )
    db.add(policy)
    db.flush()

    tool_executor = ToolExecutor(db, handlers={tool.slug: handler})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Transfer Funds",
        objective="Transfer $1000",
        status=TaskStatus.PENDING,
        priority="high",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Transfer", action="execute", resource=tool.slug, tool_id=tool.id),
        ],
    )

    res = orchestrator.execute_task(tenant.id, task.id)
    assert res.status == TaskStatus.WAITING_APPROVAL

    approval_svc = ApprovalService(db)
    pending = approval_svc.list_approvals(tenant.id, status="pending", task_id=task.id)
    target = pending[0]

    # Reject approval
    approval_svc.reject(tenant.id, target.id, user.id, reason="Transfer amount too high")

    db.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "was rejected" in (task.error or "").lower()

    # Attempting to resume must raise error
    with pytest.raises(ValueError, match="cannot be resumed|rejected"):
        orchestrator.resume_approved_task(tenant.id, task.id, target.id)

    # Tool MUST NOT have executed
    assert len(tool_calls) == 0


# ---------------------------------------------------------------------------
# Workstream 3 & 7: Idempotency & Concurrent Execution Conflict
# ---------------------------------------------------------------------------

def test_concurrent_execution_lock_prevents_duplicate_runs(db, tenant, agent):
    """Simultaneous execution attempts on the same task are rejected by idempotency lock."""
    tool = _create_tool(db, tenant, agent, f"tool_{uuid.uuid4().hex[:6]}")
    tool_executor = ToolExecutor(db, handlers={tool.slug: lambda **kw: {"ok": True}})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Concurrent Guard Task",
        objective="Test concurrency protection",
        status=TaskStatus.PENDING,
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Step 1", action="execute", resource=tool.slug, tool_id=tool.id),
        ],
    )

    # Simulate active concurrent lock
    idempotency_service = IdempotencyService(db)
    lock_key = f"task_exec:{task.id}"
    status, _ = idempotency_service.acquire_or_check(
        tenant_id=tenant.id,
        idempotency_key=lock_key,
        action="execute_task",
        resource="task",
        parameters={"task_id": str(task.id)},
        timeout_seconds=300,
    )
    assert status == "acquired"
    db.commit()

    # Second execution attempt must fail due to active concurrency lock
    with pytest.raises(ConcurrencyConflictError, match="currently in progress|already running"):
        orchestrator.execute_task(tenant.id, task.id)


# ---------------------------------------------------------------------------
# Workstream 7: Tenant Isolation & Tool Assignment at Runtime
# ---------------------------------------------------------------------------

def test_tenant_isolation_prevents_cross_tenant_task_execution(db, tenant, tenant_b, agent):
    """Tenant B cannot access or execute Tenant A's task."""
    tool = _create_tool(db, tenant, agent, f"tool_{uuid.uuid4().hex[:6]}")
    tool_executor = ToolExecutor(db, handlers={tool.slug: lambda **kw: {"ok": True}})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Tenant A Task",
        objective="Tenant A objective",
        status=TaskStatus.PENDING,
        priority="normal",
    )
    db.add(task)
    db.flush()

    # Attempt execution with Tenant B credentials
    with pytest.raises(ValueError, match="Task not found"):
        orchestrator.execute_task(tenant_id=tenant_b.id, task_id=task.id)


def test_agent_tool_assignment_enforced_at_runtime(db, tenant, agent):
    """An agent cannot execute a tool that belongs to the tenant but is not assigned to this agent."""
    unassigned_tool = Tool(
        tenant_id=tenant.id,
        name="Unassigned Tool",
        slug=f"unassigned_{uuid.uuid4().hex[:6]}",
        tool_type="function",
        description="Not assigned to agent",
        is_active=True,
    )
    db.add(unassigned_tool)
    db.flush()

    tool_executor = ToolExecutor(db, handlers={unassigned_tool.slug: lambda **kw: {"ok": True}})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Unauthorized Tool Task",
        objective="Try unassigned tool",
        status=TaskStatus.PENDING,
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Unauthorized", action="execute", resource=unassigned_tool.slug, tool_id=unassigned_tool.id),
        ],
    )

    with pytest.raises(ValueError, match="Tool is not assigned to a capability of this agent"):
        orchestrator.execute_task(tenant.id, task.id)

    db.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert "Tool is not assigned" in (task.error or "")


# ---------------------------------------------------------------------------
# Workstream 8: API Endpoints (Cancel & Retry)
# ---------------------------------------------------------------------------

def test_api_cancel_task():
    """POST /api/v1/tasks/{task_id}/cancel cancels task and records reason."""
    db = SessionLocal()
    tenant = Tenant(
        name="API Cancel Tenant",
        slug=f"api-cancel-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Cancel User",
        email=f"cancel-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(user)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Cancel Me",
        objective="Objective",
        status=TaskStatus.RUNNING,
        priority="normal",
    )
    db.add(task)
    db.commit()
    task_id = task.id
    user_id = user.id
    tenant_id = tenant.id
    db.close()

    try:
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="tenant_owner")
        response = client.post(
            f"/api/v1/tasks/{task_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "User cancelled via UI"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.CANCELLED
        assert "Cancelled: User cancelled via UI" in (data["error"] or "")
    finally:
        cleanup_db = SessionLocal()
        t = cleanup_db.get(Tenant, tenant_id)
        if t:
            cleanup_db.delete(t)
            cleanup_db.commit()
        cleanup_db.close()


def test_api_retry_failed_task():
    """POST /api/v1/tasks/{task_id}/retry allows retrying a failed task."""
    db = SessionLocal()
    tenant = Tenant(
        name="API Retry Tenant",
        slug=f"api-retry-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Retry User",
        email=f"retry-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(user)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Retry Me",
        objective="Objective",
        status=TaskStatus.FAILED,
        error="Network glitch",
        priority="normal",
    )
    db.add(task)
    db.commit()
    task_id = task.id
    user_id = user.id
    tenant_id = tenant.id
    db.close()

    try:
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="tenant_owner")
        response = client.post(
            f"/api/v1/tasks/{task_id}/retry",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Network restored", "reconciled": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == TaskStatus.PLANNED
    finally:
        cleanup_db = SessionLocal()
        t = cleanup_db.get(Tenant, tenant_id)
        if t:
            cleanup_db.delete(t)
            cleanup_db.commit()
        cleanup_db.close()


def test_api_retry_blocked_when_unreconciled():
    """POST /api/v1/tasks/{task_id}/retry blocks retry when uncertain outcome is unreconciled."""
    db = SessionLocal()
    tenant = Tenant(
        name="API Reconcile Tenant",
        slug=f"api-reconcile-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Reconcile User",
        email=f"reconcile-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(user)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Uncertain Retry",
        objective="Objective",
        status=TaskStatus.FAILED,
        error="Uncertain external outcome",
        plan={
            "steps": [
                {
                    "step_id": "step_external",
                    "status": "reconciliation_required",
                    "tool_id": str(uuid.uuid4()),
                }
            ]
        },
        priority="normal",
    )
    db.add(task)
    db.commit()
    task_id = task.id
    user_id = user.id
    tenant_id = tenant.id
    db.close()

    try:
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="tenant_owner")
        
        # 1. Blocked when reconciled=False
        response = client.post(
            f"/api/v1/tasks/{task_id}/retry",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Blind retry", "reconciled": False},
        )
        assert response.status_code == 400
        assert "reconciliation" in response.json()["detail"].lower()

        # 2. Allowed when reconciled=True
        response_ok = client.post(
            f"/api/v1/tasks/{task_id}/retry",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Reconciled manually", "reconciled": True},
        )
        assert response_ok.status_code == 200
        assert response_ok.json()["status"] == TaskStatus.PLANNED
    finally:
        cleanup_db = SessionLocal()
        t = cleanup_db.get(Tenant, tenant_id)
        if t:
            cleanup_db.delete(t)
            cleanup_db.commit()
        cleanup_db.close()


def test_api_get_task_verification():
    """GET /api/v1/tasks/{task_id}/verification returns completion verification payload."""
    db = SessionLocal()
    tenant = Tenant(
        name="API Verification Tenant",
        slug=f"api-verif-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Verification User",
        email=f"verif-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_member",
        status="active",
    )
    db.add(user)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        title="Verified Task",
        objective="Objective",
        status=TaskStatus.COMPLETED,
        result={
            "steps": [{"step_id": "step1", "status": "completed"}],
            "verification": {
                "verified": True,
                "summary": "Task verified successfully.",
                "evidence": {"steps": {"step1": {"output_verified": True}}},
                "unresolved": [],
                "details": {"steps_evaluated": 1},
            },
        },
        priority="normal",
    )
    db.add(task)
    db.commit()
    task_id = task.id
    user_id = user.id
    tenant_id = tenant.id
    db.close()

    try:
        token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="tenant_member")
        response = client.get(
            f"/api/v1/tasks/{task_id}/verification",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == str(task_id)
        assert data["verified"] is True
        assert data["summary"] == "Task verified successfully."
        assert data["evidence"]["steps"]["step1"]["output_verified"] is True
    finally:
        cleanup_db = SessionLocal()
        t = cleanup_db.get(Tenant, tenant_id)
        if t:
            cleanup_db.delete(t)
            cleanup_db.commit()
        cleanup_db.close()

