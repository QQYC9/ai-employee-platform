import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import User


client = TestClient(app)


def create_test_user():
    db = SessionLocal()

    tenant = Tenant(
        name="Tenant API Test",
        slug=f"tenant-api-{uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Tenant API User",
        email=f"user-{uuid4().hex[:8]}@example.com",
        role="owner",
        status="active",
    )

    db.add(user)
    db.commit()

    user_id = user.id
    tenant_id = tenant.id

    db.close()

    return user_id, tenant_id


def delete_test_tenant(tenant_id):
    db = SessionLocal()

    try:
        tenant = db.get(Tenant, tenant_id)

        if tenant is not None:
            db.delete(tenant)
            db.commit()

    finally:
        db.close()


def test_get_my_tenant():
    user_id, tenant_id = create_test_user()

    try:
        response = client.get(
            "/api/v1/tenants/me",
            headers={
                "X-User-ID": str(user_id),
            },
        )

        assert response.status_code == 200

        data = response.json()

        assert data["id"] == str(tenant_id)
        assert data["name"] == "Tenant API Test"
        assert data["status"] == "active"

    finally:
        delete_test_tenant(tenant_id)


def test_update_my_tenant():
    user_id, tenant_id = create_test_user()

    try:
        response = client.patch(
            "/api/v1/tenants/me",
            headers={
                "X-User-ID": str(user_id),
            },
            json={
                "name": "Updated Business Name",
            },
        )

        assert response.status_code == 200

        data = response.json()

        assert data["id"] == str(tenant_id)
        assert data["name"] == "Updated Business Name"

    finally:
        delete_test_tenant(tenant_id)


def test_update_tenant_rejects_empty_name():
    user_id, tenant_id = create_test_user()

    try:
        response = client.patch(
            "/api/v1/tenants/me",
            headers={
                "X-User-ID": str(user_id),
            },
            json={
                "name": "   ",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Tenant name cannot be empty"

    finally:
        delete_test_tenant(tenant_id)


def test_tenant_requires_authentication():
    response = client.get("/api/v1/tenants/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
