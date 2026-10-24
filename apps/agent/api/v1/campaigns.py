from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import Campaign, CampaignRecipient, User
from packages.services.campaign_service import (
    ApprovalRequiredError,
    CampaignError,
    CampaignService,
    InvalidStateTransitionError,
)
from packages.services.proactive_notification_service import ProactiveNotificationService

router = APIRouter(prefix="/campaigns", tags=["Campaigns & Proactive Notifications"])


# -----------------------------------------------------------------------------
# Request Schemas
# -----------------------------------------------------------------------------

class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    message_template: str = Field(..., min_length=1)
    goal: str | None = None
    channel_id: UUID | None = None
    audience_filter: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    requires_approval: bool = False
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)
    batch_size: int = Field(default=50, ge=1, le=500)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdateRequest(BaseModel):
    name: str | None = None
    message_template: str | None = None
    goal: str | None = None
    channel_id: UUID | None = None
    audience_filter: dict[str, Any] | None = None
    scheduled_at: datetime | None = None
    requires_approval: bool | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=1000)
    batch_size: int | None = Field(default=None, ge=1, le=500)
    metadata_json: dict[str, Any] | None = None


class CampaignScheduleRequest(BaseModel):
    scheduled_at: datetime


class ProactiveTriggerRequest(BaseModel):
    customer_id: UUID
    channel_id: UUID
    notification_type: str = Field(
        default="custom",
        description="appointment_reminder, service_followup, inactivity_reengagement, custom",
    )
    content: str | None = None
    appointment_time: str | None = None
    service_name: str | None = None
    feedback_url: str | None = None
    offer_details: str | None = None
    requires_approval: bool = False


# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------

