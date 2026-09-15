from uuid import uuid4

import pytest

from packages.core.database import SessionLocal
from packages.models.domain import User
from packages.models.tenant import Tenant
from packages.services.approval_service import ApprovalService


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


def create_tenant(
    name: str,
) -> Tenant:
    tenant, _ = create_tenant_and_user(name)
    return tenant


def test_create_approval():
    tenant = create_tenant(
        "Approval Create"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    approval = service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="send_customer_message",
        description="Agent wants to send a message to a customer.",
    )

    db.commit()

    assert approval.id is not None
    assert approval.tenant_id == tenant.id
    assert approval.requested_for == "tenant_owner"
    assert approval.action == "send_customer_message"
    assert approval.status == "pending"

    db.close()


def test_get_approval_is_tenant_scoped():
    tenant_a = create_tenant(
        "Approval Tenant A"
    )
    tenant_b = create_tenant(
        "Approval Tenant B"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    approval = service.create_approval(
        tenant_id=tenant_a.id,
        requested_for="tenant_owner",
        action="publish_content",
        description="Publish prepared content.",
    )

    db.commit()

    assert service.get_approval(
        tenant_id=tenant_a.id,
        approval_id=approval.id,
    ) is not None

    assert service.get_approval(
        tenant_id=tenant_b.id,
        approval_id=approval.id,
    ) is None

    db.close()


def test_list_approvals_filters_by_status():
    tenant, user = create_tenant_and_user(
        "Approval List"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    pending = service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="send_email",
        description="Send customer email.",
    )

    approved = service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="publish_content",
        description="Publish content.",
    )

    db.commit()

    service.approve(
        tenant_id=tenant.id,
        approval_id=approved.id,
        decision_by_user_id=user.id,
    )

    db.commit()

    approvals = service.list_approvals(
        tenant_id=tenant.id,
    )

    assert len(approvals) == 2

    pending_only = service.list_approvals(
        tenant_id=tenant.id,
        status="pending",
    )

    assert len(pending_only) == 1
    assert pending_only[0].id == pending.id

    approved_only = service.list_approvals(
        tenant_id=tenant.id,
        status="approved",
    )

    assert len(approved_only) == 1
    assert approved_only[0].id == approved.id

    db.close()


def test_approve_approval():
    tenant, user = create_tenant_and_user(
        "Approval Approve"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    approval = service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="send_customer_message",
        description="Send a message.",
    )

    db.commit()

    result = service.approve(
        tenant_id=tenant.id,
        approval_id=approval.id,
        decision_by_user_id=user.id,
        reason="Approved by business owner.",
    )

    db.commit()

    assert result.status == "approved"
    assert result.decision_by_user_id == user.id
    assert result.reason == "Approved by business owner."

    db.close()


def test_reject_approval():
    tenant, user = create_tenant_and_user(
        "Approval Reject"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    approval = service.create_approval(
        tenant_id=tenant.id,
        requested_for="platform_admin",
        action="install_integration",
        description="Agent requires a new integration.",
    )

    db.commit()

    result = service.reject(
        tenant_id=tenant.id,
        approval_id=approval.id,
        decision_by_user_id=user.id,
        reason="Integration is not authorized.",
    )

    db.commit()

    assert result.status == "rejected"
    assert result.decision_by_user_id == user.id
    assert result.reason == "Integration is not authorized."

    db.close()


def test_cancel_approval():
    tenant = create_tenant(
        "Approval Cancel"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    approval = service.create_approval(
        tenant_id=tenant.id,
        requested_for="platform_admin",
        action="request_subscription",
        description="Agent requests a subscription.",
    )

    db.commit()

    result = service.cancel(
        tenant_id=tenant.id,
        approval_id=approval.id,
    )

    db.commit()

    assert result.status == "cancelled"

    db.close()


def test_completed_approval_cannot_be_changed():
    tenant, user = create_tenant_and_user(
        "Approval Completed"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    approval = service.create_approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="publish_content",
        description="Publish content.",
    )

    db.commit()

    service.approve(
        tenant_id=tenant.id,
        approval_id=approval.id,
        decision_by_user_id=user.id,
    )

    db.commit()

    with pytest.raises(
        ValueError,
        match="Only pending approvals",
    ):
        service.reject(
            tenant_id=tenant.id,
            approval_id=approval.id,
            decision_by_user_id=user.id,
        )

    db.close()


def test_invalid_status_is_rejected():
    tenant = create_tenant(
        "Approval Invalid Status"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    with pytest.raises(
        ValueError,
        match="Invalid approval status",
    ):
        service.list_approvals(
            tenant_id=tenant.id,
            status="invalid",
        )

    db.close()


def test_empty_approval_fields_are_rejected():
    tenant = create_tenant(
        "Approval Empty Fields"
    )

    db = SessionLocal()

    service = ApprovalService(db)

    with pytest.raises(
        ValueError,
        match="Approval requested_for cannot be empty",
    ):
        service.create_approval(
            tenant_id=tenant.id,
            requested_for="   ",
            action="test",
            description="test",
        )

    with pytest.raises(
        ValueError,
        match="Approval action cannot be empty",
    ):
        service.create_approval(
            tenant_id=tenant.id,
            requested_for="tenant_owner",
            action="   ",
            description="test",
        )

    with pytest.raises(
        ValueError,
        match="Approval description cannot be empty",
    ):
        service.create_approval(
            tenant_id=tenant.id,
            requested_for="tenant_owner",
            action="test",
            description="   ",
        )

    db.close()
