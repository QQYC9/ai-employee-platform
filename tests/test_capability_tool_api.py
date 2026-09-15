from uuid import uuid4

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Capability, Tool, User
from packages.models.tenant import Tenant
from fastapi.testclient import TestClient


client = TestClient(app)


def create_tenant_and_user(
    name: str,
) -> tuple[Tenant, User]:
    db = SessionLocal()

    tenant = Tenant(
        name=name,
        slug=f"{name.lower()}-{uuid4().hex[:8]}",
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


def create_capability(
    tenant_id,
    name: str,
    slug: str,
) -> Capability:
    db = SessionLocal()

    capability = Capability(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        description="Test capability",
        config={},
        is_active=True,
    )
    db.add(capability)
    db.commit()
    db.refresh(capability)
    db.close()

    return capability


def create_tool(
    tenant_id,
    name: str,
    slug: str,
    tool_type: str = "test",
) -> Tool:
    db = SessionLocal()

    tool = Tool(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        description="Test tool",
        tool_type=tool_type,
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
    tool_type: str = "test",
) -> Tool:
    db = SessionLocal()

    tool = Tool(
        tenant_id=None,
        name=name,
        slug=slug,
        description="Global test tool",
        tool_type=tool_type,
        config={},
        is_active=True,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    db.close()

    return tool


def test_attach_tool_to_capability():
    tenant, user = create_tenant_and_user("Capability Tool Attach")

    capability = create_capability(
        tenant.id,
        "Marketing",
        f"marketing-{uuid4().hex[:8]}",
    )

    tool = create_tool(
        tenant.id,
        "Web Search",
        f"web-search-{uuid4().hex[:8]}",
    )

    response = client.post(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user.id)},
        json={
            "tool_id": str(tool.id),
            "config": {"enabled": True},
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["capability_id"] == str(capability.id)
    assert data["tool_id"] == str(tool.id)
    assert data["tenant_id"] == str(tenant.id)
    assert data["config"] == {"enabled": True}


def test_list_capability_tools():
    tenant, user = create_tenant_and_user("Capability Tool List")

    capability = create_capability(
        tenant.id,
        "Sales",
        f"sales-{uuid4().hex[:8]}",
    )

    tool = create_tool(
        tenant.id,
        "CRM Tool",
        f"crm-{uuid4().hex[:8]}",
    )

    attach_response = client.post(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user.id)},
        json={"tool_id": str(tool.id)},
    )

    assert attach_response.status_code == 201

    response = client.get(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == str(tool.id)
    assert data["items"][0]["name"] == tool.name


def test_global_tool_can_be_attached():
    tenant, user = create_tenant_and_user("Global Tool")

    capability = create_capability(
        tenant.id,
        "Research",
        f"research-{uuid4().hex[:8]}",
    )

    tool = create_global_tool(
        "Global Search",
        f"global-search-{uuid4().hex[:8]}",
    )

    response = client.post(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user.id)},
        json={"tool_id": str(tool.id)},
    )

    assert response.status_code == 201

    list_response = client.get(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user.id)},
    )

    assert list_response.status_code == 200

    items = list_response.json()["items"]

    assert len(items) == 1
    assert items[0]["id"] == str(tool.id)
    assert items[0]["scope"] == "global"


def test_tool_from_another_tenant_is_rejected():
    tenant_a, user_a = create_tenant_and_user("Tenant A")
    tenant_b, user_b = create_tenant_and_user("Tenant B")

    capability = create_capability(
        tenant_a.id,
        "Marketing",
        f"marketing-a-{uuid4().hex[:8]}",
    )

    tool = create_tool(
        tenant_b.id,
        "Private Tool",
        f"private-tool-b-{uuid4().hex[:8]}",
    )

    response = client.post(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user_a.id)},
        json={"tool_id": str(tool.id)},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Tool not found"


def test_capability_from_another_tenant_is_rejected():
    tenant_a, user_a = create_tenant_and_user("Capability Tenant A")
    tenant_b, _ = create_tenant_and_user("Capability Tenant B")

    capability = create_capability(
        tenant_b.id,
        "Private Capability",
        f"private-capability-{uuid4().hex[:8]}",
    )

    tool = create_tool(
        tenant_a.id,
        "Tenant A Tool",
        f"tenant-a-tool-{uuid4().hex[:8]}",
    )

    response = client.post(
        f"/api/v1/capabilities/{capability.id}/tools",
        headers={"X-User-ID": str(user_a.id)},
        json={"tool_id": str(tool.id)},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Capability not found"


def test_duplicate_tool_attachment_is_rejected():
    tenant, user = create_tenant_and_user("Duplicate Attachment")

    capability = create_capability(
        tenant.id,
        "Operations",
        f"operations-{uuid4().hex[:8]}",
    )

    tool = create_tool(
        tenant.id,
        "Operations Tool",
        f"operations-tool-{uuid4().hex[:8]}",
    )

    url = f"/api/v1/capabilities/{capability.id}/tools"
    headers = {"X-User-ID": str(user.id)}

    first = client.post(
        url,
        headers=headers,
        json={"tool_id": str(tool.id)},
    )

    assert first.status_code == 201

    second = client.post(
        url,
        headers=headers,
        json={"tool_id": str(tool.id)},
    )

    assert second.status_code == 400
    assert (
        second.json()["detail"]
        == "Tool is already attached to this capability"
    )


def test_detach_tool():
    tenant, user = create_tenant_and_user("Detach Tool")

    capability = create_capability(
        tenant.id,
        "Content",
        f"content-{uuid4().hex[:8]}",
    )

    tool = create_tool(
        tenant.id,
        "Content Tool",
        f"content-tool-{uuid4().hex[:8]}",
    )

    url = f"/api/v1/capabilities/{capability.id}/tools"
    headers = {"X-User-ID": str(user.id)}

    attach = client.post(
        url,
        headers=headers,
        json={"tool_id": str(tool.id)},
    )

    assert attach.status_code == 201

    delete_response = client.delete(
        f"{url}/{tool.id}",
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


def test_capability_tool_requires_authentication():
    capability_id = uuid4()

    response = client.get(
        f"/api/v1/capabilities/{capability_id}/tools",
    )

    assert response.status_code == 401
