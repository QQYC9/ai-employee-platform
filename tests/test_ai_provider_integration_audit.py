from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.ai_providers.base import (
    AIAuthenticationError,
    AIConnectionError,
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
)
from packages.ai_providers.factory import AIProviderFactory
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.ai_providers.openai_compatible_provider import OpenAICompatibleProvider
from packages.auth.jwt_service import create_access_token
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import (
    ActionPolicy,
    Agent,
    AgentCapability,
    Capability,
    CapabilityTool,
    Credential,
    Integration,
    Permission,
    Task,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.ai_provider_service import AIProviderService
from packages.services.ai_task_planner import AITaskPlanner
from packages.services.decision_engine import DecisionEngine
from packages.services.gemini_task_planner import GeminiTaskPlanner
from packages.services.task_planner import ExecutionPlan, PlanStep
from packages.tools.executor import ToolExecutor

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def tenant_a(db: Session):
    t = Tenant(
        name="Integration Audit Tenant A",
        slug=f"audit-tenant-a-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(
        name="Integration Audit Tenant B",
        slug=f"audit-tenant-b-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def owner_user_a(db: Session, tenant_a: Tenant):
    u = User(
        tenant_id=tenant_a.id,
        name="Owner User A",
        email=f"owner-audit-a-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def member_user_a(db: Session, tenant_a: Tenant):
    u = User(
        tenant_id=tenant_a.id,
        name="Member User A",
        email=f"member-audit-a-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_member",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def platform_admin_user(db: Session, tenant_a: Tenant):
    u = User(
        tenant_id=tenant_a.id,
        name="Platform Admin",
        email=f"platform-admin-{uuid.uuid4().hex[:8]}@example.com",
        role="platform_admin",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def sample_task(db: Session, tenant_a: Tenant):
    t = Task(
        tenant_id=tenant_a.id,
        title="Audit Security Task",
        objective="Analyze cloud security posture and report anomalies",
        status="pending",
        priority="high",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


VALID_PLAN_JSON = {
    "steps": [
        {
            "step_id": "s1",
            "step_type": "analysis",
            "description": "Examine firewall logs",
            "action": None,
            "resource": None,
            "tool_id": None,
            "parameters": {},
        },
        {
            "step_id": "s2",
            "step_type": "verification",
            "description": "Verify compliance report",
            "action": None,
            "resource": None,
            "tool_id": None,
            "parameters": {},
        },
    ]
}


# ---------------------------------------------------------------------------
# 1. Task Planning Uses Configured Groq Provider (openai/gpt-oss-120b)
# ---------------------------------------------------------------------------

def test_task_planning_uses_configured_groq_provider(
    db: Session,
    tenant_a: Tenant,
    sample_task: Task,
):
    service = AIProviderService(db)
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="groq-planning-cfg",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_test_groq_key_for_planning_1234",
        is_default=True,
    )
    db.commit()

    orchestrator = AgentOrchestrator(db)

    with patch.object(
        OpenAICompatibleProvider,
        "generate_json",
        return_value=VALID_PLAN_JSON,
    ) as mock_groq_gen:
        plan = orchestrator.plan_task(
            tenant_id=tenant_a.id,
            task_id=sample_task.id,
        )

        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].step_id == "s1"
        assert plan.steps[0].description == "Examine firewall logs"
        # Assert Groq generate_json was invoked
        mock_groq_gen.assert_called_once()
        prompt_arg = mock_groq_gen.call_args[0][0]
        assert "Analyze cloud security posture" in prompt_arg


# ---------------------------------------------------------------------------
# 2. Task Planning Uses OpenAI When Configured
# ---------------------------------------------------------------------------

def test_task_planning_uses_configured_openai_provider(
    db: Session,
    tenant_a: Tenant,
    sample_task: Task,
):
    service = AIProviderService(db)
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="openai-planning-cfg",
        provider="openai",
        model="gpt-4o-mini",
        api_key="sk-proj-test-openai-key-planning-1234",
        is_default=True,
    )
    db.commit()

    orchestrator = AgentOrchestrator(db)

    with patch.object(
        OpenAICompatibleProvider,
        "generate_json",
        return_value=VALID_PLAN_JSON,
    ) as mock_openai_gen:
        plan = orchestrator.plan_task(
            tenant_id=tenant_a.id,
            task_id=sample_task.id,
        )

        assert plan is not None
        assert len(plan.steps) == 2
        mock_openai_gen.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Gemini Remains Supported in Task Planning and Provider Neutrality
# ---------------------------------------------------------------------------

def test_gemini_remains_supported_in_task_planning(
    db: Session,
    tenant_a: Tenant,
    sample_task: Task,
):
    service = AIProviderService(db)
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="gemini-planning-cfg",
        provider="gemini",
        model="gemini-3.8-flash",
        api_key="AIzaSyFakeGeminiKey1234567890123456789012",
        is_default=True,
    )
    db.commit()

    orchestrator = AgentOrchestrator(db)

    with patch.object(
        GeminiProvider,
        "generate_json",
        return_value=VALID_PLAN_JSON,
    ) as mock_gemini_gen:
        plan = orchestrator.plan_task(
            tenant_id=tenant_a.id,
            task_id=sample_task.id,
        )

        assert plan is not None
        assert len(plan.steps) == 2
        mock_gemini_gen.assert_called_once()

    # Also verify AITaskPlanner is an alias to GeminiTaskPlanner
    assert issubclass(AITaskPlanner, GeminiTaskPlanner)


# ---------------------------------------------------------------------------
# 4. Changing Configured Provider Changes Provider Used in Subsequent Calls
# ---------------------------------------------------------------------------

def test_changing_configured_provider_switches_subsequent_calls(
    db: Session,
    tenant_a: Tenant,
    sample_task: Task,
):
    service = AIProviderService(db)

    # Step 1: Set Groq
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="active-cfg",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_key1",
        is_default=True,
    )
    db.commit()

    orchestrator = AgentOrchestrator(db)
    resolved_1 = orchestrator._resolve_ai_planner(tenant_id=tenant_a.id)
    assert isinstance(resolved_1.provider, OpenAICompatibleProvider)
    assert resolved_1.provider.provider_name == "groq"

    # Step 2: Switch to OpenAI
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="active-cfg",
        provider="openai",
        model="gpt-4o",
        api_key="sk-key2",
        is_default=True,
    )
    db.commit()

    resolved_2 = orchestrator._resolve_ai_planner(tenant_id=tenant_a.id)
    assert isinstance(resolved_2.provider, OpenAICompatibleProvider)
    assert resolved_2.provider.provider_name == "openai"
    assert resolved_2.provider.model == "gpt-4o"


