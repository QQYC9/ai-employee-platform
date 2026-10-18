from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    Channel,
    Conversation,
    Message,
    OutboxEvent,
    Task,
    TenantAIBudget,
    User,
)
from packages.models.tenant import Tenant
from packages.services.ai_usage_service import AIUsageService


@pytest.fixture(autouse=True)
def setup_test_env():
    """Ensure clean rate limiter and test environment settings."""
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


# =============================================================================
# 1. Platform Admin vs Tenant Admin vs Normal User (RBAC & Isolation)
# =============================================================================

def test_platform_admin_can_access_platform_overview():
    client = TestClient(app)
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.get(
        "/api/v1/admin/platform/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tenants" in data
    assert "agents" in data
    assert "tasks" in data
    assert "channels" in data
    assert "outbox" in data
    assert "ai_usage" in data


def test_tenant_admin_cannot_access_platform_overview():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Alpha")
    t_admin, t_token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    resp = client.get(
        "/api/v1/admin/platform/overview",
        headers={"Authorization": f"Bearer {t_token}"},
    )
    assert resp.status_code == 403
    assert "lacks required permissions" in resp.json()["detail"]


def test_normal_user_cannot_access_any_admin_endpoint():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Beta")
    normal_user, normal_token = create_test_user(role="tenant_user", tenant_id=tenant.id)

    # Cannot access platform admin
    resp1 = client.get(
        "/api/v1/admin/platform/overview",
        headers={"Authorization": f"Bearer {normal_token}"},
    )
    assert resp1.status_code == 403

    # Cannot access tenant admin dashboard
    resp2 = client.get(
        "/api/v1/admin/tenant/dashboard",
        headers={"Authorization": f"Bearer {normal_token}"},
    )
    assert resp2.status_code == 403


def test_unauthenticated_request_is_rejected():
    client = TestClient(app)
    resp = client.get("/api/v1/admin/platform/overview")
    assert resp.status_code == 401


# =============================================================================
# 2. Cross-Tenant Isolation Enforcement
# =============================================================================

def test_tenant_admin_cannot_access_another_tenant_dashboard():
    client = TestClient(app)
    tenant_a = create_test_tenant("Tenant A")
    tenant_b = create_test_tenant("Tenant B")

    t_admin_a, token_a = create_test_user(role="tenant_admin", tenant_id=tenant_a.id)

    # Attempting to access Tenant B's dashboard by passing tenant_id
    resp = client.get(
        f"/api/v1/admin/tenant/dashboard?tenant_id={tenant_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
    assert "Cross-tenant access forbidden" in resp.json()["detail"]


def test_platform_admin_can_access_any_tenant_dashboard():
    client = TestClient(app)
    tenant_x = create_test_tenant("Tenant X")
    platform_admin, p_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.get(
        f"/api/v1/admin/tenant/dashboard?tenant_id={tenant_x.id}",
        headers={"Authorization": f"Bearer {p_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant"]["id"] == str(tenant_x.id)
    assert data["tenant"]["name"] == "Tenant X"


# =============================================================================
# 3. Secret Masking in Channels and Dashboard
# =============================================================================

def test_secrets_masked_in_channels_response():
    client = TestClient(app)
    tenant = create_test_tenant("Secret Test Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    ch = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Support",
        channel_type="telegram",
        provider="telegram",
        status="active",
        config={
            "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            "api_key": "sk-real-super-secret-key-12345678",
            "webhook_secret": "my-ultra-secret-token",
            "chat_id": "987654321",
        },
    )
    db.add(ch)
    db.commit()
    ch_id = str(ch.id)
    db.close()

    # 1. Via tenant channels endpoint
    resp1 = client.get(
        "/api/v1/admin/tenant/channels",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200
    channels = resp1.json()["channels"]
    assert len(channels) >= 1
    found = next(c for c in channels if c["id"] == ch_id)
    cfg = found["config"]
    assert cfg["bot_token"] == "********"
    assert cfg["api_key"] == "********"
    assert cfg["webhook_secret"] == "********"
    assert cfg["chat_id"] == "987654321"  # non-secret is preserved

    # 2. Via tenant dashboard endpoint
    resp2 = client.get(
        "/api/v1/admin/tenant/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    d_channels = resp2.json()["channels"]["items"]
    d_found = next(c for c in d_channels if c["id"] == ch_id)
    assert d_found["config"]["bot_token"] == "********"
    assert d_found["config"]["api_key"] == "********"


# =============================================================================
# 4. Metrics Accuracy & Retry Deduplication
# =============================================================================

def test_task_metrics_accuracy_and_retry_deduplication():
    client = TestClient(app)
    tenant = create_test_tenant("Metrics Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    # Task 1: Completed
    t1 = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Completed Task",
        objective="Calculate payroll",
        status="completed",
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=8),
    )
    # Task 2: Failed
    t2 = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Failed Task",
        objective="Send report",
        status="failed",
        error="Network timeout",
    )
    # Task 3: In progress
    t3 = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Running Task",
        objective="Process dataset",
        status="in_progress",
    )
    db.add_all([t1, t2, t3])
    db.commit()

    # Create AI usage logs for Task 1: simulate retry execution with 2 invocations
    ai_service = AIUsageService(db)
    ai_service.record_usage(
        tenant_id=tenant.id,
        provider="openai",
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=450,
        status="success",
        task_id=t1.id,
    )
    ai_service.record_usage(
        tenant_id=tenant.id,
        provider="openai",
        model="gpt-4o",
        prompt_tokens=200,
        completion_tokens=80,
        total_tokens=280,
        duration_ms=600,
        status="success",
        task_id=t1.id,  # Same task ID (retry/followup invocation)
    )
    db.commit()
    db.close()

    # Query tenant metrics
    resp = client.get(
        "/api/v1/admin/tenant/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    metrics = resp.json()
    summary = metrics["summary"]

    assert summary["total_requests"] == 2
    assert summary["successful_requests"] == 2
    assert summary["prompt_tokens"] == 300
    assert summary["completion_tokens"] == 130
    assert summary["total_tokens"] == 430
    # Unique tasks invoked must be 1, deduplicating the retried task
    assert summary["unique_tasks_invoked"] == 1

    # Check tenant dashboard for task success rates
    resp_dash = client.get(
        "/api/v1/admin/tenant/dashboard",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_dash.status_code == 200
    dash_tasks = resp_dash.json()["tasks"]
    assert dash_tasks["total"] == 3
    assert dash_tasks["completed"] == 1
    assert dash_tasks["failed"] == 1
    assert dash_tasks["in_progress"] == 1
    # Success rate: 1 completed out of 2 finished = 50.0%
    assert dash_tasks["success_rate_pct"] == 50.0
    assert dash_tasks["failure_rate_pct"] == 50.0
    assert dash_tasks["avg_execution_latency_sec"] > 0


# =============================================================================
# 5. Usage Limits, Budget Tracking & Alert Levels
# =============================================================================

def test_budget_tracking_and_alert_levels():
    client = TestClient(app)
    tenant = create_test_tenant("Budget Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    ai_service = AIUsageService(db)

    # 1. Configure budget: 1,000 daily limit, 10,000 monthly limit
    ai_service.set_budget(
        tenant_id=tenant.id,
        daily_token_limit=1000,
        monthly_token_limit=10000,
        is_hard_limit=True,
    )
    db.commit()

    # Check initial alert status: should be normal (0% usage)
    resp1 = client.get(
        "/api/v1/admin/tenant/budget",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["alert_level"] == "normal"
    assert resp1.json()["current_day_tokens"] == 0

    # 2. Consume 850 tokens (85% of daily limit -> warning alert)
    ai_service.record_usage(
        tenant_id=tenant.id,
        provider="gemini",
        model="gemini-1.5-flash",
        prompt_tokens=500,
        completion_tokens=350,
        total_tokens=850,
    )
    db.commit()

    resp2 = client.get(
        "/api/v1/admin/tenant/budget",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["alert_level"] == "warning"
    assert resp2.json()["current_day_tokens"] == 850

    # 3. Consume 200 more tokens (1050 total -> exceeded alert)
    ai_service.record_usage(
        tenant_id=tenant.id,
        provider="gemini",
        model="gemini-1.5-flash",
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200,
    )
    db.commit()
    db.close()

    resp3 = client.get(
        "/api/v1/admin/tenant/budget",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp3.status_code == 200
    assert resp3.json()["alert_level"] == "exceeded"
    assert resp3.json()["current_day_tokens"] == 1050


# =============================================================================
# 6. Administrative Actions with Audit Log Recording
# =============================================================================

def test_platform_admin_update_tenant_budget_is_audited():
    client = TestClient(app)
    tenant = create_test_tenant("Audit Budget Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant.id}/budget",
        json={
            "daily_token_limit": 50000,
            "monthly_token_limit": 500000,
            "is_hard_limit": True,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["budget"]["daily_limit"] == 50000
    assert resp.json()["budget"]["monthly_limit"] == 500000

    # Verify AuditEvent was persisted
    db = SessionLocal()
    audit_ev = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "admin.tenant_budget.updated",
        )
    )
    assert audit_ev is not None
    assert audit_ev.user_id == admin_user.id
    assert audit_ev.event_metadata["new_budget"]["daily_limit"] == 50000
    db.close()


def test_platform_admin_update_tenant_status_is_audited():
    client = TestClient(app)
    tenant = create_test_tenant("Status Tenant", status="active")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant.id}/status",
        json={"status": "suspended"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["tenant"]["new_status"] == "suspended"

    # Verify DB status changed and AuditEvent created
    db = SessionLocal()
    refreshed_tenant = db.scalar(select(Tenant).where(Tenant.id == tenant.id))
    assert refreshed_tenant.status == "suspended"

    audit_ev = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "admin.tenant_status.updated",
        )
    )
    assert audit_ev is not None
    assert audit_ev.event_metadata["old_status"] == "active"
    assert audit_ev.event_metadata["new_status"] == "suspended"
    db.close()


# =============================================================================
# 7. Operational Health Monitoring & Handling Degraded / Unknown States
# =============================================================================

def test_operational_monitoring_healthy_state():
    client = TestClient(app)
    tenant = create_test_tenant("Monitoring Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    resp = client.get(
        "/api/v1/admin/monitoring/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_status" in data
    assert "components" in data
    assert "database" in data["components"]
    assert data["components"]["database"]["status"] == "healthy"


def test_operational_monitoring_detects_dead_letter_as_degraded():
    client = TestClient(app)
    tenant = create_test_tenant("DeadLetter Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    # Create conversation and message to satisfy foreign key constraints
    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        subject="Dead Letter Topic",
    )
    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        content="Test dead letter event",
    )
    db.add_all([conv, msg])
    db.commit()

    # Create dead-letter outbox event
    dl_event = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        message_id=msg.id,
        idempotency_key=f"dl-{uuid4().hex}",
        status="dead_letter",
        attempt_count=5,
        max_attempts=5,
        error_message="Repeated webhook failure",
    )
    db.add(dl_event)
    db.commit()
    db.close()

    resp = client.get(
        "/api/v1/admin/monitoring/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["components"]["outbox"]["status"] == "degraded"
    assert data["components"]["outbox"]["details"]["dead_letter"] >= 1
    assert data["overall_status"] == "degraded"


# =============================================================================
# 8. Pagination, Input Validation & Security Hardening
# =============================================================================

def test_tenants_overview_pagination():
    client = TestClient(app)
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.get(
        "/api/v1/admin/platform/tenants?limit=2&offset=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 2
    assert len(data["tenants"]) <= 2


def test_invalid_pagination_limit_rejected():
    client = TestClient(app)
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    # limit > 100 is forbidden
    resp = client.get(
        "/api/v1/admin/platform/tenants?limit=500",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


def test_invalid_tenant_status_update_rejected():
    client = TestClient(app)
    tenant = create_test_tenant("Invalid Status Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant.id}/status",
        json={"status": "invalid_status_xyz"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
    assert "Invalid tenant status" in resp.json()["detail"]


# =============================================================================
# 9. Advanced Security & Platform Metrics Tests
# =============================================================================

def test_platform_metrics_access_and_aggregation():
    client = TestClient(app)
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    resp = client.get(
        "/api/v1/admin/platform/metrics?time_window_days=30",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "by_provider" in data
    assert "by_model" in data
    assert "by_tenant" in data
    assert "daily_trends" in data


def test_tenant_admin_cannot_access_platform_metrics():
    client = TestClient(app)
    tenant = create_test_tenant("Restricted Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    resp = client.get(
        "/api/v1/admin/platform/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_monitoring_health_isolates_stalled_tasks_between_tenants():
    """Ensure a tenant admin never sees another tenant's stalled tasks in diagnostic samples."""
    client = TestClient(app)
    tenant_a = create_test_tenant("Stalled Tenant A")
    tenant_b = create_test_tenant("Clean Tenant B")

    t_admin_b, token_b = create_test_user(role="tenant_admin", tenant_id=tenant_b.id)

    db = SessionLocal()
    stalled_task_a = Task(
        id=uuid4(),
        tenant_id=tenant_a.id,
        title="Secret Project Payroll Processing",
        objective="Run sensitive payroll",
        status="in_progress",
        created_at=datetime.now(timezone.utc) - timedelta(hours=3),
        updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add(stalled_task_a)
    db.commit()
    stalled_task_id = str(stalled_task_a.id)
    db.close()

    # Tenant B checks health: should NOT see Tenant A's task in sample
    resp = client.get(
        "/api/v1/admin/monitoring/health",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    stalled_info = data["components"]["stalled_tasks"]["details"]
    assert stalled_info["count"] == 0
    sample_ids = [item["id"] for item in stalled_info["sample"]]
    assert stalled_task_id not in sample_ids


def test_platform_audit_logs_rbac():
    client = TestClient(app)
    tenant = create_test_tenant("Audit RBAC Tenant")
    t_admin, t_token = create_test_user(role="tenant_admin", tenant_id=tenant.id)
    p_admin, p_token = create_test_user(role="platform_admin", tenant_id=None)

    # 1. Platform admin can access
    resp_p = client.get(
        "/api/v1/admin/platform/audit-logs",
        headers={"Authorization": f"Bearer {p_token}"},
    )
    assert resp_p.status_code == 200
    assert "events" in resp_p.json()

    # 2. Tenant admin is forbidden
    resp_t = client.get(
        "/api/v1/admin/platform/audit-logs",
        headers={"Authorization": f"Bearer {t_token}"},
    )
    assert resp_t.status_code == 403


def test_ai_provider_diagnostic_unknown_when_no_data():
    """Verify system reports 'unknown' for AI providers when no telemetry logs exist in 24h."""
    client = TestClient(app)
    tenant = create_test_tenant("Empty AI Telemetry Tenant")
    t_admin, token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    resp = client.get(
        "/api/v1/admin/monitoring/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # In a tenant with zero AI calls in 24h, AI component must be 'unknown', not falsely 'healthy'
    assert data["components"]["ai_providers"]["status"] == "unknown"
