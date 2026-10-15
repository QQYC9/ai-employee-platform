import hashlib
import json
import os
import threading
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
    Approval,
    Capability,
    CapabilityTool,
    IdempotencyRecord,
    Permission,
    Task,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.approval_service import ApprovalService
from packages.services.idempotency_service import (
    ConcurrencyConflictError,
    IdempotencyService,
    IdempotencyTamperingError,
    ReconciliationRequiredError,
)
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


def _setup_tenant_user_agent(db, prefix="p5", role="owner"):
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
        role=role,
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


def _create_authorized_tool(db, tenant, agent, slug, name="Safe Tool"):
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

    ac = AgentCapability(
        tenant_id=tenant.id,
        agent_id=agent.id,
        capability_id=cap.id,
    )
    db.add(ac)

    perm = Permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="execute",
        resource=slug,
        effect="allow",
    )
    db.add(perm)
    db.flush()

    return tool


# =========================================================================
# Requirement 4.1: منع الوصول عبر مستأجر آخر (Cross-Tenant Access Blocking)
# =========================================================================
def test_cross_tenant_access_is_strictly_blocked(db):
    """
    Ensure Tenant B cannot access, view, execute, or resume Tenant A's tasks,
    nor view or decide upon Tenant A's approvals.
    """
    tenant_a, user_a, agent_a = _setup_tenant_user_agent(db, "tA")
    tenant_b, user_b, agent_b = _setup_tenant_user_agent(db, "tB")

    task_a = Task(
        tenant_id=tenant_a.id,
        agent_id=agent_a.id,
        title="Task in Tenant A",
        objective="Sensitive objective",
        status="waiting_approval",
        priority="normal",
        plan={},
    )
    db.add(task_a)
    db.flush()

    approval_a = Approval(
        tenant_id=tenant_a.id,
        task_id=task_a.id,
        requested_for="tenant_owner",
        action="execute",
        description="Approval in Tenant A",
        status="pending",
    )
    db.add(approval_a)
    db.commit()

    # 1. User B attempts to GET Task A
    res_get_task = client.get(
        f"/api/v1/tasks/{task_a.id}",
        headers={"X-User-ID": str(user_b.id)},
    )
    assert res_get_task.status_code == 404

    # 2. User B attempts to execute Task A
    res_exec_task = client.post(
        f"/api/v1/tasks/{task_a.id}/execute",
        headers={"X-User-ID": str(user_b.id)},
    )
    assert res_exec_task.status_code == 404

    # 3. User B attempts to resume Task A
    res_resume_task = client.post(
        f"/api/v1/tasks/{task_a.id}/resume",
        headers={"X-User-ID": str(user_b.id)},
        json={"approval_id": str(approval_a.id)},
    )
    assert res_resume_task.status_code == 404

    # 4. User B attempts to GET Approval A
    res_get_appr = client.get(
        f"/api/v1/approvals/{approval_a.id}",
        headers={"X-User-ID": str(user_b.id)},
    )
    assert res_get_appr.status_code in (403, 404)

    # 5. User B attempts to approve Approval A
    res_approve_appr = client.post(
        f"/api/v1/approvals/{approval_a.id}/approve",
        headers={"X-User-ID": str(user_b.id)},
        json={"reason": "Attacker trying to approve"},
    )
    assert res_approve_appr.status_code in (403, 404)

    # 6. User B attempts to reject Approval A
    res_reject_appr = client.post(
        f"/api/v1/approvals/{approval_a.id}/reject",
        headers={"X-User-ID": str(user_b.id)},
        json={"reason": "Attacker trying to reject"},
    )
    assert res_reject_appr.status_code in (403, 404)

    # 7. User B attempts to cancel Approval A
    res_cancel_appr = client.post(
        f"/api/v1/approvals/{approval_a.id}/cancel",
        headers={"X-User-ID": str(user_b.id)},
    )
    assert res_cancel_appr.status_code in (403, 404)


