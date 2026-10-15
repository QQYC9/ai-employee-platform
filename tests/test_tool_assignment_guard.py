from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.task_execution_service import TaskExecutionService
from packages.services.task_planner import ExecutionPlan, PlanStep
from packages.tools.executor import ToolExecutionResult, ToolExecutor


class FakeAuditService:
    def __init__(self):
        self.events = []

    def record_event(
        self,
        tenant_id=None,
        agent_id=None,
        user_id=None,
        event_type="",
        action=None,
        description=None,
        event_metadata=None,
    ):
        event = SimpleNamespace(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            event_type=event_type,
            action=action,
            description=description,
            event_metadata=event_metadata or {},
        )
        self.events.append(event)
        return event


class FakeApprovalService:
    def __init__(self):
        self.approvals = []

    def create_approval(
        self,
        tenant_id,
        requested_for,
        action,
        description,
        task_id=None,
        requested_by_agent_id=None,
    ):
        approval = SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            task_id=task_id,
            requested_by_agent_id=requested_by_agent_id,
            requested_for=requested_for,
            action=action,
            description=description,
            status="pending",
        )
        self.approvals.append(approval)
        return approval


class FakeAgentCapabilityService:
    def __init__(self, agent_capabilities_map=None, cross_tenant_agents=None):
        # map: (tenant_id, agent_id) -> list[Capability]
        self.agent_capabilities_map = agent_capabilities_map or {}
        self.cross_tenant_agents = cross_tenant_agents or set()

    def list_capabilities(self, tenant_id: UUID, agent_id: UUID):
        if (tenant_id, agent_id) in self.cross_tenant_agents:
            raise ValueError("Agent not found")
        if (tenant_id, agent_id) not in self.agent_capabilities_map:
            raise ValueError("Agent not found")
        return self.agent_capabilities_map[(tenant_id, agent_id)]


class FakeCapabilityToolService:
    def __init__(self, capability_tools_map=None):
        # map: (tenant_id, capability_id) -> list[Tool]
        self.capability_tools_map = capability_tools_map or {}

    def list_tools(self, tenant_id: UUID, capability_id: UUID):
        return self.capability_tools_map.get((tenant_id, capability_id), [])


class FakeDB:
    def __init__(self, tasks=None):
        self.tasks = {task.id: task for task in (tasks or [])}
        self.added = []
        self.flushed = False

    def add(self, obj):
        self.added.append(obj)
        if hasattr(obj, "id"):
            self.tasks[obj.id] = obj

    def query(self, model):
        class QueryHelper:
            def __init__(self, db, model):
                self.db = db
                self.filters = []

            def filter(self, *criteria):
                self.filters.extend(criteria)
                return self

            def first(self):
                for task in self.db.tasks.values():
                    # Match by id if in filters
                    return task
                return None

        return QueryHelper(self, model)

    def flush(self):
        self.flushed = True


def make_task(tenant_id, agent_id=None, status="pending", plan=None):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        title="Test Task",
        objective="Execute safe action",
        status=status,
        priority="normal",
        plan=plan or {},
        result={},
        error=None,
    )


# =========================================================================
# Case 1: الوكيل الذي يمتلك القدرة المرتبطة بالأداة يستطيع الوصول إلى التنفيذ
# =========================================================================
def test_agent_with_assigned_tool_executes_successfully():
    tenant_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()
    capability_id = uuid4()

    task = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db = FakeDB([task])

    cap_service = FakeAgentCapabilityService(
        agent_capabilities_map={
            (tenant_id, agent_id): [SimpleNamespace(id=capability_id, is_active=True)]
        }
    )
    tool_service = FakeCapabilityToolService(
        capability_tools_map={
            (tenant_id, capability_id): [
                SimpleNamespace(id=tool_id, slug="read_kb", is_active=True)
            ]
        }
    )
    audit_service = FakeAuditService()

    handler_calls = []
    executor = SimpleNamespace(
        handlers={"read_kb": lambda **kw: handler_calls.append(kw) or {"ok": True}}
    )

    def fake_execute(tenant_id, tool_id, action, resource, parameters, agent_id):
        res = executor.handlers["read_kb"](**(parameters or {}))
        return ToolExecutionResult(
            status="executed",
            tool_id=tool_id,
            tool_slug="read_kb",
            decision="ALLOW",
            reason="Action permitted",
            output=res,
        )

    executor.execute = fake_execute

    service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    completed_task = service.execute_tool(
        tenant_id=tenant_id,
        task_id=task.id,
        tool_id=tool_id,
        action="read",
        resource="knowledge",
        parameters={"query": "test"},
        executor=executor,
    )

    assert completed_task.status == "completed"
    assert completed_task.result == {"ok": True}
    assert len(handler_calls) == 1
    assert handler_calls[0] == {"query": "test"}


