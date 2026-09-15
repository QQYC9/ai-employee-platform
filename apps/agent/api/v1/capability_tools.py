from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import Capability, Tool, User
from packages.services.capability_tool_service import CapabilityToolService


router = APIRouter(
    prefix="/capabilities",
    tags=["capability-tools"],
)


class CapabilityToolCreateRequest(BaseModel):
    tool_id: UUID
    config: dict = Field(default_factory=dict)


def serialize_tool(tool: Tool) -> dict:
    return {
        "id": str(tool.id),
        "tenant_id": (
            str(tool.tenant_id)
            if tool.tenant_id is not None
            else None
        ),
        "name": tool.name,
        "slug": tool.slug,
        "description": tool.description,
        "tool_type": tool.tool_type,
        "config": tool.config,
        "is_active": tool.is_active,
        "scope": (
            "global"
            if tool.tenant_id is None
            else "tenant"
        ),
        "created_at": tool.created_at.isoformat(),
        "updated_at": tool.updated_at.isoformat(),
    }


@router.get("/{capability_id}/tools")
def list_capability_tools(
    capability_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = CapabilityToolService(db)

    try:
        tools = service.list_tools(
            tenant_id=current_user.tenant_id,
            capability_id=capability_id,
        )

        return {
            "items": [
                serialize_tool(tool)
                for tool in tools
            ]
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.post(
    "/{capability_id}/tools",
    status_code=status.HTTP_201_CREATED,
)
def attach_tool(
    capability_id: UUID,
    payload: CapabilityToolCreateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = CapabilityToolService(db)

    try:
        assignment = service.attach_tool(
            tenant_id=current_user.tenant_id,
            capability_id=capability_id,
            tool_id=payload.tool_id,
            config=payload.config,
        )

        db.commit()

        return {
            "id": str(assignment.tool_id),
            "capability_id": str(assignment.capability_id),
            "tool_id": str(assignment.tool_id),
            "tenant_id": str(assignment.tenant_id),
            "config": assignment.config,
        }

    except ValueError as exc:
        db.rollback()

        detail = str(exc)

        if detail in {
            "Capability not found",
            "Tool not found",
        }:
            code = status.HTTP_404_NOT_FOUND
        else:
            code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code=code,
            detail=detail,
        )


@router.delete(
    "/{capability_id}/tools/{tool_id}",
)
def detach_tool(
    capability_id: UUID,
    tool_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = CapabilityToolService(db)

    try:
        service.detach_tool(
            tenant_id=current_user.tenant_id,
            capability_id=capability_id,
            tool_id=tool_id,
        )

        db.commit()

        return {
            "status": "ok",
            "message": "Tool detached from capability",
        }

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
