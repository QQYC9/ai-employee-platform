import uuid

import pytest

from packages.models.tenant import Tenant
from packages.services.decision_engine import DecisionEngine
from tests.test_action_policy_service import db


@pytest.fixture
def tenant(db):
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Decision Test Tenant",
        slug=f"decision-{uuid.uuid4().hex[:8]}",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@pytest.fixture
def engine(db):
    return DecisionEngine(db)


def test_decision_denies_without_permission(engine, tenant):
    result = engine.decide(
        tenant_id=tenant.id,
        action="send_email",
        resource="email",
    )

    assert result.decision == "DENY"
    assert result.requires_approval is False


def test_decision_allows_permitted_action_without_policy(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission

    permission = Permission(
        tenant_id=tenant.id,
        action="read_customer",
        resource="customer",
        effect="allow",
    )

    db.add(permission)
    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="read_customer",
        resource="customer",
    )

    assert result.decision == "ALLOW"
    assert result.requires_approval is False


def test_decision_requires_approval_when_policy_requires_it(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission, ActionPolicy

    permission = Permission(
        tenant_id=tenant.id,
        action="send_customer_message",
        resource="customer_message",
        effect="allow",
    )

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="send_customer_message",
        resource="customer_message",
        requires_approval=True,
        approval_for="tenant_owner",
    )

    db.add(permission)
    db.add(policy)
    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="send_customer_message",
        resource="customer_message",
    )

    assert result.decision == "APPROVAL_REQUIRED"
    assert result.requires_approval is True
    assert result.approval_for == "tenant_owner"


def test_decision_allows_when_policy_explicitly_does_not_require_approval(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission, ActionPolicy

    permission = Permission(
        tenant_id=tenant.id,
        action="create_content",
        resource="content",
        effect="allow",
    )

    policy = ActionPolicy(
        tenant_id=tenant.id,
        action="create_content",
        resource="content",
        requires_approval=False,
    )

    db.add(permission)
    db.add(policy)
    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="create_content",
        resource="content",
    )

    assert result.decision == "ALLOW"
    assert result.requires_approval is False
def test_explicit_deny_overrides_allow(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="delete_customer",
            resource="customer",
            effect="allow",
        )
    )

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="delete_customer",
            resource="customer",
            effect="deny",
        )
    )

    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="delete_customer",
        resource="customer",
    )

    assert result.decision == "DENY"


def test_agent_specific_permission_does_not_apply_to_other_agent(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Agent, Permission

    agent_a = Agent(
        tenant_id=tenant.id,
        name="Agent A",
        agent_type="digital_employee",
    )

    agent_b = Agent(
        tenant_id=tenant.id,
        name="Agent B",
        agent_type="digital_employee",
    )

    db.add_all([agent_a, agent_b])
    db.flush()

    db.add(
        Permission(
            tenant_id=tenant.id,
            agent_id=agent_a.id,
            action="send_email",
            resource="email",
            effect="allow",
        )
    )

    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        agent_id=agent_b.id,
        action="send_email",
        resource="email",
    )

    assert result.decision == "DENY"


def test_permission_from_another_tenant_does_not_apply(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission

    other_tenant = Tenant(
        id=uuid.uuid4(),
        name="Other Tenant",
        slug=f"other-{uuid.uuid4().hex[:8]}",
    )

    db.add(other_tenant)
    db.flush()

    db.add(
        Permission(
            tenant_id=other_tenant.id,
            action="refund_order",
            resource="order",
            effect="allow",
        )
    )

    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="refund_order",
        resource="order",
    )

    assert result.decision == "DENY"


def test_action_policy_for_different_resource_does_not_apply(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission, ActionPolicy

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="publish",
            resource="content",
            effect="allow",
        )
    )

    db.add(
        ActionPolicy(
            tenant_id=tenant.id,
            action="publish",
            resource="website",
            requires_approval=True,
            approval_for="tenant_owner",
        )
    )

    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="publish",
        resource="content",
    )

    assert result.decision == "ALLOW"
    assert result.requires_approval is False
def test_decision_engine_creates_pending_approval(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission, ActionPolicy

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="send_invoice",
            resource="invoice",
            effect="allow",
        )
    )

    db.add(
        ActionPolicy(
            tenant_id=tenant.id,
            action="send_invoice",
            resource="invoice",
            requires_approval=True,
            approval_for="tenant_owner",
        )
    )

    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="send_invoice",
        resource="invoice",
    )

    assert result.decision == "APPROVAL_REQUIRED"
    assert result.requires_approval is True


def test_decision_engine_does_not_create_approval_for_allow(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="create_draft",
            resource="content",
            effect="allow",
        )
    )

    db.commit()

    result = engine.decide(
        tenant_id=tenant.id,
        action="create_draft",
        resource="content",
    )

    assert result.decision == "ALLOW"
    assert result.requires_approval is False
def test_request_approval_creates_pending_approval(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission, ActionPolicy

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="send_invoice",
            resource="invoice",
            effect="allow",
        )
    )

    db.add(
        ActionPolicy(
            tenant_id=tenant.id,
            action="send_invoice",
            resource="invoice",
            requires_approval=True,
            approval_for="tenant_owner",
        )
    )

    db.commit()

    approval = engine.request_approval(
        tenant_id=tenant.id,
        action="send_invoice",
        resource="invoice",
        description="Send invoice to customer",
        requested_for="tenant_owner",
    )

    assert approval.tenant_id == tenant.id
    assert approval.action == "send_invoice"
    assert approval.description == "Send invoice to customer"
    assert approval.requested_for == "tenant_owner"
    assert approval.status == "pending"


def test_request_approval_rejects_action_without_approval_requirement(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Permission

    db.add(
        Permission(
            tenant_id=tenant.id,
            action="create_draft",
            resource="content",
            effect="allow",
        )
    )

    db.commit()

    with pytest.raises(
        ValueError,
        match="Approval is not required",
    ):
        engine.request_approval(
            tenant_id=tenant.id,
            action="create_draft",
            resource="content",
            description="Create content draft",
            requested_for="tenant_owner",
        )
def test_request_approval_rejects_denied_action(
    db,
    engine,
    tenant,
):
    from packages.models.domain import Approval

    with pytest.raises(
        ValueError,
        match="Approval is not required",
    ):
        engine.request_approval(
            tenant_id=tenant.id,
            action="delete_everything",
            resource="system",
            description="Dangerous action",
            requested_for="tenant_owner",
        )

    approvals = list(
        db.query(Approval)
        .filter(Approval.tenant_id == tenant.id)
        .all()
    )

    assert approvals == []
