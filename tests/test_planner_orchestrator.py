import uuid

import pytest

from packages.core.database import SessionLocal
from packages.models.domain import Permission, Task, Tool
from packages.models.tenant import Tenant
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.task_planner import PlanStep, TaskPlanner
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
    tenant = Tenant(
        name="Planner Test Tenant",
        slug=f"planner-{uuid.uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.flush()

    return tenant


@pytest.fixture
def task(db, tenant):
    task = Task(
        tenant_id=tenant.id,
        title="Test task",
        objective="Research the market",
        status="pending",
        priority="normal",
        plan={},
        result={},
    )

    db.add(task)
    db.flush()

    return task


def test_basic_plan_contains_lifecycle_steps(db, task):
    planner = TaskPlanner()

    plan = planner.create_basic_plan(task)

    assert plan.objective == task.objective
    assert [step.step_id for step in plan.steps] == [
        "understand",
        "execute",
        "verify",
    ]


def test_custom_plan_is_validated(db, task):
    planner = TaskPlanner()

    plan = planner.create_plan(
        task=task,
        steps=[
            PlanStep(
                step_id="research",
                step_type="tool",
                description="Research competitors",
                action="research",
                resource="competitors",
                parameters={"query": "main competitors"},
            ),
        ],
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].action == "research"


def test_empty_plan_is_rejected(db, task):
    planner = TaskPlanner()

    with pytest.raises(
        ValueError,
        match="Execution plan must contain at least one step",
    ):
        planner.create_plan(
            task=task,
            steps=[],
        )


def test_orchestrator_persists_basic_plan(db, tenant, task):
    orchestrator = AgentOrchestrator(db)

    plan = orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert task.plan["objective"] == task.objective
    assert len(task.plan["steps"]) == 3
    assert plan.steps[0].step_id == "understand"


def test_orchestrator_executes_non_tool_plan(db, tenant, task):
    orchestrator = AgentOrchestrator(db)

    result = orchestrator.execute_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert result.status == "completed"
    assert result.task_id == task.id

    db.refresh(task)

    assert task.status == "completed"
    assert "steps" in task.result
    assert len(task.result["steps"]) == 3


def test_orchestrator_executes_tool_step(db, tenant, task):
    tool = Tool(
        tenant_id=tenant.id,
        name="Test Tool",
        slug=f"test-tool-{uuid.uuid4().hex[:8]}",
        description="Test execution tool",
        tool_type="test",
        config={},
        is_active=True,
    )

    db.add(tool)
    db.flush()

    permission = Permission(
        tenant_id=tenant.id,
        action="research",
        resource="competitors",
        effect="allow",
        conditions={},
    )

    db.add(permission)
    db.flush()

    calls = []

    def handler(**parameters):
        calls.append(parameters)

        return {
            "found": 3,
            "query": parameters["query"],
        }

    tool_executor = ToolExecutor(
        db,
        handlers={
            tool.slug: handler,
        },
    )

    orchestrator = AgentOrchestrator(
        db,
        executor=tool_executor,
    )

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="research",
                step_type="tool",
                description="Research competitors",
                action="research",
                resource="competitors",
                tool_id=tool.id,
                parameters={
                    "query": "main competitors",
                },
            ),
        ],
    )

    result = orchestrator.execute_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert result.status == "completed"
    assert calls == [
        {
            "query": "main competitors",
        }
    ]

    db.refresh(task)

    assert task.status == "completed"
    assert task.result["steps"][0]["result"] == {
        "found": 3,
        "query": "main competitors",
    }


def test_orchestrator_rejects_tool_step_without_tool(db, tenant, task):
    orchestrator = AgentOrchestrator(db)

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="missing-tool",
                step_type="tool",
                description="Execute missing tool",
                action="test",
                resource="test",
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="Tool step requires tool_id",
    ):
        orchestrator.execute_task(
            tenant_id=tenant.id,
            task_id=task.id,
        )

    db.refresh(task)

    assert task.status == "failed"
    assert "Tool step requires tool_id" in task.error

