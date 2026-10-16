from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import Customer, User
from packages.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("/status")
def customers_status():
    return {
        "status": "ok",
        "service": "customers",
    }


class CustomerCreateRequest(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    customer_type: str = "individual"
    profile: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None


class CustomerUpdateRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    status: str | None = None
    customer_type: str | None = None
    profile: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None


def serialize_customer(customer: Customer) -> dict[str, Any]:
    return {
        "id": str(customer.id),
        "tenant_id": str(customer.tenant_id),
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "status": customer.status,
        "customer_type": customer.customer_type,
        "profile": customer.profile or {},
        "metadata_json": customer.metadata_json or {},
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CustomerService(db)
    try:
        customer = service.create_customer(
            tenant_id=current_user.tenant_id,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            customer_type=payload.customer_type,
            profile=payload.profile,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        db.refresh(customer)
        return serialize_customer(customer)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_customers(
    status: str | None = Query(default=None),
    customer_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CustomerService(db)
    try:
        customers = service.list_customers(
            tenant_id=current_user.tenant_id,
            status=status,
            customer_type=customer_type,
            search=search,
            limit=limit,
            offset=offset,
        )
        return [serialize_customer(c) for c in customers]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{customer_id}")
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CustomerService(db)
    customer = service.get_customer(current_user.tenant_id, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return serialize_customer(customer)


@router.patch("/{customer_id}")
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CustomerService(db)
    try:
        customer = service.update_customer(
            tenant_id=current_user.tenant_id,
            customer_id=customer_id,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            status=payload.status,
            customer_type=payload.customer_type,
            profile=payload.profile,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        db.refresh(customer)
        return serialize_customer(customer)
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_role = (current_user.role or "").strip().lower()
    is_admin_or_owner = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    if not is_admin_or_owner:
        raise HTTPException(status_code=403, detail="Forbidden: User lacks permission to delete customers")

    service = CustomerService(db)
    try:
        service.delete_customer(current_user.tenant_id, customer_id)
        db.commit()
        return {"status": "success", "message": "Customer deleted"}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
