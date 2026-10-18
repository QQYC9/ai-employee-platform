from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.auth.dependencies import (
    get_current_user,
    get_db,
    require_platform_admin,
    require_tenant_admin,
)
from packages.models.domain import AuditEvent, User
from packages.models.tenant import Tenant
from packages.services.admin_dashboard_service import AdminDashboardService

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
)


# -----------------------------------------------------------------------------
# Request & Response Schemas
# -----------------------------------------------------------------------------

class TenantBudgetUpdateRequest(BaseModel):
    daily_token_limit: int | None = Field(default=None, ge=0)
    monthly_token_limit: int | None = Field(default=None, ge=0)
    is_hard_limit: bool = True


class TenantStatusUpdateRequest(BaseModel):
    status: str = Field(..., min_length=3, max_length=50)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def resolve_target_tenant_id(
    current_user: User,
    requested_tenant_id: UUID | None,
) -> UUID:
    """
    Enforce strict tenant scoping:
    - Platform admin can view any specified tenant, or defaults to requested_tenant_id.
    - Tenant admin can ONLY access their own current_user.tenant_id. Cross-tenant access is rejected with 403.
    """
    user_role = (current_user.role or "").strip().lower()
    is_platform_admin = user_role in ("platform_admin", "superadmin")

    if is_platform_admin:
        if requested_tenant_id is not None:
            return requested_tenant_id
        if current_user.tenant_id is not None:
            return current_user.tenant_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Platform admin must specify tenant_id when not bound to a tenant",
        )

    # For Tenant Admin: must be bound to a tenant
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not associated with any tenant",
        )

    # If tenant admin attempts to view a different tenant
    if requested_tenant_id is not None and requested_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-tenant access forbidden: you cannot access another tenant's administrative data",
        )

    return current_user.tenant_id


# =============================================================================
# 1. Platform Admin Endpoints (/api/v1/admin/platform/*)
# =============================================================================