# =========================================================================
# Requirement 4.2: منع مستخدم غير مخوّل من الموافقة أو الاستئناف
# =========================================================================
def test_unauthorized_user_blocked_from_approval_and_resumption(db):
    """
    Ensure a non-owner/non-admin user (role='tenant_user') cannot approve
    or reject owner approvals, and cannot resume tasks they do not own.
    """
    tenant, owner_user, agent = _setup_tenant_user_agent(db, "auth_t", role="owner")

    # Create regular user in the same tenant
    regular_user = User(
        tenant_id=tenant.id,
        name="Regular User",
        email=f"reg-{uuid.uuid4().hex[:6]}@test.com",
        role="tenant_user",
        status="active",
    )
    db.add(regular_user)
    db.flush()

    # Create a task and approval requiring 'tenant_owner'
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        requested_by_user_id=owner_user.id,
        title="Owner Restricted Task",
        objective="Requires owner approval",
        status="waiting_approval",
        priority="high",
        plan={},
    )
    db.add(task)
    db.flush()

    approval_service = ApprovalService(db)
    approval = approval_service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="execute",
        description="High privilege action",
        task_id=task.id,
    )
    db.commit()

    # Regular user attempts to approve -> HTTP 403 Forbidden
    res_reg_approve = client.post(
        f"/api/v1/approvals/{approval.id}/approve",
        headers={"X-User-ID": str(regular_user.id)},
        json={"reason": "Attempt by regular user"},
    )
    assert res_reg_approve.status_code == 403
    assert "not authorized" in res_reg_approve.json()["detail"].lower()

    # Regular user attempts to reject -> HTTP 403 Forbidden
    res_reg_reject = client.post(
        f"/api/v1/approvals/{approval.id}/reject",
        headers={"X-User-ID": str(regular_user.id)},
        json={"reason": "Attempt by regular user"},
    )
    assert res_reg_reject.status_code == 403

    # Regular user attempts to cancel -> HTTP 403 Forbidden
    res_reg_cancel = client.post(
        f"/api/v1/approvals/{approval.id}/cancel",
        headers={"X-User-ID": str(regular_user.id)},
    )
    assert res_reg_cancel.status_code == 403

    # Owner user approves successfully
    res_owner_approve = client.post(
        f"/api/v1/approvals/{approval.id}/approve",
        headers={"X-User-ID": str(owner_user.id)},
        json={"reason": "Authorized owner approval"},
    )
    assert res_owner_approve.status_code == 200

    # Another unprivileged user in the tenant attempts to resume -> HTTP 403 Forbidden
    third_user = User(
        tenant_id=tenant.id,
        name="Third User",
        email=f"third-{uuid.uuid4().hex[:6]}@test.com",
        role="tenant_user",
        status="active",
    )
    db.add(third_user)
    db.commit()

    res_unauth_resume = client.post(
        f"/api/v1/tasks/{task.id}/resume",
        headers={"X-User-ID": str(third_user.id)},
        json={"approval_id": str(approval.id)},
    )
    assert res_unauth_resume.status_code == 403
    assert "lacks permissions to resume" in res_unauth_resume.json()["detail"].lower()


