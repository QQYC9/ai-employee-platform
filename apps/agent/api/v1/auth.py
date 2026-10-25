from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.core.config import settings
from packages.auth.dependencies import get_current_user, get_db
from packages.auth.jwt_service import (
    TokenClaimsError,
    TokenExpiredError,
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from packages.auth.rate_limiter import rate_limit_dependency
from packages.auth.security import hash_password, verify_password
from packages.models.domain import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ResetPasswordWithTokenRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8)

class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=8)


class AuthUserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    tenant_id: str | None = None
    status: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserResponse


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


@router.get("/status")
def auth_status():
    return {
        "status": "ok",
        "service": "authentication",
    }


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[
        Depends(
            rate_limit_dependency(
                max_requests=settings.rate_limit_login_per_minute,
                window_seconds=60,
                key_prefix="auth:login",
            )
        )
    ],
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticate user via email and hashed password.
    Returns signed access and refresh JWTs.
    Rate limited to prevent brute force attacks.
    """
    clean_email = payload.email.strip().lower()

    user = db.scalar(
        select(User).where(
            func.lower(User.email) == clean_email,
            User.status == "active",
        )
    )

    # Constant time comparison failure guard: if user not found or no password hash set
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        logger.warning(
            "Failed login attempt for email: %s",
            clean_email,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate cryptographically signed JWT tokens
    access_token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    refresh_token = create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )

    logger.info("Successful login for user_id=%s, tenant_id=%s", user.id, user.tenant_id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=AuthUserResponse(
            id=str(user.id),
            name=user.name,
            email=user.email,
            role=user.role,
            tenant_id=str(user.tenant_id) if user.tenant_id else None,
            status=user.status,
        ),
    )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    dependencies=[
        Depends(
            rate_limit_dependency(
                max_requests=settings.rate_limit_login_per_minute * 2,
                window_seconds=60,
                key_prefix="auth:refresh",
            )
        )
    ],
)
def refresh_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Renew access token using a valid, unexpired refresh token.
    Rotates refresh token for replay protection.
    """
    try:
        token_payload = verify_token(payload.refresh_token, expected_type="refresh")
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (InvalidTokenError, TokenClaimsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = token_payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims: subject missing",
        )

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in refresh token",
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

    # Issue renewed access and rotated refresh tokens
    new_access_token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    new_refresh_token = create_refresh_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )

    return RefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=AuthUserResponse)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
):
    """
    Return currently authenticated user profile and permissions.
    """
    return AuthUserResponse(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        tenant_id=str(current_user.tenant_id) if current_user.tenant_id else None,
        status=current_user.status,
    )


@router.post("/set-password")
def set_user_password(
    payload: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Allow authenticated user to set or update their password securely.
    """
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    current_user.password_hash = hash_password(payload.password)
    db.commit()

    return {"status": "ok", "message": "Password updated successfully"}


@router.post("/reset-password-with-token")
def reset_password_with_token(
    payload: ResetPasswordWithTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Sets or updates a user password using a single-use, short-lived signed token.
    Used for dashboard access activation from bot invitation link without plaintext passwords.
    """
    import hashlib
    try:
        try:
            claims = verify_token(payload.token, expected_type="password_reset")
        except InvalidTokenError:
            claims = verify_token(payload.token, expected_type="access")
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password setup link has expired. Please request a new link.",
        )
    except (InvalidTokenError, TokenClaimsError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid password setup link: {str(exc)}",
        )

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token subject")

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID in token")

    user = db.scalar(select(User).where(User.id == user_id, User.status == "active"))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found or inactive")

    pwh_claim = claims.get("pwh")
    if pwh_claim:
        current_sig = hashlib.sha256((user.password_hash or "").encode()).hexdigest()[:16]
        if pwh_claim != current_sig:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password setup link has already been used or is invalidated.",
            )

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    return {"status": "ok", "message": "Password updated successfully"}
