from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.auth.jwt_service import (
    InvalidTokenError,
    TokenClaimsError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from packages.auth.rate_limiter import rate_limiter
from packages.auth.security import hash_password, verify_password
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import ActionPolicy, Approval, Task, User
from packages.models.tenant import Tenant
from packages.services.task_service import TaskService


@pytest.fixture(autouse=True)
def reset_rate_limiter_and_settings():
    """Ensure clean state before and after each test."""
    rate_limiter.reset()
    original_env = settings.environment
    original_allow = settings.allow_dev_auth_header
    original_jwt_key = settings.jwt_secret_key
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    yield
    rate_limiter.reset()
    settings.environment = original_env
    settings.allow_dev_auth_header = original_allow
    settings.jwt_secret_key = original_jwt_key


def create_tenant_and_user_with_password(
    name: str = "Auth Test Tenant",
    role: str = "tenant_owner",
    password: str = "SecurePass123!",
) -> tuple[Tenant, User]:
    db = SessionLocal()
    tenant = Tenant(
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name=f"{name} User",
        email=f"user-{uuid4().hex[:8]}@example.com",
        role=role,
        status="active",
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(tenant)
    db.refresh(user)
    db.close()
    return tenant, user


# =========================================================================
# 1. Password Security & Hashing Tests
# =========================================================================

def test_password_hashing_and_verification():
    raw_pwd = "MySecretPassword123!"
    hashed = hash_password(raw_pwd)

    assert hashed.startswith("pbkdf2:sha256:200000$")
    assert verify_password(raw_pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(raw_pwd, "") is False
    assert verify_password(raw_pwd, "malformed:hash") is False


def test_password_hash_empty_string_fails():
    with pytest.raises(ValueError):
        hash_password("")


# =========================================================================
# 2. JWT Cryptographic Issuance & Verification Tests
# =========================================================================

def test_jwt_token_creation_and_claims():
    user_id = uuid4()
    tenant_id = uuid4()
    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="tenant_owner",
    )

    payload = verify_token(token, expected_type="access")
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "tenant_owner"
    assert payload["token_type"] == "access"
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_expired_token_rejected():
    user_id = uuid4()
    token = create_access_token(
        user_id=user_id,
        tenant_id=None,
        role="member",
        expires_delta=timedelta(seconds=-10),
    )

    with pytest.raises(TokenExpiredError):
        verify_token(token, expected_type="access")


def test_jwt_tampered_signature_rejected():
    user_id = uuid4()
    token = create_access_token(user_id=user_id, tenant_id=None, role="member")
    # Tamper with the payload part
    header, payload, sig = token.split(".")
    tampered_token = f"{header}.eyJzdWIiOiAic3Bvb2ZlZCJ9.{sig}"

    with pytest.raises(InvalidTokenError):
        verify_token(tampered_token, expected_type="access")


def test_jwt_wrong_secret_key_rejected():
    user_id = uuid4()
    token = create_access_token(
        user_id=user_id,
        tenant_id=None,
        role="member",
        signing_key="correct-key-32chars-min-length-123",
    )

    with pytest.raises(InvalidTokenError):
        verify_token(
            token,
            expected_type="access",
            signing_key="wrong-key-32chars-min-length-12345",
        )


def test_jwt_token_type_mismatch():
    user_id = uuid4()
    refresh_tok = create_refresh_token(user_id=user_id, tenant_id=None, role="member")

    with pytest.raises(InvalidTokenError) as exc_info:
        verify_token(refresh_tok, expected_type="access")
    assert "Expected token_type 'access'" in str(exc_info.value)


# =========================================================================
# 3. Authentication Routes (/api/v1/auth/login, refresh, me)
# =========================================================================

def test_auth_status_endpoint():
    client = TestClient(app)
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "authentication"


def test_login_success():
    client = TestClient(app)
    tenant, user = create_tenant_and_user_with_password(
        name="Login Success", password="CorrectPassword123!"
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "CorrectPassword123!",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == user.email
    assert data["user"]["tenant_id"] == str(tenant.id)


def test_login_failure_wrong_password():
    client = TestClient(app)
    _, user = create_tenant_and_user_with_password(
        name="Login Fail", password="RealPassword123!"
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "WrongPassword456!",
        },
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_login_failure_nonexistent_email():
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "AnyPassword123!",
        },
    )
    assert response.status_code == 401


def test_login_rate_limiting():
    client = TestClient(app)
    _, user = create_tenant_and_user_with_password(name="Rate Limit User")

    # Send up to the limit (10 requests)
    for _ in range(settings.rate_limit_login_per_minute):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong"},
        )
        assert res.status_code == 401

    # 11th request must be rejected with 429
    res = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong"},
    )
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_token_refresh_flow():
    client = TestClient(app)
    tenant, user = create_tenant_and_user_with_password(name="Refresh Flow")

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "SecurePass123!"},
    )
    assert login_res.status_code == 200
    refresh_token = login_res.json()["refresh_token"]

    # Exchange refresh token for new access token
    refresh_res = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res.status_code == 200
    refresh_data = refresh_res.json()
    assert "access_token" in refresh_data
    assert "refresh_token" in refresh_data


