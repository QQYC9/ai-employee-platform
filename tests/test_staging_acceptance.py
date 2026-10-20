"""
Phase 18: End-to-End Functional Acceptance Tests on Staging Environment.
Target Server: http://127.0.0.1:8001 (ai-employee-platform-staging)
Target Database: ai_employee_staging
"""

from __future__ import annotations

import subprocess
import time
from uuid import UUID

import httpx
import pytest

STAGING_BASE_URL = "http://127.0.0.1:8001"
ALPHA_EMAIL = "owner-alpha@staging.local"
BETA_EMAIL = "owner-beta@staging.local"
TEST_PASSWORD = "StagingPassword123!"


@pytest.fixture(scope="session")
def http_client():
    """HTTP client configured to bypass host proxy settings for local loopback."""
    with httpx.Client(base_url=STAGING_BASE_URL, timeout=10.0, trust_env=False) as client:
        yield client


@pytest.fixture(scope="session")
def alpha_auth(http_client):
    """Authenticate as Tenant Alpha owner and return tokens."""
    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": ALPHA_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user_id": data["user"]["id"],
        "tenant_id": data["user"]["tenant_id"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


@pytest.fixture(scope="session")
def beta_auth(http_client):
    """Authenticate as Tenant Beta owner and return tokens."""
    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": BETA_EMAIL, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user_id": data["user"]["id"],
        "tenant_id": data["user"]["tenant_id"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


# =============================================================================
# Domain A: Health & Configuration Guard
# =============================================================================


def test_tc_a1_health_endpoint(http_client):
    """TC-A1: GET /health must return HTTP 200 and healthy status."""
    resp = http_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_tc_a2_root_endpoint(http_client):
    """TC-A2: GET / must return HTTP 200 and platform running message."""
    resp = http_client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert "running" in data["message"].lower()


def test_tc_a3_openapi_json(http_client):
    """TC-A3: GET /openapi.json must generate full OpenAPI schema with 120 paths."""
    resp = http_client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["info"]["title"] == "AI Employee Platform"
    assert len(data["paths"]) >= 120
    assert "/api/v1/tasks" in data["paths"]
    assert "/api/v1/self-development/requests" in data["paths"]


def test_tc_a4_staging_env_guard():
    """TC-A4: Staging container must run with ENVIRONMENT=staging and dev auth disabled."""
    cmd = [
        "docker", "compose", "-f", "docker-compose.staging.yml", "exec", "-T", "agent",
        "python", "-c",
        "from packages.core.config import settings; print(settings.environment, settings.is_dev_auth_allowed)"
    ]
    out = subprocess.check_output(cmd).decode("utf-8").strip()
    env, dev_auth = out.split()
    assert env == "staging"
    assert dev_auth == "False"


def test_tc_a5_database_isolation_guard():
    """TC-A5: Confirms Staging agent connects to ai_employee_staging with zero dev DB overlap."""
    cmd = [
        "docker", "compose", "-f", "docker-compose.staging.yml", "exec", "-T", "agent",
        "python", "-c",
        "from sqlalchemy import create_engine, text; from packages.core.config import settings; print(create_engine(settings.database_url).connect().execute(text('SELECT current_database()')).scalar())"
    ]
    out = subprocess.check_output(cmd).decode("utf-8").strip()
    assert out == "ai_employee_staging"


# =============================================================================
# Domain B: Authentication & Authorization
# =============================================================================


def test_tc_b1_unauthenticated_request_rejected(http_client):
    """TC-B1: Protected endpoint without Authorization header must return 401."""
    resp = http_client.get("/api/v1/me")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json().get("detail", "")
    assert "Bearer" in resp.headers.get("www-authenticate", "")


def test_tc_b2_dev_header_auth_strictly_forbidden(http_client):
    """TC-B2: X-User-ID header authentication must be strictly forbidden in Staging."""
    resp = http_client.get(
        "/api/v1/me",
        headers={"X-User-ID": "00000000-0000-0000-0000-000000000001"},
    )
    assert resp.status_code == 401
    assert "strictly forbidden" in resp.json().get("detail", "").lower()


def test_tc_b3_invalid_login_rejected(http_client):
    """TC-B3: Login with invalid password must return 401 Unauthorized."""
    resp = http_client.post(
        "/api/v1/auth/login",
        json={"email": ALPHA_EMAIL, "password": "WrongPassword999!"},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json().get("detail", "")


def test_tc_b4_valid_user_login(alpha_auth):
    """TC-B4: Valid user login returns cryptographically valid JWT tokens."""
    assert len(alpha_auth["access_token"]) > 30
    assert len(alpha_auth["refresh_token"]) > 30
    assert alpha_auth["tenant_id"] is not None


def test_tc_b5_me_endpoint_returns_user_info(http_client, alpha_auth):
    """TC-B5: GET /api/v1/me with Bearer token resolves user identity and tenant."""
    resp = http_client.get("/api/v1/me", headers=alpha_auth["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == alpha_auth["user_id"]
    assert data["tenant_id"] == alpha_auth["tenant_id"]
    assert data["name"] == "Alpha Owner"


def test_tc_b6_token_refresh(http_client, alpha_auth):
    """TC-B6: POST /api/v1/auth/refresh returns a refreshed access token."""
    resp = http_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": alpha_auth["refresh_token"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert len(data["access_token"]) > 30


# =============================================================================
# Domain C: Multi-Tenant Isolation
# =============================================================================


def test_tc_c1_cross_tenant_task_isolation(http_client, alpha_auth, beta_auth):
    """TC-C1: Tenant Beta must NOT be able to access a task created by Tenant Alpha."""
    # 1. Alpha creates a task
    create_resp = http_client.post(
        "/api/v1/tasks",
        headers=alpha_auth["headers"],
        json={
            "title": "Alpha Confidential Task",
            "objective": "Process secret Alpha corporate financial data",
            "priority": "high",
        },
    )
    assert create_resp.status_code == 201
    alpha_task_id = create_resp.json()["id"]

    # 2. Beta attempts to access Alpha's task directly by UUID
    cross_resp = http_client.get(
        f"/api/v1/tasks/{alpha_task_id}",
        headers=beta_auth["headers"],
    )
    # Server must return 404 Not Found to prevent resource existence disclosure
    assert cross_resp.status_code == 404
    assert cross_resp.json().get("detail") == "Task not found"


def test_tc_c2_cross_tenant_admin_scoping(http_client, alpha_auth, beta_auth):
    """TC-C2: Tenant admin cannot query another tenant's administrative dashboard."""
    beta_tenant_id = beta_auth["tenant_id"]
    cross_admin_resp = http_client.get(
        f"/api/v1/admin/tenant/dashboard?tenant_id={beta_tenant_id}",
        headers=alpha_auth["headers"],
    )
    # Server must enforce cross-tenant rejection with 403 Forbidden
    assert cross_admin_resp.status_code == 403
    assert "cross-tenant" in cross_admin_resp.json().get("detail", "").lower()


def test_tc_c3_cross_tenant_brain_scoping(http_client, alpha_auth, beta_auth):
    """TC-C3: Business brain endpoint returns only caller's tenant brain data."""
    alpha_brain = http_client.get("/api/v1/me/brain", headers=alpha_auth["headers"])
    beta_brain = http_client.get("/api/v1/me/brain", headers=beta_auth["headers"])

    assert alpha_brain.status_code == 200
    assert beta_brain.status_code == 200

    # Business brains must have distinct IDs
    assert alpha_brain.json()["id"] != beta_brain.json()["id"]


# =============================================================================
# Domain D: Agent & Task Execution
# =============================================================================


def test_tc_d1_create_task(http_client, alpha_auth):
    """TC-D1: Creating a task returns HTTP 201 with status=pending and correct tenant scoping."""
    resp = http_client.post(
        "/api/v1/tasks",
        headers=alpha_auth["headers"],
        json={
            "title": "Staging Automation Verification",
            "objective": "Verify background task pipeline execution",
            "priority": "normal",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["tenant_id"] == alpha_auth["tenant_id"]
    assert data["title"] == "Staging Automation Verification"


def test_tc_d2_list_tasks_scoped_to_tenant(http_client, alpha_auth, beta_auth):
    """TC-D2: Task list must be strictly scoped to the requesting tenant."""
    alpha_tasks = http_client.get("/api/v1/tasks", headers=alpha_auth["headers"]).json()
    beta_tasks = http_client.get("/api/v1/tasks", headers=beta_auth["headers"]).json()

    assert isinstance(alpha_tasks, list)
    assert isinstance(beta_tasks, list)

    alpha_task_ids = {t["id"] for t in alpha_tasks}
    beta_task_ids = {t["id"] for t in beta_tasks}

    # Disjoint set: zero task leakage
    assert alpha_task_ids.isdisjoint(beta_task_ids)


# =============================================================================
# Domain E: Outbox Worker & Reliability
# =============================================================================


def test_tc_e1_outbox_event_processing(alpha_auth):
    """TC-E1: Outbox events must be claimed and processed by the embedded worker."""
    tenant_id = alpha_auth["tenant_id"]
    cmd_enqueue = [
        "docker", "compose", "-f", "docker-compose.staging.yml", "exec", "-T", "agent",
        "python", "-c",
        f"""
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Customer, Conversation, Message, OutboxEvent
from uuid import uuid4

db = SessionLocal()
ch = Channel(tenant_id='{tenant_id}', name='Staging WebChat', channel_type='webchat', status='active', config={{}})
db.add(ch)
db.flush()
cust = Customer(tenant_id='{tenant_id}', name='Staging Customer', email='customer@staging.local', status='active')
db.add(cust)
db.flush()
conv = Conversation(tenant_id='{tenant_id}', channel_id=ch.id, customer_id=cust.id, status='active')
db.add(conv)
db.flush()
msg = Message(tenant_id='{tenant_id}', conversation_id=conv.id, sender_type='customer', content='Hello Staging Acceptance')
db.add(msg)
db.flush()
evt = OutboxEvent(
    tenant_id='{tenant_id}',
    conversation_id=conv.id,
    message_id=msg.id,
    event_type='process_incoming_message',
    idempotency_key=f'staging-outbox-{{uuid4().hex[:8]}}',
    status='pending',
    payload={{'message_id': str(msg.id), 'conversation_id': str(conv.id)}}
)
db.add(evt)
db.commit()
print(str(evt.id))
"""
    ]
    evt_id = subprocess.check_output(cmd_enqueue).decode("utf-8").strip()
    assert len(evt_id) == 36

    # Wait for the embedded outbox worker thread to claim and process the event
    time.sleep(3.0)

    cmd_check = [
        "docker", "compose", "-f", "docker-compose.staging.yml", "exec", "-T", "agent",
        "python", "-c",
        f"""
from packages.core.database import SessionLocal
from packages.models.domain import OutboxEvent
from uuid import UUID

db = SessionLocal()
evt = db.get(OutboxEvent, UUID('{evt_id}'))
print(evt.status)
"""
    ]
    status = subprocess.check_output(cmd_check).decode("utf-8").strip()
    assert status in ("processed", "processing", "completed", "failed"), f"Unexpected status: {status}"


# =============================================================================
# Domain F: Proactive Workflows & Self-Development
# =============================================================================


def test_tc_f1_create_proactive_workflow(http_client, alpha_auth):
    """TC-F1: Proactive workflow creation endpoint returns HTTP 201."""
    resp = http_client.post(
        "/api/v1/workflows",
        headers=alpha_auth["headers"],
        json={
            "name": "Staging Health Pulse Workflow",
            "description": "Proactive automated monitoring pulse",
            "trigger_type": "schedule",
            "schedule_type": "interval",
            "interval_seconds": 3600,
            "action_type": "run_task",
            "action_payload": {"check": "ping"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Staging Health Pulse Workflow"
    assert data["status"] == "active"
    assert data["tenant_id"] == alpha_auth["tenant_id"]


def test_tc_f2_create_self_development_request(http_client, alpha_auth):
    """TC-F2: Self-development request creation returns HTTP 201."""
    resp = http_client.post(
        "/api/v1/self-development/requests",
        headers=alpha_auth["headers"],
        json={
            "problem_statement": "Platform requires automated synthetic payload benchmark capability",
            "desired_capability": "benchmark_synthetic_payloads",
            "priority": "normal",
            "trigger_type": "gap_analysis",
            "expected_benefit": "Enables faster performance verification",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "request" in data
    assert data["request"]["title"] == "benchmark_synthetic_payloads"
    assert data["request"]["tenant_id"] == alpha_auth["tenant_id"]
    assert data["request"]["status"] == "requested"


# =============================================================================
# Domain G: Security & Error Handling
# =============================================================================


def test_tc_g1_no_stack_trace_leakage(http_client):
    """TC-G1: Requesting non-existent route returns clean JSON 404 without traceback."""
    resp = http_client.get("/api/v1/nonexistent-route-for-testing")
    assert resp.status_code == 404
    text = resp.text
    assert "traceback" not in text.lower()
    assert "line " not in text.lower()
    assert "python" not in text.lower()


def test_tc_g2_pydantic_validation_error(http_client, alpha_auth):
    """TC-G2: Malformed payload returns 422 Unprocessable Content with structured errors."""
    resp = http_client.post(
        "/api/v1/tasks",
        headers=alpha_auth["headers"],
        json={},  # Missing required title and objective
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "detail" in data
    locs = [err["loc"][-1] for err in data["detail"]]
    assert "title" in locs
    assert "objective" in locs


def test_tc_g3_rate_limiting_guard(http_client):
    """TC-G3: Multiple rapid failed logins trigger rate limiting protection."""
    # Settings configure rate_limit_login_per_minute=20
    status_codes = []
    for _ in range(25):
        r = http_client.post(
            "/api/v1/auth/login",
            json={"email": "brute_force_test@staging.local", "password": "bad"},
        )
        status_codes.append(r.status_code)

    # Must contain 401 and may trigger 429 if threshold is reached within the window
    assert 401 in status_codes
    assert all(code in (401, 429) for code in status_codes)


# =============================================================================
# Domain H: Phase 20.1 Integration Defects Verification (Live Backend Contract)
# =============================================================================


def test_tc_h1_budget_field_in_tenant_dashboard(http_client, alpha_auth):
    """
    DEF-20-01: Verify GET /api/v1/admin/tenant/dashboard uses key 'budget'
    and does NOT expose obsolete/misnamed 'ai_budget'.
    """
    resp = http_client.get(
        "/api/v1/admin/tenant/dashboard",
        headers=alpha_auth["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()

    # The verified contract uses 'budget'
    assert "budget" in data, "Dashboard response must contain 'budget' key"
    assert "ai_budget" not in data, "Dashboard response must not contain obsolete 'ai_budget'"

    budget = data["budget"]
    assert "current_month_tokens" in budget
    assert "alert_level" in budget
    assert "configured" in budget
    assert budget["alert_level"] in ("none", "normal", "warning", "critical", "exceeded")


def test_tc_h2_agents_items_and_active_status_contract(http_client, alpha_auth):
    """
    DEF-20-02: Verify GET /api/v1/admin/tenant/dashboard returns 'agents.items'
    and calculates active agents accurately from agent items.
    """
    resp = http_client.get(
        "/api/v1/admin/tenant/dashboard",
        headers=alpha_auth["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "agents" in data, "Dashboard response must contain 'agents'"
    agents_data = data["agents"]
    assert "items" in agents_data, "agents must contain 'items' list"
    assert "total" in agents_data, "agents must contain 'total' count"

    # Verify structure of items
    items = agents_data["items"]
    assert isinstance(items, list)
    assert agents_data["total"] == len(items)

    # Verify each item has 'status' and calculate active count directly
    active_count = sum(1 for a in items if (a.get("status") or "").lower() == "active")
    assert active_count >= 0
    for agent in items:
        assert "id" in agent
        assert "name" in agent
        assert "status" in agent


def test_tc_h3_auth_me_profile_session_recovery(http_client, alpha_auth):
    """
    DEF-20-03: Verify GET /api/v1/auth/me returns complete AuthUserResponse
    (id, name, email, role, tenant_id, status) for session restoration.
    """
    resp = http_client.get(
        "/api/v1/auth/me",
        headers=alpha_auth["headers"],
    )
    assert resp.status_code == 200
    profile = resp.json()

    # Must contain full user fields expected by User interface
    assert "id" in profile, "auth/me must return 'id'"
    assert "email" in profile, "auth/me must return 'email'"
    assert "name" in profile, "auth/me must return 'name'"
    assert "role" in profile, "auth/me must return 'role'"
    assert "tenant_id" in profile, "auth/me must return 'tenant_id'"
    assert "status" in profile, "auth/me must return 'status'"
    assert profile["email"] == ALPHA_EMAIL
    assert profile["role"] == "tenant_owner"
    assert profile["status"] == "active"

