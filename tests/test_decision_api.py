from uuid import uuid4

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Permission, ActionPolicy, User
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


def test_decision_check_requires_authentication():
    response = client.post(
        "/api/v1/decision/check",
        json={
            "action": "send_message",
            "resource": "customer",
        },
    )

    assert response.status_code == 401


def test_decision_check_rejects_missing_action():
    _, user = create_tenant_and_user(
        "Decision API Validation"
    )

    response = client.post(
        "/api/v1/decision/check",
        headers={"X-User-ID": str(user.id)},
        json={
            "resource": "customer",
        },
    )

    assert response.status_code == 422


def test_decision_check_returns_deny():
    _, user = create_tenant_and_user(
        "Decision API Deny"
    )

    response = client.post(
        "/api/v1/decision/check",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "delete_customer",
            "resource": "customer",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["decision"] == "DENY"
    assert data["requires_approval"] is False


def test_decision_check_returns_allow():
    tenant, user = create_tenant_and_user(
        "Decision API Allow"
    )

    db = SessionLocal()

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="read_customer",
            resource="customer",
            effect="allow",
        )
    )

    db.commit()
    db.close()

    response = client.post(
        "/api/v1/decision/check",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "read_customer",
            "resource": "customer",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["decision"] == "ALLOW"
    assert data["requires_approval"] is False


def test_decision_check_returns_approval_required():
    tenant, user = create_tenant_and_user(
        "Decision API Approval"
    )

    db = SessionLocal()

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="send_customer_message",
            resource="customer_message",
            effect="allow",
        )
    )

    db.add(
        ActionPolicy(
            tenant_id=tenant.id,
            action="send_customer_message",
            resource="customer_message",
            requires_approval=True,
            approval_for="tenant_owner",
        )
    )

    db.commit()
    db.close()

    response = client.post(
        "/api/v1/decision/check",
        headers={"X-User-ID": str(user.id)},
        json={
            "action": "send_customer_message",
            "resource": "customer_message",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["decision"] == "APPROVAL_REQUIRED"
    assert data["requires_approval"] is True
    assert data["approval_for"] == "tenant_owner"
