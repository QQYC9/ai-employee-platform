from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.ai_providers.base import AIProvider
from packages.ai_providers.factory import AIProviderFactory
from packages.auth.jwt_service import create_access_token
from packages.core.crypto import SecretsEncryptionService
from packages.core.database import SessionLocal
from packages.models.domain import Integration, User
from packages.models.tenant import Tenant

client = TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _create_user(
    db: Session,
    email: str,
    role: str,
    tenant_id: uuid.UUID | None = None,
    name: str = "Test User",
) -> tuple[User, str]:
    """Helper to create an active user and generate a signed access token."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        name=name,
        role=role,
        tenant_id=tenant_id,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    return user, token


def _create_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        name=name,
        slug=f"tenant-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def _cleanup(db: Session, user_ids: list[uuid.UUID], integration_ids: list[uuid.UUID], tenant_ids: list[uuid.UUID]):
    for i_id in integration_ids:
        integ = db.scalar(select(Integration).where(Integration.id == i_id))
        if integ:
            db.delete(integ)
    for u_id in user_ids:
        u = db.scalar(select(User).where(User.id == u_id))
        if u:
            db.delete(u)
    for t_id in tenant_ids:
        t = db.scalar(select(Tenant).where(Tenant.id == t_id))
        if t:
            db.delete(t)
    db.commit()


def test_1_platform_admin_full_crud_and_encryption(db: Session):
    """
    Test Batch A: Platform superadmin can register, read, update, and soft-delete
    a platform-level integration. Secrets must be encrypted at rest and masked in responses.
    """
    created_users = []
    created_integrations = []
    created_tenants = []

    try:
        admin_user, admin_token = _create_user(
            db,
            email=f"superadmin-{uuid.uuid4().hex[:6]}@platform.local",
            role="platform_admin",
            tenant_id=None,
        )
        created_users.append(admin_user.id)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Register a global platform AI provider (Groq)
        fake_api_key = "gsk_live_test_super_secret_key_1234567890"
        create_payload = {
            "name": f"groq-global-{uuid.uuid4().hex[:6]}",
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "api_key": fake_api_key,
            "base_url": "https://api.groq.com/openai/v1",
            "temperature": 0.3,
            "max_tokens": 4096,
            "is_default": True,
        }

        res = client.post("/api/v1/admin/integrations", json=create_payload, headers=headers)
        assert res.status_code == 201, res.text
        created_data = res.json()
        integration_id = uuid.UUID(created_data["id"])
        created_integrations.append(integration_id)

        # 2. Verify response masks secret key
        assert created_data["tenant_id"] is None
        assert created_data["provider"] == "groq"
        assert created_data["model"] == "openai/gpt-oss-120b"
        assert created_data["is_default"] is True
        assert fake_api_key not in res.text
        assert "gsk_" in created_data["masked_api_key"] or "********" in created_data["masked_api_key"]

        # 3. Verify DB record stores AES-256-GCM encrypted key with enc:v1: prefix
        db_record = db.scalar(select(Integration).where(Integration.id == integration_id))
        assert db_record is not None
        assert db_record.tenant_id is None
        raw_config = db_record.config
        assert "encrypted_api_key" in raw_config
        encrypted_val = raw_config["encrypted_api_key"]
        assert encrypted_val.startswith(SecretsEncryptionService.PREFIX)
        assert fake_api_key not in str(raw_config)

        # Decrypt to ensure integrity
        decrypted = SecretsEncryptionService().decrypt(encrypted_val)
        assert decrypted == fake_api_key

        # 4. List platform integrations
        res_list = client.get("/api/v1/admin/integrations", headers=headers)
        assert res_list.status_code == 200
        items = res_list.json()
        assert any(item["id"] == str(integration_id) for item in items)
        for item in items:
            assert fake_api_key not in str(item)

        # 5. Get single platform integration
        res_get = client.get(f"/api/v1/admin/integrations/{integration_id}", headers=headers)
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["id"] == str(integration_id)
        assert fake_api_key not in res_get.text

        # 6. Update platform integration (change model and temperature)
        update_payload = {
            "model": "openai/gpt-oss-200b",
            "temperature": 0.5,
        }
        res_update = client.patch(
            f"/api/v1/admin/integrations/{integration_id}",
            json=update_payload,
            headers=headers,
        )
        assert res_update.status_code == 200
        updated_data = res_update.json()
        assert updated_data["model"] == "openai/gpt-oss-200b"
        assert updated_data["temperature"] == 0.5

        # 7. Soft delete platform integration
        res_del = client.delete(f"/api/v1/admin/integrations/{integration_id}", headers=headers)
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"

        # Verify status is marked 'deleted' in DB
        db.refresh(db_record)
        assert db_record.status == "deleted"

    finally:
        _cleanup(db, created_users, created_integrations, created_tenants)


def test_2_strict_rbac_rejections(db: Session):
    """
    Test Batch A: Server-side RBAC enforcement.
    Platform integrations endpoint MUST reject tenant_owner, tenant_admin,
    tenant_member with 403 Forbidden, and unauthenticated requests with 401 Unauthorized.
    """
    created_users = []
    created_integrations = []
    created_tenants = []

    try:
        tenant = _create_tenant(db, "Tenant Corp")
        created_tenants.append(tenant.id)

        # Create 3 tenant users with different roles
        owner_user, owner_token = _create_user(db, f"owner-{uuid.uuid4().hex[:6]}@corp.local", "tenant_owner", tenant.id)
        admin_user, admin_token = _create_user(db, f"admin-{uuid.uuid4().hex[:6]}@corp.local", "tenant_admin", tenant.id)
        member_user, member_token = _create_user(db, f"member-{uuid.uuid4().hex[:6]}@corp.local", "tenant_member", tenant.id)
        created_users.extend([owner_user.id, admin_user.id, member_user.id])

        # 1. Unauthenticated request -> 401 Unauthorized
        res_unauth = client.get("/api/v1/admin/integrations")
        assert res_unauth.status_code == 401

        # 2. Tenant Owner -> 403 Forbidden
        res_owner = client.get("/api/v1/admin/integrations", headers={"Authorization": f"Bearer {owner_token}"})
        assert res_owner.status_code == 403
        assert "not permitted" in res_owner.json()["detail"].lower()

        res_owner_post = client.post(
            "/api/v1/admin/integrations",
            json={"name": "hack", "provider": "openai", "model": "gpt-4o"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert res_owner_post.status_code == 403

        # 3. Tenant Admin -> 403 Forbidden
        res_admin = client.get("/api/v1/admin/integrations", headers={"Authorization": f"Bearer {admin_token}"})
        assert res_admin.status_code == 403

        # 4. Tenant Member -> 403 Forbidden
        res_member = client.get("/api/v1/admin/integrations", headers={"Authorization": f"Bearer {member_token}"})
        assert res_member.status_code == 403

        # 5. Superadmin role -> 200 OK (Authorized)
        super_user, super_token = _create_user(db, f"super-{uuid.uuid4().hex[:6]}@platform.local", "superadmin", None)
        created_users.append(super_user.id)
        res_super = client.get("/api/v1/admin/integrations", headers={"Authorization": f"Bearer {super_token}"})
        assert res_super.status_code == 200

    finally:
        _cleanup(db, created_users, created_integrations, created_tenants)


def test_3_platform_integration_connection_testing(db: Session):
    """
    Test Batch A: Test connection endpoint performs live validation in-memory
    without leaking API keys in logs or responses.
    """
    created_users = []
    created_integrations = []
    created_tenants = []

    try:
        admin_user, admin_token = _create_user(
            db,
            email=f"admin-{uuid.uuid4().hex[:6]}@platform.local",
            role="platform_admin",
            tenant_id=None,
        )
        created_users.append(admin_user.id)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create integration
        res = client.post(
            "/api/v1/admin/integrations",
            json={
                "name": f"test-provider-{uuid.uuid4().hex[:6]}",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-test-fake-key-for-mocking-12345",
            },
            headers=headers,
        )
        assert res.status_code == 201
        integration_id = uuid.UUID(res.json()["id"])
        created_integrations.append(integration_id)

        # Mock the provider connection test to simulate successful ping
        mock_provider = MagicMock(spec=AIProvider)
        mock_provider.test_connection.return_value = {
            "success": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "latency_ms": 142.5,
            "error_type": None,
            "error_message": None,
        }

        with patch.object(AIProviderFactory, "create_provider", return_value=mock_provider):
            test_res = client.post(f"/api/v1/admin/integrations/{integration_id}/test", headers=headers)
            assert test_res.status_code == 200
            test_data = test_res.json()
            assert test_data["success"] is True
            assert test_data["latency_ms"] == 142.5
            assert "sk-test-fake-key" not in test_res.text

        # Verify DB persisted test status
        db_record = db.scalar(select(Integration).where(Integration.id == integration_id))
        assert db_record.config["last_test_status"] == "success"
        assert db_record.config["last_tested_at"] is not None

    finally:
        _cleanup(db, created_users, created_integrations, created_tenants)


def test_4_agent_execution_picks_up_platform_integration(db: Session):
    """
    Test Requirement 4: Updating a platform integration reflects in agent resolution.
    AIProviderFactory.create_provider() dynamically uses the platform integration.
    """
    created_users = []
    created_integrations = []
    created_tenants = []

    try:
        tenant = _create_tenant(db, "Execution Tenant")
        created_tenants.append(tenant.id)

        admin_user, admin_token = _create_user(
            db,
            email=f"admin-{uuid.uuid4().hex[:6]}@platform.local",
            role="superadmin",
            tenant_id=None,
        )
        created_users.append(admin_user.id)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Register default platform integration with a distinct custom model name
        unique_model_name = f"openai/gpt-platform-{uuid.uuid4().hex[:6]}"
        unique_key = "gsk_platform_default_key_test_9999"

        res = client.post(
            "/api/v1/admin/integrations",
            json={
                "name": f"default-platform-{uuid.uuid4().hex[:6]}",
                "provider": "groq",
                "model": unique_model_name,
                "api_key": unique_key,
                "is_default": True,
            },
            headers=headers,
        )
        assert res.status_code == 201
        integration_id = uuid.UUID(res.json()["id"])
        created_integrations.append(integration_id)

        # Instantiate provider for a tenant that has NO custom integration
        # It MUST resolve to the platform-level default integration!
        provider = AIProviderFactory.create_provider(
            tenant_id=tenant.id,
            db=db,
        )

        assert provider is not None
        assert provider.model == unique_model_name
        # Verify decrypted API key reached the provider instance in-memory
        assert getattr(provider, "api_key", None) == unique_key

    finally:
        _cleanup(db, created_users, created_integrations, created_tenants)
