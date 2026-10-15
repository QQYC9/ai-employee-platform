from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import uuid
import pytest

from packages.ai_providers.base import (
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
)
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.context.models import AgentContext, TaskContext
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
from packages.services.gemini_task_planner import GeminiTaskPlanner
from packages.services.task_execution_service import TaskExecutionService
from packages.services.task_planner import PlanStep
from packages.tools.executor import ToolExecutor


class MockAIProvider:
    """Mock AIProvider for deterministic, offline testing."""

    def __init__(
        self,
        json_response: dict | None = None,
        text_response: str | None = None,
        error_to_raise: Exception | None = None,
    ):
        self.json_response = json_response or {}
        self.text_response = text_response or ""
        self.error_to_raise = error_to_raise
        self.last_prompt: str | None = None
        self.last_system_instruction: str | None = None
        self.call_count = 0

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> dict:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction
        if self.error_to_raise:
            raise self.error_to_raise
        return self.json_response

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction
        if self.error_to_raise:
            raise self.error_to_raise
        return self.text_response


@pytest.fixture(autouse=True)
def enable_ai_planning(monkeypatch):
    monkeypatch.setattr(
        "packages.services.agent_orchestrator.settings.ai_planning_enabled",
        True,
    )


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
        name="Phase 6 Tenant",
        slug=f"p6-tenant-{uuid.uuid4().hex[:8]}",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def user(db, tenant):
    u = User(
        tenant_id=tenant.id,
        name="Tenant Owner",
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        role="owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def agent(db, tenant):
    ag = Agent(
        tenant_id=tenant.id,
        name="Planning Agent",
        agent_type="worker",
        status="active",
        system_config={},
    )
    db.add(ag)
    db.flush()
    return ag


def _setup_agent_tool(db, tenant, agent, slug: str, name: str = "Test Tool") -> Tool:
    tool = Tool(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        tool_type="test",
        config={},
        is_active=True,
    )
    db.add(tool)
    db.flush()

    capability = Capability(
        tenant_id=tenant.id,
        name=f"Cap for {name}",
        slug=f"cap-{slug}",
        config={},
        is_active=True,
    )
    db.add(capability)
    db.flush()

    cap_tool = CapabilityTool(
        tenant_id=tenant.id,
        capability_id=capability.id,
        tool_id=tool.id,
    )
    db.add(cap_tool)

    agent_cap = AgentCapability(
        tenant_id=tenant.id,
        agent_id=agent.id,
        capability_id=capability.id,
    )
    db.add(agent_cap)
    db.flush()

    return tool


# ============================================================================
# 1. Valid Planning and End-to-End Execution
# ============================================================================


def test_gemini_planning_valid_creation_and_execution(db, tenant, agent):
    tool = _setup_agent_tool(db, tenant, agent, f"search_{uuid.uuid4().hex[:6]}", "Search Tool")

    perm = Permission(
        tenant_id=tenant.id,
        action="search",
        resource=tool.slug,
        effect="allow",
        conditions={},
    )
    db.add(perm)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Market Survey",
        objective="Analyze competitors and search latest data",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "step_1",
                    "step_type": "analysis",
                    "description": "Analyze competitor landscape",
                },
                {
                    "step_id": "step_2",
                    "step_type": "tool",
                    "description": "Search competitor details",
                    "action": "search",
                    "resource": tool.slug,
                    "tool_id": str(tool.id),
                    "parameters": {"query": "tech industry"},
                },
                {
                    "step_id": "step_3",
                    "step_type": "verification",
                    "description": "Verify findings",
                },
            ]
        }
    )

    planner = GeminiTaskPlanner(provider=mock_provider, decision_engine=DecisionEngine(db))

    calls = []

    def search_handler(**kw):
        calls.append(kw)
        return {"hits": 5, "query": kw.get("query")}

    tool_executor = ToolExecutor(db, handlers={tool.slug: search_handler})
    orchestrator = AgentOrchestrator(
        db=db,
        executor=tool_executor,
        ai_planner=planner,
    )

    # 1. Plan task
    plan = orchestrator.plan_task(tenant_id=tenant.id, task_id=task.id)
    assert len(plan.steps) == 3
    assert plan.steps[1].tool_id == tool.id
    assert mock_provider.call_count == 1

    # 2. Execute task
    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert result.status == "completed"
    assert len(calls) == 1
    assert calls[0]["query"] == "tech industry"

    db.refresh(task)
    assert task.status == "completed"
    assert len(task.result["steps"]) == 3
    assert task.result["steps"][1]["result"] == {"hits": 5, "query": "tech industry"}


