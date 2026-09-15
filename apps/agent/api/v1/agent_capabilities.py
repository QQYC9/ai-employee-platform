from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
from packages.services.agent_capability_service import (
    AgentCapabilityService,
)
from packages.tenants.context import tenant_context


router = APIRouter(
    prefix="/agents",
    tags=["Agent Capabilities"],
)


class AttachCapabilityRequest(BaseModel):
    capability_id: UUID
    config: dict = Field(default_factory=dict)


class AssignedCapabilityResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    config: dict


@router.get(
    "/{agent_id}/capabilities",
    response_model=list[AssignedCapabilityResponse],
)
def list_agent_capabilities(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentCapabilityService(db)

        try:
            capabilities = service.list_capabilities(
                tenant_id=current_user.tenant_id,
                agent_id=agent_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )

        return [
            AssignedCapabilityResponse(
                id=str(capability.id),
                name=capability.name,
                slug=capability.slug,
                description=capability.description,
                config=capability.config or {},
            )
            for capability in capabilities
        ]


@router.post(
    "/{agent_id}/capabilities",
    status_code=status.HTTP_201_CREATED,
)
def attach_capability(
    agent_id: UUID,
    payload: AttachCapabilityRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentCapabilityService(db)

        try:
            assignment = service.attach_capability(
                tenant_id=current_user.tenant_id,
                agent_id=agent_id,
                capability_id=payload.capability_id,
                config=payload.config,
            )

            db.commit()

        except ValueError as exc:
            db.rollback()

            message = str(exc)

            if message in {
                "Agent not found",
                "Capability not found",
            }:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=message,
                )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message,
            )

        return {
            "id": str(assignment.id),
            "agent_id": str(assignment.agent_id),
            "capability_id": str(assignment.capability_id),
            "config": assignment.config or {},
        }


@router.delete(
    "/{agent_id}/capabilities/{capability_id}",
)
def detach_capability(
    agent_id: UUID,
    capability_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentCapabilityService(db)

        try:
            service.detach_capability(
                tenant_id=current_user.tenant_id,
                agent_id=agent_id,
                capability_id=capability_id,
            )

            db.commit()

        except ValueError as exc:
            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )

        return {
            "status": "ok",
            "agent_id": str(agent_id),
            "capability_id": str(capability_id),
        }
