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


def test_authenticated_request_resolves_tenant():
    db = SessionLocal()

    try:
        tenant = Tenant(
            name="HTTP Test Business",
            slug=f"http-test-{uuid4().hex[:8]}",
        )
        db.add(tenant)
        db.flush()

        user = User(
            tenant_id=tenant.id,
            name="HTTP Test User",
            email=f"http-{uuid4().hex[:8]}@example.com",
            role="owner",
            status="active",
        )
        db.add(user)
        db.commit()

        response = client.get(
            "/api/v1/me",
            headers={
                "X-User-ID": str(user.id),
            },
        )

        assert response.status_code == 200

        data = response.json()

        assert data["user_id"] == str(user.id)
        assert data["tenant_id"] == str(tenant.id)
        assert data["name"] == "HTTP Test User"
        assert data["role"] == "owner"

        db.delete(tenant)
        db.commit()

    finally:
        db.close()


def test_request_without_authentication_is_rejected():
    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_request_with_invalid_user_is_rejected():
    response = client.get(
        "/api/v1/me",
        headers={
            "X-User-ID": str(uuid4()),
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "User not found or inactive"