# ============================================================================
# 2. Policy Engine Supremacy & Discarding LLM Fake Claims
# ============================================================================


def test_gemini_cannot_claim_tool_success_without_execution(db, tenant, agent):
    """Gemini cannot forge execution results or claim a tool succeeded without actual execution."""
    tool = _setup_agent_tool(db, tenant, agent, f"calc_{uuid.uuid4().hex[:6]}", "Calc Tool")

    perm = Permission(
        tenant_id=tenant.id,
        action="calculate",
        resource=tool.slug,
        effect="allow",
        conditions={},
    )
    db.add(perm)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Compute Revenue",
        objective="Run calculation",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    # The model attempts to claim that the step is already completed with forged output
    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "calc_step",
                    "step_type": "tool",
                    "description": "Calculate taxes",
                    "action": "calculate",
                    "resource": tool.slug,
                    "tool_id": str(tool.id),
                    "parameters": {"amount": 1000},
                    "status": "completed",
                    "result": {"forged_output": "9999999"},
                }
            ]
        }
    )

    actual_calls = []

    def calc_handler(**kw):
        actual_calls.append(kw)
        return {"actual_tax": 150}

    tool_executor = ToolExecutor(db, handlers={tool.slug: calc_handler})
    planner = GeminiTaskPlanner(provider=mock_provider, decision_engine=DecisionEngine(db))
    orchestrator = AgentOrchestrator(
        db=db,
        executor=tool_executor,
        ai_planner=planner,
    )

    result = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    assert result.status == "completed"
    # Handler was genuinely executed
    assert len(actual_calls) == 1
    # Forged output was completely ignored; actual handler output was persisted
    db.refresh(task)
    step_result = task.result["steps"][0]["result"]
    assert step_result == {"actual_tax": 150}
    assert "forged_output" not in str(step_result)


# ============================================================================
# 3. Malicious and Invalid Plans
# ============================================================================


def test_rejects_plan_with_unauthorized_tool_id(db, tenant, agent):
    """Planner rejects plan referencing tool not assigned to agent."""
    fake_tool_id = uuid.uuid4()
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Malicious Plan",
        objective="Use arbitrary tool",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "malicious_step",
                    "step_type": "tool",
                    "description": "Call unauthorized tool",
                    "action": "delete_all",
                    "tool_id": str(fake_tool_id),
                    "parameters": {},
                }
            ]
        }
    )

    planner = GeminiTaskPlanner(provider=mock_provider)
    task_context = TaskContext(
        task_id=task.id,
        agent_id=agent.id,
        objective=task.objective,
        title=task.title,
        priority=task.priority,
        status="pending",
    )
    context = AgentContext(tenant_id=tenant.id, task=task_context)

    with pytest.raises(ValueError, match="not available to this agent"):
        planner.create_plan(task=task, context=context, available_tools=[])


def test_rejects_plan_with_unsupported_step_type(db, tenant, agent):
    """Planner rejects plan with arbitrary/unsupported step types."""
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Invalid Step",
        objective="Run shell",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "shell_step",
                    "step_type": "arbitrary_shell_command",
                    "description": "Execute bash",
                }
            ]
        }
    )

    planner = GeminiTaskPlanner(provider=mock_provider)
    context = AgentContext(
        tenant_id=tenant.id,
        task=TaskContext(
            task_id=task.id,
            agent_id=agent.id,
            objective=task.objective,
            title=task.title,
            priority=task.priority,
            status="pending",
        ),
    )

    with pytest.raises(ValueError, match="Unsupported plan step type"):
        planner.create_plan(task=task, context=context, available_tools=[])


