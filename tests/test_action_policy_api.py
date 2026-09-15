from uuid import uuid4

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import User
from packages.models.tenant import Tenant
from fastapi.testclient import TestClient


client = TestClient(app)


def create_tenant_and_user(
    name: str,
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
        email=f"{uuid4().hex}@example.com",
        role="owner",
        status="active",
    )
    db.add(user)

    db.commit()
    db.refresh(tenant)
    db.refresh(user)
    db.close()

    return tenant, user


def test_create_action_policy_api():
    tenant, user = create_tenant_and_user(
        "Action Policy API Create"
    )

    response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_email",
            "resource": "customer",
            "requires_approval": True,
            "approval_for": "tenant_owner",
            "conditions": {
                "business_hours_only": True
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["tenant_id"] == str(tenant.id)
    assert data["action"] == "send_email"
    assert data["resource"] == "customer"
    assert data["requires_approval"] is True
    assert data["approval_for"] == "tenant_owner"
    assert data["conditions"] == {
        "business_hours_only": True
    }
    assert data["is_active"] is True


def test_create_action_policy_requires_approval_for():
    _, user = create_tenant_and_user(
        "Action Policy API Validation"
    )

    response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_email",
            "requires_approval": True,
        },
    )

    assert response.status_code == 400
    assert "approval_for is required" in response.json()["detail"]


def test_list_action_policies():
    tenant, user = create_tenant_and_user(
        "Action Policy API List"
    )

    create_response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "create_quote",
            "resource": "customer",
        },
    )

    assert create_response.status_code == 201

    response = client.get(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    items = response.json()["items"]

    assert len(items) == 1
    assert items[0]["action"] == "create_quote"
    assert items[0]["tenant_id"] == str(tenant.id)


def test_get_action_policy():
    _, user = create_tenant_and_user(
        "Action Policy API Get"
    )

    create_response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "publish_content",
            "resource": "social_media",
        },
    )

    assert create_response.status_code == 201

    policy_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/action-policies/{policy_id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == policy_id
    assert data["action"] == "publish_content"
    assert data["resource"] == "social_media"


def test_update_action_policy():
    _, user = create_tenant_and_user(
        "Action Policy API Update"
    )

    create_response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_email",
            "resource": "customer",
        },
    )

    assert create_response.status_code == 201

    policy_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/action-policies/{policy_id}",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_customer_email",
            "requires_approval": True,
            "approval_for": "tenant_owner",
            "conditions": {
                "limit": 100
            },
            "is_active": False,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["action"] == "send_customer_email"
    assert data["requires_approval"] is True
    assert data["approval_for"] == "tenant_owner"
    assert data["conditions"] == {
        "limit": 100
    }
    assert data["is_active"] is False


def test_delete_action_policy():
    _, user = create_tenant_and_user(
        "Action Policy API Delete"
    )

    create_response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "delete_customer",
            "resource": "customer",
        },
    )

    assert create_response.status_code == 201

    policy_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/action-policies/{policy_id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "ok"

    get_response = client.get(
        f"/api/v1/action-policies/{policy_id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert get_response.status_code == 404


def test_action_policy_cannot_cross_tenants():
    _, user_a = create_tenant_and_user(
        "Action Policy API Tenant A"
    )
    _, user_b = create_tenant_and_user(
        "Action Policy API Tenant B"
    )

    create_response = client.post(
        "/api/v1/action-policies",
        headers={"X-User-ID": str(user_a.id)},
        json={
            "action": "send_message",
            "resource": "customer",
        },
    )

    assert create_response.status_code == 201

    policy_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/action-policies/{policy_id}",
        headers={"X-User-ID": str(user_b.id)},
    )

    assert response.status_code == 404


def test_action_policy_requires_authentication():
    response = client.get(
        "/api/v1/action-policies",
    )

    assert response.status_code == 401