# ---------------------------------------------------------------------------
# 5. No Hidden Fallback Occurs After Provider Failure (Fail-Fast)
# ---------------------------------------------------------------------------

def test_no_hidden_fallback_after_provider_failure(
    db: Session,
    tenant_a: Tenant,
    sample_task: Task,
):
    service = AIProviderService(db)
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="groq-failing",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_failing_key",
        is_default=True,
    )
    db.commit()

    orchestrator = AgentOrchestrator(db)

    # When Groq fails with 401 Authentication Error
    with patch.object(
        OpenAICompatibleProvider,
        "generate_json",
        side_effect=AIAuthenticationError("Invalid Groq API key"),
    ):
        with patch.object(GeminiProvider, "generate_json") as mock_gemini_fallback:
            with pytest.raises(ValueError, match="AI planning generation failed"):
                orchestrator.plan_task(
                    tenant_id=tenant_a.id,
                    task_id=sample_task.id,
                )
            # Verify Gemini was NEVER called as a silent fallback
            mock_gemini_fallback.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Missing or Invalid Configuration Produces Safe, Clear Error
# ---------------------------------------------------------------------------

def test_missing_configuration_produces_safe_error(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "")
    with pytest.raises(ValueError, match="No AI provider configured"):
        AIProviderFactory.create_provider()


def test_invalid_provider_name_produces_clear_error():
    with pytest.raises(ValueError, match="Unsupported AI provider: 'non_existent_provider'"):
        AIProviderFactory.create_provider(provider_name="non_existent_provider")


def test_missing_api_key_produces_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    with pytest.raises(ValueError, match="GROQ_API_KEY cannot be empty"):
        AIProviderFactory.create_provider(provider_name="groq", api_key="")


# ---------------------------------------------------------------------------
# 7. Tenant-Specific Configuration Overrides Platform Configuration Only For That Tenant
# ---------------------------------------------------------------------------

def test_tenant_specific_configuration_overrides_platform_for_that_tenant(
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
):
    service = AIProviderService(db)

    # 1. Platform-wide default is OpenAI
    service.register_or_update_config(
        tenant_id=None,
        name="global-platform-cfg",
        provider="openai",
        model="gpt-4o-mini",
        api_key="sk-platform-key",
        is_default=True,
    )

    # 2. Tenant A explicitly configures Groq
    service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="tenant-a-groq",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_tenant_a_key",
        is_default=True,
    )
    db.commit()

    # Tenant A should resolve to Groq
    cfg_a = service.get_active_config(tenant_id=tenant_a.id)
    assert cfg_a is not None
    assert cfg_a["provider"] == "groq"
    assert cfg_a["model"] == "openai/gpt-oss-120b"

    # Tenant B has no custom config -> falls back to Platform global (OpenAI)
    cfg_b = service.get_active_config(tenant_id=tenant_b.id)
    assert cfg_b is not None
    assert cfg_b["provider"] == "openai"
    assert cfg_b["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 8. Cross-Tenant Provider Configuration Access and RBAC is Rejected
# ---------------------------------------------------------------------------

def test_cross_tenant_provider_access_rejected_in_service(
    db: Session,
    tenant_a: Tenant,
    tenant_b: Tenant,
):
    service = AIProviderService(db)
    dto_a = service.register_or_update_config(
        tenant_id=tenant_a.id,
        name="private-a-config",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="gsk_tenant_a_private_key",
    )
    db.commit()

    # Tenant B cannot get Tenant A's config
    assert service.get_config(tenant_id=tenant_b.id, integration_id=uuid.UUID(dto_a["id"])) is None

    # Tenant B cannot test Tenant A's config
    with pytest.raises(ValueError, match="not found for tenant"):
        service.test_config(tenant_id=tenant_b.id, integration_id=uuid.UUID(dto_a["id"]))


def test_ordinary_member_cannot_create_provider_config(
    member_user_a: User,
):
    token = create_access_token(
        user_id=member_user_a.id,
        tenant_id=member_user_a.tenant_id,
        role=member_user_a.role,  # tenant_member
    )
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "name": "unauthorized-cfg",
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "api_key": "gsk_hacker_key",
    }
    resp = client.post("/api/v1/ai-providers/configs", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "lacks required permissions" in resp.json()["detail"]


def test_tenant_owner_cannot_configure_platform_level_provider(
    owner_user_a: User,
):
    token = create_access_token(
        user_id=owner_user_a.id,
        tenant_id=owner_user_a.tenant_id,
        role=owner_user_a.role,  # tenant_owner (not platform_admin)
    )
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "name": "illegal-platform-cfg",
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "api_key": "gsk_some_key",
        "is_platform_level": True,
    }
    resp = client.post("/api/v1/ai-providers/configs", json=payload, headers=headers)
    assert resp.status_code == 403
    assert "Only platform administrators can configure platform-level" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 9. Provider Credentials Never Appear in API Responses, Logs, or Error Messages