def test_rejects_plan_with_secret_leak_in_parameters(db, tenant, agent):
    """Planner rejects plan with secret keys/credentials leaked into parameters."""
    tool = _setup_agent_tool(db, tenant, agent, f"api_call_{uuid.uuid4().hex[:6]}")
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Secret Leak",
        objective="Run API call",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "leak_step",
                    "step_type": "tool",
                    "description": "Call with token",
                    "action": "call",
                    "tool_id": str(tool.id),
                    "parameters": {"api_key": "AQ.secret_credentials_leak"},
                }
            ]
        }
    )

    planner = GeminiTaskPlanner(provider=mock_provider)
    context = AgentContext(
        tenant_id=tenant.id,
        task=TaskContext(
            task_id=task.id,
            agent_id=agent.id,
            objective=task.objective,
            title=task.title,
            priority=task.priority,
            status="pending",
        ),
    )

    with pytest.raises(ValueError, match="must not contain raw credentials or secret key"):
        planner.create_plan(
            task=task,
            context=context,
            available_tools=[{"id": str(tool.id), "slug": tool.slug, "name": tool.name}],
        )


def test_rejects_unpermitted_action_at_planning_time(db, tenant, agent):
    """When DecisionEngine is present, planning validates permissions before execution."""
    tool = _setup_agent_tool(db, tenant, agent, f"danger_{uuid.uuid4().hex[:6]}")
    # Note: No permission is granted for action 'nuke_data'

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Forbidden Action",
        objective="Nuke data",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "step_nuke",
                    "step_type": "tool",
                    "description": "Nuke database",
                    "action": "nuke_data",
                    "resource": tool.slug,
                    "tool_id": str(tool.id),
                    "parameters": {},
                }
            ]
        }
    )

    planner = GeminiTaskPlanner(
        provider=mock_provider,
        decision_engine=DecisionEngine(db),
    )
    context = AgentContext(
        tenant_id=tenant.id,
        task=TaskContext(
            task_id=task.id,
            agent_id=agent.id,
            objective=task.objective,
            title=task.title,
            priority=task.priority,
            status="pending",
        ),
    )

    with pytest.raises(ValueError, match="Agent is not permitted to perform action"):
        planner.create_plan(
            task=task,
            context=context,
            available_tools=[{"id": str(tool.id), "slug": tool.slug, "name": tool.name}],
        )


# ============================================================================
# 4. Multi-Tenant Isolation
# ============================================================================


def test_multi_tenant_isolation_rejects_context_mismatch(db, tenant, agent):
    """Planner rejects planning when context tenant does not match task tenant."""
    other_tenant = Tenant(name="Tenant B", slug=f"t-b-{uuid.uuid4().hex[:6]}")
    db.add(other_tenant)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Tenant A Task",
        objective="Do work",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    other_context = AgentContext(
        tenant_id=other_tenant.id,
        task=TaskContext(
            task_id=task.id,
            agent_id=agent.id,
            objective=task.objective,
            title=task.title,
            priority=task.priority,
            status="pending",
        ),
    )

    mock_provider = MockAIProvider(json_response={"steps": []})
    planner = GeminiTaskPlanner(provider=mock_provider)

    with pytest.raises(ValueError, match="Context tenant does not match task tenant"):
        planner.create_plan(task=task, context=other_context, available_tools=[])

    assert mock_provider.call_count == 0


