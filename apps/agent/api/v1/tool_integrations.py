from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import Integration, User
from packages.services.tool_integration_service import ToolIntegrationService


router = APIRouter(
    prefix="/tools",
    tags=["tool-integrations"],
)


class ToolIntegrationCreateRequest(BaseModel):
    integration_id: UUID
    config: dict = Field(default_factory=dict)


def serialize_integration(integration: Integration) -> dict:
    return {
        "id": str(integration.id),
        "tenant_id": (
            str(integration.tenant_id)
            if integration.tenant_id is not None
            else None
        ),
        "name": integration.name,
        "provider": integration.provider,
        "status": integration.status,
        "config": integration.config,
        "scope": (
            "global"
            if integration.tenant_id is None
            else "tenant"
        ),
        "created_at": integration.created_at.isoformat(),
        "updated_at": integration.updated_at.isoformat(),
    }


@router.get("/{tool_id}/integrations")
def list_tool_integrations(
    tool_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolIntegrationService(db)

    try:
        integrations = service.list_integrations(
            tenant_id=current_user.tenant_id,
            tool_id=tool_id,
        )

        return {
            "items": [
                serialize_integration(integration)
                for integration in integrations
            ]
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.post(
    "/{tool_id}/integrations",
    status_code=status.HTTP_201_CREATED,
)
def attach_integration(
    tool_id: UUID,
    payload: ToolIntegrationCreateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolIntegrationService(db)

    try:
        assignment = service.attach_integration(
            tenant_id=current_user.tenant_id,
            tool_id=tool_id,
            integration_id=payload.integration_id,
            config=payload.config,
        )

        db.commit()

        return {
            "id": str(assignment.integration_id),
            "tool_id": str(assignment.tool_id),
            "integration_id": str(assignment.integration_id),
            "tenant_id": str(assignment.tenant_id),
            "config": assignment.config,
        }

    except ValueError as exc:
        db.rollback()

        detail = str(exc)

        if detail in {
            "Tool not found",
            "Integration not found",
        }:
            code = status.HTTP_404_NOT_FOUND
        else:
            code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code=code,
            detail=detail,
        )


@router.delete(
    "/{tool_id}/integrations/{integration_id}",
)
def detach_integration(
    tool_id: UUID,
    integration_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolIntegrationService(db)

    try:
        service.detach_integration(
            tenant_id=current_user.tenant_id,
            tool_id=tool_id,
            integration_id=integration_id,
        )

        db.commit()

        return {
            "status": "ok",
            "message": "Integration detached from tool",
        }

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
