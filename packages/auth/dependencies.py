from __future__ import annotations

from typing import Callable, Sequence
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.auth.jwt_service import (
    TokenClaimsError,
    TokenExpiredError,
    InvalidTokenError,
    verify_token,
)
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
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the authenticated user from the request.

    Priority:
    1. Authorization: Bearer <jwt_token>
       - Cryptographically signed and verified token.
       - Validates signature, expiration, issuer, audience.
       - Extracts user identity and confirms active status and tenant validity in DB.
    2. Fallback: X-User-ID header (ONLY in development/testing mode)
       - Strictly rejected with 401 Unauthorized in production or when
         allow_dev_auth_header is False.
    """
    # Handle direct function calls where Header default isn't evaluated by FastAPI
    auth_str = authorization if isinstance(authorization, str) else None
    dev_header_str = x_user_id if isinstance(x_user_id, str) else None

    # 1. Bearer Token Authentication
    if auth_str is not None and auth_str.strip().lower().startswith("bearer "):
        token = auth_str.strip()[7:].strip()
        try:
            payload = verify_token(token, expected_type="access")
        except TokenExpiredError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer error=\"invalid_token\", error_description=\"The token has expired\""},
            )
        except (InvalidTokenError, TokenClaimsError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(exc)}",
                headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
            )

        sub = payload.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token subject missing",
            )

        try:
            user_id = UUID(sub)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user identity in token",
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

        # Tenant integrity validation: if token contains tenant_id, it must match user's actual tenant in DB
        token_tenant_id = payload.get("tenant_id")
        if token_tenant_id is not None and user.tenant_id is not None:
            if str(user.tenant_id) != str(token_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token tenant claims mismatch",
                )

        return user

    # 2. Development Stub (X-User-ID Header)
    if dev_header_str is not None:
        if not settings.is_dev_auth_allowed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-User-ID header authentication is strictly forbidden in this environment",
            )

        try:
            user_id = UUID(dev_header_str)
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

    # 3. No authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    """
    Enforce Role-Based Access Control (RBAC).
    Platform admins always bypass tenant-level role restrictions.
    """
    norm_allowed = {r.strip().lower() for r in allowed_roles}

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = (current_user.role or "").strip().lower()

        # Platform superadmin has full access across all operations
        if user_role in ("platform_admin", "superadmin"):
            return current_user

        if user_role in norm_allowed:
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation not permitted: role '{current_user.role}' lacks required permissions",
        )

    return role_checker


# Convenient RBAC shortcuts
require_platform_admin = require_roles("platform_admin", "superadmin")
require_tenant_owner = require_roles("tenant_owner", "owner")
require_tenant_admin = require_roles("tenant_owner", "owner", "tenant_admin", "admin")


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
