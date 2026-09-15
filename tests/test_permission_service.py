from uuid import uuid4

import pytest

from packages.core.database import SessionLocal
from packages.models.domain import Agent, Permission, User
from packages.models.tenant import Tenant
from packages.services.permission_service import PermissionService


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


def test_create_permission():
    tenant, _ = create_tenant_and_user(
        "Permission Create"
    )

    db = SessionLocal()

    service = PermissionService(db)

    permission = service.create_permission(
        tenant_id=tenant.id,
        action="send_message",
        resource="customer",
        effect="allow",
        conditions={"channel": "whatsapp"},
    )

    db.commit()

    assert permission.id is not None
    assert permission.tenant_id == tenant.id
    assert permission.action == "send_message"
    assert permission.resource == "customer"
    assert permission.effect == "allow"
    assert permission.conditions == {
        "channel": "whatsapp"
    }

    db.close()


def test_create_deny_permission():
    tenant, _ = create_tenant_and_user(
        "Permission Deny"
    )

    db = SessionLocal()

    service = PermissionService(db)

    permission = service.create_permission(
        tenant_id=tenant.id,
        action="delete_customer",
        resource="customer",
        effect="deny",
    )

    db.commit()

    assert permission.effect == "deny"

    db.close()


def test_empty_action_is_rejected():
    tenant, _ = create_tenant_and_user(
        "Empty Action"
    )

    db = SessionLocal()

    service = PermissionService(db)

    with pytest.raises(
        ValueError,
        match="Permission action cannot be empty",
    ):
        service.create_permission(
            tenant_id=tenant.id,
            action="   ",
            resource="customer",
        )

    db.close()


def test_empty_resource_is_rejected():
    tenant, _ = create_tenant_and_user(
        "Empty Resource"
    )

    db = SessionLocal()

    service = PermissionService(db)

    with pytest.raises(
        ValueError,
        match="Permission resource cannot be empty",
    ):
        service.create_permission(
            tenant_id=tenant.id,
            action="send_message",
            resource="   ",
        )

    db.close()


def test_invalid_effect_is_rejected():
    tenant, _ = create_tenant_and_user(
        "Invalid Effect"
    )

    db = SessionLocal()

    service = PermissionService(db)

    with pytest.raises(
        ValueError,
        match="Permission effect must be allow or deny",
    ):
        service.create_permission(
            tenant_id=tenant.id,
            action="send_message",
            resource="customer",
            effect="maybe",
        )

    db.close()


def test_duplicate_permission_is_rejected():
    tenant, _ = create_tenant_and_user(
        "Duplicate Permission"
    )

    db = SessionLocal()

    service = PermissionService(db)

    service.create_permission(
        tenant_id=tenant.id,
        action="send_message",
        resource="customer",
    )

    with pytest.raises(
        ValueError,
        match="Permission already exists",
    ):
        service.create_permission(
            tenant_id=tenant.id,
            action="send_message",
            resource="customer",
        )

    db.rollback()
    db.close()


def test_is_allowed_returns_false_when_no_permission_exists():
    tenant, _ = create_tenant_and_user(
        "No Permission"
    )

    db = SessionLocal()

    service = PermissionService(db)

    assert (
        service.is_allowed(
            tenant_id=tenant.id,
            action="send_message",
            resource="customer",
        )
        is False
    )

    db.close()


def test_is_allowed_returns_true_for_allow_permission():
    tenant, _ = create_tenant_and_user(
        "Allowed Permission"
    )

    db = SessionLocal()

    service = PermissionService(db)

    service.create_permission(
        tenant_id=tenant.id,
        action="send_message",
        resource="customer",
        effect="allow",
    )

    db.commit()

    assert (
        service.is_allowed(
            tenant_id=tenant.id,
            action="send_message",
            resource="customer",
        )
        is True
    )

    db.close()


def test_deny_overrides_allow():
    tenant, _ = create_tenant_and_user(
        "Deny Override"
    )

    db = SessionLocal()

    service = PermissionService(db)

    service.create_permission(
        tenant_id=tenant.id,
        action="send_message",
        resource="customer",
        effect="allow",
    )

    permission = Permission(
        tenant_id=tenant.id,
        agent_id=None,
        action="send_message",
        resource="customer",
        effect="deny",
        conditions={},
    )
    db.add(permission)
    db.commit()

    assert (
        service.is_allowed(
            tenant_id=tenant.id,
            action="send_message",
            resource="customer",
        )
        is False
    )

    db.close()


def test_agent_specific_permission():
    tenant, _ = create_tenant_and_user(
        "Agent Permission"
    )

    agent = create_agent(
        tenant.id,
        "Sales Agent",
    )

    db = SessionLocal()

    service = PermissionService(db)

    service.create_permission(
        tenant_id=tenant.id,
        agent_id=agent.id,
        action="send_quote",
        resource="customer",
        effect="allow",
    )

    db.commit()

    assert (
        service.is_allowed(
            tenant_id=tenant.id,
            agent_id=agent.id,
            action="send_quote",
            resource="customer",
        )
        is True
    )

    assert (
        service.is_allowed(
            tenant_id=tenant.id,
            action="send_quote",
            resource="customer",
        )
        is False
    )

    db.close()


def test_permission_is_tenant_scoped():
    tenant_a, _ = create_tenant_and_user(
        "Permission Tenant A"
    )
    tenant_b, _ = create_tenant_and_user(
        "Permission Tenant B"
    )

    db = SessionLocal()

    service = PermissionService(db)

    permission = service.create_permission(
        tenant_id=tenant_a.id,
        action="send_message",
        resource="customer",
        effect="allow",
    )

    db.commit()

    assert (
        service.get_permission(
            tenant_id=tenant_a.id,
            permission_id=permission.id,
        )
        is not None
    )

    assert (
        service.get_permission(
            tenant_id=tenant_b.id,
            permission_id=permission.id,
        )
        is None
    )

    db.close()
