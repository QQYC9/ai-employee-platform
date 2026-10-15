from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt

from packages.core.config import settings


class JWTAuthError(Exception):
    """Base exception for JWT errors."""
    pass


class TokenExpiredError(JWTAuthError):
    """Token has expired."""
    pass


class InvalidTokenError(JWTAuthError):
    """Token is invalid, malformed, or tampered with."""
    pass


class TokenClaimsError(JWTAuthError):
    """Token claims (iss, aud, type) are invalid."""
    pass


def _get_signing_key(override_key: str | None = None) -> str:
    key = override_key or settings.jwt_secret_key
    if not key or (settings.environment.lower() in ("production", "prod") and key.startswith("dev-")):
        raise ValueError("Insecure or missing JWT_SECRET_KEY in production environment")
    return key


def create_access_token(
    user_id: UUID | str,
    tenant_id: UUID | str | None,
    role: str,
    expires_delta: timedelta | None = None,
    signing_key: str | None = None,
) -> str:
    """
    Issue a signed JWT access token.
    """
    now = datetime.now(timezone.utc)
    expire_minutes = settings.jwt_access_token_expire_minutes
    expires_at = now + (expires_delta or timedelta(minutes=expire_minutes))

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "role": role,
        "token_type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid4()),
    }

    key = _get_signing_key(signing_key)
    return jwt.encode(payload, key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: UUID | str,
    tenant_id: UUID | str | None,
    role: str,
    expires_delta: timedelta | None = None,
    signing_key: str | None = None,
) -> str:
    """
    Issue a signed JWT refresh token.
    """
    now = datetime.now(timezone.utc)
    expire_days = settings.jwt_refresh_token_expire_days
    expires_at = now + (expires_delta or timedelta(days=expire_days))

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "role": role,
        "token_type": "refresh",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid4()),
    }

    key = _get_signing_key(signing_key)
    return jwt.encode(payload, key, algorithm=settings.jwt_algorithm)


def verify_token(
    token: str,
    expected_type: str = "access",
    signing_key: str | None = None,
    verify_aud: bool = True,
    verify_iss: bool = True,
) -> dict[str, Any]:
    """
    Verify and decode a signed JWT token.
    Enforces signature, expiration, issuer, audience, and token type.
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Missing or empty token")

    key = _get_signing_key(signing_key)

    options = {
        "require": ["exp", "sub"],
        "verify_signature": True,
        "verify_exp": True,
        "verify_iat": True,
    }
    if verify_aud:
        options["require"].append("aud")
    if verify_iss:
        options["require"].append("iss")

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer if verify_iss else None,
            audience=settings.jwt_audience if verify_aud else None,
            options=options,
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Token has expired") from e
    except jwt.InvalidIssuerError as e:
        raise TokenClaimsError("Invalid token issuer") from e
    except jwt.InvalidAudienceError as e:
        raise TokenClaimsError("Invalid token audience") from e
    except jwt.InvalidSignatureError as e:
        raise InvalidTokenError("Invalid token signature") from e
    except jwt.DecodeError as e:
        raise InvalidTokenError("Malformed or unparseable token") from e
    except jwt.PyJWTError as e:
        raise InvalidTokenError(f"JWT validation error: {str(e)}") from e

    token_type = payload.get("token_type")
    if token_type != expected_type:
        raise InvalidTokenError(
            f"Expected token_type '{expected_type}', found '{token_type}'"
        )

    return payload
