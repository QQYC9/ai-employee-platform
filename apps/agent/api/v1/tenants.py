from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
from packages.services.business_brain_service import BusinessBrainService
from packages.services.tenant_provisioning_service import (
    TenantProvisioningRequest,
    TenantProvisioningResponse,
    TenantProvisioningService,
)
from packages.services.tenant_service import TenantService
from packages.tenants.context import tenant_context


router = APIRouter(
    prefix="/tenants",
    tags=["Tenants"],
)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    status: str


class TenantUpdateRequest(BaseModel):
    name: str | None = None


class BusinessBrainUpdateRequest(BaseModel):
    identity: dict | None = None
    products: dict | None = None
    services: dict | None = None
    pricing: dict | None = None
    brand: dict | None = None
    customers: dict | None = None
    competitors: dict | None = None
    marketing: dict | None = None
    sales: dict | None = None
    operations: dict | None = None
    policies: dict | None = None
    people: dict | None = None
    goals: dict | None = None
    strategy: dict | None = None
    preferences: dict | None = None
    performance: dict | None = None
    lessons: dict | None = None


@router.post(
    "/provision",
    response_model=TenantProvisioningResponse,
    status_code=status.HTTP_201_CREATED,
)
def provision_tenant(
    payload: TenantProvisioningRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Provision a new commercial tenant, initial owner, BusinessBrain,
    and initial Digital Employee in an atomic transaction.
    Restricted to platform administrators.
    """
    user_role = (current_user.role or "").strip().lower()
    if user_role not in ("platform_admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation not permitted: role '{current_user.role}' lacks platform administration privileges",
        )

    service = TenantProvisioningService(db)
    try:
        result = service.provision_tenant(payload)
        return result
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get("/me", response_model=TenantResponse)
def get_my_tenant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the authenticated user's tenant.

    The tenant is derived from the authenticated user.
    The client never supplies tenant_id.
    """
    with tenant_context(current_user.tenant_id):
        service = TenantService(db)

        tenant = service.get_current_tenant(
            current_user.tenant_id
        )

        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found",
            )

        return TenantResponse(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
        )


@router.patch("/me", response_model=TenantResponse)
def update_my_tenant(
    payload: TenantUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the authenticated user's tenant.
    Only tenant owners or administrators are permitted.
    """
    user_role = (current_user.role or "").strip().lower()
    if user_role not in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tenant owners or administrators can update tenant details",
        )

    with tenant_context(current_user.tenant_id):
        service = TenantService(db)

        try:
            tenant = service.update_current_tenant(
                tenant_id=current_user.tenant_id,
                name=payload.name,
            )
            db.commit()

        except ValueError as exc:
            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        return TenantResponse(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
        )


@router.get("/me/brain")
def get_my_business_brain(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the authenticated user's tenant BusinessBrain.
    Scoped strictly to the caller's tenant.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant",
        )

    service = BusinessBrainService(db)
    brain = service.get_brain(current_user.tenant_id)

    if brain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BusinessBrain not found for this tenant",
        )

    return service.serialize_brain(brain)


@router.patch("/me/brain")
def update_my_business_brain(
    payload: BusinessBrainUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the authenticated user's tenant BusinessBrain.
    Only tenant owners or administrators are permitted.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant",
        )

    user_role = (current_user.role or "").strip().lower()
    if user_role not in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tenant owners or administrators can update BusinessBrain",
        )

    service = BusinessBrainService(db)
    try:
        update_data = (
            payload.model_dump(exclude_unset=True)
            if hasattr(payload, "model_dump")
            else payload.dict(exclude_unset=True)
        )
        brain = service.update_brain(
            tenant_id=current_user.tenant_id,
            **update_data,
        )
        db.commit()
        return service.serialize_brain(brain)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get("/status")
def tenants_status():
    return {
        "status": "ok",
        "service": "tenants",
    }