# =========================================================================
# Case 2: الوكيل الذي لا يمتلك الأداة لا يستطيع تنفيذها
# =========================================================================
def test_agent_without_assigned_tool_is_blocked_and_fails_task():
    tenant_id = uuid4()
    agent_id = uuid4()
    assigned_tool_id = uuid4()
    unassigned_tool_id = uuid4()
    capability_id = uuid4()

    task = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db = FakeDB([task])

    cap_service = FakeAgentCapabilityService(
        agent_capabilities_map={
            (tenant_id, agent_id): [SimpleNamespace(id=capability_id, is_active=True)]
        }
    )
    tool_service = FakeCapabilityToolService(
        capability_tools_map={
            (tenant_id, capability_id): [
                SimpleNamespace(id=assigned_tool_id, slug="allowed_tool", is_active=True)
            ]
        }
    )
    audit_service = FakeAuditService()

    handler_calls = []
    executor = SimpleNamespace(
        execute=lambda **kw: handler_calls.append(kw)
    )

    service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    with pytest.raises(ValueError, match="Tool is not assigned to a capability of this agent"):
        service.execute_tool(
            tenant_id=tenant_id,
            task_id=task.id,
            tool_id=unassigned_tool_id,
            action="execute",
            resource="system",
            executor=executor,
        )

    # 1. Handler is NEVER called
    assert handler_calls == []
    # 2. Task status transitioned to failed
    assert task.status == "failed"
    assert "Tool is not assigned to a capability of this agent" in task.error
    # 3. AuditEvent is recorded with status=blocked
    assert len(audit_service.events) == 1
    assert audit_service.events[0].event_type == "tool_execution_blocked"
    assert audit_service.events[0].event_metadata["status"] == "blocked"


# =========================================================================
# Case 3: الأداة غير النشطة أو القدرة غير النشطة لا تسمح بالتنفيذ
# =========================================================================
def test_inactive_capability_or_inactive_tool_is_blocked():
    tenant_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()
    capability_id = uuid4()

    # 3a: Capability is inactive (omitted by list_capabilities query)
    task1 = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db1 = FakeDB([task1])
    cap_service1 = FakeAgentCapabilityService(
        agent_capabilities_map={(tenant_id, agent_id): []}  # Inactive capability filtered out
    )
    tool_service1 = FakeCapabilityToolService()
    audit1 = FakeAuditService()

    handler_calls = []
    executor = SimpleNamespace(execute=lambda **kw: handler_calls.append(kw))

    service1 = TaskExecutionService(
        db=db1,
        audit_service=audit1,
        agent_capability_service=cap_service1,
        capability_tool_service=tool_service1,
    )

    with pytest.raises(ValueError, match="Tool is not assigned"):
        service1.execute_tool(
            tenant_id=tenant_id,
            task_id=task1.id,
            tool_id=tool_id,
            action="execute",
            resource="system",
            executor=executor,
        )

    assert handler_calls == []
    assert task1.status == "failed"
    assert len(audit1.events) == 1

    # 3b: Tool is inactive (omitted by list_tools query)
    task2 = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db2 = FakeDB([task2])
    cap_service2 = FakeAgentCapabilityService(
        agent_capabilities_map={
            (tenant_id, agent_id): [SimpleNamespace(id=capability_id, is_active=True)]
        }
    )
    tool_service2 = FakeCapabilityToolService(
        capability_tools_map={(tenant_id, capability_id): []}  # Inactive tool filtered out
    )
    audit2 = FakeAuditService()

    service2 = TaskExecutionService(
        db=db2,
        audit_service=audit2,
        agent_capability_service=cap_service2,
        capability_tool_service=tool_service2,
    )

    with pytest.raises(ValueError, match="Tool is not assigned"):
        service2.execute_tool(
            tenant_id=tenant_id,
            task_id=task2.id,
            tool_id=tool_id,
            action="execute",
            resource="system",
            executor=executor,
        )

    assert handler_calls == []
    assert task2.status == "failed"
    assert len(audit2.events) == 1