# =========================================================================
# Requirement 4.3: تغيير الأداة أو الإجراء أو المورد أو المعاملات بعد الموافقة
# =========================================================================
def test_tampering_of_tool_action_resource_params_after_approval(db):
    """
    Verify that altering any of:
      - parameters
      - action
      - resource
      - tool_id
    after an approval is granted prevents execution of the altered action
    without a fresh approval.
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "tamper_t")
    tool1 = _create_authorized_tool(db, tenant, agent, f"tool1_{uuid.uuid4().hex[:6]}")
    tool2 = _create_authorized_tool(db, tenant, agent, f"tool2_{uuid.uuid4().hex[:6]}")

    perm_tx = Permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="transfer_funds",
        resource=tool1.slug,
        effect="allow",
    )
    db.add(perm_tx)

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="transfer_funds",
        resource=tool1.slug,
        requires_approval=True,
        approval_for="tenant_owner",
        is_active=True,
    )
    db.add(policy)
    db.commit()

    calls = []
    def tool_handler(**kw):
        calls.append(kw)
        return {"status": "transferred", "data": kw}

    tool_executor = ToolExecutor(db, handlers={tool1.slug: tool_handler, tool2.slug: tool_handler})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    # Subcase A: Tampering parameters
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        requested_by_user_id=user.id,
        title="Fund Transfer Task",
        objective="Transfer funds safely",
        status="pending",
        priority="high",
    )
    db.add(task)
    db.flush()

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="step_tx",
                step_type="tool",
                description="Transfer 100",
                action="transfer_funds",
                resource=tool1.slug,
                tool_id=tool1.id,
                parameters={"amount": 100},
            )
        ],
    )

    # Step hits approval barrier
    res = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res.status == "waiting_approval"

    appr_service = ApprovalService(db)
    approvals = appr_service.list_approvals(tenant_id=tenant.id, task_id=task.id)
    assert len(approvals) == 1
    approval = approvals[0]
    appr_service.approve(tenant_id=tenant.id, approval_id=approval.id, decision_by_user_id=user.id)
    db.commit()

    # Resume the approved task into running status
    from packages.services.task_execution_service import TaskExecutionService
    exec_service = TaskExecutionService(db)
    exec_service.resume_approved_task(tenant_id=tenant.id, task_id=task.id, approval_id=approval.id)
    db.commit()

    # Tamper parameters: change 100 to 999999
    db.refresh(task)
    tampered_steps = list(task.plan["steps"])
    tampered_steps[0]["parameters"]["amount"] = 999999
    task.plan = {"objective": task.objective, "steps": tampered_steps}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "plan")
    db.commit()

    # Attempt to execute with tampered parameters -> blocked, resets to waiting_approval
    res_tampered_param = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res_tampered_param.status == "waiting_approval"
    assert len(calls) == 0  # Tool was never called!

    # Subcase B: Tampering action (transfer_funds -> drain_account)
    # Resume again
    task.status = "running"
    tampered_steps[0]["parameters"]["amount"] = 100  # restore
    tampered_steps[0]["action"] = "drain_account"
    task.plan = {"objective": task.objective, "steps": tampered_steps}
    flag_modified(task, "plan")
    db.commit()

    res_tampered_action = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res_tampered_action.status in ("waiting_approval", "failed")
    assert len(calls) == 0

    # Subcase C: Tampering tool_id
    task.status = "running"
    tampered_steps[0]["action"] = "transfer_funds"
    tampered_steps[0]["tool_id"] = str(tool2.id)
    tampered_steps[0]["resource"] = tool2.slug
    task.plan = {"objective": task.objective, "steps": tampered_steps}
    flag_modified(task, "plan")
    db.commit()

    res_tampered_tool = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res_tampered_tool.status in ("waiting_approval", "failed")
    assert len(calls) == 0


# =========================================================================
# Requirement 4.4: تكرار الطلبات بالتزامن (Concurrency & Idempotency Locking)
# =========================================================================
def test_concurrent_requests_handled_with_idempotency(db):
    """
    Verify persistent idempotency locking in PostgreSQL:
      - First request acquires in_progress lock.
      - Concurrent request attempting the same key raises ConcurrencyConflictError (HTTP 409).
      - After completion, subsequent calls return cached output without re-executing.
      - Reusing key with altered parameters raises IdempotencyTamperingError.
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "concurrent_t")
    tool = _create_authorized_tool(db, tenant, agent, f"tool_conc_{uuid.uuid4().hex[:6]}")

    idem_service = IdempotencyService(db)
    idem_key = f"key_{uuid.uuid4().hex}"

    # 1. First call acquires lock
    status1, out1 = idem_service.acquire_or_check(
        tenant_id=tenant.id,
        idempotency_key=idem_key,
        action="execute",
        resource=tool.slug,
        tool_id=tool.id,
        parameters={"order_id": 123},
    )
    assert status1 == "acquired"
    assert out1 is None
    db.commit()

    # 2. Concurrent second call attempting the same key hits in_progress lock
    with pytest.raises(ConcurrencyConflictError):
        idem_service.acquire_or_check(
            tenant_id=tenant.id,
            idempotency_key=idem_key,
            action="execute",
            resource=tool.slug,
            tool_id=tool.id,
            parameters={"order_id": 123},
        )

    # 3. First call completes and persists result
    completed_record = idem_service.complete(
        tenant_id=tenant.id,
        idempotency_key=idem_key,
        result={"status": "order_placed", "order_id": 123},
    )
    assert completed_record is not None
    assert completed_record.status == "completed"
    db.commit()

    # 4. Subsequent third call retrieves completed result
    status3, out3 = idem_service.acquire_or_check(
        tenant_id=tenant.id,
        idempotency_key=idem_key,
        action="execute",
        resource=tool.slug,
        tool_id=tool.id,
        parameters={"order_id": 123},
    )
    assert status3 == "completed"
    assert out3 == {"status": "order_placed", "order_id": 123}

    # 5. Attacker tries to reuse the same idempotency key with altered parameters
    with pytest.raises(IdempotencyTamperingError):
        idem_service.acquire_or_check(
            tenant_id=tenant.id,
            idempotency_key=idem_key,
            action="execute",
            resource=tool.slug,
            tool_id=tool.id,
            parameters={"order_id": 99999},  # Tampered!
        )


