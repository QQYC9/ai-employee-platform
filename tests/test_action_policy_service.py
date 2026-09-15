from uuid import uuid4

import pytest

from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.services.action_policy_service import ActionPolicyService


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant_id(db):
    tenant = Tenant(
        name="Action Policy Test Tenant",
        slug=f"action-policy-test-{uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.flush()
    return tenant.id


def test_create_policy(db, tenant_id):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource="customer",
        requires_approval=True,
        approval_for="tenant_owner",
        conditions={"business_hours_only": True},
    )

    assert policy.id is not None
    assert policy.tenant_id == tenant_id
    assert policy.action == "send_email"
    assert policy.resource == "customer"
    assert policy.requires_approval is True
    assert policy.approval_for == "tenant_owner"
    assert policy.conditions == {"business_hours_only": True}
    assert policy.is_active is True


def test_create_policy_requires_approval_for_approver(db, tenant_id):
    service = ActionPolicyService(db)

    with pytest.raises(
        ValueError,
        match="approval_for is required",
    ):
        service.create_policy(
            tenant_id=tenant_id,
            action="send_email",
            requires_approval=True,
        )


def test_create_policy_rejects_invalid_approver(db, tenant_id):
    service = ActionPolicyService(db)

    with pytest.raises(
        ValueError,
        match="Invalid approval_for",
    ):
        service.create_policy(
            tenant_id=tenant_id,
            action="send_email",
            requires_approval=True,
            approval_for="unknown_role",
        )


def test_create_policy_rejects_empty_action(db, tenant_id):
    service = ActionPolicyService(db)

    with pytest.raises(
        ValueError,
        match="Action policy action cannot be empty",
    ):
        service.create_policy(
            tenant_id=tenant_id,
            action="   ",
        )


def test_get_policy(db, tenant_id):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=tenant_id,
        action="publish_post",
    )

    found = service.get_policy(
        tenant_id=tenant_id,
        policy_id=policy.id,
    )

    assert found is not None
    assert found.id == policy.id


def test_get_policy_does_not_cross_tenant(db, tenant_id):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=tenant_id,
        action="publish_post",
    )

    other_tenant = uuid4()

    found = service.get_policy(
        tenant_id=other_tenant,
        policy_id=policy.id,
    )

    assert found is None


def test_list_policies_includes_tenant_and_global(db, tenant_id):
    service = ActionPolicyService(db)

    tenant_policy = service.create_policy(
        tenant_id=tenant_id,
        action="send_email",
    )

    global_policy = service.create_policy(
        tenant_id=None,
        action="publish_post",
    )

    policies = service.list_policies(tenant_id)

    policy_ids = {policy.id for policy in policies}

    assert tenant_policy.id in policy_ids
    assert global_policy.id in policy_ids


def test_resolve_policy_prefers_tenant_exact_resource(db, tenant_id):
    service = ActionPolicyService(db)

    service.create_policy(
        tenant_id=None,
        action="send_email",
        resource=None,
    )

    service.create_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource=None,
    )

    exact = service.create_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource="customer",
    )

    resolved = service.resolve_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource="customer",
    )

    assert resolved is not None
    assert resolved.id == exact.id


def test_resolve_policy_prefers_tenant_generic_over_global(db, tenant_id):
    service = ActionPolicyService(db)

    service.create_policy(
        tenant_id=None,
        action="send_email",
        resource=None,
    )

    tenant_policy = service.create_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource=None,
    )

    resolved = service.resolve_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource="customer",
    )

    assert resolved is not None
    assert resolved.id == tenant_policy.id


def test_resolve_policy_uses_global_exact_resource(db, tenant_id):
    service = ActionPolicyService(db)

    global_policy = service.create_policy(
        tenant_id=None,
        action="send_email",
        resource="customer",
    )

    resolved = service.resolve_policy(
        tenant_id=tenant_id,
        action="send_email",
        resource="customer",
    )

    assert resolved is not None
    assert resolved.id == global_policy.id


def test_resolve_policy_returns_none_when_not_found(db, tenant_id):
    service = ActionPolicyService(db)

    resolved = service.resolve_policy(
        tenant_id=tenant_id,
        action="nonexistent_action",
    )

    assert resolved is None


def test_update_policy(db, tenant_id):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=tenant_id,
        action="send_email",
    )

    updated = service.update_policy(
        tenant_id=tenant_id,
        policy_id=policy.id,
        action="send_customer_email",
        resource="customer",
        requires_approval=True,
        approval_for="tenant_owner",
        conditions={"limit": 100},
        is_active=False,
    )

    assert updated.action == "send_customer_email"
    assert updated.resource == "customer"
    assert updated.requires_approval is True
    assert updated.approval_for == "tenant_owner"
    assert updated.conditions == {"limit": 100}
    assert updated.is_active is False


def test_global_policy_cannot_be_updated_by_tenant(db):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=None,
        action="send_email",
    )

    with pytest.raises(
        ValueError,
        match="Global action policies cannot be modified",
    ):
        service.update_policy(
            tenant_id=uuid4(),
            policy_id=policy.id,
            action="new_action",
        )


def test_delete_policy(db, tenant_id):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=tenant_id,
        action="delete_customer",
    )

    service.delete_policy(
        tenant_id=tenant_id,
        policy_id=policy.id,
    )

    assert service.get_policy(
        tenant_id=tenant_id,
        policy_id=policy.id,
    ) is None


def test_global_policy_cannot_be_deleted_by_tenant(db):
    service = ActionPolicyService(db)

    policy = service.create_policy(
        tenant_id=None,
        action="delete_customer",
    )

    with pytest.raises(
        ValueError,
        match="Global action policies cannot be deleted",
    ):
        service.delete_policy(
            tenant_id=uuid4(),
            policy_id=policy.id,
        )
