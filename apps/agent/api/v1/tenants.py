from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
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
    """
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


@router.get("/status")
def tenants_status():
    return {
        "status": "ok",
        "service": "tenants",
    }
