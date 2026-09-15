import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import Agent, User


client = TestClient(app)


def create_test_user():
    db = SessionLocal()

    tenant = Tenant(
        name="Agent API Test",
        slug=f"agent-api-{uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Agent API User",
        email=f"agent-{uuid4().hex[:8]}@example.com",
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


def test_create_agent():
    user_id, tenant_id = create_test_user()

    try:
        response = client.post(
            "/api/v1/agents",
            headers={
                "X-User-ID": str(user_id),
            },
            json={
                "name": "Main Digital Employee",
                "agent_type": "main",
            },
        )

        assert response.status_code == 201

        data = response.json()

        assert data["name"] == "Main Digital Employee"
        assert data["agent_type"] == "main"
        assert data["status"] == "active"

    finally:
        delete_test_tenant(tenant_id)


def test_list_agents_is_tenant_scoped():
    user_id_a, tenant_id_a = create_test_user()
    user_id_b, tenant_id_b = create_test_user()

    db = SessionLocal()

    try:
        agent_a = Agent(
            tenant_id=tenant_id_a,
            name="Agent A",
            agent_type="main",
            status="active",
            system_config={},
        )

        agent_b = Agent(
            tenant_id=tenant_id_b,
            name="Agent B",
            agent_type="main",
            status="active",
            system_config={},
        )

        db.add_all([agent_a, agent_b])
        db.commit()

        response_a = client.get(
            "/api/v1/agents",
            headers={
                "X-User-ID": str(user_id_a),
            },
        )

        assert response_a.status_code == 200

        agents_a = response_a.json()

        assert len(agents_a) == 1
        assert agents_a[0]["name"] == "Agent A"

        response_b = client.get(
            "/api/v1/agents",
            headers={
                "X-User-ID": str(user_id_b),
            },
        )

        assert response_b.status_code == 200

        agents_b = response_b.json()

        assert len(agents_b) == 1
        assert agents_b[0]["name"] == "Agent B"

    finally:
        db.close()
        delete_test_tenant(tenant_id_a)
        delete_test_tenant(tenant_id_b)


def test_agent_cannot_be_accessed_by_another_tenant():
    user_id_a, tenant_id_a = create_test_user()
    user_id_b, tenant_id_b = create_test_user()

    db = SessionLocal()

    try:
        agent_a = Agent(
            tenant_id=tenant_id_a,
            name="Private Agent A",
            agent_type="main",
            status="active",
            system_config={},
        )

        db.add(agent_a)
        db.commit()

        agent_id = agent_a.id

        response = client.get(
            f"/api/v1/agents/{agent_id}",
            headers={
                "X-User-ID": str(user_id_b),
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Agent not found"

    finally:
        db.close()
        delete_test_tenant(tenant_id_a)
        delete_test_tenant(tenant_id_b)


def test_agent_requires_authentication():
    response = client.get("/api/v1/agents")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
