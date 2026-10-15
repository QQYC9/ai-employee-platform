import uuid
import pytest

from packages.core.database import SessionLocal
from packages.models.domain import ActionPolicy, Agent, AgentCapability, Capability, CapabilityTool, Permission, Task, Tool, User
from packages.models.tenant import Tenant
from packages.services.action_policy_service import ActionPolicyService
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.approval_service import ApprovalService
from packages.services.audit_service import AuditService
from packages.services.decision_engine import DecisionEngine
from packages.services.task_execution_service import TaskExecutionService
from packages.services.task_planner import PlanStep
from packages.tools.executor import ToolExecutor


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
        name="Phase 3 Lifecycle Tenant",
        slug=f"p3-tenant-{uuid.uuid4().hex[:8]}",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def agent(db, tenant):
    ag = Agent(
        tenant_id=tenant.id,
        name="Lifecycle Agent",
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
        name="Tenant Owner",
        email=f"owner-{uuid.uuid4().hex[:8]}@test.com",
        role="owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


def _create_tool_with_capability(db, tenant, agent, slug, name="Test Tool"):
    tool = Tool(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        tool_type="function",
        description="Lifecycle test tool",
        is_active=True,
    )
    db.add(tool)
    db.flush()

    capability = Capability(
        tenant_id=tenant.id,
        name=f"Cap for {slug}",
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


def test_step_failure_stops_execution_and_never_marks_completed(db, tenant, agent):
    """Focus 2: Handling step failure without mistakenly marking task as completed."""
    tool1 = _create_tool_with_capability(db, tenant, agent, f"tool1_{uuid.uuid4().hex[:6]}")
    tool2 = _create_tool_with_capability(db, tenant, agent, f"tool2_{uuid.uuid4().hex[:6]}")

    tool1_calls = []
    tool2_calls = []

    def handler1(**kwargs):
        tool1_calls.append(kwargs)
        return {"step1": "done"}

    def handler2(**kwargs):
        tool2_calls.append(kwargs)
        return {"step2": "should not run"}

    # We register a failing handler for an unregistered tool or let it fail
    tool_executor = ToolExecutor(db, handlers={tool1.slug: handler1, tool2.slug: handler2})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    # Tool 3 is missing a handler
    tool3 = _create_tool_with_capability(db, tenant, agent, f"tool3_{uuid.uuid4().hex[:6]}")

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Failure Stop Task",
        objective="Run 3 steps with step 2 failing",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Step 1", action="execute", resource=tool1.slug, tool_id=tool1.id),
            PlanStep(step_id="step2", step_type="tool", description="Step 2 - Fails", action="execute", resource=tool3.slug, tool_id=tool3.id),
            PlanStep(step_id="step3", step_type="tool", description="Step 3", action="execute", resource=tool2.slug, tool_id=tool2.id),
        ],
    )

    with pytest.raises(ValueError, match="No execution handler registered"):
        orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    db.refresh(task)
    assert task.status == "failed"
    assert "No execution handler" in (task.error or "")
    assert len(tool1_calls) == 1
    assert len(tool2_calls) == 0  # Step 3 MUST NEVER RUN


def test_approval_barrier_stops_execution_without_bypassing(db, tenant, agent):
    """Focus 3: Required approvals halt execution immediately."""
    tool = _create_tool_with_capability(db, tenant, agent, f"guarded_{uuid.uuid4().hex[:6]}")

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

    calls = []
    tool_executor = ToolExecutor(db, handlers={tool.slug: lambda **kw: calls.append(kw)})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Approval Barrier Task",
        objective="Verify approval stops execution",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="understand", description="Analyze request"),
            PlanStep(step_id="step2", step_type="tool", description="Run guarded tool", action="execute", resource=tool.slug, tool_id=tool.id),
            PlanStep(step_id="step3", step_type="verify", description="Verify result"),
        ],
    )

    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    assert result.status == "waiting_approval"
    db.refresh(task)
    assert task.status == "waiting_approval"
    assert len(calls) == 0  # Tool handler NEVER executed


