from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.context.models import AgentContext, TaskContext
from packages.services.gemini_task_planner import GeminiTaskPlanner


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def generate_json(
        self,
        prompt,
        *,
        system_instruction=None,
        temperature=0.1,
    ):
        self.last_prompt = prompt
        return self.response

    def generate_text(
        self,
        prompt,
        *,
        system_instruction=None,
        temperature=0.2,
    ):
        raise NotImplementedError


@pytest.fixture
def planning_data():
    tenant_id = uuid4()
    task_id = uuid4()
    tool_id = uuid4()

    task = SimpleNamespace(
        id=task_id,
        tenant_id=tenant_id,
        objective="Research the market",
        title="Market research",
        priority="normal",
    )

    task_context = TaskContext(
        task_id=task_id,
        agent_id=None,
        objective=task.objective,
        title=task.title,
        priority=task.priority,
        status="pending",
    )

    context = AgentContext(
        tenant_id=tenant_id,
        task=task_context,
        business={"identity": {"name": "Test business"}},
    )

    tools = [
        {
            "id": str(tool_id),
            "name": "Market Research",
            "slug": "market-research",
            "description": "Research market information",
            "tool_type": "research",
        }
    ]

    return task, context, tools, tool_id


def test_creates_valid_plan(planning_data):
    task, context, tools, tool_id = planning_data
    provider = FakeProvider(
        {
            "steps": [
                {
                    "step_id": "analyze",
                    "step_type": "analysis",
                    "description": "Analyze the research objective",
                },
                {
                    "step_id": "research",
                    "step_type": "tool",
                    "description": "Research the market",
                    "action": "research",
                    "resource": "market",
                    "tool_id": str(tool_id),
                    "parameters": {"query": "market trends"},
                },
                {
                    "step_id": "verify",
                    "step_type": "verification",
                    "description": "Verify the research result",
                },
            ]
        }
    )

    plan = GeminiTaskPlanner(provider).create_plan(
        task, context, tools
    )

    assert len(plan.steps) == 3
    assert plan.steps[1].tool_id == tool_id
    assert plan.objective == task.objective
    assert provider.last_prompt is not None


def test_rejects_tool_not_available_to_agent(planning_data):
    task, context, tools, _ = planning_data
    provider = FakeProvider(
        {
            "steps": [
                {
                    "step_id": "research",
                    "step_type": "tool",
                    "description": "Use an unknown tool",
                    "action": "research",
                    "resource": "market",
                    "tool_id": str(uuid4()),
                    "parameters": {},
                }
            ]
        }
    )

    with pytest.raises(
        ValueError,
        match="not available to this agent",
    ):
        GeminiTaskPlanner(provider).create_plan(
            task, context, tools
        )


def test_rejects_context_from_another_tenant(planning_data):
    task, context, tools, _ = planning_data
    other_context = AgentContext(
        tenant_id=uuid4(),
        task=context.task,
    )
    provider = FakeProvider({"steps": []})

    with pytest.raises(
        ValueError,
        match="Context tenant does not match task tenant",
    ):
        GeminiTaskPlanner(provider).create_plan(
            task, other_context, tools
        )

    assert provider.last_prompt is None


def test_rejects_empty_steps(planning_data):
    task, context, tools, _ = planning_data
    provider = FakeProvider({"steps": []})

    with pytest.raises(
        ValueError,
        match="non-empty steps array",
    ):
        GeminiTaskPlanner(provider).create_plan(
            task, context, tools
        )


def test_rejects_duplicate_step_ids(planning_data):
    task, context, tools, _ = planning_data
    provider = FakeProvider(
        {
            "steps": [
                {
                    "step_id": "analyze",
                    "step_type": "analysis",
                    "description": "First analysis",
                },
                {
                    "step_id": "analyze",
                    "step_type": "verification",
                    "description": "Second step",
                },
            ]
        }
    )

    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        GeminiTaskPlanner(provider).create_plan(
            task, context, tools
        )


def test_rejects_too_many_steps(planning_data):
    task, context, tools, _ = planning_data
    provider = FakeProvider(
        {
            "steps": [
                {
                    "step_id": f"step-{index}",
                    "step_type": "analysis",
                    "description": f"Analysis {index}",
                }
                for index in range(13)
            ]
        }
    )

    with pytest.raises(
        ValueError,
        match="cannot exceed 12 steps",
    ):
        GeminiTaskPlanner(provider).create_plan(
            task, context, tools
        )
