from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import User
from packages.tenants.context import tenant_context


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_current_user(
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the authenticated user from the request.

    Temporary development authentication:
    X-User-ID header identifies the user.

    The authentication mechanism can later be replaced
    by JWT/OAuth without changing tenant resolution.
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        user_id = UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity",
        )

    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.status == "active",
        )
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Tenant:
    """
    Resolve the tenant from the authenticated user.

    The tenant ID is NEVER accepted directly from the client.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant",
        )

    tenant = db.scalar(
        select(Tenant).where(
            Tenant.id == current_user.tenant_id,
            Tenant.status == "active",
        )
    )

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant not found or inactive",
        )

    return tenant


def activate_tenant_context(current_user: User):
    """
    Activate the authenticated user's tenant context.
    """
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant",
        )

    return tenant_context(current_user.tenant_id)
