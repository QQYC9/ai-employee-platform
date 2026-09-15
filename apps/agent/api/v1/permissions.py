from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import Permission, User
from packages.services.permission_service import PermissionService


router = APIRouter(
    prefix="/permissions",
    tags=["permissions"],
)


class PermissionCreateRequest(BaseModel):
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    effect: str = "allow"
    agent_id: UUID | None = None
    conditions: dict = Field(default_factory=dict)


class PermissionUpdateRequest(BaseModel):
    effect: str | None = None
    conditions: dict | None = None


def serialize_permission(
    permission: Permission,
) -> dict:
    return {
        "id": str(permission.id),
        "tenant_id": str(permission.tenant_id),
        "agent_id": (
            str(permission.agent_id)
            if permission.agent_id is not None
            else None
        ),
        "action": permission.action,
        "resource": permission.resource,
        "effect": permission.effect,
        "conditions": permission.conditions,
        "created_at": permission.created_at.isoformat(),
    }


@router.get("")
def list_permissions(
    agent_id: UUID | None = None,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = PermissionService(db)

    permissions = service.list_permissions(
        tenant_id=current_user.tenant_id,
        agent_id=agent_id,
    )

    return {
        "items": [
            serialize_permission(permission)
            for permission in permissions
        ]
    }


@router.get("/{permission_id}")
def get_permission(
    permission_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = PermissionService(db)

    permission = service.get_permission(
        tenant_id=current_user.tenant_id,
        permission_id=permission_id,
    )

    if permission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Permission not found",
        )

    return serialize_permission(permission)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def create_permission(
    payload: PermissionCreateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = PermissionService(db)

    try:
        permission = service.create_permission(
            tenant_id=current_user.tenant_id,
            action=payload.action,
            resource=payload.resource,
            effect=payload.effect,
            agent_id=payload.agent_id,
            conditions=payload.conditions,
        )

        db.commit()

        return serialize_permission(permission)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.patch("/{permission_id}")
def update_permission(
    permission_id: UUID,
    payload: PermissionUpdateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = PermissionService(db)

    try:
        permission = service.update_permission(
            tenant_id=current_user.tenant_id,
            permission_id=permission_id,
            effect=payload.effect,
            conditions=payload.conditions,
        )

        db.commit()

        return serialize_permission(permission)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND
            if str(exc) == "Permission not found"
            else status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.delete("/{permission_id}")
def delete_permission(
    permission_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = PermissionService(db)

    try:
        service.delete_permission(
            tenant_id=current_user.tenant_id,
            permission_id=permission_id,
        )

        db.commit()

        return {
            "status": "ok",
            "message": "Permission deleted",
        }

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
