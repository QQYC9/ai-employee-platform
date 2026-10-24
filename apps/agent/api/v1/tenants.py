from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
from packages.services.business_brain_service import BusinessBrainService
from packages.services.business_readiness_service import BusinessReadinessService
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


class BusinessProfileUpdateRequest(BaseModel):
    commercial_name: str | None = None
    legal_name: str | None = None
    business_type: str | None = None
    description: str | None = None
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None
    operating_hours: dict[str, Any] | None = None
    products: dict[str, Any] | list[dict[str, Any]] | None = None
    services: dict[str, Any] | list[dict[str, Any]] | None = None
    pricing: dict[str, Any] | None = None
    policies: dict[str, Any] | None = None
    operations: dict[str, Any] | None = None


class BusinessProfileResponse(BaseModel):
    tenant_id: str
    commercial_name: str
    legal_name: str | None = None
    business_type: str | None = None
    description: str | None = None
    contact: dict[str, Any] = {}
    address: dict[str, Any] = {}
    operating_hours: dict[str, Any] = {}
    products: dict[str, Any] = {}
    services: dict[str, Any] = {}
    pricing: dict[str, Any] = {}
    policies: dict[str, Any] = {}
    operations: dict[str, Any] = {}
    version: int = 1
    updated_at: str | None = None


class CatalogUpdateRequest(BaseModel):
    products: dict[str, Any] | list[dict[str, Any]] | None = None
    services: dict[str, Any] | list[dict[str, Any]] | None = None
    pricing: dict[str, Any] | None = None
    replace_all: bool = False


class CatalogResponse(BaseModel):
    tenant_id: str
    products: dict[str, Any] = {}
    services: dict[str, Any] = {}
    pricing: dict[str, Any] = {}
    version: int = 1


class PoliciesUpdateRequest(BaseModel):
    delivery: dict[str, Any] | str | None = None
    returns: dict[str, Any] | str | None = None
    exchange: dict[str, Any] | str | None = None
    payment: dict[str, Any] | list[str] | str | None = None
    warranty: dict[str, Any] | str | None = None
    terms: str | None = None
    replace_all: bool = False


class PoliciesResponse(BaseModel):
    tenant_id: str
    policies: dict[str, Any] = {}
    version: int = 1


class BusinessReadinessResponse(BaseModel):
    tenant_id: str
    overall_score: float
    overall_status: str
    has_critical_blockers: bool
    readiness_summary: str
    critical_blockers: dict[str, list[str]] = {}
    domains: dict[str, Any] = {}
    discovery_questions: list[dict[str, Any]] = []
    evaluated_at: str


ADMIN_ROLES = {"owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin"}


def _require_admin(user: User, action: str = "update") -> None:
    if user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant",
        )
    user_role = (user.role or "").strip().lower()
    if user_role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation not permitted: role '{user.role}' lacks administrator privileges to {action}",
        )


def _require_tenant_user(user: User) -> None:
    if user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant",
        )


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
            updated_by_user_id=current_user.id,
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


@router.get("/me/profile", response_model=BusinessProfileResponse)
def get_my_business_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the authenticated tenant's complete business profile:
    Commercial & legal name, business type, description, address,
    contact info, operating hours, products, services, pricing, and policies.
    """
    _require_tenant_user(current_user)
    with tenant_context(current_user.tenant_id):
        service = BusinessBrainService(db)
        try:
            return service.get_profile(current_user.tenant_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )


@router.put("/me/profile", response_model=BusinessProfileResponse)
@router.patch("/me/profile", response_model=BusinessProfileResponse)
def update_my_business_profile(
    payload: BusinessProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the authenticated tenant's business profile.
    Supports commercial name, legal name, business type, description,
    address, contact info, operating hours, catalog, and policies.
    Enforces server-side RBAC: restricted to tenant owners and administrators.
    """
    _require_admin(current_user, action="update business profile")
    with tenant_context(current_user.tenant_id):
        service = BusinessBrainService(db)
        try:
            update_data = (
                payload.model_dump(exclude_unset=True)
                if hasattr(payload, "model_dump")
                else payload.dict(exclude_unset=True)
            )
            profile = service.update_profile(
                tenant_id=current_user.tenant_id,
                profile_data=update_data,
                user_id=current_user.id,
            )
            db.commit()
            return profile
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )


@router.get("/me/catalog", response_model=CatalogResponse)
def get_my_catalog(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated tenant's catalog (products, services, pricing)."""
    _require_tenant_user(current_user)
    with tenant_context(current_user.tenant_id):
        service = BusinessBrainService(db)
        return service.get_catalog(current_user.tenant_id)


@router.put("/me/catalog", response_model=CatalogResponse)
def update_my_catalog(
    payload: CatalogUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update products, services, and pricing in BusinessBrain (SSOT)."""
    _require_admin(current_user, action="update catalog")
    with tenant_context(current_user.tenant_id):
        service = BusinessBrainService(db)
        try:
            catalog = service.update_catalog(
                tenant_id=current_user.tenant_id,
                products=payload.products,
                services=payload.services,
                pricing=payload.pricing,
                replace_all=payload.replace_all,
                user_id=current_user.id,
            )
            db.commit()
            return catalog
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )


@router.get("/me/policies", response_model=PoliciesResponse)
def get_my_policies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated tenant's policies (delivery, returns, exchange, payment)."""
    _require_tenant_user(current_user)
    with tenant_context(current_user.tenant_id):
        service = BusinessBrainService(db)
        return service.get_policies(current_user.tenant_id)


@router.put("/me/policies", response_model=PoliciesResponse)
def update_my_policies(
    payload: PoliciesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update business policies in BusinessBrain (SSOT)."""
    _require_admin(current_user, action="update policies")
    with tenant_context(current_user.tenant_id):
        service = BusinessBrainService(db)
        try:
            update_data = (
                payload.model_dump(exclude_unset=True, exclude={"replace_all"})
                if hasattr(payload, "model_dump")
                else {k: v for k, v in payload.dict(exclude_unset=True).items() if k != "replace_all"}
            )
            policies = service.update_policies(
                tenant_id=current_user.tenant_id,
                policies=update_data,
                replace_all=payload.replace_all,
                user_id=current_user.id,
            )
            db.commit()
            return policies
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )


@router.get("/me/readiness", response_model=BusinessReadinessResponse)
def get_my_business_readiness(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Evaluate the authenticated tenant's AI employee readiness across business domains:
    - General FAQ & identity
    - Catalog presentation & pricing
    - Order taking & fulfillment
    - Delivery & shipping
    - After-sales support & returns

    Returns readiness scores, domain statuses, blocking requirements,
    actionable suggestions, and structured discovery questions.
    Pure read operation: does not mutate or write changes to the business profile.
    """
    _require_tenant_user(current_user)
    with tenant_context(current_user.tenant_id):
        service = BusinessReadinessService(db)
        try:
            return service.evaluate_tenant_readiness(current_user.tenant_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            )


@router.get("/status")
def tenants_status():
    return {
        "status": "ok",
        "service": "tenants",
    }
