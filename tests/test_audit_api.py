from uuid import uuid4

from apps.agent.main import app
from fastapi.testclient import TestClient
from packages.core.database import SessionLocal
from packages.models.domain import AuditEvent, User
from packages.models.tenant import Tenant


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


def create_audit_event(
    tenant_id,
) -> AuditEvent:
    db = SessionLocal()

    event = AuditEvent(
        tenant_id=tenant_id,
        event_type="tool_execution",
        action="run_tool",
        description="Test tool execution",
        event_metadata={
            "tool_slug": "test_tool",
            "status": "executed",
        },
    )

    db.add(event)
    db.commit()
    db.refresh(event)
    db.close()

    return event


def test_audit_requires_authentication():
    response = client.get(
        "/api/v1/audit",
    )

    assert response.status_code == 401


def test_list_audit_events():
    tenant, user = create_tenant_and_user(
        "Audit API List"
    )

    event = create_audit_event(tenant.id)

    response = client.get(
        "/api/v1/audit",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    items = response.json()

    assert len(items) == 1
    assert items[0]["id"] == str(event.id)
    assert items[0]["tenant_id"] == str(tenant.id)
    assert items[0]["event_type"] == "tool_execution"
    assert items[0]["action"] == "run_tool"
    assert items[0]["event_metadata"]["tool_slug"] == "test_tool"


def test_audit_cannot_cross_tenants():
    tenant_a, user_a = create_tenant_and_user(
        "Audit API Tenant A"
    )

    _, user_b = create_tenant_and_user(
        "Audit API Tenant B"
    )

    event = create_audit_event(tenant_a.id)

    response = client.get(
        f"/api/v1/audit/{event.id}",
        headers={"X-User-ID": str(user_b.id)},
    )

    assert response.status_code == 404


def test_get_audit_event():
    tenant, user = create_tenant_and_user(
        "Audit API Get"
    )

    event = create_audit_event(tenant.id)

    response = client.get(
        f"/api/v1/audit/{event.id}",
        headers={"X-User-ID": str(user.id)},
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == str(event.id)
    assert data["tenant_id"] == str(tenant.id)
    assert data["event_type"] == "tool_execution"
    assert data["action"] == "run_tool"
    assert data["description"] == "Test tool execution"
