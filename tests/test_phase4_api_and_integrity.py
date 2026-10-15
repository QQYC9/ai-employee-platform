import os
import uuid
import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.config import Settings
from packages.core.database import SessionLocal
from packages.models.domain import (
    ActionPolicy,
    Agent,
    AgentCapability,
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
from packages.services.decision_engine import DecisionEngine
from packages.services.task_planner import PlanStep
from packages.tools.executor import ToolExecutor


client = TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _setup_tenant_user_agent(db, prefix="p4"):
    uid = uuid.uuid4().hex[:8]
    tenant = Tenant(
        name=f"Tenant {prefix} {uid}",
        slug=f"t-{prefix}-{uid}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name=f"User {prefix}",
        email=f"user-{prefix}-{uid}@test.com",
        role="owner",
        status="active",
    )
    db.add(user)
    db.flush()

    agent = Agent(
        tenant_id=tenant.id,
        name=f"Agent {prefix}",
        agent_type="worker",
        status="active",
        system_config={},
    )
    db.add(agent)
    db.flush()

    return tenant, user, agent


def _create_authorized_tool(db, tenant, agent, slug, name="Safe Internal Tool"):
    tool = Tool(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        tool_type="internal",
        description=f"Internal tool {slug}",
        is_active=True,
    )
    db.add(tool)
    db.flush()

    cap = Capability(
        tenant_id=tenant.id,
        name=f"Cap for {slug}",
        slug=f"cap-{uuid.uuid4().hex[:8]}",
        is_active=True,
    )
    db.add(cap)
    db.flush()

    ct = CapabilityTool(
        tenant_id=tenant.id,
        capability_id=cap.id,
        tool_id=tool.id,
    )
    db.add(ct)
    db.flush()

    ac = AgentCapability(
        tenant_id=tenant.id,
        agent_id=agent.id,
        capability_id=cap.id,
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


# =========================================================================
# Point 1: سلامة الموافقات وعدم السماح بتغيير الإجراء أو المعاملات
# =========================================================================
def test_approval_integrity_blocks_tampered_parameters_and_plan(db):
    """
    Verifies that changing parameters or modifying the plan after approval
    is granted rejects the prior approval and halts execution.
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "appr_sec")
    tool = _create_authorized_tool(db, tenant, agent, f"safe_calc_{uuid.uuid4().hex[:6]}")

    # ActionPolicy requires approval
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
    def handler(**kwargs):
        calls.append(kwargs)
        return {"computed": kwargs.get("amount", 0) * 2}

    tool_executor = ToolExecutor(db, handlers={tool.slug: handler})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Guarded Calculation",
        objective="Calculate value securely",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    # Step planned with original parameters amount=100
    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="step_calc",
                step_type="tool",
                description="Calculate amount",
                action="execute",
                resource=tool.slug,
                tool_id=tool.id,
                parameters={"amount": 100},
            )
        ],
    )

    # 1. Execute task -> hits approval barrier
    res = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res.status == "waiting_approval"
    assert len(calls) == 0

    # 2. Fetch the created approval
    appr_service = ApprovalService(db)
    approvals = appr_service.list_approvals(tenant_id=tenant.id, task_id=task.id)
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.status == "pending"

    # User approves the original request (amount=100)
    appr_service.approve(tenant_id=tenant.id, approval_id=approval.id, decision_by_user_id=user.id)
    db.commit()

    # 3. Simulate tampering: modify the task plan parameters to amount=999999
    db.refresh(task)
    tampered_steps = list(task.plan["steps"])
    tampered_steps[0]["parameters"]["amount"] = 999999
    task.plan = {"objective": task.objective, "steps": tampered_steps}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "plan")
    db.commit()

    # 4. Resume the approved task into running status
    from packages.services.task_execution_service import TaskExecutionService
    exec_service = TaskExecutionService(db)
    exec_service.resume_approved_task(tenant_id=tenant.id, task_id=task.id, approval_id=approval.id)
    db.commit()

    # 5. Attempt to execute the task with tampered parameters
    # The previous approval was for amount=100. It MUST NOT allow amount=999999!
    res_tampered = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    # Must be blocked and pause again for approval!
    assert res_tampered.status == "waiting_approval"
    assert len(calls) == 0  # Handler was NEVER invoked with tampered parameters!


# =========================================================================
# Point 2: سلامة الاستئناف ومنع التكرار (Crash-before-save & Idempotency)
# =========================================================================
def test_resumption_with_crash_in_progress_reconciles_without_duplicate_call(db):
    """
    Scenario A: Tool handler executed externally, but application crashed before
    the step could be marked 'completed'. Resuming uses idempotency key to reconcile
    and NEVER calls the external handler a second time.
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "idem_rec")
    tool = _create_authorized_tool(db, tenant, agent, f"payment_sync_{uuid.uuid4().hex[:6]}")

    handler_invocations = []
    def external_payment_handler(**kw):
        handler_invocations.append(kw)
        return {"payment_id": "pay_xyz_123", "status": "settled"}

    tool_executor = ToolExecutor(db, handlers={tool.slug: external_payment_handler})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Payment Task",
        objective="Process payment once",
        status="running",
        priority="normal",
    )
    db.add(task)
    db.flush()

    idempotency_key = f"{task.id}:step_pay"

    # Pre-load idempotency cache simulating successful external processing
    tool_executor._idempotency_cache[f"{tenant.id}:{tool.id}:{idempotency_key}"] = {
        "payment_id": "pay_xyz_123",
        "status": "settled",
    }

    # Step was left 'in_progress' due to crash before writing 'completed'
    task.plan = {
        "objective": task.objective,
        "steps": [
            {
                "step_id": "step_pay",
                "step_type": "tool",
                "description": "Process external payment",
                "action": "execute",
                "resource": tool.slug,
                "tool_id": str(tool.id),
                "parameters": {"amount": 50, "idempotency_key": idempotency_key},
                "status": "in_progress",  # Left in-progress from crash
            }
        ],
    }
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "plan")
    db.commit()

    # Resume execution
    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    # Verified completed via idempotency without duplicate external call!
    assert result.status == "completed"
    assert len(handler_invocations) == 0  # No second charge!
    db.refresh(task)
    assert task.status == "completed"
    assert task.plan["steps"][0]["status"] == "completed"
    assert task.plan["steps"][0]["result"] == {"payment_id": "pay_xyz_123", "status": "settled"}