def test_multi_tenant_isolation_cannot_use_other_tenant_tool(db, tenant, agent):
    """An agent cannot plan or execute using a tool belonging to another tenant."""
    other_tenant = Tenant(name="Tenant B", slug=f"tb-{uuid.uuid4().hex[:6]}")
    db.add(other_tenant)
    db.flush()

    other_tool = Tool(
        tenant_id=other_tenant.id,
        name="Secret Tool B",
        slug=f"sec_b_{uuid.uuid4().hex[:6]}",
        tool_type="test",
        config={},
        is_active=True,
    )
    db.add(other_tool)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Cross Tenant Attack",
        objective="Steal Tenant B data",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "steal_step",
                    "step_type": "tool",
                    "description": "Access other tenant tool",
                    "action": "read",
                    "tool_id": str(other_tool.id),
                    "parameters": {},
                }
            ]
        }
    )

    tool_executor = ToolExecutor(db, handlers={other_tool.slug: lambda **kw: None})
    planner = GeminiTaskPlanner(provider=mock_provider, decision_engine=DecisionEngine(db))
    orchestrator = AgentOrchestrator(
        db=db,
        executor=tool_executor,
        ai_planner=planner,
    )

    with pytest.raises(ValueError, match="not available to this agent"):
        orchestrator.plan_task(tenant_id=tenant.id, task_id=task.id)


# ============================================================================
# 5. Required Approval Handling
# ============================================================================


def test_plan_with_action_requiring_approval_pauses_execution(db, tenant, agent, user):
    """Actions requiring approval pause execution in waiting_approval status and do not run handler."""
    tool = _setup_agent_tool(db, tenant, agent, f"wire_{uuid.uuid4().hex[:6]}", "Wire Transfer")

    perm = Permission(
        tenant_id=tenant.id,
        action="transfer",
        resource=tool.slug,
        effect="allow",
        conditions={},
    )
    db.add(perm)

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="transfer",
        resource=tool.slug,
        requires_approval=True,
        approval_for="tenant_owner",
        is_active=True,
    )
    db.add(policy)
    db.flush()

    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Wire Money",
        objective="Transfer vendor payment",
        status="pending",
        priority="high",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        json_response={
            "steps": [
                {
                    "step_id": "prep",
                    "step_type": "analysis",
                    "description": "Prepare transfer details",
                },
                {
                    "step_id": "wire_step",
                    "step_type": "tool",
                    "description": "Execute wire transfer",
                    "action": "transfer",
                    "resource": tool.slug,
                    "tool_id": str(tool.id),
                    "parameters": {"amount": 50000},
                },
            ]
        }
    )

    wire_calls = []

    def wire_handler(**kw):
        wire_calls.append(kw)
        return {"transfer_id": "tx_50k", "status": "sent"}

    tool_executor = ToolExecutor(db, handlers={tool.slug: wire_handler})
    planner = GeminiTaskPlanner(provider=mock_provider, decision_engine=DecisionEngine(db))
    orchestrator = AgentOrchestrator(
        db=db,
        executor=tool_executor,
        ai_planner=planner,
    )

    # 1. Plan task - detects approval requirement
    plan = orchestrator.plan_task(tenant_id=tenant.id, task_id=task.id)
    assert plan.steps[1].requires_approval is True

    # 2. Execute task - pauses at step requiring approval
    res1 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res1.status == "waiting_approval"
    assert len(wire_calls) == 0  # Tool handler NOT called

    db.refresh(task)
    assert task.status == "waiting_approval"

    # 3. Owner approves
    approval_svc = ApprovalService(db)
    approvals = approval_svc.list_approvals(tenant_id=tenant.id, task_id=task.id)
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.status == "pending"

    approval_svc.approve(
        tenant_id=tenant.id,
        approval_id=approval.id,
        decision_by_user_id=user.id,
        reason="Approved by owner",
    )

    # 4. Resume approved task
    exec_svc = TaskExecutionService(db)
    exec_svc.resume_approved_task(
        tenant_id=tenant.id,
        task_id=task.id,
        approval_id=approval.id,
    )

    # 5. Execute resumed task
    res2 = orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)
    assert res2.status == "completed"
    assert len(wire_calls) == 1
    assert wire_calls[0]["amount"] == 50000


# ============================================================================
# 6. Gemini Failure Handling (Timeout, API Error, Sanitization)
# ============================================================================