# =========================================================================
# Case 4: الوكيل غير الموجود أو المملوك لمستأجر آخر لا يستطيع تنفيذ الأداة
# =========================================================================
def test_cross_tenant_or_nonexistent_agent_is_blocked():
    tenant_a = uuid4()
    tenant_b = uuid4()
    agent_of_b = uuid4()
    tool_id = uuid4()

    task = make_task(tenant_id=tenant_a, agent_id=agent_of_b, status="pending")
    db = FakeDB([task])

    cap_service = FakeAgentCapabilityService(
        cross_tenant_agents={(tenant_a, agent_of_b)}
    )
    tool_service = FakeCapabilityToolService()
    audit_service = FakeAuditService()

    handler_calls = []
    executor = SimpleNamespace(execute=lambda **kw: handler_calls.append(kw))

    service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    with pytest.raises(ValueError, match="Agent not found"):
        service.execute_tool(
            tenant_id=tenant_a,
            task_id=task.id,
            tool_id=tool_id,
            action="execute",
            resource="system",
            executor=executor,
        )

    assert handler_calls == []
    assert task.status == "failed"
    assert "Agent not found" in task.error
    assert len(audit_service.events) == 1
    assert audit_service.events[0].event_type == "tool_execution_blocked"


# =========================================================================
# Case 5: الخطة المحفوظة مسبقًا لا تتجاوز ارتباطات الأدوات الحالية
# =========================================================================
def test_saved_plan_with_unassigned_tool_is_blocked_at_orchestration():
    tenant_id = uuid4()
    agent_id = uuid4()
    unassigned_tool_id = uuid4()

    # Pre-saved plan attempting to run an unassigned tool
    saved_plan = {
        "objective": "Run malicious tool",
        "steps": [
            {
                "step_id": "step-1",
                "step_type": "tool",
                "description": "Execute unassigned tool",
                "action": "run_unassigned",
                "resource": "secret_data",
                "tool_id": str(unassigned_tool_id),
                "parameters": {},
            }
        ],
    }

    task = make_task(
        tenant_id=tenant_id,
        agent_id=agent_id,
        status="pending",
        plan=saved_plan,
    )
    db = FakeDB([task])

    cap_service = FakeAgentCapabilityService(
        agent_capabilities_map={(tenant_id, agent_id): []}
    )
    tool_service = FakeCapabilityToolService()
    audit_service = FakeAuditService()

    handler_calls = []
    tool_executor = SimpleNamespace(
        handlers={"run_unassigned": lambda **kw: handler_calls.append(kw)},
        execute=lambda **kw: handler_calls.append(kw),
    )

    task_exec_service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    orchestrator = AgentOrchestrator(
        db=db,
        executor=tool_executor,
        context_builder=SimpleNamespace(
            build=lambda **kw: SimpleNamespace(tenant_id=tenant_id)
        ),
    )
    orchestrator.executor = task_exec_service

    with pytest.raises(ValueError, match="Tool is not assigned to a capability of this agent"):
        orchestrator.execute_task(
            tenant_id=tenant_id,
            task_id=task.id,
        )

    assert handler_calls == []
    assert task.status == "failed"
    assert "Tool is not assigned to a capability of this agent" in task.error
    assert len(audit_service.events) == 1


