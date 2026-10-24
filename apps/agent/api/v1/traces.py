from __future__ import annotations

from datetime import datetime
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import User
from packages.services.permission_service import PermissionService
from packages.services.tracing_query_service import TracingQueryService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/traces",
    tags=["Execution Traces"],
)

ALLOWED_TRACING_ROLES = {
    "platform_admin",
    "superadmin",
    "tenant_owner",
    "owner",
    "tenant_admin",
    "admin",
    "operator",
    "auditor",
    "developer",
}


def verify_tracing_access(
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> User:
    """
    Enforce Role-Based Access Control and permission checks for Execution Traces.
    Strictly denies unprivileged roles (e.g. guest, customer, restricted).
    """
    role = (current_user.role or "").strip().lower()

    if role in ALLOWED_TRACING_ROLES:
        return current_user

    # Also check dynamic granular permissions if available
    if current_user.tenant_id is not None:
        perm_svc = PermissionService(db)
        if perm_svc.is_allowed(
            tenant_id=current_user.tenant_id,
            action="traces:read",
            resource="traces",
        ):
            return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Operation not permitted: role '{current_user.role}' lacks tracing read permissions",
    )


@router.get("")
def list_execution_traces(
    status: str | None = Query(default=None, description="Filter by status (running, completed, failed, paused)"),
    trigger_type: str | None = Query(default=None, description="Filter by trigger type"),
    task_id: UUID | None = Query(default=None, description="Filter by associated task ID"),
    agent_id: UUID | None = Query(default=None, description="Filter by associated agent ID"),
    conversation_id: UUID | None = Query(default=None, description="Filter by associated conversation ID"),
    started_after: str | None = Query(default=None, description="Filter traces started on or after timestamp (ISO format)"),
    started_before: str | None = Query(default=None, description="Filter traces started on or before timestamp (ISO format)"),
    limit: int = Query(default=20, ge=1, description="Page limit (automatically clamped to max 100)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$", description="Sort order by started_at"),
    current_user: User = Depends(verify_tracing_access),
    db: Session = Depends(get_db),
):
    """
    List execution traces for the authenticated tenant with filtering, sorting, and pagination.
    """
    effective_limit = max(1, min(limit, 100))
    service = TracingQueryService(db)
    items, total = service.list_traces(
        tenant_id=current_user.tenant_id,
        status=status,
        trigger_type=trigger_type,
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        started_after=started_after,
        started_before=started_before,
        limit=effective_limit,
        offset=offset,
        sort_order=sort_order,
    )

    return {
        "items": items,
        "total": total,
        "limit": effective_limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
    }


@router.get("/{trace_id}")
def get_execution_trace(
    trace_id: UUID,
    current_user: User = Depends(verify_tracing_access),
    db: Session = Depends(get_db),
):
    """
    Get detailed execution trace record by UUID.
    Guarantees strict tenant isolation (returns 404 if not found or belongs to another tenant).
    """
    service = TracingQueryService(db)
    trace = service.get_trace(tenant_id=current_user.tenant_id, trace_id_or_pk=trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution trace not found",
        )
    return trace


@router.get("/{trace_id}/steps")
def get_execution_trace_steps(
    trace_id: UUID,
    format: str = Query(default="tree", pattern="^(tree|flat)$", description="Format: 'tree' for hierarchical or 'flat' for sequential"),
    current_user: User = Depends(verify_tracing_access),
    db: Session = Depends(get_db),
):
    """
    Get execution steps for a specific trace.
    Returns either a hierarchical parent-child tree or a flat ordered list.
    """
    service = TracingQueryService(db)
    steps = service.get_trace_steps(
        tenant_id=current_user.tenant_id,
        trace_id_or_pk=trace_id,
        format=format,
    )
    if steps is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution trace not found",
        )
    return {
        "trace_id": str(trace_id),
        "format": format,
        "steps": steps,
    }


@router.get("/{trace_id}/summary")
def get_execution_trace_summary(
    trace_id: UUID,
    current_user: User = Depends(verify_tracing_access),
    db: Session = Depends(get_db),
):
    """
    Get high-level summary metrics of an execution trace and its steps.
    """
    service = TracingQueryService(db)
    summary = service.get_trace_summary(
        tenant_id=current_user.tenant_id,
        trace_id_or_pk=trace_id,
    )
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution trace not found",
        )
    return summary
