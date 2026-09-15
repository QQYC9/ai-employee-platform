from uuid import uuid4

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Tool, User
from packages.models.tenant import Tenant


client = TestClient(app)


def create_test_user(name: str = "Tool Test"):
    db = SessionLocal()

    try:
        tenant = Tenant(
            name=f"{name} Tenant",
            slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
            status="active",
        )

        db.add(tenant)
        db.flush()

        user = User(
            tenant_id=tenant.id,
            name=name,
            email=f"{uuid4().hex}@example.com",
            role="owner",
            status="active",
        )

        db.add(user)
        db.commit()

        db.refresh(tenant)
        db.refresh(user)

        return tenant, user

    finally:
        db.close()


def test_create_tool():
    tenant, user = create_test_user("Tool Create")

    response = client.post(
        "/api/v1/tools",
        headers={
            "X-User-ID": str(user.id),
        },
        json={
            "name": "Web Search",
            "slug": "web-search",
            "tool_type": "search",
            "description": "Search the web",
            "config": {
                "provider": "test",
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "Web Search"
    assert data["slug"] == "web-search"
    assert data["tool_type"] == "search"
    assert data["tenant_id"] == str(tenant.id)
    assert data["scope"] == "tenant"
    assert data["is_active"] is True


def test_list_tools_is_tenant_scoped():
    tenant_one, user_one = create_test_user("Tool Tenant One")
    tenant_two, _ = create_test_user("Tool Tenant Two")

    db = SessionLocal()

    try:
        tool_one = Tool(
            tenant_id=tenant_one.id,
            name="Tool One",
            slug=f"tool-one-{uuid4().hex[:8]}",
            description="Tenant one tool",
            tool_type="test",
            config={},
            is_active=True,
        )

        tool_two = Tool(
            tenant_id=tenant_two.id,
            name="Tool Two",
            slug=f"tool-two-{uuid4().hex[:8]}",
            description="Tenant two tool",
            tool_type="test",
            config={},
            is_active=True,
        )

        db.add_all([tool_one, tool_two])
        db.commit()

    finally:
        db.close()

    response = client.get(
        "/api/v1/tools",
        headers={
            "X-User-ID": str(user_one.id),
        },
    )

    assert response.status_code == 200

    items = response.json()["items"]

    assert any(
        item["name"] == "Tool One"
        for item in items
    )

    assert not any(
        item["name"] == "Tool Two"
        for item in items
    )


def test_global_tool_is_visible_to_tenant():
    _, user = create_test_user("Global Tool Visibility")

    db = SessionLocal()

    try:
        global_tool = Tool(
            tenant_id=None,
            name="Global Search",
            slug=f"global-search-{uuid4().hex[:8]}",
            description="Global search tool",
            tool_type="search",
            config={},
            is_active=True,
        )

        db.add(global_tool)
        db.commit()

        slug = global_tool.slug

    finally:
        db.close()

    response = client.get(
        "/api/v1/tools",
        headers={
            "X-User-ID": str(user.id),
        },
    )

    assert response.status_code == 200

    items = response.json()["items"]

    assert any(
        item["slug"] == slug
        and item["scope"] == "global"
        for item in items
    )


def test_tool_requires_authentication():
    response = client.get("/api/v1/tools")

    assert response.status_code == 401
