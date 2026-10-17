from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.ai_providers.base import AIBudgetExceededError
from packages.auth.jwt_service import create_access_token
from packages.core.database import SessionLocal
from packages.models.domain import AIUsageLog, TenantAIBudget, User
from packages.models.tenant import Tenant
from packages.services.ai_usage_service import AIUsageService


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant_a(db: Session) -> Tenant:
    t = Tenant(name="Tenant Alpha", slug=f"alpha-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def tenant_b(db: Session) -> Tenant:
    t = Tenant(name="Tenant Beta", slug=f"beta-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def admin_user(db: Session, tenant_a: Tenant) -> User:
    u = User(
        name="Alpha Admin",
        email=f"admin-{uuid.uuid4().hex[:6]}@alpha.com",
        role="tenant_admin",
        status="active",
        tenant_id=tenant_a.id,
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def auth_headers(admin_user: User, tenant_a: Tenant) -> dict[str, str]:
    token = create_access_token(
        user_id=admin_user.id,
        tenant_id=tenant_a.id,
        role=admin_user.role,
    )
    return {"Authorization": f"Bearer {token}"}


def test_record_usage_and_summary_aggregation(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)

    # Record successful request for Groq
    log1 = service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=100,
        completion_tokens=50,
        duration_ms=250,
        status="success",
    )
    assert log1.total_tokens == 150
    assert log1.duration_ms == 250

    # Record fallback request for OpenAI
    log2 = service.record_usage(
        tenant_id=tenant_a.id,
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=120,
        completion_tokens=80,
        duration_ms=450,
        status="success",
        fallback_from_provider="groq",
        fallback_reason="Rate limit (429)",
    )
    assert log2.total_tokens == 200
    assert log2.fallback_from_provider == "groq"

    # Record failed request
    log3 = service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=0,
        completion_tokens=0,
        duration_ms=1000,
        status="error",
        error_category="TRANSIENT_NETWORK",
        error_message="Socket timeout after 1000ms",
    )
    assert log3.status == "error"
    db.commit()

    summary = service.get_usage_summary(tenant_a.id)
    assert summary["total_requests"] == 3
    assert summary["successful_requests"] == 2
    assert summary["fallback_requests"] == 1
    assert summary["error_requests"] == 1
    assert summary["total_tokens"] == 350
    assert summary["total_prompt_tokens"] == 220
    assert summary["total_completion_tokens"] == 130
    assert "groq" in summary["by_provider"]
    assert "openai" in summary["by_provider"]


def test_record_usage_updates_budget_counters(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    service.set_budget(
        tenant_a.id,
        daily_token_limit=5000,
        monthly_token_limit=100000,
        is_hard_limit=True,
    )
    db.commit()

    status_before = service.get_budget_status(tenant_a.id)
    assert status_before["current_day_tokens"] == 0
    assert status_before["daily_remaining"] == 5000

    service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=300,
        completion_tokens=200,
    )
    db.commit()

    status_after = service.get_budget_status(tenant_a.id)
    assert status_after["current_day_tokens"] == 500
    assert status_after["current_month_tokens"] == 500
    assert status_after["daily_remaining"] == 4500
    assert status_after["monthly_remaining"] == 99500


def test_check_budget_available_allows_under_quota(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    service.set_budget(
        tenant_a.id,
        daily_token_limit=5000,
        monthly_token_limit=50000,
        is_hard_limit=True,
    )
    db.commit()

    # Should not raise exception
    service.check_budget_available(tenant_a.id, estimated_tokens=1000)


def test_check_budget_available_raises_on_daily_limit_exceeded(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    service.set_budget(
        tenant_a.id,
        daily_token_limit=1000,
        monthly_token_limit=50000,
        is_hard_limit=True,
    )
    db.commit()

    # Consume 900 tokens
    service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=500,
        completion_tokens=400,
    )
    db.commit()

    # 900 + 200 > 1000 daily limit -> raise AIBudgetExceededError
    with pytest.raises(AIBudgetExceededError, match="Daily AI token limit exceeded"):
        service.check_budget_available(tenant_a.id, estimated_tokens=200)


def test_check_budget_available_raises_on_monthly_limit_exceeded(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    service.set_budget(
        tenant_a.id,
        daily_token_limit=50000,
        monthly_token_limit=2000,
        is_hard_limit=True,
    )
    db.commit()

    # Consume 1800 tokens
    service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=1000,
        completion_tokens=800,
    )
    db.commit()

    # 1800 + 300 > 2000 monthly limit -> raise AIBudgetExceededError
    with pytest.raises(AIBudgetExceededError, match="Monthly AI token limit exceeded"):
        service.check_budget_available(tenant_a.id, estimated_tokens=300)


def test_soft_limit_does_not_raise(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    service.set_budget(
        tenant_a.id,
        daily_token_limit=500,
        monthly_token_limit=1000,
        is_hard_limit=False,  # Soft limit
    )
    db.commit()

    service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=400,
        completion_tokens=400,
    )
    db.commit()

    # 800 > 500, but is_hard_limit is False -> must NOT raise
    service.check_budget_available(tenant_a.id, estimated_tokens=500)


def test_budget_counter_rollover_on_new_day_and_month(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    budget = service.set_budget(
        tenant_a.id,
        daily_token_limit=1000,
        monthly_token_limit=5000,
        is_hard_limit=True,
    )
    budget.current_day_tokens = 800
    budget.current_month_tokens = 2500
    # Simulate last reset was yesterday
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    budget.last_reset_date = yesterday
    db.commit()

    # Day rollover: daily resets to 0, monthly remains
    now = datetime.now(timezone.utc)
    service._sync_budget_reset(budget, now)
    assert budget.current_day_tokens == 0
    assert budget.current_month_tokens == 2500

    # Simulate month rollover: last reset was 35 days ago
    past_month = datetime.now(timezone.utc) - timedelta(days=35)
    budget.current_day_tokens = 400
    budget.current_month_tokens = 2500
    budget.last_reset_date = past_month
    db.commit()

    service._sync_budget_reset(budget, now)
    assert budget.current_day_tokens == 0
    assert budget.current_month_tokens == 0


def test_tenant_isolation_on_usage_and_budgets(db: Session, tenant_a: Tenant, tenant_b: Tenant):
    service = AIUsageService(db)

    service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=500,
        completion_tokens=500,
    )
    service.record_usage(
        tenant_id=tenant_b.id,
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=100,
    )
    db.commit()

    sum_a = service.get_usage_summary(tenant_a.id)
    sum_b = service.get_usage_summary(tenant_b.id)

    assert sum_a["total_tokens"] == 1000
    assert "groq" in sum_a["by_provider"]
    assert "openai" not in sum_a["by_provider"]

    assert sum_b["total_tokens"] == 200
    assert "openai" in sum_b["by_provider"]
    assert "groq" not in sum_b["by_provider"]


def test_privacy_and_zero_secret_leakage_in_usage_logs(db: Session, tenant_a: Tenant):
    service = AIUsageService(db)
    log = service.record_usage(
        tenant_id=tenant_a.id,
        provider="groq",
        model="llama-3.3-70b",
        prompt_tokens=50,
        completion_tokens=20,
        duration_ms=120,
    )
    db.commit()

    # Verify model columns
    assert not hasattr(log, "prompt")
    assert not hasattr(log, "response")
    assert not hasattr(log, "api_key")
    assert not hasattr(log, "secret")

    # Verify dict representation contains no sensitive fields
    data = service.list_usage_logs(tenant_a.id)
    assert len(data) >= 1
    first = data[0]
    assert "provider" in first
    assert "model" in first
    assert "total_tokens" in first
    assert "prompt" not in first
    assert "api_key" not in first


def test_api_endpoints_budget_and_usage(tenant_a: Tenant, auth_headers: dict[str, str], db: Session):
    client = TestClient(app)

    # 1. Update budget via PUT
    put_res = client.put(
        "/api/v1/ai-providers/budget",
        headers=auth_headers,
        json={
            "daily_token_limit": 15000,
            "monthly_token_limit": 300000,
            "is_hard_limit": True,
        },
    )
    assert put_res.status_code == 200
    b_data = put_res.json()
    assert b_data["configured"] is True
    assert b_data["daily_limit"] == 15000
    assert b_data["monthly_limit"] == 300000

    # 2. Get budget via GET
    get_res = client.get(
        "/api/v1/ai-providers/budget",
        headers=auth_headers,
    )
    assert get_res.status_code == 200
    assert get_res.json()["daily_limit"] == 15000

    # 3. Record some usage and query summary
    service = AIUsageService(db)
    service.record_usage(
        tenant_id=tenant_a.id,
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=350,
        completion_tokens=150,
        duration_ms=310,
        status="success",
    )
    db.commit()

    sum_res = client.get(
        "/api/v1/ai-providers/usage/summary",
        headers=auth_headers,
    )
    assert sum_res.status_code == 200
    sum_data = sum_res.json()
    assert sum_data["total_tokens"] >= 500
    assert sum_data["successful_requests"] >= 1

    # 4. Query usage logs
    logs_res = client.get(
        "/api/v1/ai-providers/usage/logs?limit=10",
        headers=auth_headers,
    )
    assert logs_res.status_code == 200
    logs_data = logs_res.json()
    assert len(logs_data) >= 1
    assert logs_data[0]["provider"] == "gemini"
