from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.auth.rate_limiter import rate_limiter
from packages.auth.security import hash_password
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import (
    Agent,
    AIUsageLog,
    AuditEvent,
    Capability,
    CapabilityVersion,
    Channel,
    Conversation,
    ExecutionStep,
    ExecutionTrace,
    Integration,
    Message,
    OutboxEvent,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.ai_provider_service import AIProviderService


@pytest.fixture(autouse=True)
def setup_test_env():
    rate_limiter.reset()
    orig_env = settings.environment
    orig_allow = settings.allow_dev_auth_header
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    yield
    rate_limiter.reset()
    settings.environment = orig_env
    settings.allow_dev_auth_header = orig_allow


def create_test_tenant(name: str = "Test Tenant", status: str = "active") -> Tenant:
    db = SessionLocal()
    tenant = Tenant(
        id=uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        status=status,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    db.close()
    return tenant


def create_test_user(
    role: str = "tenant_user",
    tenant_id=None,
    name: str = "Test User",
) -> tuple[User, str]:
    db = SessionLocal()
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        email=f"user-{uuid4().hex[:8]}@example.com",
        role=role,
        status="active",
        password_hash=hash_password("SecurePass123!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    token = create_access_token(user.id, user.tenant_id, user.role)
    return user, token


def test_platform_admin_access_tenant_tasks():
    tenant = create_test_tenant("Tasks Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    db = SessionLocal()
    task1 = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Analyze Q3 Financials",
        objective="Run profit and loss summary",
        status="completed",
        priority="high",
        plan={},
        result={"summary": "Q3 profit +15%"},
    )
    task2 = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Send Customer Notification",
        objective="Send invoice email",
        status="pending",
        priority="normal",
        plan={},
        result={},
    )
    db.add_all([task1, task2])
    db.commit()
    db.close()

    client = TestClient(app)
    response = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["tasks"]) == 2
    titles = [t["title"] for t in data["tasks"]]
    assert "Analyze Q3 Financials" in titles
    assert "Send Customer Notification" in titles

    # Test filtering by status
    filtered_res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/tasks?status=completed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert filtered_res.status_code == 200
    filtered_data = filtered_res.json()
    assert filtered_data["total"] == 1
    assert filtered_data["tasks"][0]["title"] == "Analyze Q3 Financials"


def test_platform_admin_access_tenant_traces_and_steps():
    tenant = create_test_tenant("Traces Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    db = SessionLocal()
    trace_pk = uuid4()
    trace_uuid = uuid4()
    trace = ExecutionTrace(
        id=trace_pk,
        tenant_id=tenant.id,
        trace_id=trace_uuid,
        trigger_type="inbound_message",
        status="completed",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_ms=450,
        metadata_json={"source": "whatsapp"},
    )
    db.add(trace)
    db.flush()

    step = ExecutionStep(
        id=uuid4(),
        tenant_id=tenant.id,
        trace_id=trace_pk,
        step_order=1,
        step_type="ai_generation",
        step_name="Draft Response",
        status="completed",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_ms=300,
    )
    db.add(step)
    db.commit()
    db.close()

    client = TestClient(app)
    # List traces
    res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/traces",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    traces_data = res.json()
    assert traces_data["total"] == 1
    assert traces_data["items"][0]["trigger_type"] == "inbound_message"

    # Get steps
    steps_res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/traces/{trace_uuid}/steps",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert steps_res.status_code == 200
    steps_data = steps_res.json()
    assert len(steps_data) == 1
    assert steps_data[0]["step_name"] == "Draft Response"


def test_platform_admin_access_tenant_capabilities_separation():
    tenant_a = create_test_tenant("Caps Tenant A")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    db = SessionLocal()
    # 1. Global approved shared capability
    shared_cap = Capability(
        id=uuid4(),
        tenant_id=None,
        name="Global PDF Parser",
        slug="global-pdf-parser",
        description="Standard library parser",
        is_active=True,
    )
    # 2. Tenant custom capability
    tenant_cap = Capability(
        id=uuid4(),
        tenant_id=tenant_a.id,
        name="Custom Accounting Sync",
        slug="custom-accounting-sync",
        description="Tenant specific plugin",
        is_active=True,
    )
    # 3. Self-development version proposal
    evolved_version = CapabilityVersion(
        id=uuid4(),
        tenant_id=tenant_a.id,
        version_number=2,
        slug="custom-accounting-sync",
        name="Custom Accounting Sync v2",
        description="Optimized speed",
        status="active",
        risk_level="low",
    )
    db.add_all([shared_cap, tenant_cap, evolved_version])
    db.commit()
    db.close()

    client = TestClient(app)
    res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/capabilities",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()

    # Verify logical separation:
    # 1) Custom tenant capabilities
    assert len(data["tenant_capabilities"]) >= 1
    assert any(c["slug"] == "custom-accounting-sync" for c in data["tenant_capabilities"])
    # 2) Shared global library
    assert len(data["shared_capabilities"]) >= 1
    assert any(c["slug"] == "global-pdf-parser" for c in data["shared_capabilities"])
    # 3) Self-development versions
    assert len(data["self_development_versions"]) >= 1
    assert data["self_development_versions"][0]["version_number"] == 2


def test_platform_admin_access_tenant_errors_diagnostic():
    tenant = create_test_tenant("Errors Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    db = SessionLocal()
    # 1. Failed task with error
    failed_task = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Sync CRM Contacts",
        objective="Pull updated leads",
        status="failed",
        error="CRM connection timeout after 30s",
    )
    # 2. Failed trace
    failed_trace = ExecutionTrace(
        id=uuid4(),
        tenant_id=tenant.id,
        trace_id=uuid4(),
        trigger_type="cron_job",
        status="failed",
        error_summary={"reason": "RateLimitExceeded", "code": 429},
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    # 3. AI provider error
    ai_err = AIUsageLog(
        id=uuid4(),
        tenant_id=tenant.id,
        provider="openai",
        model="gpt-4o",
        status="error",
        error_category="context_length_exceeded",
        error_message="Maximum token limit exceeded",
    )
    # 4. Outbox dead letter
    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        status="active",
        subject="Support issue",
    )
    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        content="Help with payment",
        sender_type="customer",
        message_type="text",
    )
    db.add_all([conv, msg])
    db.flush()

    outbox_dl = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        message_id=msg.id,
        idempotency_key=f"outbox-{uuid4().hex}",
        event_type="notification.email.send",
        payload={"recipient": "user@example.com"},
        status="dead_letter",
        attempt_count=5,
        error_message="SMTP host unreachable",
    )
    db.add_all([failed_task, failed_trace, ai_err, outbox_dl])
    db.commit()
    db.close()

    client = TestClient(app)
    res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/errors",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    diag = res.json()
    assert diag["total_errors"] == 4
    assert len(diag["tasks_errors"]) == 1
    assert "CRM connection timeout" in diag["tasks_errors"][0]["error_message"]
    assert len(diag["traces_errors"]) == 1
    assert diag["traces_errors"][0]["error_summary"]["code"] == 429
    assert len(diag["ai_errors"]) == 1
    assert diag["ai_errors"][0]["error_category"] == "context_length_exceeded"
    assert len(diag["outbox_errors"]) == 1
    assert "SMTP host unreachable" in diag["outbox_errors"][0]["error_message"]