def test_refresh_with_expired_token():
    client = TestClient(app)
    _, user = create_tenant_and_user_with_password(name="Expired Refresh")
    expired_ref = create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        expires_delta=timedelta(seconds=-5),
    )

    res = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": expired_ref},
    )
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_auth_me_endpoint_with_bearer():
    client = TestClient(app)
    tenant, user = create_tenant_and_user_with_password(name="Me Endpoint")
    token = create_access_token(user.id, tenant.id, user.role)

    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    profile = res.json()
    assert profile["id"] == str(user.id)
    assert profile["email"] == user.email
    assert profile["tenant_id"] == str(tenant.id)


# =========================================================================
# 4. Production Rejection of X-User-ID Stub
# =========================================================================

def test_x_user_id_accepted_in_dev_mode():
    client = TestClient(app)
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    tenant, user = create_tenant_and_user_with_password(name="Dev Header Allowed")

    res = client.get(
        "/api/v1/tenants/me",
        headers={"X-User-ID": str(user.id)},
    )
    assert res.status_code == 200
    assert res.json()["id"] == str(tenant.id)


def test_x_user_id_strictly_forbidden_in_production():
    client = TestClient(app)
    settings.environment = "production"
    tenant, user = create_tenant_and_user_with_password(name="Prod Blocked Header")

    res = client.get(
        "/api/v1/tenants/me",
        headers={"X-User-ID": str(user.id)},
    )
    assert res.status_code == 401
    assert "forbidden in this environment" in res.json()["detail"]


def test_bearer_token_works_in_production():
    client = TestClient(app)
    settings.environment = "production"
    settings.jwt_secret_key = "production-secure-signing-key-minimum-32chars!"
    tenant, user = create_tenant_and_user_with_password(name="Prod Bearer Works")
    token = create_access_token(user.id, tenant.id, user.role)

    res = client.get(
        "/api/v1/tenants/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["id"] == str(tenant.id)


def test_production_rejects_insecure_default_key():
    settings.environment = "production"
    settings.jwt_secret_key = "dev-insecure-jwt-secret-replace-in-production-min32chars"
    with pytest.raises(ValueError) as exc:
        create_access_token(uuid4(), None, "member")
    assert "Insecure or missing JWT_SECRET_KEY in production" in str(exc.value)


def test_missing_authentication_rejected():
    client = TestClient(app)
    res = client.get("/api/v1/tenants/me")
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]


# =========================================================================
# 5. Multi-Tenant Isolation & Anti-Tampering
# =========================================================================