# ---------------------------------------------------------------------------

def test_provider_credentials_never_appear_in_api_responses_or_errors(
    owner_user_a: User,
):
    secret_key = "gsk_extremely_confidential_secret_key_999888777"
    token = create_access_token(
        user_id=owner_user_a.id,
        tenant_id=owner_user_a.tenant_id,
        role=owner_user_a.role,
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create config
    resp = client.post(
        "/api/v1/ai-providers/configs",
        json={
            "name": "secret-test-cfg",
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "api_key": secret_key,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    # Key must NOT appear in response
    assert secret_key not in json.dumps(data)
    assert "gsk_" in data["masked_api_key"]
    config_id = data["id"]

    # 2. Get config
    get_resp = client.get(f"/api/v1/ai-providers/configs/{config_id}", headers=headers)
    assert get_resp.status_code == 200
    assert secret_key not in json.dumps(get_resp.json())

    # 3. Connection error message sanitization
    provider = OpenAICompatibleProvider(
        api_key=secret_key,
        model="openai/gpt-oss-120b",
        provider_name="groq",
    )
    sanitized = provider._sanitize(f"Authorization header failed with Bearer {secret_key}")
    assert secret_key not in sanitized
    assert "[REDACTED_KEY]" in sanitized


# ---------------------------------------------------------------------------
# 10. Existing Planning Schema Validation and Execution Approval Policies Remain Intact
# ---------------------------------------------------------------------------

def test_schema_validation_and_approval_policies_intact_with_multi_provider(
    db: Session,
    tenant_a: Tenant,
    sample_task: Task,
):
    # Setup Tool and ActionPolicy requiring approval
    tool_id = uuid.uuid4()
    policy = ActionPolicy(
        tenant_id=tenant_a.id,
        action="execute_deploy",
        resource="production_cluster",
        requires_approval=True,
        approval_for="admin",
    )
    perm = Permission(
        tenant_id=tenant_a.id,
        action="execute_deploy",
        resource="production_cluster",
        effect="allow",
    )
    db.add(policy)
    db.add(perm)
    db.commit()

    decision_engine = DecisionEngine(db)

    # Plan with tool step requiring approval
    plan_with_tool = {
        "steps": [
            {
                "step_id": "step_tool_1",
                "step_type": "tool",
                "description": "Deploy to production",
                "action": "execute_deploy",
                "resource": "production_cluster",
                "tool_id": str(tool_id),
                "parameters": {"env": "prod"},
            }
        ]
    }

    mock_provider = MagicMock(spec=AIProvider)
    mock_provider.generate_json.return_value = plan_with_tool

    planner = AITaskPlanner(
        provider=mock_provider,
        decision_engine=decision_engine,
    )

    available_tools = [
        {
            "id": str(tool_id),
            "name": "Deploy Tool",
            "slug": "deploy-tool",
            "tool_type": "custom",
        }
    ]

    from packages.context.models import AgentContext, TaskContext
    task_ctx = TaskContext(
        task_id=sample_task.id,
        agent_id=sample_task.agent_id,
        objective=sample_task.objective,
        title=sample_task.title,
        priority=sample_task.priority,
        status=sample_task.status,
    )
    context = AgentContext(
        tenant_id=tenant_a.id,
        task=task_ctx,
        business={},
        memories=[],
        knowledge=[],
        policies=[],
    )

    plan = planner.create_plan(
        task=sample_task,
        context=context,
        available_tools=available_tools,
        decision_engine=decision_engine,
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].step_id == "step_tool_1"
    assert plan.steps[0].step_type == "tool"
    assert plan.steps[0].requires_approval is True
    assert plan.steps[0].approval_for == "admin"
