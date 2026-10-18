from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import (
    get_current_user,
    get_db,
    require_tenant_admin,
)
from packages.models.domain import (
    CapabilityVersion,
    DevelopmentRequest,
    DevelopmentRun,
    User,
)
from packages.self_development.continuous_improvement import ContinuousImprovementService
from packages.self_development.engine import SelfDevelopmentEngine

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/self-development",
    tags=["Self-Development"],
)


# -----------------------------------------------------------------------------
# Request / Response Schemas
# -----------------------------------------------------------------------------


class CreateDevelopmentRequestPayload(BaseModel):
    problem_statement: str = Field(min_length=5, max_length=2000)
    desired_capability: str = Field(min_length=3, max_length=255)
    slug: str | None = Field(default=None, max_length=150)
    agent_id: UUID | None = None
    task_id: UUID | None = None
    trigger_type: str = Field(default="gap_analysis", max_length=50)
    priority: str = Field(default="normal", max_length=20)
    expected_benefit: str | None = None
    reference_context: dict[str, Any] = Field(default_factory=dict)


class PrepareSpecificationPayload(BaseModel):
    specification: dict[str, Any]


class RunDevelopmentPayload(BaseModel):
    implementation_code: str = Field(min_length=10)


class ReviewApprovalPayload(BaseModel):
    approved: bool
    reason: str | None = None


class RollbackPayload(BaseModel):
    target_version_number: int | None = None
    reason: str | None = None


# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------


def serialize_request(req: DevelopmentRequest) -> dict[str, Any]:
    return {
        "id": str(req.id),
        "tenant_id": str(req.tenant_id),
        "agent_id": str(req.agent_id) if req.agent_id else None,
        "request_type": req.request_type,
        "title": req.title,
        "reason": req.reason,
        "requirements": req.requirements or {},
        "expected_benefit": req.expected_benefit,
        "requested_from": req.requested_from,
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
    }


def serialize_version(v: CapabilityVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "tenant_id": str(v.tenant_id),
        "capability_id": str(v.capability_id) if v.capability_id else None,
        "request_id": str(v.request_id) if v.request_id else None,
        "version_number": v.version_number,
        "slug": v.slug,
        "name": v.name,
        "description": v.description,
        "specification": v.specification or {},
        "risk_level": v.risk_level,
        "status": v.status,
        "approval_id": str(v.approval_id) if v.approval_id else None,
        "test_results": v.test_results or {},
        "activated_at": v.activated_at.isoformat() if v.activated_at else None,
        "rolled_back_at": v.rolled_back_at.isoformat() if v.rolled_back_at else None,
        "rollback_reason": v.rollback_reason,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


def serialize_run(run: DevelopmentRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "request_id": str(run.request_id) if run.request_id else None,
        "capability_version_id": str(run.capability_version_id) if run.capability_version_id else None,
        "run_type": run.run_type,
        "status": run.status,
        "test_summary": run.test_summary or {},
        "security_verdict": run.security_verdict or {},
        "logs": run.logs,
        "error_message": run.error_message,
        "duration_ms": run.duration_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: CreateDevelopmentRequestPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    requirements = dict(payload.reference_context)
    if payload.slug:
        requirements["slug"] = payload.slug
    if payload.task_id:
        requirements["task_id"] = str(payload.task_id)
    requirements["trigger_type"] = payload.trigger_type

    try:
        req, is_duplicate = engine.create_development_request(
            tenant_id=current_user.tenant_id,
            title=payload.desired_capability,
            reason=payload.problem_statement,
            requirements=requirements,
            expected_benefit=payload.expected_benefit,
            requested_from="agent" if payload.agent_id else "user",
            agent_id=payload.agent_id,
            priority=payload.priority,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "request": serialize_request(req),
        "is_duplicate": is_duplicate,
    }


@router.get("/requests")
def list_requests(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    items = engine.list_requests(
        tenant_id=current_user.tenant_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return {
        "items": [serialize_request(r) for r in items],
        "count": len(items),
    }


@router.get("/requests/{request_id}")
def get_request_details(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    req = engine.get_request(tenant_id=current_user.tenant_id, request_id=request_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development request not found",
        )
    return serialize_request(req)


@router.post("/requests/{request_id}/spec", status_code=status.HTTP_201_CREATED)
def prepare_specification(
    request_id: UUID,
    payload: PrepareSpecificationPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    try:
        version = engine.prepare_specification(
            tenant_id=current_user.tenant_id,
            request_id=request_id,
            spec_data=payload.specification,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"version": serialize_version(version)}


@router.post("/versions/{version_id}/develop")
def run_development(
    version_id: UUID,
    payload: RunDevelopmentPayload,
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    try:
        version, run = engine.develop_and_test(
            tenant_id=current_user.tenant_id,
            version_id=version_id,
            implementation_code=payload.implementation_code,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {
        "version": serialize_version(version),
        "run": serialize_run(run),
    }


@router.get("/versions/{version_id}/runs")
def list_runs(
    version_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    runs = engine.list_runs_for_version(
        tenant_id=current_user.tenant_id,
        version_id=version_id,
    )
    return {
        "items": [serialize_run(r) for r in runs],
        "count": len(runs),
    }


@router.post("/versions/{version_id}/approve")
def approve_version(
    version_id: UUID,
    payload: ReviewApprovalPayload,
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    try:
        version = engine.review_and_approve(
            tenant_id=current_user.tenant_id,
            version_id=version_id,
            user=current_user,
            approved=payload.approved,
            reason=payload.reason,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"version": serialize_version(version)}


@router.post("/versions/{version_id}/activate")
def activate_version(
    version_id: UUID,
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    try:
        version = engine.activate_version(
            tenant_id=current_user.tenant_id,
            version_id=version_id,
            user=current_user,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"version": serialize_version(version)}


@router.post("/capabilities/{slug}/rollback")
def rollback_capability(
    slug: str,
    payload: RollbackPayload,
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    try:
        version = engine.disable_or_rollback(
            tenant_id=current_user.tenant_id,
            slug=slug,
            user=current_user,
            reason=payload.reason,
            rollback_to_version_number=payload.target_version_number,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return {"version": serialize_version(version)}



@router.get("/capabilities/{slug}/versions")
def list_capability_versions(
    slug: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authenticated user must belong to a tenant",
        )

    engine = SelfDevelopmentEngine(db=db)
    versions = engine.list_versions_for_slug(
        tenant_id=current_user.tenant_id,
        slug=slug,
    )
    return {
        "items": [serialize_version(v) for v in versions],
        "count": len(versions),
    }


@router.get("/reports/continuous-improvement")
def get_continuous_improvement_report(
    days: int = Query(default=30, ge=1, le=365),
    platform_wide: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = ContinuousImprovementService(db=db)
    user_role = (current_user.role or "").strip().lower()
    is_platform_admin = user_role in ("platform_admin", "superadmin")

    if platform_wide:
        if not is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform-wide continuous improvement report requires platform_admin role",
            )
        return service.generate_platform_report(days=days)

    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required for tenant-scoped continuous improvement report",
        )

    return service.generate_tenant_report(tenant_id=current_user.tenant_id, days=days)