def test_resumption_with_unverifiable_in_progress_halts_for_manual_reconciliation(db):
    """
    Scenario B: Crash occurred during execution, but tool cannot verify status.
    System halts execution with 'reconciliation_required' rather than repeating unsafe actions.
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "unverif_halt")
    tool = _create_authorized_tool(db, tenant, agent, f"blind_action_{uuid.uuid4().hex[:6]}")

    handler_invocations = []
    def blind_handler(**kw):
        handler_invocations.append(kw)
        return {"done": True}

    tool_executor = ToolExecutor(db, handlers={tool.slug: blind_handler})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Unverified Task",
        objective="Safety halt test",
        status="running",
        priority="normal",
    )
    db.add(task)
    db.flush()

    # Step was left in_progress with no cached/verifiable external status
    task.plan = {
        "objective": task.objective,
        "steps": [
            {
                "step_id": "step_blind",
                "step_type": "tool",
                "description": "Unverifiable external action",
                "action": "execute",
                "resource": tool.slug,
                "tool_id": str(tool.id),
                "parameters": {"param": 1},
                "status": "in_progress",
            }
        ],
    }
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "plan")
    db.commit()

    res = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    # Must fail safely and require manual reconciliation
    assert res.status == "failed"
    assert "Manual reconciliation required" in (res.error or "")
    assert len(handler_invocations) == 0  # Tool was NOT called blindly!
    db.refresh(task)
    assert task.status == "failed"
    assert task.plan["steps"][0]["status"] == "reconciliation_required"


# =========================================================================
# Point 3: إعدادات الاتصال وأسبقية DATABASE_URL
# =========================================================================
def test_database_url_environment_precedence():
    """
    Verifies that Settings respects DATABASE_URL environment variable and does
    not hardcode local URLs over production configurations.
    """
    orig_env = os.environ.get("DATABASE_URL")
    try:
        custom_url = "postgresql+psycopg://prod_user:strong_password@db.prod.internal:5432/platform_prod"
        os.environ["DATABASE_URL"] = custom_url

        settings = Settings()
        assert settings.database_url == custom_url

    finally:
        if orig_env is not None:
            os.environ["DATABASE_URL"] = orig_env
        else:
            os.environ.pop("DATABASE_URL", None)


# =========================================================================
# Phase 4: دورة المهمة الكاملة عبر FastAPI (Full End-to-End API Lifecycle)
# =========================================================================
def test_fastapi_task_lifecycle_end_to_end(db):
    """
    Phase 4 End-to-End Test:
    1. POST /api/v1/tasks -> Create task
    2. POST /api/v1/tasks/{task_id}/plan -> Plan task with safe low-risk internal steps
    3. POST /api/v1/tasks/{task_id}/execute -> Executes step 1, halts at step 2 (requires approval)
    4. GET /api/v1/approvals?task_id={task_id} -> Verify approval is pending
    5. POST /api/v1/approvals/{approval_id}/approve -> Approve the action
    6. POST /api/v1/tasks/{task_id}/resume -> Resume task, completes step 2
    7. GET /api/v1/tasks/{task_id} -> Retrieve final task and result
    8. GET /api/v1/audit -> Verify audit trail
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "e2e_api")

    # Step 1: Low-risk internal tool (formatting)
    tool_format = _create_authorized_tool(
        db, tenant, agent, f"format_text_{uuid.uuid4().hex[:6]}", name="Format Text"
    )
    # Step 2: Guarded tool (requires approval)
    tool_publish = _create_authorized_tool(
        db, tenant, agent, f"publish_report_{uuid.uuid4().hex[:6]}", name="Publish Report"
    )

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="execute",
        resource=tool_publish.slug,
        requires_approval=True,
        approval_for="tenant_owner",
        is_active=True,
    )
    db.add(policy)
    db.commit()

    headers = {
        "X-User-ID": str(user.id),
    }

    # Register in-memory handlers on the application's default ToolExecutor if needed,
    # or register on ToolExecutor via ToolExecutor.handlers
    from packages.tools.executor import ToolExecutor
    # Register mock handlers for these test slugs
    def handle_format(**kw):
        return {"formatted_text": "Q3 Executive Summary"}

    def handle_publish(**kw):
        return {"report_id": "rep_999", "status": "published_internally"}

    # Register handlers globally on any ToolExecutor instance via class/default registry
    # In our implementation ToolExecutor accepts handlers or we can monkeypatch/register handlers:
    from packages.services.agent_orchestrator import AgentOrchestrator
    orig_init = AgentOrchestrator.__init__

    def patched_init(self, db, executor=None, context_builder=None):
        if executor is None:
            executor = ToolExecutor(
                db,
                handlers={
                    tool_format.slug: handle_format,
                    tool_publish.slug: handle_publish,
                },
            )
        orig_init(self, db, executor=executor, context_builder=context_builder)

    AgentOrchestrator.__init__ = patched_init

    try:
        # 1. POST /api/v1/tasks (Create task)
        resp_create = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "title": "Quarterly Report Lifecycle",
                "objective": "Format and publish quarterly report",
                "agent_id": str(agent.id),
                "priority": "high",
            },
        )
        assert resp_create.status_code == 201, resp_create.text
        task_data = resp_create.json()
        task_id = task_data["id"]
        assert task_data["status"] == "pending"

        # 2. POST /api/v1/tasks/{task_id}/plan (Plan task with 2 steps)
        resp_plan = client.post(
            f"/api/v1/tasks/{task_id}/plan",
            headers=headers,
            json={
                "steps": [
                    {
                        "step_id": "step_1_format",
                        "step_type": "tool",
                        "description": "Format report content",
                        "action": "execute",
                        "resource": tool_format.slug,
                        "tool_id": str(tool_format.id),
                        "parameters": {"mode": "summary"},
                    },
                    {
                        "step_id": "step_2_publish",
                        "step_type": "tool",
                        "description": "Publish formatted report",
                        "action": "execute",
                        "resource": tool_publish.slug,
                        "tool_id": str(tool_publish.id),
                        "parameters": {"channel": "internal"},
                    },
                ]
            },
        )
        assert resp_plan.status_code == 200, resp_plan.text
        planned_task = resp_plan.json()
        assert len(planned_task["plan"]["steps"]) == 2

        # 3. POST /api/v1/tasks/{task_id}/execute (Execute task)
        resp_exec = client.post(
            f"/api/v1/tasks/{task_id}/execute",
            headers=headers,
        )
        assert resp_exec.status_code == 200, resp_exec.text
        exec_data = resp_exec.json()
        assert exec_data["orchestration"]["status"] == "waiting_approval"
        assert exec_data["task"]["status"] == "waiting_approval"

        # 4. GET /api/v1/approvals?task_id={task_id} (Check approval)
        resp_apprs = client.get(
            f"/api/v1/approvals?task_id={task_id}",
            headers=headers,
        )
        assert resp_apprs.status_code == 200, resp_apprs.text
        apprs_data = resp_apprs.json()
        assert len(apprs_data) == 1
        approval_id = apprs_data[0]["id"]
        assert apprs_data[0]["status"] == "pending"
        assert apprs_data[0]["action"] == "execute"

        # 5. POST /api/v1/approvals/{approval_id}/approve (Approve)
        resp_approve = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            headers=headers,
            json={"reason": "Approved quarterly publishing by owner"},
        )
        assert resp_approve.status_code == 200, resp_approve.text
        assert resp_approve.json()["status"] == "approved"

        # 6. POST /api/v1/tasks/{task_id}/resume (Resume task)
        resp_resume = client.post(
            f"/api/v1/tasks/{task_id}/resume",
            headers=headers,
            json={"approval_id": approval_id},
        )
        assert resp_resume.status_code == 200, resp_resume.text
        resume_data = resp_resume.json()
        assert resume_data["orchestration"]["status"] == "completed"
        assert resume_data["task"]["status"] == "completed"

        # 7. GET /api/v1/tasks/{task_id} (Retrieve final task)
        resp_get = client.get(
            f"/api/v1/tasks/{task_id}",
            headers=headers,
        )
        assert resp_get.status_code == 200, resp_get.text
        final_task = resp_get.json()
        assert final_task["status"] == "completed"
        # Result data comes from actual execution output
        assert final_task["result"] is not None
        steps_out = final_task["result"]["steps"]
        assert len(steps_out) == 2
        assert steps_out[0]["result"] == {"formatted_text": "Q3 Executive Summary"}
        assert steps_out[1]["result"] == {"report_id": "rep_999", "status": "published_internally"}

        # 8. GET /api/v1/audit (Verify audit trail)
        resp_audit = client.get(
            "/api/v1/audit",
            headers=headers,
        )
        assert resp_audit.status_code == 200, resp_audit.text
        audit_events = resp_audit.json()
        event_types = [e["event_type"] for e in audit_events]
        assert "approval_requested" in event_types
        assert "task_resumed" in event_types
        assert "tool_execution" in event_types
        assert "task_completed" in event_types

    finally:
        AgentOrchestrator.__init__ = orig_init