def test_tenant_isolation_prevents_cross_tenant_leakage():
    tenant_a = create_test_tenant("Tenant Alpha")
    tenant_b = create_test_tenant("Tenant Beta")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    db = SessionLocal()
    # Add task to Tenant B only
    task_b = Task(
        id=uuid4(),
        tenant_id=tenant_b.id,
        title="Secret Task for Tenant B",
        objective="Confidential operation",
        status="pending",
    )
    db.add(task_b)
    db.commit()
    db.close()

    client = TestClient(app)
    # Query tasks for Tenant A
    res_a = client.get(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_a.status_code == 200
    tasks_a = res_a.json()["tasks"]
    assert len(tasks_a) == 0
    assert not any(t["title"] == "Secret Task for Tenant B" for t in tasks_a)


def test_unauthorized_and_cross_tenant_access_rejection():
    tenant_a = create_test_tenant("Tenant A Security")
    tenant_b = create_test_tenant("Tenant B Security")

    # Regular tenant user for Tenant A
    user_a, token_a = create_test_user(role="tenant_admin", tenant_id=tenant_a.id)

    client = TestClient(app)
    # 1. No token -> 401 Unauthorized
    unauth_res = client.get(f"/api/v1/admin/platform/tenants/{tenant_a.id}/tasks")
    assert unauth_res.status_code == 401

    # 2. Tenant admin calling platform admin endpoint -> 403 Forbidden
    forbidden_res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/tasks",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert forbidden_res.status_code == 403


def test_tenant_self_management_of_integrations():
    """Verify tenant admin can manage their own integration without raw key exposure."""
    tenant = create_test_tenant("Integration Self-Management Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)
    tenant_admin, tenant_token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    client = TestClient(app)

    # 1. Tenant admin registers their own AI Provider integration
    create_res = client.post(
        "/api/v1/ai-providers/configs",
        headers={"Authorization": f"Bearer {tenant_token}"},
        json={
            "name": "tenant-custom-groq",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_super_secret_groq_key_99999",
            "is_default": True,
        },
    )
    assert create_res.status_code == 201
    created_cfg = create_res.json()
    assert created_cfg["name"] == "tenant-custom-groq"
    # Verify API key is masked and not exposed
    assert created_cfg["masked_api_key"] != "gsk_super_secret_groq_key_99999"
    assert "9999" in created_cfg["masked_api_key"]

    # 2. Platform admin inspects integrations for this tenant
    admin_res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/integrations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_res.status_code == 200
    configs = admin_res.json()
    assert any(c["name"] == "tenant-custom-groq" for c in configs)
    for c in configs:
        # Guarantee no plaintext secret leaks
        assert "gsk_super_secret_groq_key_99999" not in str(c)

    # 3. Platform admin can safely update the integration status (e.g. disable on emergency)
    int_id = created_cfg["id"]
    patch_res = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant.id}/integrations/{int_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "disabled"


def test_admin_create_tenant_integration_and_isolation():
    """Verify platform admin can create an integration scoped to a specific tenant with full encryption and masking."""
    tenant = create_test_tenant("Admin Provisioned Integration Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)
    tenant_admin, tenant_token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    client = TestClient(app)

    # 1. Tenant admin cannot call platform admin route (403)
    unauthorized_res = client.post(
        f"/api/v1/admin/platform/tenants/{tenant.id}/integrations",
        headers={"Authorization": f"Bearer {tenant_token}"},
        json={
            "name": "unauthorized-groq",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_unauthorized_key_12345",
        },
    )
    assert unauthorized_res.status_code == 403

    # 2. Platform admin creates tenant-scoped integration
    create_res = client.post(
        f"/api/v1/admin/platform/tenants/{tenant.id}/integrations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "tenant-admin-bound-groq",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_prod_secret_admin_created_key_77777",
            "temperature": 0.3,
            "max_tokens": 4096,
            "is_default": True,
        },
    )
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["name"] == "tenant-admin-bound-groq"
    assert created_data["provider"] == "groq"
    assert created_data["model"] == "llama-3.3-70b-versatile"
    assert created_data["is_default"] is True
    # Secrets must NEVER be returned plaintext
    assert "gsk_prod_secret_admin_created_key_77777" not in str(created_data)
    assert created_data["masked_api_key"] != "gsk_prod_secret_admin_created_key_77777"
    assert "7777" in created_data["masked_api_key"]

    # 3. Verify in DB that it is scoped strictly to this tenant
    db = SessionLocal()
    intg = db.scalar(select(Integration).where(Integration.id == created_data["id"]))
    assert intg is not None
    assert intg.tenant_id == tenant.id
    db.close()


def test_admin_test_tenant_integration_connection():
    """Verify platform admin can trigger an isolated test connection for a tenant's integration with mocks."""
    tenant = create_test_tenant("Admin Test Connection Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    client = TestClient(app)

    # 1. Create integration for tenant
    create_res = client.post(
        f"/api/v1/admin/platform/tenants/{tenant.id}/integrations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "groq-for-testing",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_valid_mock_key_88888",
            "is_default": True,
        },
    )
    assert create_res.status_code == 201
    integration_id = create_res.json()["id"]

    # 2. Test connection with successful mock
    mock_provider = MagicMock()
    mock_provider.test_connection.return_value = {
        "success": True,
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "latency_ms": 32.5,
        "error_type": None,
        "error_message": None,
    }

    with patch("packages.ai_providers.factory.AIProviderFactory.create_provider", return_value=mock_provider):
        test_res = client.post(
            f"/api/v1/admin/platform/tenants/{tenant.id}/integrations/{integration_id}/test",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert test_res.status_code == 200
        data = test_res.json()
        assert data["success"] is True
        assert data["latency_ms"] == 32.5
        assert data["error_type"] is None

    # Verify DB updated last_test_status
    db = SessionLocal()
    intg = db.scalar(select(Integration).where(Integration.id == integration_id))
    assert intg.config["last_test_status"] == "success"
    assert intg.config["last_test_result"]["latency_ms"] == 32.5
    db.close()

    # 3. Test connection with failing mock (authentication failure)
    mock_provider.test_connection.return_value = {
        "success": False,
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "latency_ms": 12.1,
        "error_type": "AuthenticationError",
        "error_message": "Invalid API Key provided",
    }

    with patch("packages.ai_providers.factory.AIProviderFactory.create_provider", return_value=mock_provider):
        test_fail_res = client.post(
            f"/api/v1/admin/platform/tenants/{tenant.id}/integrations/{integration_id}/test",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert test_fail_res.status_code == 200
        fail_data = test_fail_res.json()
        assert fail_data["success"] is False
        assert fail_data["error_type"] == "AuthenticationError"
        assert fail_data["error_message"] == "Invalid API Key provided"

    # Verify DB updated last_test_status to failed
    db = SessionLocal()
    intg = db.scalar(select(Integration).where(Integration.id == integration_id))
    assert intg.config["last_test_status"] == "failed"
    db.close()


def test_admin_cross_tenant_integration_test_rejection():
    """Verify platform admin cannot test an integration using the wrong tenant URL (strict tenant scoping)."""
    tenant_a = create_test_tenant("Tenant A Scoping")
    tenant_b = create_test_tenant("Tenant B Scoping")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    client = TestClient(app)

    # Create integration on Tenant B
    create_res = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_b.id}/integrations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "tenant-b-exclusive-groq",
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_tenant_b_key_55555",
        },
    )
    assert create_res.status_code == 201
    int_b_id = create_res.json()["id"]

    # Attempt to test Tenant B's integration under Tenant A's endpoint -> Must return 404
    cross_res = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/integrations/{int_b_id}/test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cross_res.status_code == 404
    assert "not found for tenant" in cross_res.json()["detail"]


def test_admin_tenant_channels_crud_and_masking():
    """Verify platform admin can manage communication channels (Telegram, WhatsApp, Facebook, etc.) for a tenant with masked secrets and connectivity tests."""
    tenant = create_test_tenant("Admin Channels Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    client = TestClient(app)

    # 1. Register a WhatsApp channel
    res_whatsapp = client.post(
        f"/api/v1/admin/platform/tenants/{tenant.id}/channels",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "واتساب خدمة العملاء",
            "channel_type": "whatsapp",
            "provider": "meta",
            "config": {
                "phone_number_id": "1029384756",
                "phone_number": "+966512345678",
                "access_token": "EAAB_super_secret_access_token_whatsapp",
            },
        },
    )
    assert res_whatsapp.status_code == 201
    wa_data = res_whatsapp.json()
    assert wa_data["name"] == "واتساب خدمة العملاء"
    assert wa_data["channel_type"] == "whatsapp"
    assert wa_data["status"] == "active"
    # Secrets must NEVER be plaintext
    assert "EAAB_super_secret_access_token_whatsapp" not in str(wa_data)
    assert wa_data["config"]["access_token"] == "********"
    wa_channel_id = wa_data["id"]

    # 2. Register a Telegram channel
    res_telegram = client.post(
        f"/api/v1/admin/platform/tenants/{tenant.id}/channels",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "بوت تيليجرام الدعم",
            "channel_type": "telegram",
            "provider": "telegram",
            "config": {
                "bot_token": "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_raw_secret",
                "bot_username": "@SupportBot",
            },
        },
    )
    assert res_telegram.status_code == 201
    tg_data = res_telegram.json()
    assert "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_raw_secret" not in str(tg_data)
    tg_channel_id = tg_data["id"]

    # 3. List channels for tenant
    list_res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant.id}/channels",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_res.status_code == 200
    channels_list = list_res.json()
    assert len(channels_list) == 2
    channel_ids = [c["id"] for c in channels_list]
    assert wa_channel_id in channel_ids
    assert tg_channel_id in channel_ids

    # 4. Test WhatsApp channel connectivity with mock connector
    from packages.connectors.base import ConnectionTestResult
    mock_connector = MagicMock()
    mock_connector.test_connection.return_value = ConnectionTestResult(
        connected=True,
        status="connected",
        latency_ms=48.5,
        details={"phone_number": "+966512345678", "verified": True},
    )

    with patch("packages.services.channel_service.ChannelService.get_connector", return_value=mock_connector):
        test_res = client.post(
            f"/api/v1/admin/platform/tenants/{tenant.id}/channels/{wa_channel_id}/test",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert test_res.status_code == 200
        test_data = test_res.json()
        assert test_data["connected"] is True
        assert test_data["status"] == "connected"
        assert test_data["latency_ms"] == 48.5

    # Verify persisted in database
    db = SessionLocal()
    ch_db = db.scalar(select(Channel).where(Channel.id == wa_channel_id))
    assert ch_db.config["last_test_status"] == "success"
    assert ch_db.config["last_test_result"]["latency_ms"] == 48.5
    db.close()

    # 5. Update channel status to disabled
    patch_res = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant.id}/channels/{wa_channel_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "disabled"

    # 6. Delete Telegram channel
    del_res = client.delete(
        f"/api/v1/admin/platform/tenants/{tenant.id}/channels/{tg_channel_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify soft deleted in database
    db = SessionLocal()
    ch_deleted = db.scalar(select(Channel).where(Channel.id == tg_channel_id))
    assert ch_deleted.status == "deleted"
    db.close()


def test_admin_cross_tenant_channel_isolation():
    """Verify strict multi-tenant isolation prevents cross-tenant access to channels."""
    tenant_a = create_test_tenant("Tenant A Channels")
    tenant_b = create_test_tenant("Tenant B Channels")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    client = TestClient(app)

    # 1. Create channel on Tenant B
    res_b = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_b.id}/channels",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "قناة مستأجر ب الحصرية",
            "channel_type": "telegram",
            "provider": "telegram",
            "config": {"bot_token": "999999:B_secret_token"},
        },
    )
    assert res_b.status_code == 201
    ch_b_id = res_b.json()["id"]

    # 2. Attempt to get Tenant B's channel under Tenant A's endpoint -> 404
    get_res = client.get(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/channels/{ch_b_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_res.status_code == 404
    assert "not found for tenant" in get_res.json()["detail"]

    # 3. Attempt to test Tenant B's channel under Tenant A's endpoint -> 404
    test_res = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/channels/{ch_b_id}/test",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert test_res.status_code == 404
    assert "not found for tenant" in test_res.json()["detail"]

    # 4. Attempt to update Tenant B's channel under Tenant A's endpoint -> 404
    patch_res = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/channels/{ch_b_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled"},
    )
    assert patch_res.status_code == 404

    # 5. Attempt to delete Tenant B's channel under Tenant A's endpoint -> 404
    del_res = client.delete(
        f"/api/v1/admin/platform/tenants/{tenant_a.id}/channels/{ch_b_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert del_res.status_code == 404