# =========================================================================
# Requirement 4.5: التعطل والاستئناف مع نجاح الإجراء الخارجي أو غموض نتيجته
# =========================================================================
def test_crash_resume_verifiable_vs_ambiguous(db):
    """
    Case 1 (Verifiable):
      External tool succeeded and was saved to persistent idempotency storage.
      Application crashed before step completed.
      Resuming recovers output from PostgreSQL and does not call tool again.

    Case 2 (Ambiguous / Non-Verifiable):
      External tool does not support verification and crashed in-progress.
      System stops automatic retry, transitions step to 'reconciliation_required',
      sets task to 'failed' and demands manual settlement. Tool is not called twice.
    """
    tenant, user, agent = _setup_tenant_user_agent(db, "crash_t")
    tool = _create_authorized_tool(db, tenant, agent, f"tool_crash_{uuid.uuid4().hex[:6]}")

    invocations = []
    def unverified_payment_tool(**kw):
        invocations.append(kw)
        return {"payment_id": "pay_999"}

    # unverified tool has no verify_status or idempotency support
    tool_executor = ToolExecutor(db, handlers={tool.slug: unverified_payment_tool})
    orchestrator = AgentOrchestrator(db, executor=tool_executor)

    # ----------------------------------------------------
    # Case 1: Verifiable via persistent IdempotencyRecord
    # ----------------------------------------------------
    task_verifiable = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        requested_by_user_id=user.id,
        title="Verifiable Crash Task",
        objective="Handle verifiable crash",
        status="running",
        priority="normal",
    )
    db.add(task_verifiable)
    db.flush()

    key_verifiable = f"{task_verifiable.id}:step_pay"

    # Save completed record in PostgreSQL simulating successful tool execution before crash
    idem_service = IdempotencyService(db)
    idem_service.acquire_or_check(
        tenant_id=tenant.id,
        idempotency_key=key_verifiable,
        action="execute",
        resource=tool.slug,
        tool_id=tool.id,
        parameters={"amount": 50, "idempotency_key": key_verifiable},
    )
    idem_service.complete(
        tenant_id=tenant.id,
        idempotency_key=key_verifiable,
        result={"payment_id": "pay_verified_123", "status": "confirmed"},
    )
    db.commit()

    # Step was left 'in_progress' in plan due to application crash
    task_verifiable.plan = {
        "objective": task_verifiable.objective,
        "steps": [
            {
                "step_id": "step_pay",
                "step_type": "tool",
                "description": "Process payment",
                "action": "execute",
                "resource": tool.slug,
                "tool_id": str(tool.id),
                "parameters": {"amount": 50, "idempotency_key": key_verifiable},
                "status": "in_progress",
            }
        ],
    }
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task_verifiable, "plan")
    db.commit()

    # Resuming reconciles from DB without invoking external tool
    res_rec = orchestrator.execute_task(tenant_id=tenant.id, task_id=task_verifiable.id)
    assert res_rec.status == "completed"
    assert len(invocations) == 0  # ZERO calls to tool!
    assert res_rec.result["steps"][0]["result"] == {
        "payment_id": "pay_verified_123",
        "status": "confirmed",
    }

    # ----------------------------------------------------
    # Case 2: Ambiguous / Unverifiable Tool
    # ----------------------------------------------------
    task_ambiguous = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        requested_by_user_id=user.id,
        title="Ambiguous Crash Task",
        objective="Handle unverifiable crash",
        status="running",
        priority="normal",
    )
    db.add(task_ambiguous)
    db.flush()

    key_ambiguous = f"{task_ambiguous.id}:step_blind"

    # Step left in_progress from crash, but no completed record exists
    task_ambiguous.plan = {
        "objective": task_ambiguous.objective,
        "steps": [
            {
                "step_id": "step_blind",
                "step_type": "tool",
                "description": "Blind payment",
                "action": "execute",
                "resource": tool.slug,
                "tool_id": str(tool.id),
                "parameters": {"amount": 75, "idempotency_key": key_ambiguous},
                "status": "in_progress",
            }
        ],
    }
    flag_modified(task_ambiguous, "plan")
    db.commit()

    # Resuming MUST NOT execute blind retry! Must require manual reconciliation
    res_ambiguous = orchestrator.execute_task(tenant_id=tenant.id, task_id=task_ambiguous.id)
    assert res_ambiguous.status == "failed"
    assert len(invocations) == 0  # ZERO duplicate invocations!
    assert "manual reconciliation required" in res_ambiguous.error.lower()

    # Verify task in DB is marked reconciliation_required
    db.refresh(task_ambiguous)
    assert task_ambiguous.status == "failed"
    assert task_ambiguous.plan["steps"][0]["status"] == "reconciliation_required"