def test_resumed_task_does_not_repeat_previously_completed_steps(db, tenant, agent, user):
    """Focus 4: Idempotency & Safe Resume without repeating external actions."""
    charge_tool = _create_tool_with_capability(db, tenant, agent, f"charge_{uuid.uuid4().hex[:6]}")
    deploy_tool = _create_tool_with_capability(db, tenant, agent, f"deploy_{uuid.uuid4().hex[:6]}")
    notify_tool = _create_tool_with_capability(db, tenant, agent, f"notify_{uuid.uuid4().hex[:6]}")

    # deploy_tool requires approval
    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="execute",
        resource=deploy_tool.slug,
        requires_approval=True,
        approval_for="tenant_owner",
        is_active=True,
    )
    db.add(policy)
    db.flush()

    charge_calls = []
    deploy_calls = []
    notify_calls = []

    def charge_handler(**kw):
        charge_calls.append(kw)
        return {"charged_amount": 100, "tx_id": "tx_999"}

    def deploy_handler(**kw):
        deploy_calls.append(kw)
        return {"deployed": True, "version": "v1.0"}

    def notify_handler(**kw):
        notify_calls.append(kw)
        return {"notified": True}

    tool_executor = ToolExecutor(
        db,
        handlers={
            charge_tool.slug: charge_handler,
            deploy_tool.slug: deploy_handler,
            notify_tool.slug: notify_handler,
        },
    )
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Safe Multi-Step Deployment",
        objective="Charge, Deploy with approval, then Notify",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step_charge", step_type="tool", description="Charge fee", action="execute", resource=charge_tool.slug, tool_id=charge_tool.id),
            PlanStep(step_id="step_deploy", step_type="tool", description="Deploy system", action="execute", resource=deploy_tool.slug, tool_id=deploy_tool.id),
            PlanStep(step_id="step_notify", step_type="tool", description="Send notification", action="execute", resource=notify_tool.slug, tool_id=notify_tool.id),
        ],
    )

    # First execution run -> pauses at step_deploy for approval
    res1 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res1.status == "waiting_approval"
    assert len(charge_calls) == 1
    assert len(deploy_calls) == 0
    assert len(notify_calls) == 0

    db.refresh(task)
    assert task.status == "waiting_approval"

    # Human approves the pending approval
    approval_service = ApprovalService(db)
    approvals = approval_service.list_approvals(tenant_id=tenant.id, task_id=task.id)
    assert len(approvals) == 1
    pending_approval = approvals[0]
    assert pending_approval.status == "pending"

    approval_service.approve(
        tenant_id=tenant.id,
        approval_id=pending_approval.id,
        decision_by_user_id=user.id,
        reason="Approved by owner",
    )

    # Resume the task
    exec_service = TaskExecutionService(db)
    exec_service.resume_approved_task(
        tenant_id=tenant.id,
        task_id=task.id,
        approval_id=pending_approval.id,
    )

    db.refresh(task)
    assert task.status == "running"

    # Second execution run -> must NOT re-charge! Must pick up and complete deploy & notify!
    res2 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res2.status == "completed"

    # CRITICAL IDEMPOTENCY CHECK:
    assert len(charge_calls) == 1  # CHARGE WAS NOT REPEATED!
    assert len(deploy_calls) == 1  # Deploy ran once after approval
    assert len(notify_calls) == 1  # Notify ran once

    db.refresh(task)
    assert task.status == "completed"
    assert task.result["steps"][0]["result"] == {"charged_amount": 100, "tx_id": "tx_999"}
    assert task.result["steps"][1]["result"] == {"deployed": True, "version": "v1.0"}
    assert task.result["steps"][2]["result"] == {"notified": True}


def test_rejected_approval_denies_and_fails_task_on_resume(db, tenant, agent, user):
    """Focus 3 & 5: When approval is rejected, task fails and blocked audit is logged."""
    tool = _create_tool_with_capability(db, tenant, agent, f"danger_{uuid.uuid4().hex[:6]}")

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

    calls = []
    tool_executor = ToolExecutor(db, handlers={tool.slug: lambda **kw: calls.append(kw)})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Rejection Test Task",
        objective="Verify rejection fails task",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Guarded tool", action="execute", resource=tool.slug, tool_id=tool.id),
        ],
    )

    res1 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res1.status == "waiting_approval"

    approval_service = ApprovalService(db)
    pending_approval = approval_service.list_approvals(tenant_id=tenant.id, task_id=task.id)[0]

    approval_service.reject(
        tenant_id=tenant.id,
        approval_id=pending_approval.id,
        decision_by_user_id=user.id,
        reason="Operation unsafe",
    )

    # Resume/execute task with rejected approval -> should be DENIED
    task.status = "running"
    db.flush()

    res2 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res2.status == "failed"
    assert "rejected" in res2.error.lower()
    assert len(calls) == 0


def test_audit_trail_records_complete_lifecycle(db, tenant, agent):
    """Focus 5: Audit events logged for task completion, failure, and blocking."""
    tool = _create_tool_with_capability(db, tenant, agent, f"audit_tool_{uuid.uuid4().hex[:6]}")

    tool_executor = ToolExecutor(db, handlers={tool.slug: lambda **kw: {"status": "ok"}})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Audit Trail Task",
        objective="Verify all audit events",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(step_id="step1", step_type="tool", description="Audit tool", action="execute", resource=tool.slug, tool_id=tool.id),
        ],
    )

    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert result.status == "completed"

    audit_service = AuditService(db)
    events = audit_service.list_events(tenant_id=tenant.id)
    event_types = [e.event_type for e in events]

    assert "tool_execution" in event_types
    assert "task_completed" in event_types


def test_result_data_comes_from_actual_execution_not_hallucination(db, tenant, agent):
    """Focus 6: Verification that result data strictly originates from handler output."""
    tool = _create_tool_with_capability(db, tenant, agent, f"real_tool_{uuid.uuid4().hex[:6]}")

    secret_signature = f"verified-exec-{uuid.uuid4().hex}"

    def real_computation(**kwargs):
        return {
            "signature": secret_signature,
            "items_computed": 42,
            "raw_input": kwargs.get("input_param"),
        }

    tool_executor = ToolExecutor(db, handlers={tool.slug: real_computation})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Real Execution Verification",
        objective="Ensure results reflect real execution",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="exec_step",
                step_type="tool",
                description="Run real computation",
                action="execute",
                resource=tool.slug,
                tool_id=tool.id,
                parameters={"input_param": "benchmark_value"},
            ),
        ],
    )

    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert result.status == "completed"

    step_result = result.result["steps"][0]["result"]
    assert step_result["signature"] == secret_signature
    assert step_result["items_computed"] == 42
    assert step_result["raw_input"] == "benchmark_value"

    db.refresh(task)
    assert task.result["steps"][0]["result"]["signature"] == secret_signature