def test_cross_tenant_resource_isolation():
    client = TestClient(app)
    tenant_a, user_a = create_tenant_and_user_with_password(name="Tenant A")
    tenant_b, user_b = create_tenant_and_user_with_password(name="Tenant B")

    # User A creates a task in Tenant A
    db = SessionLocal()
    task_service = TaskService(db)
    task_a = task_service.create_task(
        tenant_id=tenant_a.id,
        title="Secret Task A",
        objective="Confidential objective A",
    )
    task_a_id = task_a.id
    db.commit()
    db.close()

    # User B authenticates with their own valid Bearer token
    token_b = create_access_token(user_b.id, tenant_b.id, user_b.role)

    # User B attempts to access User A's task by known ID
    res = client.get(
        f"/api/v1/tasks/{task_a_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    # Must be 404 Not Found (or 403 Forbidden) - never leak task details!
    assert res.status_code == 404
    assert res.json()["detail"] == "Task not found"


def test_token_tenant_tampering_rejected():
    client = TestClient(app)
    tenant_a, user_a = create_tenant_and_user_with_password(name="Tenant A User")
    tenant_b, _ = create_tenant_and_user_with_password(name="Tenant B")

    # Attacker crafts a token with user_a's ID but tenant_b's tenant_id
    tampered_token = create_access_token(
        user_id=user_a.id,
        tenant_id=tenant_b.id,
        role=user_a.role,
    )

    res = client.get(
        "/api/v1/tenants/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert res.status_code == 401
    assert "tenant claims mismatch" in res.json()["detail"].lower()


# =========================================================================
# 6. Role-Based Access Control (RBAC) & Least Privilege
# =========================================================================

def test_regular_user_cannot_update_tenant():
    client = TestClient(app)
    tenant, regular_user = create_tenant_and_user_with_password(
        name="Member Tenant", role="tenant_user"
    )
    token = create_access_token(regular_user.id, tenant.id, regular_user.role)

    res = client.patch(
        "/api/v1/tenants/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Hacked Tenant Name"},
    )
    assert res.status_code == 403
    assert "Only tenant owners or administrators" in res.json()["detail"]


def test_tenant_owner_can_update_tenant():
    client = TestClient(app)
    tenant, owner_user = create_tenant_and_user_with_password(
        name="Owner Tenant", role="tenant_owner"
    )
    token = create_access_token(owner_user.id, tenant.id, owner_user.role)

    res = client.patch(
        "/api/v1/tenants/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Renamed Tenant Name"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed Tenant Name"


def test_regular_user_cannot_manage_action_policies():
    client = TestClient(app)
    tenant, regular_user = create_tenant_and_user_with_password(
        name="Policy Member", role="tenant_user"
    )
    token = create_access_token(regular_user.id, tenant.id, regular_user.role)

    res = client.post(
        "/api/v1/action-policies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "action": "delete_database",
            "resource": "db",
            "requires_approval": False,
        },
    )
    assert res.status_code == 403
    assert "Only tenant owners or administrators" in res.json()["detail"]


def test_tenant_owner_can_create_action_policy():
    client = TestClient(app)
    tenant, owner = create_tenant_and_user_with_password(
        name="Policy Owner", role="tenant_owner"
    )
    token = create_access_token(owner.id, tenant.id, owner.role)

    res = client.post(
        "/api/v1/action-policies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "action": "wire_transfer",
            "resource": "bank",
            "requires_approval": True,
            "approval_for": "tenant_owner",
        },
    )
    assert res.status_code == 201
    assert res.json()["action"] == "wire_transfer"


def test_platform_admin_access():
    client = TestClient(app)
    tenant, admin_user = create_tenant_and_user_with_password(
        name="Platform Admin Tenant", role="platform_admin"
    )
    token = create_access_token(admin_user.id, tenant.id, admin_user.role)

    # Platform admin can create policies
    res = client.post(
        "/api/v1/action-policies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "action": "system_maintenance",
            "resource": "server",
            "requires_approval": False,
        },
    )
    assert res.status_code == 201


# =========================================================================
# 7. End-to-End Task Lifecycle with Production Bearer Token
# =========================================================================

def test_full_task_lifecycle_authenticated():
    client = TestClient(app)
    tenant, owner = create_tenant_and_user_with_password(
        name="E2E Lifecycle", role="tenant_owner"
    )
    token = create_access_token(owner.id, tenant.id, owner.role)
    auth_header = {"Authorization": f"Bearer {token}"}

    # 1. Create Task
    create_res = client.post(
        "/api/v1/tasks",
        headers=auth_header,
        json={
            "title": "Production Deployment Verification",
            "objective": "Verify system security and generate report",
        },
    )
    assert create_res.status_code == 201
    task_id = create_res.json()["id"]

    # 2. Plan Task
    plan_res = client.post(
        f"/api/v1/tasks/{task_id}/plan",
        headers=auth_header,
        json={
            "steps": [
                {
                    "step_id": "step_1",
                    "step_type": "tool",
                    "action": "audit_check",
                    "description": "Run audit check",
                }
            ]
        },
    )
    assert plan_res.status_code == 200

    # 3. Retrieve Task
    get_res = client.get(
        f"/api/v1/tasks/{task_id}",
        headers=auth_header,
    )
    assert get_res.status_code == 200
    assert get_res.json()["id"] == task_id
    assert get_res.json()["tenant_id"] == str(tenant.id)