def test_gemini_timeout_handling(db, tenant, agent):
    """Gemini timeout raises AIProviderTimeoutError and is handled cleanly."""
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Timeout Task",
        objective="Analyze complex data",
        status="pending",
        priority="normal",
    )
    db.add(task)
    db.flush()

    mock_provider = MockAIProvider(
        error_to_raise=AIProviderTimeoutError("Gemini request timed out: deadline exceeded")
    )
    planner = GeminiTaskPlanner(provider=mock_provider)
    orchestrator = AgentOrchestrator(db=db, ai_planner=planner)

    with pytest.raises(ValueError, match="AI planning generation failed"):
        orchestrator.plan_task(tenant_id=tenant.id, task_id=task.id)


def test_gemini_provider_sanitizes_api_keys_in_errors():
    """GeminiProvider sanitizes API keys and authorization headers from error messages."""
    fake_key = "AQ.TestSecretKey1234567890abcdef"
    with patch("packages.ai_providers.gemini_provider.genai.Client") as mock_client:
        mock_instance = mock_client.return_value
        mock_instance.models.generate_content.side_effect = Exception(
            f"Failed calling https://generativelanguage.googleapis.com/v1beta/models?key={fake_key}"
        )

        provider = GeminiProvider(api_key=fake_key, model="test-model")

        with pytest.raises(AIProviderError) as exc_info:
            provider.generate_text("Hello")

        # The raw secret key must not appear in the exception message
        assert fake_key not in str(exc_info.value)
        assert "[REDACTED_KEY]" in str(exc_info.value)


def test_gemini_provider_strips_markdown_code_fences():
    """GeminiProvider properly unwraps ```json ``` code fences before parsing."""
    with patch("packages.ai_providers.gemini_provider.genai.Client") as mock_client:
        mock_instance = mock_client.return_value
        mock_response = MagicMock()
        mock_response.text = '```json\n{"steps": [{"step_id": "s1", "step_type": "analysis", "description": "Test"}]}\n```'
        mock_instance.models.generate_content.return_value = mock_response

        provider = GeminiProvider(api_key="test-key", model="test-model")
        result = provider.generate_json("Generate plan")

        assert isinstance(result, dict)
        assert "steps" in result
        assert result["steps"][0]["step_id"] == "s1"


def test_pre_execution_validation_blocks_tampered_plan(db, tenant, agent):
    """Pre-execution validation prevents running a plan injected with an unauthorized tool."""
    unauthorized_tool_id = uuid.uuid4()
    task = Task(
        tenant_id=tenant.id,
        agent_id=agent.id,
        title="Tampered Plan Task",
        objective="Run unassigned tool",
        status="pending",
        priority="normal",
        plan={
            "objective": "Run unassigned tool",
            "steps": [
                {
                    "step_id": "tampered_step",
                    "step_type": "tool",
                    "description": "Execute unassigned tool",
                    "action": "execute",
                    "resource": "resource",
                    "tool_id": str(unauthorized_tool_id),
                    "parameters": {},
                }
            ],
        },
    )
    db.add(task)
    db.flush()

    orchestrator = AgentOrchestrator(db=db)

    with pytest.raises(ValueError, match="Tool is not assigned to a capability of this agent"):
        orchestrator.execute_task(tenant_id=tenant.id, task_id=task.id)

    db.refresh(task)
    assert task.status == "failed"


def test_gemini_provider_json_timeout_raises_timeout_error():
    """GeminiProvider.generate_json raises AIProviderTimeoutError on timeout."""
    with patch("packages.ai_providers.gemini_provider.genai.Client") as mock_client:
        mock_instance = mock_client.return_value
        mock_instance.models.generate_content.side_effect = TimeoutError("Network timeout exceeded")

        provider = GeminiProvider(api_key="test-key", model="test-model")

        with pytest.raises(AIProviderTimeoutError, match="timed out"):
            provider.generate_json("Generate json")


def test_ai_provider_factory_resolution():
    """get_ai_provider respects AI_PROVIDER setting and rejects unknown providers."""
    from packages.ai_providers import get_ai_provider

    with patch("packages.ai_providers.gemini_provider.settings.gemini_api_key", "test-key"):
        gemini = get_ai_provider("gemini")
        assert isinstance(gemini, GeminiProvider)

    with pytest.raises(ValueError, match="Unsupported AI provider"):
        get_ai_provider("openai_unsupported")