def serialize_campaign(c: Campaign) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "tenant_id": str(c.tenant_id),
        "name": c.name,
        "goal": c.goal,
        "message_template": c.message_template,
        "channel_id": str(c.channel_id) if c.channel_id else None,
        "status": c.status,
        "audience_filter": c.audience_filter or {},
        "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        "metrics": c.metrics or {},
        "requires_approval": c.requires_approval,
        "approval_id": str(c.approval_id) if c.approval_id else None,
        "rate_limit_per_minute": c.rate_limit_per_minute,
        "batch_size": c.batch_size,
        "metadata_json": c.metadata_json or {},
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def serialize_recipient(r: CampaignRecipient) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "tenant_id": str(r.tenant_id),
        "campaign_id": str(r.campaign_id),
        "customer_id": str(r.customer_id),
        "channel_id": str(r.channel_id) if r.channel_id else None,
        "recipient_address": r.recipient_address,
        "status": r.status,
        "skip_reason": r.skip_reason,
        "error_message": r.error_message,
        "message_id": str(r.message_id) if r.message_id else None,
        "outbox_event_id": str(r.outbox_event_id) if r.outbox_event_id else None,
        "rendered_content": r.rendered_content,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.create_campaign(
            tenant_id=current_user.tenant_id,
            name=payload.name,
            message_template=payload.message_template,
            goal=payload.goal,
            channel_id=payload.channel_id,
            audience_filter=payload.audience_filter,
            scheduled_at=payload.scheduled_at,
            requires_approval=payload.requires_approval,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            batch_size=payload.batch_size,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        return serialize_campaign(camp)
    except CampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_campaigns(
    status: str | None = Query(None, description="draft, scheduled, running, paused, completed, cancelled"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    items = service.list_campaigns(
        current_user.tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [serialize_campaign(c) for c in items],
        "limit": limit,
        "offset": offset,
        "total": len(items),
    }


@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    camp = service.get_campaign(current_user.tenant_id, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return serialize_campaign(camp)


@router.patch("/{campaign_id}")
def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.update_campaign(
            tenant_id=current_user.tenant_id,
            campaign_id=campaign_id,
            name=payload.name,
            goal=payload.goal,
            message_template=payload.message_template,
            channel_id=payload.channel_id,
            audience_filter=payload.audience_filter,
            scheduled_at=payload.scheduled_at,
            requires_approval=payload.requires_approval,
            rate_limit_per_minute=payload.rate_limit_per_minute,
            batch_size=payload.batch_size,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        return serialize_campaign(camp)
    except CampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{campaign_id}/schedule")
def schedule_campaign(
    campaign_id: UUID,
    payload: CampaignScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.schedule_campaign(
            current_user.tenant_id,
            campaign_id,
            payload.scheduled_at,
        )
        db.commit()
        return serialize_campaign(camp)
    except (CampaignError, InvalidStateTransitionError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{campaign_id}/start")
def start_campaign(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.start_campaign(current_user.tenant_id, campaign_id)
        # Immediately process initial batch
        service.process_campaign_batch(current_user.tenant_id, campaign_id)
        db.commit()
        return serialize_campaign(camp)
    except ApprovalRequiredError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except (CampaignError, InvalidStateTransitionError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{campaign_id}/pause")
def pause_campaign(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.pause_campaign(current_user.tenant_id, campaign_id)
        db.commit()
        return serialize_campaign(camp)
    except (CampaignError, InvalidStateTransitionError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{campaign_id}/resume")
def resume_campaign(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.resume_campaign(current_user.tenant_id, campaign_id)
        # Continue processing batch
        service.process_campaign_batch(current_user.tenant_id, campaign_id)
        db.commit()
        return serialize_campaign(camp)
    except (CampaignError, InvalidStateTransitionError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{campaign_id}/cancel")
def cancel_campaign(
    campaign_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        camp = service.cancel_campaign(current_user.tenant_id, campaign_id)
        db.commit()
        return serialize_campaign(camp)
    except (CampaignError, InvalidStateTransitionError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{campaign_id}/process-batch")
def process_campaign_batch(
    campaign_id: UUID,
    batch_size: int | None = Query(None, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    try:
        enqueued = service.process_campaign_batch(
            current_user.tenant_id,
            campaign_id,
            batch_size=batch_size,
        )
        db.commit()
        camp = service.get_campaign(current_user.tenant_id, campaign_id)
        return {
            "enqueued_count": enqueued,
            "campaign": serialize_campaign(camp) if camp else None,
        }
    except CampaignError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{campaign_id}/recipients")
def list_recipients(
    campaign_id: UUID,
    status: str | None = Query(None, description="pending, enqueued, sent, delivered, failed, skipped"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = CampaignService(db)
    camp = service.get_campaign(current_user.tenant_id, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    recipients = service.get_recipients(
        current_user.tenant_id,
        campaign_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [serialize_recipient(r) for r in recipients],
        "limit": limit,
        "offset": offset,
        "total": len(recipients),
    }


# -----------------------------------------------------------------------------
# Proactive Customer Notifications Endpoint
# -----------------------------------------------------------------------------

@router.post("/proactive/trigger", status_code=status.HTTP_201_CREATED)
def trigger_proactive_notification(
    payload: ProactiveTriggerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")

    service = ProactiveNotificationService(db)
    ntype = (payload.notification_type or "custom").lower().strip()

    try:
        if ntype == "appointment_reminder":
            if not payload.appointment_time or not payload.service_name:
                raise ValueError("appointment_time and service_name are required for appointment reminders")
            res = service.send_appointment_reminder(
                tenant_id=current_user.tenant_id,
                customer_id=payload.customer_id,
                channel_id=payload.channel_id,
                appointment_time=payload.appointment_time,
                service_name=payload.service_name,
                requires_approval=payload.requires_approval,
            )
        elif ntype == "service_followup":
            if not payload.service_name:
                raise ValueError("service_name is required for service follow-up")
            res = service.send_service_followup(
                tenant_id=current_user.tenant_id,
                customer_id=payload.customer_id,
                channel_id=payload.channel_id,
                service_name=payload.service_name,
                feedback_url=payload.feedback_url,
                requires_approval=payload.requires_approval,
            )
        elif ntype == "inactivity_reengagement":
            res = service.send_inactivity_reengagement(
                tenant_id=current_user.tenant_id,
                customer_id=payload.customer_id,
                channel_id=payload.channel_id,
                offer_details=payload.offer_details,
                requires_approval=payload.requires_approval,
            )
        else:
            if not payload.content:
                raise ValueError("content is required for custom proactive message")
            res = service.send_proactive_customer_message(
                tenant_id=current_user.tenant_id,
                customer_id=payload.customer_id,
                channel_id=payload.channel_id,
                content=payload.content,
                notification_type=ntype,
                requires_approval=payload.requires_approval,
            )

        db.commit()
        return res
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
