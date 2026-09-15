from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import ActionPolicy, User
from packages.services.action_policy_service import ActionPolicyService


router = APIRouter(
    prefix="/action-policies",
    tags=["action-policies"],
)


class ActionPolicyCreateRequest(BaseModel):
    action: str = Field(min_length=1)
    resource: str | None = None
    requires_approval: bool = False
    approval_for: str | None = None
    conditions: dict = Field(default_factory=dict)
    is_active: bool = True


class ActionPolicyUpdateRequest(BaseModel):
    action: str | None = Field(default=None, min_length=1)
    resource: str | None = None
    requires_approval: bool | None = None
    approval_for: str | None = None
    conditions: dict | None = None
    is_active: bool | None = None


def serialize_action_policy(
    policy: ActionPolicy,
) -> dict:
    return {
        "id": str(policy.id),
        "tenant_id": (
            str(policy.tenant_id)
            if policy.tenant_id is not None
            else None
        ),
        "action": policy.action,
        "resource": policy.resource,
        "requires_approval": policy.requires_approval,
        "approval_for": policy.approval_for,
        "conditions": policy.conditions,
        "is_active": policy.is_active,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


@router.get("")
def list_action_policies(
    action: str | None = None,
    resource: str | None = None,
    active_only: bool = True,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ActionPolicyService(db)

    policies = service.list_policies(
        tenant_id=current_user.tenant_id,
        action=action,
        resource=resource,
        active_only=active_only,
    )

    return {
        "items": [
            serialize_action_policy(policy)
            for policy in policies
        ]
    }


@router.get("/{policy_id}")
def get_action_policy(
    policy_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ActionPolicyService(db)

    policy = service.get_policy(
        tenant_id=current_user.tenant_id,
        policy_id=policy_id,
    )

    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action policy not found",
        )

    return serialize_action_policy(policy)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def create_action_policy(
    payload: ActionPolicyCreateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ActionPolicyService(db)

    try:
        policy = service.create_policy(
            tenant_id=current_user.tenant_id,
            action=payload.action,
            resource=payload.resource,
            requires_approval=payload.requires_approval,
            approval_for=payload.approval_for,
            conditions=payload.conditions,
            is_active=payload.is_active,
        )

        db.commit()

        return serialize_action_policy(policy)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.patch("/{policy_id}")
def update_action_policy(
    policy_id: UUID,
    payload: ActionPolicyUpdateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ActionPolicyService(db)

    try:
        policy = service.update_policy(
            tenant_id=current_user.tenant_id,
            policy_id=policy_id,
            action=payload.action,
            resource=payload.resource,
            requires_approval=payload.requires_approval,
            approval_for=payload.approval_for,
            conditions=payload.conditions,
            is_active=payload.is_active,
        )

        db.commit()

        return serialize_action_policy(policy)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if str(exc) == "Action policy not found"
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=str(exc),
        )


@router.delete("/{policy_id}")
def delete_action_policy(
    policy_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ActionPolicyService(db)

    try:
        service.delete_policy(
            tenant_id=current_user.tenant_id,
            policy_id=policy_id,
        )

        db.commit()

        return {
            "status": "ok",
            "message": "Action policy deleted",
        }

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
