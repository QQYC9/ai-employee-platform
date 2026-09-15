from uuid import uuid4

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Agent, Capability, User
from packages.models.tenant import Tenant


client = TestClient(app)


def create_test_user(
    tenant_name: str,
) -> tuple[Tenant, User]:
    db = SessionLocal()

    tenant = Tenant(
        name=tenant_name,
        slug=f"{tenant_name.lower()}-{uuid4().hex[:8]}",
        status="active",
    )

    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Test User",
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
    name: str = "Main Agent",
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

    agent_id = agent.id

    db.close()

    return agent_id


def create_capability(
    tenant_id,
    name: str = "Marketing",
    slug: str | None = None,
) -> Capability:
    db = SessionLocal()

    capability = Capability(
        tenant_id=tenant_id,
        name=name,
        slug=slug or f"{name.lower()}-{uuid4().hex[:8]}",
        description=f"{name} capability",
        config={},
        is_active=True,
    )

    db.add(capability)
    db.commit()
    db.refresh(capability)

    capability_id = capability.id

    db.close()

    return capability_id


def create_global_capability(
    name: str = "Research",
) -> Capability:
    db = SessionLocal()

    capability = Capability(
        tenant_id=None,
        name=name,
        slug=f"{name.lower()}-{uuid4().hex[:8]}",
        description=f"Global {name} capability",
        config={},
        is_active=True,
    )

    db.add(capability)
    db.commit()
    db.refresh(capability)

    capability_id = capability.id

    db.close()

    return capability_id


def test_attach_capability_to_agent():
    tenant, user = create_test_user(
        "Agent Capability Attach"
    )

    agent_id = create_agent(
        tenant.id,
    )

    capability_id = create_capability(
        tenant.id,
        "Marketing",
    )

    response = client.post(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
        json={
            "capability_id": str(capability_id),
            "config": {
                "priority": "high",
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["agent_id"] == str(agent_id)
    assert data["capability_id"] == str(capability_id)
    assert data["config"]["priority"] == "high"


def test_list_agent_capabilities():
    tenant, user = create_test_user(
        "Agent Capability List"
    )

    agent_id = create_agent(
        tenant.id,
    )

    marketing_id = create_capability(
        tenant.id,
        "Marketing",
    )

    sales_id = create_capability(
        tenant.id,
        "Sales",
    )

    for capability_id in [
        marketing_id,
        sales_id,
    ]:
        response = client.post(
            f"/api/v1/agents/{agent_id}/capabilities",
            headers={
                "X-User-ID": str(user.id),
            },
            json={
                "capability_id": str(capability_id),
            },
        )

        assert response.status_code == 201

    response = client.get(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
    )

    assert response.status_code == 200

    data = response.json()

    slugs = {
        capability["slug"]
        for capability in data
    }

    assert any(
        slug.startswith("marketing-")
        for slug in slugs
    )

    assert any(
        slug.startswith("sales-")
        for slug in slugs
    )


def test_global_capability_can_be_attached():
    tenant, user = create_test_user(
        "Agent Global Capability"
    )

    agent_id = create_agent(
        tenant.id,
    )

    capability_id = create_global_capability()

    response = client.post(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
        json={
            "capability_id": str(capability_id),
        },
    )

    assert response.status_code == 201

    response = client.get(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["name"] == "Research"


def test_agent_cannot_use_capability_from_another_tenant():
    tenant_one, user_one = create_test_user(
        "Agent Capability Tenant One"
    )

    tenant_two, _ = create_test_user(
        "Agent Capability Tenant Two"
    )

    agent_id = create_agent(
        tenant_one.id,
    )

    capability_id = create_capability(
        tenant_two.id,
        "Private Capability",
    )

    response = client.post(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user_one.id),
        },
        json={
            "capability_id": str(capability_id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Capability not found"


def test_agent_from_another_tenant_cannot_be_accessed():
    tenant_one, user_one = create_test_user(
        "Agent Isolation One"
    )

    tenant_two, _ = create_test_user(
        "Agent Isolation Two"
    )

    agent_two_id = create_agent(
        tenant_two.id,
        "Private Agent",
    )

    capability_id = create_capability(
        tenant_one.id,
        "Marketing",
    )

    response = client.post(
        f"/api/v1/agents/{agent_two_id}/capabilities",
        headers={
            "X-User-ID": str(user_one.id),
        },
        json={
            "capability_id": str(capability_id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent not found"


def test_duplicate_capability_assignment_is_rejected():
    tenant, user = create_test_user(
        "Agent Capability Duplicate"
    )

    agent_id = create_agent(
        tenant.id,
    )

    capability_id = create_capability(
        tenant.id,
        "Marketing",
    )

    payload = {
        "capability_id": str(capability_id),
    }

    first_response = client.post(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
        json=payload,
    )

    assert first_response.status_code == 201

    second_response = client.post(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
        json=payload,
    )

    assert second_response.status_code == 400
    assert (
        second_response.json()["detail"]
        == "Capability is already attached to this agent"
    )


def test_detach_capability():
    tenant, user = create_test_user(
        "Agent Capability Detach"
    )

    agent_id = create_agent(
        tenant.id,
    )

    capability_id = create_capability(
        tenant.id,
        "Marketing",
    )

    attach_response = client.post(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
        json={
            "capability_id": str(capability_id),
        },
    )

    assert attach_response.status_code == 201

    delete_response = client.delete(
        f"/api/v1/agents/{agent_id}/capabilities/{capability_id}",
        headers={
            "X-User-ID": str(user.id),
        },
    )

    assert delete_response.status_code == 200

    assert delete_response.json()["status"] == "ok"

    list_response = client.get(
        f"/api/v1/agents/{agent_id}/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
    )

    assert list_response.status_code == 200
    assert list_response.json() == []


def test_agent_capability_requires_authentication():
    response = client.get(
        f"/api/v1/agents/{uuid4()}/capabilities"
    )

    assert response.status_code == 401