# =========================================================================
# Case 6: إزالة ارتباط الأداة بعد التخطيط تمنع استخدامها عند التنفيذ
# =========================================================================
def test_detaching_tool_after_planning_blocks_execution():
    tenant_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()
    capability_id = uuid4()

    saved_plan = {
        "objective": "Execute dynamically detached tool",
        "steps": [
            {
                "step_id": "step-1",
                "step_type": "tool",
                "description": "Call detached tool",
                "action": "call_tool",
                "resource": "resource_a",
                "tool_id": str(tool_id),
                "parameters": {},
            }
        ],
    }

    task = make_task(
        tenant_id=tenant_id,
        agent_id=agent_id,
        status="pending",
        plan=saved_plan,
    )
    db = FakeDB([task])

    # Tool was attached during planning, but now detached!
    cap_service = FakeAgentCapabilityService(
        agent_capabilities_map={
            (tenant_id, agent_id): [SimpleNamespace(id=capability_id, is_active=True)]
        }
    )
    # Capability has NO tools now (detached)
    tool_service = FakeCapabilityToolService(
        capability_tools_map={(tenant_id, capability_id): []}
    )
    audit_service = FakeAuditService()

    handler_calls = []
    tool_executor = SimpleNamespace(
        handlers={"call_tool": lambda **kw: handler_calls.append(kw)},
        execute=lambda **kw: handler_calls.append(kw),
    )

    task_exec_service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    orchestrator = AgentOrchestrator(
        db=db,
        executor=tool_executor,
        context_builder=SimpleNamespace(
            build=lambda **kw: SimpleNamespace(tenant_id=tenant_id)
        ),
    )
    orchestrator.executor = task_exec_service

    with pytest.raises(ValueError, match="Tool is not assigned to a capability of this agent"):
        orchestrator.execute_task(
            tenant_id=tenant_id,
            task_id=task.id,
        )

    assert handler_calls == []
    assert task.status == "failed"
    assert "Tool is not assigned to a capability of this agent" in task.error


# =========================================================================
# Case 7: عدم وجود agent_id يُعالج وفق السلوك المصرح به ولا يسمح بتجاوز الصلاحيات
# =========================================================================
def test_missing_agent_id_requires_tenant_permission():
    tenant_id = uuid4()
    tool_id = uuid4()

    task = make_task(tenant_id=tenant_id, agent_id=None, status="pending")
    db = FakeDB([task])
    audit_service = FakeAuditService()

    handler_calls = []
    executor = SimpleNamespace()

    # 7a: When decision engine denies (no tenant permission)
    def fake_execute_denied(tenant_id, tool_id, action, resource, parameters, agent_id):
        return ToolExecutionResult(
            status="blocked",
            tool_id=tool_id,
            tool_slug="global_tool",
            decision="DENY",
            reason="Action is not permitted.",
        )

    executor.execute = fake_execute_denied

    service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
    )

    failed_task = service.execute_tool(
        tenant_id=tenant_id,
        task_id=task.id,
        tool_id=tool_id,
        action="read",
        resource="system",
        executor=executor,
    )

    assert failed_task.status == "failed"
    assert failed_task.error == "Action is not permitted."
    assert handler_calls == []

    # 7b: When decision engine allows (explicit tenant permission exists)
    task2 = make_task(tenant_id=tenant_id, agent_id=None, status="pending")
    db2 = FakeDB([task2])

    def fake_execute_allowed(tenant_id, tool_id, action, resource, parameters, agent_id):
        handler_calls.append({"agent": agent_id})
        return ToolExecutionResult(
            status="executed",
            tool_id=tool_id,
            tool_slug="global_tool",
            decision="ALLOW",
            reason="Action permitted",
            output={"result": "tenant_wide_success"},
        )

    executor.execute = fake_execute_allowed

    service2 = TaskExecutionService(
        db=db2,
        audit_service=audit_service,
    )

    completed_task = service2.execute_tool(
        tenant_id=tenant_id,
        task_id=task2.id,
        tool_id=tool_id,
        action="read",
        resource="system",
        executor=executor,
    )

    assert completed_task.status == "completed"
    assert completed_task.result == {"result": "tenant_wide_success"}
    assert handler_calls == [{"agent": None}]


