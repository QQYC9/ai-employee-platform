from uuid import uuid4

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Agent, User
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


def create_agent(
    tenant_id,
    name: str,
) -> Agent:
    db = SessionLocal()

    agent = Agent(
        tenant_id=tenant_id,
        name=name,
        agent_type="main",
        status="active",
        system_config={},
    )
    db.add(agent)

    db.commit()
    db.refresh(agent)
    db.close()

    return agent


def test_create_permission_api():
    tenant, user = create_tenant_and_user(
        "Permission API Create"
    )

    response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_message",
            "resource": "customer",
            "effect": "allow",
            "conditions": {
                "channel": "whatsapp"
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["tenant_id"] == str(tenant.id)
    assert data["agent_id"] is None
    assert data["action"] == "send_message"
    assert data["resource"] == "customer"
    assert data["effect"] == "allow"
    assert data["conditions"] == {
        "channel": "whatsapp"
    }


def test_list_permissions():
    tenant, user = create_tenant_and_user(
        "Permission API List"
    )

    create_response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "create_quote",
            "resource": "customer",
            "effect": "allow",
        },
    )

    assert create_response.status_code == 201

    response = client.get(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    items = response.json()["items"]

    assert len(items) == 1
    assert items[0]["action"] == "create_quote"
    assert items[0]["tenant_id"] == str(tenant.id)


def test_get_permission():
    _, user = create_tenant_and_user(
        "Permission API Get"
    )

    create_response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "publish_content",
            "resource": "social_media",
            "effect": "deny",
        },
    )

    permission_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/permissions/{permission_id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == permission_id
    assert data["effect"] == "deny"


def test_update_permission():
    _, user = create_tenant_and_user(
        "Permission API Update"
    )

    create_response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_email",
            "resource": "customer",
            "effect": "deny",
        },
    )

    permission_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/permissions/{permission_id}",
        headers={"X-User-ID": str(user.id)},
        json={
            "effect": "allow",
            "conditions": {
                "approved": True
            },
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["effect"] == "allow"
    assert data["conditions"] == {
        "approved": True
    }


def test_delete_permission():
    _, user = create_tenant_and_user(
        "Permission API Delete"
    )

    create_response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "delete_customer",
            "resource": "customer",
            "effect": "deny",
        },
    )

    permission_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/v1/permissions/{permission_id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "ok"

    get_response = client.get(
        f"/api/v1/permissions/{permission_id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert get_response.status_code == 404


def test_agent_specific_permission():
    _, user = create_tenant_and_user(
        "Permission API Agent"
    )

    agent = create_agent(
        user.tenant_id,
        "Sales Agent",
    )

    response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "create_quote",
            "resource": "customer",
            "effect": "allow",
            "agent_id": str(agent.id),
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["agent_id"] == str(agent.id)


def test_permission_cannot_cross_tenants():
    tenant_a, user_a = create_tenant_and_user(
        "Permission API Tenant A"
    )
    _, user_b = create_tenant_and_user(
        "Permission API Tenant B"
    )

    create_response = client.post(
        "/api/v1/permissions",
        headers={"X-User-ID": str(user_a.id)},
        json={
            "action": "send_message",
            "resource": "customer",
            "effect": "allow",
        },
    )

    assert create_response.status_code == 201

    permission_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/permissions/{permission_id}",
        headers={"X-User-ID": str(user_b.id)},
    )

    assert response.status_code == 404


def test_permission_requires_authentication():
    response = client.get(
        "/api/v1/permissions",
    )

    assert response.status_code == 401
