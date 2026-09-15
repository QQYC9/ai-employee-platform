from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_db
from packages.auth.context import get_tenant_context
from packages.models.domain import Tool, User
from packages.services.tool_service import ToolService


router = APIRouter(
    prefix="/tools",
    tags=["tools"],
)


class ToolCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100)
    tool_type: str = Field(min_length=1, max_length=100)
    description: str | None = None
    config: dict = Field(default_factory=dict)


class ToolUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    tool_type: str | None = None
    config: dict | None = None
    is_active: bool | None = None


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


@router.get("/status")
def tools_status():
    return {
        "status": "ok",
        "service": "tools",
    }


@router.get("")
def list_tools(
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolService(db)

    tools = service.list_tools(
        current_user.tenant_id
    )

    return {
        "items": [
            serialize_tool(tool)
            for tool in tools
        ]
    }


@router.get("/{tool_id}")
def get_tool(
    tool_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolService(db)

    tool = service.get_tool(
        current_user.tenant_id,
        tool_id,
    )

    if tool is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found",
        )

    return serialize_tool(tool)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tool(
    payload: ToolCreateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolService(db)

    try:
        tool = service.create_tool(
            tenant_id=current_user.tenant_id,
            name=payload.name,
            slug=payload.slug,
            tool_type=payload.tool_type,
            description=payload.description,
            config=payload.config,
        )

        db.commit()
        db.refresh(tool)

        return serialize_tool(tool)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.patch("/{tool_id}")
def update_tool(
    tool_id: UUID,
    payload: ToolUpdateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = ToolService(db)

    try:
        tool = service.update_tool(
            tenant_id=current_user.tenant_id,
            tool_id=tool_id,
            name=payload.name,
            description=payload.description,
            tool_type=payload.tool_type,
            config=payload.config,
            is_active=payload.is_active,
        )

        db.commit()
        db.refresh(tool)

        return serialize_tool(tool)

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
