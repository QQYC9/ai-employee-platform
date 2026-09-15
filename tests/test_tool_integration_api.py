from uuid import uuid4

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Integration, Tool, User
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


def create_tool(
    tenant_id,
    name: str,
    slug: str,
) -> Tool:
    db = SessionLocal()

    tool = Tool(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        description="Test tool",
        tool_type="test",
        config={},
        is_active=True,
    )
    db.add(tool)

    db.commit()
    db.refresh(tool)
    db.close()

    return tool


def create_global_tool(
    name: str,
    slug: str,
) -> Tool:
    db = SessionLocal()

    tool = Tool(
        tenant_id=None,
        name=name,
        slug=slug,
        description="Global test tool",
        tool_type="test",
        config={},
        is_active=True,
    )
    db.add(tool)

    db.commit()
    db.refresh(tool)
    db.close()

    return tool


def create_integration(
    tenant_id,
    name: str,
    provider: str,
) -> Integration:
    db = SessionLocal()

    integration = Integration(
        tenant_id=tenant_id,
        name=name,
        provider=provider,
        status="active",
        config={},
    )
    db.add(integration)

    db.commit()
    db.refresh(integration)
    db.close()

    return integration


def create_global_integration(
    name: str,
    provider: str,
) -> Integration:
    db = SessionLocal()

    integration = Integration(
        tenant_id=None,
        name=name,
        provider=provider,
        status="active",
        config={},
    )
    db.add(integration)

    db.commit()
    db.refresh(integration)
    db.close()

    return integration


def test_attach_integration_to_tool():
    tenant, user = create_tenant_and_user(
        "Tool Integration Attach"
    )

    tool = create_tool(
        tenant.id,
        "CRM Tool",
        f"crm-{uuid4().hex[:8]}",
    )

    integration = create_integration(
        tenant.id,
        "CRM Integration",
        "crm",
    )

    response = client.post(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user.id)},
        json={
            "integration_id": str(integration.id),
            "config": {"enabled": True},
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["tool_id"] == str(tool.id)
    assert data["integration_id"] == str(integration.id)
    assert data["tenant_id"] == str(tenant.id)
    assert data["config"] == {"enabled": True}


def test_list_tool_integrations():
    tenant, user = create_tenant_and_user(
        "Tool Integration List"
    )

    tool = create_tool(
        tenant.id,
        "Sales Tool",
        f"sales-{uuid4().hex[:8]}",
    )

    integration = create_integration(
        tenant.id,
        "Sales CRM",
        "crm",
    )

    attach_response = client.post(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user.id)},
        json={
            "integration_id": str(integration.id),
        },
    )

    assert attach_response.status_code == 201

    response = client.get(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(integration.id)
    assert data["items"][0]["name"] == integration.name
    assert data["items"][0]["provider"] == "crm"


def test_global_integration_can_be_attached():
    tenant, user = create_tenant_and_user(
        "Global Integration"
    )

    tool = create_tool(
        tenant.id,
        "Messaging Tool",
        f"messaging-{uuid4().hex[:8]}",
    )

    integration = create_global_integration(
        "Global Messaging",
        "messaging",
    )

    response = client.post(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user.id)},
        json={
            "integration_id": str(integration.id),
        },
    )

    assert response.status_code == 201

    list_response = client.get(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user.id)},
    )

    assert list_response.status_code == 200

    items = list_response.json()["items"]

    assert len(items) == 1
    assert items[0]["id"] == str(integration.id)
    assert items[0]["scope"] == "global"


def test_integration_from_another_tenant_is_rejected():
    tenant_a, user_a = create_tenant_and_user(
        "Integration Tenant A"
    )
    tenant_b, _ = create_tenant_and_user(
        "Integration Tenant B"
    )

    tool = create_tool(
        tenant_a.id,
        "Tenant A Tool",
        f"tenant-a-tool-{uuid4().hex[:8]}",
    )

    integration = create_integration(
        tenant_b.id,
        "Tenant B Integration",
        "private-service",
    )

    response = client.post(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user_a.id)},
        json={
            "integration_id": str(integration.id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Integration not found"


def test_tool_from_another_tenant_is_rejected():
    tenant_a, user_a = create_tenant_and_user(
        "Tool Tenant A"
    )
    tenant_b, _ = create_tenant_and_user(
        "Tool Tenant B"
    )

    tool = create_tool(
        tenant_b.id,
        "Tenant B Tool",
        f"tenant-b-tool-{uuid4().hex[:8]}",
    )

    integration = create_integration(
        tenant_a.id,
        "Tenant A Integration",
        "private-service",
    )

    response = client.post(
        f"/api/v1/tools/{tool.id}/integrations",
        headers={"X-User-ID": str(user_a.id)},
        json={
            "integration_id": str(integration.id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Tool not found"


def test_duplicate_integration_attachment_is_rejected():
    tenant, user = create_tenant_and_user(
        "Duplicate Integration"
    )

    tool = create_tool(
        tenant.id,
        "Duplicate Tool",
        f"duplicate-tool-{uuid4().hex[:8]}",
    )

    integration = create_integration(
        tenant.id,
        "Duplicate Integration",
        "service",
    )

    url = f"/api/v1/tools/{tool.id}/integrations"
    headers = {"X-User-ID": str(user.id)}

    first = client.post(
        url,
        headers=headers,
        json={
            "integration_id": str(integration.id),
        },
    )

    assert first.status_code == 201

    second = client.post(
        url,
        headers=headers,
        json={
            "integration_id": str(integration.id),
        },
    )

    assert second.status_code == 400
    assert (
        second.json()["detail"]
        == "Integration is already attached to this tool"
    )


def test_detach_integration():
    tenant, user = create_tenant_and_user(
        "Detach Integration"
    )

    tool = create_tool(
        tenant.id,
        "Detach Tool",
        f"detach-tool-{uuid4().hex[:8]}",
    )

    integration = create_integration(
        tenant.id,
        "Detach Integration",
        "service",
    )

    url = f"/api/v1/tools/{tool.id}/integrations"
    headers = {"X-User-ID": str(user.id)}

    attach = client.post(
        url,
        headers=headers,
        json={
            "integration_id": str(integration.id),
        },
    )

    assert attach.status_code == 201

    delete_response = client.delete(
        f"{url}/{integration.id}",
        headers=headers,
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "ok"

    list_response = client.get(
        url,
        headers=headers,
    )

    assert list_response.status_code == 200
    assert list_response.json()["items"] == []


def test_tool_integration_requires_authentication():
    response = client.get(
        f"/api/v1/tools/{uuid4()}/integrations",
    )

    assert response.status_code == 401