@router.get("/platform/overview")
def get_platform_overview(
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform superadmin overview: aggregates all tenants, agents, tasks, outbox events,
    channels, AI consumption, and operational metrics across the entire platform.
    """
    service = AdminDashboardService(db)
    return service.get_platform_summary()


@router.get("/platform/tenants")
def list_tenants_overview(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant_status: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Paginated overview of all tenants with agent counts, task performance,
    and quota budget statuses.
    """
    service = AdminDashboardService(db)
    return service.list_tenants_overview(
        limit=limit,
        offset=offset,
        status=tenant_status,
    )


@router.patch("/platform/tenants/{tenant_id}/budget")
def update_tenant_budget(
    tenant_id: UUID,
    payload: TenantBudgetUpdateRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform admin updates AI budget quotas for a specific tenant.
    Action is recorded in the immutable administrative audit log.
    """
    service = AdminDashboardService(db)
    try:
        updated = service.update_tenant_budget(
            tenant_id=tenant_id,
            admin_user=current_user,
            daily_token_limit=payload.daily_token_limit,
            monthly_token_limit=payload.monthly_token_limit,
            is_hard_limit=payload.is_hard_limit,
        )
        return {"status": "success", "budget": updated}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/platform/tenants/{tenant_id}/status")
def update_tenant_status(
    tenant_id: UUID,
    payload: TenantStatusUpdateRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform admin updates operational status of a tenant (e.g. active, suspended).
    Action is recorded in the administrative audit log.
    """
    service = AdminDashboardService(db)
    try:
        result = service.update_tenant_status(
            tenant_id=tenant_id,
            admin_user=current_user,
            new_status=payload.status,
        )
        return {"status": "success", "tenant": result}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/platform/metrics")
def get_platform_metrics(
    time_window_days: int = Query(default=30, ge=1, le=90),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform-wide AI metrics: aggregated token usage, error rates, latencies,
    and provider/model breakdowns across all tenants.
    """
    service = AdminDashboardService(db)
    return service.get_platform_metrics(time_window_days=time_window_days)


@router.get("/platform/audit-logs")
def list_platform_audit_logs(
    tenant_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Paginated administrative audit events across the platform.
    """
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc())
    if tenant_id is not None:
        query = query.where(AuditEvent.tenant_id == tenant_id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type.strip())

    events = list(db.scalars(query.offset(offset).limit(limit)).all())
    return {
        "limit": limit,
        "offset": offset,
        "events": [
            {
                "id": str(e.id),
                "tenant_id": str(e.tenant_id) if e.tenant_id else None,
                "user_id": str(e.user_id) if e.user_id else None,
                "agent_id": str(e.agent_id) if e.agent_id else None,
                "event_type": e.event_type,
                "action": e.action,
                "description": e.description,
                "event_metadata": e.event_metadata,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


# =============================================================================
# 2. Tenant Admin Endpoints (/api/v1/admin/tenant/*)
# =============================================================================

@router.get("/tenant/dashboard")
def get_tenant_dashboard(
    tenant_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Comprehensive dashboard for tenant admin: tasks breakdown, agent status,
    connected channels with masked secrets, outbox status, and budget alerts.
    Enforces strict tenant isolation.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    service = AdminDashboardService(db)
    try:
        return service.get_tenant_dashboard(target_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/tenant/metrics")
def get_tenant_metrics(
    tenant_id: UUID | None = Query(default=None),
    time_window_days: int = Query(default=30, ge=1, le=90),
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Aggregated usage and latency metrics for tenant, including AI token consumption
    by provider/model, daily trends, and task retry deduplication.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    service = AdminDashboardService(db)
    return service.get_tenant_metrics(
        tenant_id=target_tenant_id,
        time_window_days=time_window_days,
    )


@router.get("/tenant/budget")
def get_tenant_budget(
    tenant_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Current token quota, remaining daily/monthly tokens, and alert threshold warnings.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    service = AdminDashboardService(db)
    status_info = service.ai_usage_service.get_budget_status(target_tenant_id)
    alert_level = service._compute_budget_alert_level(status_info)
    return {
        **status_info,
        "alert_level": alert_level,
    }


@router.get("/tenant/channels")
def get_tenant_channels(
    tenant_id: UUID | None = Query(default=None),
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    List connected communication channels with masked secrets (tokens/passwords never exposed).
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    service = AdminDashboardService(db)
    dashboard = service.get_tenant_dashboard(target_tenant_id)
    return {
        "tenant_id": str(target_tenant_id),
        "channels": dashboard.get("channels", {}).get("items", []),
    }


@router.get("/tenant/audit-logs")
def list_tenant_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Paginated audit events strictly scoped to caller's tenant.
    """
    tenant_id = resolve_target_tenant_id(current_user, None)
    query = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.created_at.desc())
    )
    if event_type:
        query = query.where(AuditEvent.event_type == event_type.strip())

    events = list(db.scalars(query.offset(offset).limit(limit)).all())
    return {
        "tenant_id": str(tenant_id),
        "limit": limit,
        "offset": offset,
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "action": e.action,
                "description": e.description,
                "user_id": str(e.user_id) if e.user_id else None,
                "agent_id": str(e.agent_id) if e.agent_id else None,
                "event_metadata": e.event_metadata,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


# =============================================================================
# 3. Operational Monitoring (/api/v1/admin/monitoring/health)
# =============================================================================

@router.get("/monitoring/health")
def get_operational_health(
    current_user: User = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    System diagnostic health evaluation: database, outbox queue, stalled tasks,
    and AI provider reliability. Available to platform and tenant admins.
    Enforces tenant scoping so tenant admins only inspect their own tenant's health.
    """
    service = AdminDashboardService(db)
    user_role = (current_user.role or "").strip().lower()
    is_platform_admin = user_role in ("platform_admin", "superadmin")
    return service.get_operational_monitoring(
        target_tenant_id=current_user.tenant_id,
        is_platform_admin=is_platform_admin,
    )