# =========================================================================
# Requirement 4.6: بقاء الإعدادات المحلية قابلة للتجاوز بواسطة متغيرات البيئة
# =========================================================================
def test_local_settings_overridable_by_env_vars():
    """
    Verify that environment variables strictly override default configuration values.
    """
    custom_db = "postgresql+psycopg://override_user:override_pass@custom-host:5433/custom_db"
    custom_redis = "redis://override-redis:6379/3"
    custom_ai = "custom_provider"

    old_db = os.environ.get("DATABASE_URL")
    old_redis = os.environ.get("REDIS_URL")
    old_ai = os.environ.get("AI_PROVIDER")

    try:
        os.environ["DATABASE_URL"] = custom_db
        os.environ["REDIS_URL"] = custom_redis
        os.environ["AI_PROVIDER"] = custom_ai

        settings = Settings()
        assert settings.database_url == custom_db
        assert settings.redis_url == custom_redis
        assert settings.ai_provider == custom_ai
    finally:
        if old_db is not None:
            os.environ["DATABASE_URL"] = old_db
        else:
            os.environ.pop("DATABASE_URL", None)
        if old_redis is not None:
            os.environ["REDIS_URL"] = old_redis
        else:
            os.environ.pop("REDIS_URL", None)
        if old_ai is not None:
            os.environ["AI_PROVIDER"] = old_ai
        else:
            os.environ.pop("AI_PROVIDER", None)

