from types import SimpleNamespace
from uuid import uuid4

from packages.services.agent_orchestrator import AgentOrchestrator


def test_available_tools_only_include_registered_handlers(monkeypatch):
    tenant_id = uuid4()
    agent_id = uuid4()
    expected_capability_id = uuid4()

    assigned_tools = [
        SimpleNamespace(
            id=uuid4(),
            name="Registered tool",
            slug="registered-tool",
            description="Can execute",
            tool_type="test",
        ),
        SimpleNamespace(
            id=uuid4(),
            name="Missing handler",
            slug="missing-handler",
            description="Cannot execute",
            tool_type="test",
        ),
    ]

    class FakeAgentCapabilityService:
        def __init__(self, db):
            pass

        def list_capabilities(self, tenant_id, agent_id):
            assert tenant_id == expected_tenant_id
            assert agent_id == expected_agent_id
            return [SimpleNamespace(id=expected_capability_id)]

    class FakeCapabilityToolService:
        def __init__(self, db):
            pass

        def list_tools(self, tenant_id, capability_id):
            assert tenant_id == expected_tenant_id
            assert capability_id == expected_capability_id
            return assigned_tools

    expected_tenant_id = tenant_id
    expected_agent_id = agent_id

    monkeypatch.setattr(
        "packages.services.agent_orchestrator.AgentCapabilityService",
        FakeAgentCapabilityService,
    )
    monkeypatch.setattr(
        "packages.services.agent_orchestrator.CapabilityToolService",
        FakeCapabilityToolService,
    )

    executor = SimpleNamespace(
        handlers={"registered-tool": lambda **kwargs: None}
    )
    orchestrator = AgentOrchestrator(
        db=object(),
        executor=executor,
        context_builder=object(),
    )

    result = orchestrator._get_available_tools(
        tenant_id=tenant_id,
        agent_id=agent_id,
    )

    assert len(result) == 1
    assert result[0]["id"] == str(assigned_tools[0].id)
    assert result[0]["slug"] == "registered-tool"


def test_available_tools_are_empty_without_agent():
    orchestrator = AgentOrchestrator(
        db=object(),
        executor=SimpleNamespace(
            handlers={"registered-tool": lambda: None}
        ),
        context_builder=object(),
    )

    assert orchestrator._get_available_tools(
        tenant_id=uuid4(),
        agent_id=None,
    ) == []


def test_available_tools_are_empty_without_executor():
    orchestrator = AgentOrchestrator(
        db=object(),
        context_builder=object(),
    )

    assert orchestrator._get_available_tools(
        tenant_id=uuid4(),
        agent_id=uuid4(),
    ) == []


def test_ai_planning_disabled_uses_no_ai_planner(monkeypatch):
    monkeypatch.setattr(
        "packages.services.agent_orchestrator.settings.ai_planning_enabled",
        False,
    )

    orchestrator = AgentOrchestrator(
        db=object(),
        context_builder=object(),
    )

    assert orchestrator._resolve_ai_planner() is None


def test_injected_ai_planner_is_used_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "packages.services.agent_orchestrator.settings.ai_planning_enabled",
        True,
    )

    expected_planner = object()
    orchestrator = AgentOrchestrator(
        db=object(),
        context_builder=object(),
        ai_planner=expected_planner,
    )

    assert orchestrator._resolve_ai_planner() is expected_planner