def test_orchestrator_waits_for_approval(db, tenant, task):
    tool = Tool(
        tenant_id=tenant.id,
        name="Approval Tool",
        slug=f"approval-tool-{uuid.uuid4().hex[:8]}",
        description="Tool requiring approval",
        tool_type="test",
        config={},
        is_active=True,
    )

    db.add(tool)
    db.flush()

    permission = Permission(
        tenant_id=tenant.id,
        action="publish",
        resource="content",
        effect="allow",
        conditions={},
    )

    db.add(permission)
    db.flush()

    from packages.models.domain import ActionPolicy

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="publish",
        resource="content",
        requires_approval=True,
        approval_for="tenant_owner",
        conditions={},
        is_active=True,
    )

    db.add(policy)
    db.flush()

    def handler(**parameters):
        return {"published": True}

    tool_executor = ToolExecutor(
        db,
        handlers={
            tool.slug: handler,
        },
    )

    orchestrator = AgentOrchestrator(
        db,
        executor=tool_executor,
    )

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="publish",
                step_type="tool",
                description="Publish content",
                action="publish",
                resource="content",
                tool_id=tool.id,
                parameters={"content": "Test content"},
            ),
        ],
    )

    result = orchestrator.execute_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert result.status == "waiting_approval"
    assert result.task_id == task.id

    db.refresh(task)

    assert task.status == "waiting_approval"
    assert result.result["steps"] == []


def test_orchestrator_handles_tool_failure(db, tenant, task):
    tool = Tool(
        tenant_id=tenant.id,
        name="Failing Tool",
        slug=f"failing-tool-{uuid.uuid4().hex[:8]}",
        description="Tool that fails",
        tool_type="test",
        config={},
        is_active=True,
    )

    db.add(tool)
    db.flush()

    permission = Permission(
        tenant_id=tenant.id,
        action="research",
        resource="market",
        effect="allow",
        conditions={},
    )

    db.add(permission)
    db.flush()

    def handler(**parameters):
        raise RuntimeError("External research service failed")

    tool_executor = ToolExecutor(
        db,
        handlers={
            tool.slug: handler,
        },
    )

    orchestrator = AgentOrchestrator(
        db,
        executor=tool_executor,
    )

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
        steps=[
            PlanStep(
                step_id="research",
                step_type="tool",
                description="Research market",
                action="research",
                resource="market",
                tool_id=tool.id,
                parameters={"query": "market"},
            ),
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="External research service failed",
    ):
        orchestrator.execute_task(
            tenant_id=tenant.id,
            task_id=task.id,
        )

    db.refresh(task)

    assert task.status == "failed"
    assert task.error == "External research service failed"

def test_orchestrator_builds_context_before_planning(
    db,
    tenant,
    task,
    monkeypatch,
):
    from packages.context.models import AgentContext, TaskContext

    calls = []

    class FakeContextBuilder:
        def __init__(self, retriever=None):
            pass

        def build(self, tenant_id, task, **kwargs):
            calls.append(
                {
                    "tenant_id": tenant_id,
                    "task_id": task.task_id,
                    "objective": task.objective,
                }
            )

            return AgentContext(
                tenant_id=tenant_id,
                task=task,
            )

    monkeypatch.setattr(
        "packages.services.agent_orchestrator.ContextBuilder",
        FakeContextBuilder,
        raising=False,
    )

    orchestrator = AgentOrchestrator(db)

    plan = orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert plan.objective == task.objective
    assert calls == [
        {
            "tenant_id": tenant.id,
            "task_id": task.id,
            "objective": task.objective,
        }
    ]

def test_orchestrator_passes_same_context_object_to_planner(
    db, tenant, task,
):
    from packages.context.models import AgentContext, TaskContext

    task_context = TaskContext(
        task_id=task.id,
        agent_id=task.agent_id,
        objective=task.objective,
        title=task.title,
        priority=task.priority,
        status=task.status,
    )
    expected_context = AgentContext(
        tenant_id=tenant.id,
        task=task_context,
    )

    class FakeContextBuilder:
        def build(self, tenant_id, task, **kwargs):
            return expected_context

    class CapturingPlanner:
        def __init__(self):
            self.received_context = None

        def create_basic_plan(self, task, context=None):
            self.received_context = context
            return TaskPlanner().create_basic_plan(
                task,
                context=context,
            )

    planner = CapturingPlanner()
    orchestrator = AgentOrchestrator(
        db,
        planner=planner,
        context_builder=FakeContextBuilder(),
    )

    orchestrator.plan_task(
        tenant_id=tenant.id,
        task_id=task.id,
    )

    assert planner.received_context is expected_context


def test_planner_rejects_context_from_another_tenant(
    db, tenant, task,
):
    from packages.context.models import AgentContext, TaskContext

    other_tenant = Tenant(
        name="Other Planner Tenant",
        slug=f"other-planner-{uuid.uuid4().hex[:8]}",
    )
    db.add(other_tenant)
    db.flush()

    foreign_context = AgentContext(
        tenant_id=other_tenant.id,
        task=TaskContext(
            task_id=task.id,
            agent_id=task.agent_id,
            objective=task.objective,
            title=task.title,
            priority=task.priority,
            status=task.status,
        ),
    )

    with pytest.raises(
        ValueError,
        match="Context tenant does not match task tenant",
    ):
        TaskPlanner().create_basic_plan(
            task,
            context=foreign_context,
        )
