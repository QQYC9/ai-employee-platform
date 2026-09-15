from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_db
from packages.auth.context import get_tenant_context
from packages.models.domain import Approval, User
from packages.services.approval_service import ApprovalService


router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
)


class ApprovalCreateRequest(BaseModel):
    requested_for: str = Field(min_length=1)
    action: str = Field(min_length=1)
    description: str = Field(min_length=1)
    task_id: UUID | None = None
    requested_by_agent_id: UUID | None = None


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = None


def approval_response(approval: Approval) -> dict:
    return {
        "id": str(approval.id),
        "tenant_id": str(approval.tenant_id),
        "task_id": (
            str(approval.task_id)
            if approval.task_id is not None
            else None
        ),
        "requested_by_agent_id": (
            str(approval.requested_by_agent_id)
            if approval.requested_by_agent_id is not None
            else None
        ),
        "requested_for": approval.requested_for,
        "action": approval.action,
        "description": approval.description,
        "status": approval.status,
        "decision_by_user_id": (
            str(approval.decision_by_user_id)
            if approval.decision_by_user_id is not None
            else None
        ),
        "reason": approval.reason,
        "created_at": approval.created_at,
        "updated_at": approval.updated_at,
    }


@router.get("")
def list_approvals(
    status: str | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ApprovalService(db)

    try:
        approvals = service.list_approvals(
            tenant_id=current_user.tenant_id,
            status=status,
            task_id=task_id,
            agent_id=agent_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return [
        approval_response(approval)
        for approval in approvals
    ]


@router.get("/{approval_id}")
def get_approval(
    approval_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ApprovalService(db)

    approval = service.get_approval(
        tenant_id=current_user.tenant_id,
        approval_id=approval_id,
    )

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail="Approval not found",
        )

    return approval_response(approval)


@router.post("", status_code=201)
def create_approval(
    payload: ApprovalCreateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ApprovalService(db)

    try:
        approval = service.create_approval(
            tenant_id=current_user.tenant_id,
            requested_for=payload.requested_for,
            action=payload.action,
            description=payload.description,
            task_id=payload.task_id,
            requested_by_agent_id=payload.requested_by_agent_id,
        )

        db.commit()
        db.refresh(approval)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return approval_response(approval)


@router.post("/{approval_id}/approve")
def approve_approval(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ApprovalService(db)

    try:
        approval = service.approve(
            tenant_id=current_user.tenant_id,
            approval_id=approval_id,
            decision_by_user_id=current_user.id,
            reason=payload.reason,
        )

        db.commit()
        db.refresh(approval)

    except ValueError as exc:
        db.rollback()

        status_code = (
            404
            if str(exc) == "Approval not found"
            else 400
        )

        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        )

    return approval_response(approval)


@router.post("/{approval_id}/reject")
def reject_approval(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ApprovalService(db)

    try:
        approval = service.reject(
            tenant_id=current_user.tenant_id,
            approval_id=approval_id,
            decision_by_user_id=current_user.id,
            reason=payload.reason,
        )

        db.commit()
        db.refresh(approval)

    except ValueError as exc:
        db.rollback()

        status_code = (
            404
            if str(exc) == "Approval not found"
            else 400
        )

        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        )

    return approval_response(approval)


@router.post("/{approval_id}/cancel")
def cancel_approval(
    approval_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ApprovalService(db)

    try:
        approval = service.cancel(
            tenant_id=current_user.tenant_id,
            approval_id=approval_id,
        )

        db.commit()
        db.refresh(approval)

    except ValueError as exc:
        db.rollback()

        status_code = (
            404
            if str(exc) == "Approval not found"
            else 400
        )

        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        )

    return approval_response(approval)
