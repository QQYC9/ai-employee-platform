from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.auth.dependencies import (
    get_current_user,
    get_db,
    require_platform_admin,
    require_tenant_admin,
)
from packages.core.database import SessionLocal
from packages.models.domain import (
    Agent,
    AuditEvent,
    Channel,
    Conversation,
    Integration,
    Message,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.admin_dashboard_service import AdminDashboardService
from packages.services.ai_provider_service import AIProviderService
from packages.services.audit_service import AuditService
from packages.services.channel_service import ChannelService
from packages.services.conversation_service import ConversationService
from packages.services.tracing_query_service import TracingQueryService
from apps.agent.api.v1.channels import serialize_channel

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


class EmergencyChannelStatusRequest(BaseModel):
    status: Literal["active", "disabled"]
    reason: str = Field(min_length=15, max_length=1000)


class EmergencyAgentStatusRequest(BaseModel):
    status: Literal["active", "disabled"]
    reason: str = Field(min_length=15, max_length=1000)


class EmergencyTaskCancelRequest(BaseModel):
    reason: str = Field(min_length=15, max_length=1000)


class TenantIntegrationStatusUpdateRequest(BaseModel):
    status: Literal["active", "inactive", "disabled", "deleted"]


class TenantIntegrationCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Reference name, e.g. 'groq-tenant-prod'")
    provider: str = Field(..., description="Provider name: 'groq', 'openai', or 'gemini'")
    model: str = Field(..., min_length=1, max_length=100, description="Model identifier, e.g. 'llama-3.3-70b-versatile'")
    api_key: str | None = Field(default=None, description="Secret API key (encrypted at rest using AES-256-GCM)")
    base_url: str | None = Field(default=None, description="Optional custom base URL endpoint")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    is_default: bool = Field(default=False, description="Set as default provider for this tenant")
    extra_params: dict[str, Any] | None = None


class TenantChannelCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    channel_type: str = Field(..., min_length=2, max_length=50)
    provider: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class TenantChannelUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    provider: str | None = None
    config: dict[str, Any] | None = None


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
    search: str | None = Query(default=None),
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
        search=search,
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


# =============================================================================
# 4. Audited Sensitive Conversations & Messages (/api/v1/admin/platform/tenants/{tenant_id}/*)
# =============================================================================

@router.get("/platform/tenants/{tenant_id}/conversations")
def list_tenant_conversations(
    tenant_id: UUID,
    customer_id: UUID | None = Query(default=None),
    channel_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform admin lists conversations for a specific tenant.
    Strict tenant validation is enforced.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    service = ConversationService(db)
    conversations = service.list_conversations(
        tenant_id=target_tenant_id,
        customer_id=customer_id,
        channel_id=channel_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "tenant_id": str(target_tenant_id),
        "limit": limit,
        "offset": offset,
        "conversations": [
            {
                "id": str(c.id),
                "tenant_id": str(c.tenant_id),
                "customer_id": str(c.customer_id) if c.customer_id else None,
                "channel_id": str(c.channel_id) if c.channel_id else None,
                "subject": c.subject,
                "external_id": c.external_id,
                "status": c.status,
                "metadata_json": c.metadata_json or {},
                "started_at": c.started_at.isoformat() if c.started_at else None,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            }
            for c in conversations
        ],
    }


@router.get("/platform/tenants/{tenant_id}/conversations/{conversation_id}/messages")
def get_tenant_conversation_messages(
    tenant_id: UUID,
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    reason: str | None = Query(default=None),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Platform admin reads customer conversation messages for a tenant.
    Strict Pre-Fetch Audit Locking:
    1. Tenant and conversation existence are verified without fetching message contents.
    2. An audit record is written and committed in an INDEPENDENT database session.
       If audit logging fails, message content is NEVER queried from the database.
    3. Messages are fetched from the database.
    4. Audit record is updated to 'disclosed'. If updating fails, disclosure is blocked.
    5. Clean serialized messages are returned only upon complete audit confirmation.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)

    # 1. Verification without message content loading
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    conv = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == target_tenant_id,
        )
    )
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found for this tenant",
        )

    # 2. Pre-fetch audit recording in an independent database session
    audit_event_id: UUID | None = None
    try:
        with SessionLocal() as audit_session:
            audit_svc = AuditService(audit_session)
            event = audit_svc.record_access_event(
                tenant_id=target_tenant_id,
                user_id=current_user.id,
                resource_type="conversation_messages",
                resource_id=conversation_id,
                action="access_requested",
                reason=reason,
                event_metadata={
                    "status": "attempted",
                    "limit": limit,
                    "offset": offset,
                },
            )
            audit_session.commit()
            audit_event_id = event.id
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Administrative audit logging failed; access denied",
        )

    # 3. Fetch messages from database
    conv_svc = ConversationService(db)
    messages = conv_svc.list_messages(
        tenant_id=target_tenant_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )

    # 4. Post-fetch audit finalization
    try:
        with SessionLocal() as audit_session:
            audit_svc = AuditService(audit_session)
            audit_svc.update_access_event_status(
                event_id=audit_event_id,
                status="disclosed",
                extra_metadata={
                    "disclosed_count": len(messages),
                },
            )
            audit_session.commit()
    except Exception:
        # Prevent unconfirmed disclosure: mark failure and abort response
        try:
            with SessionLocal() as fail_session:
                audit_svc = AuditService(fail_session)
                audit_svc.update_access_event_status(
                    event_id=audit_event_id,
                    status="audit_finalization_failed",
                    extra_metadata={"error": "failed_to_finalize_audit"},
                )
                fail_session.commit()
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Administrative audit finalization failed; access disclosure blocked",
        )

    # 5. Safe serialization: content delivered only after confirmed audit finalization
    return [
        {
            "id": str(m.id),
            "tenant_id": str(m.tenant_id),
            "conversation_id": str(m.conversation_id),
            "customer_id": str(m.customer_id) if m.customer_id else None,
            "sender_type": m.sender_type,
            "sender_id": str(m.sender_id) if m.sender_id else None,
            "message_type": m.message_type,
            "content": m.content,
            "external_id": m.external_id,
            "metadata_json": m.metadata_json or {},
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


# =============================================================================
# 5. Operational Emergency Infrastructure Interventions
# =============================================================================

@router.patch("/platform/tenants/{tenant_id}/channels/{channel_id}/status")
def emergency_update_channel_status(
    tenant_id: UUID,
    channel_id: UUID,
    payload: EmergencyChannelStatusRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Emergency intervention: toggle channel operational status (active / disabled).
    Strict multi-tenant isolation, state transition verification, and atomic audit logging.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.tenant_id == target_tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found for this tenant",
        )

    if channel.status == payload.status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Channel is already in status '{channel.status}'",
        )

    old_status = channel.status
    channel.status = payload.status

    try:
        audit_svc = AuditService(db)
        audit_svc.record_event(
            tenant_id=target_tenant_id,
            user_id=current_user.id,
            event_type="admin.emergency.channel_status",
            action="emergency_channel_status_change",
            description=(
                f"Platform admin '{current_user.email}' changed channel '{channel.id}' "
                f"status from '{old_status}' to '{payload.status}'."
            ),
            event_metadata={
                "channel_id": str(channel.id),
                "channel_type": channel.channel_type,
                "old_status": old_status,
                "new_status": payload.status,
                "reason": payload.reason,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "tenant_id": str(target_tenant_id),
        "channel_id": str(channel.id),
        "old_status": old_status,
        "new_status": payload.status,
    }


@router.patch("/platform/tenants/{tenant_id}/agents/{agent_id}/status")
def emergency_update_agent_status(
    tenant_id: UUID,
    agent_id: UUID,
    payload: EmergencyAgentStatusRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Emergency intervention: toggle agent operational status (active / disabled).
    Strict multi-tenant isolation, state transition verification, and atomic audit logging.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == target_tenant_id,
        )
    )
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found for this tenant",
        )

    if agent.status == payload.status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent is already in status '{agent.status}'",
        )

    old_status = agent.status
    agent.status = payload.status

    try:
        audit_svc = AuditService(db)
        audit_svc.record_event(
            tenant_id=target_tenant_id,
            user_id=current_user.id,
            event_type="admin.emergency.agent_status",
            action="emergency_agent_status_change",
            description=(
                f"Platform admin '{current_user.email}' changed agent '{agent.id}' "
                f"status from '{old_status}' to '{payload.status}'."
            ),
            event_metadata={
                "agent_id": str(agent.id),
                "old_status": old_status,
                "new_status": payload.status,
                "reason": payload.reason,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "tenant_id": str(target_tenant_id),
        "agent_id": str(agent.id),
        "old_status": old_status,
        "new_status": payload.status,
    }


@router.post("/platform/tenants/{tenant_id}/tasks/{task_id}/emergency-cancel")
def emergency_cancel_task(
    tenant_id: UUID,
    task_id: UUID,
    payload: EmergencyTaskCancelRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Emergency intervention: abort and cancel a stuck or runaway task.
    Rejects terminal tasks (completed, failed, cancelled) with 409 Conflict.
    Enforces atomic mutation and audit logging.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    task = db.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.tenant_id == target_tenant_id,
        )
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found for this tenant",
        )

    if task.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel task in terminal status '{task.status}'",
        )

    old_status = task.status
    task.status = "cancelled"
    task.error = f"Emergency cancellation by platform admin: {payload.reason}"

    try:
        audit_svc = AuditService(db)
        audit_svc.record_event(
            tenant_id=target_tenant_id,
            user_id=current_user.id,
            event_type="admin.emergency.task_cancelled",
            action="emergency_task_cancel",
            description=(
                f"Platform admin '{current_user.email}' emergency cancelled task '{task.id}' "
                f"in status '{old_status}'."
            ),
            event_metadata={
                "task_id": str(task.id),
                "old_status": old_status,
                "new_status": "cancelled",
                "reason": payload.reason,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "tenant_id": str(target_tenant_id),
        "task_id": str(task.id),
        "old_status": old_status,
        "new_status": "cancelled",
    }


# =============================================================================
# 6. Tenant Management Detail Hub Endpoints
# =============================================================================

@router.get("/platform/tenants/{tenant_id}/tasks")
def list_tenant_tasks_admin(
    tenant_id: UUID,
    status: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Paginated list of tasks for a specific tenant with optional status and agent filters.
    Strict tenant validation is enforced.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    service = AdminDashboardService(db)
    return service.get_tenant_tasks(
        tenant_id=target_tenant_id,
        status=status,
        agent_id=agent_id,
        limit=limit,
        offset=offset,
    )


@router.get("/platform/tenants/{tenant_id}/traces")
def list_tenant_traces_admin(
    tenant_id: UUID,
    status: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    task_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    conversation_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Paginated execution traces for a specific tenant with status, trigger, and association filters.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    effective_limit = max(1, min(limit, 100))
    service = TracingQueryService(db)
    items, total = service.list_traces(
        tenant_id=target_tenant_id,
        status=status,
        trigger_type=trigger_type,
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        limit=effective_limit,
        offset=offset,
        sort_order=sort_order,
    )
    return {
        "tenant_id": str(target_tenant_id),
        "items": items,
        "total": total,
        "limit": effective_limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
    }


@router.get("/platform/tenants/{tenant_id}/traces/{trace_id}/steps")
def get_tenant_trace_steps_admin(
    tenant_id: UUID,
    trace_id: UUID,
    format: str = Query(default="tree", pattern="^(tree|flat)$"),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    Execution steps hierarchy (tree or flat) for a specific trace within a tenant.
    Guarantees strict tenant scoping.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = TracingQueryService(db)
    steps = service.get_trace_steps(
        tenant_id=target_tenant_id,
        trace_id_or_pk=trace_id,
        format=format,
    )
    if steps is None:
        raise HTTPException(status_code=404, detail="Execution trace not found")
    return steps


@router.get("/platform/tenants/{tenant_id}/traces/{trace_id}")
def get_tenant_trace_admin(
    tenant_id: UUID,
    trace_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get detailed execution trace record by UUID for a specific tenant.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = TracingQueryService(db)
    trace = service.get_trace(tenant_id=target_tenant_id, trace_id_or_pk=trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Execution trace not found")
    return trace


@router.get("/platform/tenants/{tenant_id}/integrations")
def list_tenant_integrations_admin(
    tenant_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    List AI integrations visible to this tenant (tenant-specific + global platform defaults).
    All secret API keys are masked.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = AdminDashboardService(db)
    return service.get_tenant_integrations(target_tenant_id)


@router.patch("/platform/tenants/{tenant_id}/integrations/{integration_id}/status")
def update_tenant_integration_status_admin(
    tenant_id: UUID,
    integration_id: UUID,
    payload: TenantIntegrationStatusUpdateRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform admin updates the operational status of an integration configured for a tenant.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = AIProviderService(db)
    try:
        dto = service.update_status(
            tenant_id=target_tenant_id,
            integration_id=integration_id,
            status=payload.status,
        )
        db.commit()
        return dto
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/platform/tenants/{tenant_id}/integrations", status_code=status.HTTP_201_CREATED)
def create_tenant_integration_admin(
    tenant_id: UUID,
    payload: TenantIntegrationCreateRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform admin registers an AI provider integration specifically for this tenant.
    API keys are encrypted at rest with AES-256-GCM in tenant's credentials.
    Returned DTO always masks secrets.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = AIProviderService(db)
    try:
        dto = service.register_or_update_config(
            tenant_id=target_tenant_id,
            name=payload.name,
            provider=payload.provider,
            model=payload.model,
            api_key=payload.api_key,
            base_url=payload.base_url,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            is_default=payload.is_default,
            extra_params=payload.extra_params,
        )
        db.commit()
        return dto
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/platform/tenants/{tenant_id}/integrations/{integration_id}/test", status_code=status.HTTP_200_OK)
def test_tenant_integration_admin(
    tenant_id: UUID,
    integration_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Platform admin triggers an isolated live connection test for an integration configured for this tenant.
    Verifies that the integration belongs to this tenant or is platform-level fallback.
    Executes live handshake without leaking secrets, updates DB telemetry, and logs audit record.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    integration = db.scalar(
        select(Integration).where(
            Integration.id == integration_id,
            or_(Integration.tenant_id == target_tenant_id, Integration.tenant_id.is_(None)),
            Integration.status != "deleted",
        )
    )
    if integration is None:
        raise HTTPException(
            status_code=404,
            detail=f"Integration '{integration_id}' not found for tenant '{target_tenant_id}'",
        )

    service = AIProviderService(db)
    try:
        test_result = service.test_config(tenant_id=target_tenant_id, integration_id=integration_id)
        db.commit()
        return test_result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/platform/tenants/{tenant_id}/capabilities")
def get_tenant_capabilities_admin(
    tenant_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get tenant capabilities logically separated:
    - tenant_capabilities (custom for this tenant)
    - shared_capabilities (approved global platform library)
    - self_development_versions (proposals and versions)
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = AdminDashboardService(db)
    return service.get_tenant_capabilities(target_tenant_id)


@router.get("/platform/tenants/{tenant_id}/errors")
def get_tenant_errors_admin(
    tenant_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Diagnostic error center: aggregates real failure events across tasks, traces, AI telemetry, and outbox.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = AdminDashboardService(db)
    return service.get_tenant_errors(tenant_id=target_tenant_id, limit=limit)


# =============================================================================
# 7. Tenant Communication Channels Management (Platform Admin Hub)
# =============================================================================

@router.get("/platform/tenants/{tenant_id}/channels", status_code=status.HTTP_200_OK)
def list_tenant_channels_admin(
    tenant_id: UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    channel_type: str | None = Query(default=None),
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """
    List all communication channels registered for a specific tenant with masked secrets.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = ChannelService(db)
    channels = service.list_channels(tenant_id=target_tenant_id, status=status_filter, channel_type=channel_type)
    return [serialize_channel(ch, service) for ch in channels]


@router.post("/platform/tenants/{tenant_id}/channels", status_code=status.HTTP_201_CREATED)
def create_tenant_channel_admin(
    tenant_id: UUID,
    payload: TenantChannelCreateRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Register a communication channel (Telegram, WhatsApp, Facebook, Instagram, etc.)
    scoped strictly to a specific tenant with AES-256-GCM encrypted secrets.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = ChannelService(db)
    try:
        channel = service.register_channel(
            tenant_id=target_tenant_id,
            name=payload.name,
            channel_type=payload.channel_type,
            provider=payload.provider,
            config=payload.config,
        )
        db.commit()
        return serialize_channel(channel, service)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/platform/tenants/{tenant_id}/channels/{channel_id}", status_code=status.HTTP_200_OK)
def get_tenant_channel_admin(
    tenant_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Retrieve details of a specific communication channel for a tenant (secrets masked).
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = ChannelService(db)
    channel = service.get_channel(tenant_id=target_tenant_id, channel_id=channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found for tenant '{target_tenant_id}'")
    return serialize_channel(channel, service)


@router.patch("/platform/tenants/{tenant_id}/channels/{channel_id}", status_code=status.HTTP_200_OK)
def update_tenant_channel_admin(
    tenant_id: UUID,
    channel_id: UUID,
    payload: TenantChannelUpdateRequest,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Update configuration, credentials, or operational status of a tenant's communication channel.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = ChannelService(db)
    try:
        channel = service.update_channel(
            tenant_id=target_tenant_id,
            channel_id=channel_id,
            name=payload.name,
            status=payload.status,
            provider=payload.provider,
            config=payload.config,
        )
        db.commit()
        return serialize_channel(channel, service)
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.post("/platform/tenants/{tenant_id}/channels/{channel_id}/test", status_code=status.HTTP_200_OK)
def test_tenant_channel_admin(
    tenant_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Execute an isolated live connectivity test against the channel connector without leaking secrets.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = ChannelService(db)
    channel = service.get_channel(tenant_id=target_tenant_id, channel_id=channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found for tenant '{target_tenant_id}'")

    try:
        result = service.test_channel_connection(tenant_id=target_tenant_id, channel_id=channel_id)
        db.commit()
        return result.to_dict()
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.delete("/platform/tenants/{tenant_id}/channels/{channel_id}", status_code=status.HTTP_200_OK)
def delete_tenant_channel_admin(
    tenant_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Soft-delete a communication channel registered for this tenant.
    """
    target_tenant_id = resolve_target_tenant_id(current_user, tenant_id)
    tenant = db.scalar(select(Tenant).where(Tenant.id == target_tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    service = ChannelService(db)
    try:
        service.delete_channel(tenant_id=target_tenant_id, channel_id=channel_id)
        db.commit()
        return {"status": "deleted", "channel_id": str(channel_id)}
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


