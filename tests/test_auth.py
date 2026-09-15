import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException

from packages.auth.dependencies import get_current_user, get_current_tenant
from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import User


def test_user_resolves_to_its_tenant():
    db = SessionLocal()

    try:
        tenant = Tenant(
            name="Auth Test Business",
            slug=f"auth-test-{uuid4().hex[:8]}",
        )
        db.add(tenant)
        db.flush()

        user = User(
            tenant_id=tenant.id,
            name="Auth Test User",
            email=f"auth-{uuid4().hex[:8]}@example.com",
            role="owner",
            status="active",
        )
        db.add(user)
        db.flush()

        resolved_user = get_current_user(
            x_user_id=str(user.id),
            db=db,
        )

        assert resolved_user.id == user.id
        assert resolved_user.tenant_id == tenant.id

        resolved_tenant = get_current_tenant(
            resolved_user,
            db=db,
        )

        assert resolved_tenant.id == tenant.id

    finally:
        db.rollback()
        db.close()


def test_missing_identity_is_rejected():
    db = SessionLocal()

    try:
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(
                x_user_id=None,
                db=db,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Authentication required"

    finally:
        db.close()
