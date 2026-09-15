from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
from packages.services.capability_service import CapabilityService
from packages.tenants.context import tenant_context


router = APIRouter(
    prefix="/capabilities",
    tags=["Capabilities"],
)


class CapabilityResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    config: dict
    is_active: bool
    scope: str


class CapabilityCreateRequest(BaseModel):
    name: str
    slug: str
    description: str | None = None
    config: dict = Field(default_factory=dict)


class CapabilityUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict | None = None
    is_active: bool | None = None


def serialize_capability(capability) -> CapabilityResponse:
    return CapabilityResponse(
        id=str(capability.id),
        name=capability.name,
        slug=capability.slug,
        description=capability.description,
        config=capability.config or {},
        is_active=capability.is_active,
        scope=(
            "global"
            if capability.tenant_id is None
            else "tenant"
        ),
    )


@router.get("/status")
def capabilities_status():
    return {
        "status": "ok",
        "service": "capabilities",
    }


@router.get(
    "",
    response_model=list[CapabilityResponse],
)
def list_capabilities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = CapabilityService(db)

        capabilities = service.list_capabilities(
            tenant_id=current_user.tenant_id,
        )

        return [
            serialize_capability(capability)
            for capability in capabilities
        ]


@router.get(
    "/{capability_id}",
    response_model=CapabilityResponse,
)
def get_capability(
    capability_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = CapabilityService(db)

        capability = service.get_capability(
            tenant_id=current_user.tenant_id,
            capability_id=capability_id,
        )

        if capability is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Capability not found",
            )

        return serialize_capability(capability)


@router.post(
    "",
    response_model=CapabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_capability(
    payload: CapabilityCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = CapabilityService(db)

        try:
            capability = service.create_capability(
                tenant_id=current_user.tenant_id,
                name=payload.name,
                slug=payload.slug,
                description=payload.description,
                config=payload.config,
            )

            db.commit()

        except ValueError as exc:
            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        return serialize_capability(capability)


@router.patch(
    "/{capability_id}",
    response_model=CapabilityResponse,
)
def update_capability(
    capability_id: UUID,
    payload: CapabilityUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = CapabilityService(db)

        try:
            capability = service.update_capability(
                tenant_id=current_user.tenant_id,
                capability_id=capability_id,
                name=payload.name,
                description=payload.description,
                config=payload.config,
                is_active=payload.is_active,
            )

            db.commit()

        except ValueError as exc:
            db.rollback()

            if str(exc) == "Capability not found":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        return serialize_capability(capability)