# =========================================================================
# Case 8: رفض الأداة لا يؤدي إلى استدعاء المعالج
# =========================================================================
def test_blocked_tool_never_invokes_handler():
    tenant_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()

    task = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db = FakeDB([task])

    # Agent has no capabilities
    cap_service = FakeAgentCapabilityService(agent_capabilities_map={(tenant_id, agent_id): []})
    tool_service = FakeCapabilityToolService()

    handler_invocations = []
    executor = SimpleNamespace(
        handlers={"critical_tool": lambda **kw: handler_invocations.append("EXECUTED!")},
        execute=lambda **kw: handler_invocations.append("EXECUTED VIA EXECUTE!"),
    )

    service = TaskExecutionService(
        db=db,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    with pytest.raises(ValueError):
        service.execute_tool(
            tenant_id=tenant_id,
            task_id=task.id,
            tool_id=tool_id,
            action="danger_action",
            resource="danger_resource",
            executor=executor,
        )

    assert handler_invocations == []


# =========================================================================
# Case 9: يتم تسجيل حالة الفشل أو الحظر في سجل التدقيق وفق تصميم النظام
# =========================================================================
def test_blocked_tool_records_audit_event_with_metadata():
    tenant_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()

    task = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db = FakeDB([task])
    audit_service = FakeAuditService()

    cap_service = FakeAgentCapabilityService(agent_capabilities_map={(tenant_id, agent_id): []})
    tool_service = FakeCapabilityToolService()

    service = TaskExecutionService(
        db=db,
        audit_service=audit_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    with pytest.raises(ValueError):
        service.execute_tool(
            tenant_id=tenant_id,
            task_id=task.id,
            tool_id=tool_id,
            action="unassigned_action",
            resource="restricted_resource",
            executor=SimpleNamespace(),
        )

    assert len(audit_service.events) == 1
    event = audit_service.events[0]
    assert event.tenant_id == tenant_id
    assert event.agent_id == agent_id
    assert event.event_type == "tool_execution_blocked"
    assert event.action == "unassigned_action"
    assert event.event_metadata["tool_id"] == str(tool_id)
    assert event.event_metadata["resource"] == "restricted_resource"
    assert event.event_metadata["status"] == "blocked"
    assert event.event_metadata["decision"] == "DENY"


# =========================================================================
# Case 10: تظل آلية الموافقة تعمل مع الأداة المصرح بها التي تتطلب موافقة
# =========================================================================
def test_approval_flow_preserved_when_tool_assigned_and_policy_requires_approval():
    tenant_id = uuid4()
    agent_id = uuid4()
    tool_id = uuid4()
    capability_id = uuid4()

    task = make_task(tenant_id=tenant_id, agent_id=agent_id, status="pending")
    db = FakeDB([task])

    cap_service = FakeAgentCapabilityService(
        agent_capabilities_map={
            (tenant_id, agent_id): [SimpleNamespace(id=capability_id, is_active=True)]
        }
    )
    tool_service = FakeCapabilityToolService(
        capability_tools_map={
            (tenant_id, capability_id): [
                SimpleNamespace(id=tool_id, slug="financial_transfer", is_active=True)
            ]
        }
    )
    approval_service = FakeApprovalService()

    executor = SimpleNamespace()

    # Decision Engine says APPROVAL_REQUIRED
    def fake_execute_needs_approval(tenant_id, tool_id, action, resource, parameters, agent_id):
        return ToolExecutionResult(
            status="blocked",
            tool_id=tool_id,
            tool_slug="financial_transfer",
            decision="APPROVAL_REQUIRED",
            reason="Action is permitted but requires approval.",
        )

    executor.execute = fake_execute_needs_approval

    service = TaskExecutionService(
        db=db,
        approval_service=approval_service,
        agent_capability_service=cap_service,
        capability_tool_service=tool_service,
    )

    paused_task = service.execute_tool(
        tenant_id=tenant_id,
        task_id=task.id,
        tool_id=tool_id,
        action="transfer",
        resource="bank_account",
        executor=executor,
    )

    # 1. Task transitions to waiting_approval
    assert paused_task.status == "waiting_approval"
    # 2. Approval request is created
    assert len(approval_service.approvals) == 1
    approval = approval_service.approvals[0]
    assert approval.action == "transfer"
    assert approval.status == "pending"
    assert approval.task_id == task.id
    assert approval.requested_for == "tenant_owner"
