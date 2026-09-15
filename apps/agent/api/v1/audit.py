from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import AuditEvent, User
from packages.services.audit_service import AuditService


router = APIRouter(
    prefix="/audit",
    tags=["audit"],
)


def audit_response(event: AuditEvent) -> dict:
    return {
        "id": str(event.id),
        "tenant_id": (
            str(event.tenant_id)
            if event.tenant_id is not None
            else None
        ),
        "agent_id": (
            str(event.agent_id)
            if event.agent_id is not None
            else None
        ),
        "user_id": (
            str(event.user_id)
            if event.user_id is not None
            else None
        ),
        "event_type": event.event_type,
        "action": event.action,
        "description": event.description,
        "event_metadata": event.event_metadata,
        "created_at": event.created_at,
    }


@router.get("")
def list_audit_events(
    event_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = AuditService(db)

    try:
        events = service.list_events(
            tenant_id=current_user.tenant_id,
            event_type=event_type,
            action=action,
            agent_id=agent_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return [
        audit_response(event)
        for event in events
    ]


@router.get("/{event_id}")
def get_audit_event(
    event_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    service = AuditService(db)

    event = service.get_event(
        tenant_id=current_user.tenant_id,
        event_id=event_id,
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Audit event not found",
        )

    return audit_response(event)
