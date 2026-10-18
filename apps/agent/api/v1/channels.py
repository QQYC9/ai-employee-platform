from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import Channel, User
from packages.services.channel_service import ChannelService

router = APIRouter(prefix="/channels", tags=["Channels"])


@router.get("/status")
def channels_status():
    return {
        "status": "ok",
        "service": "channels",
    }


class ChannelRegisterRequest(BaseModel):
    name: str
    channel_type: str
    provider: str | None = None
    config: dict[str, Any] | None = None


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    provider: str | None = None
    config: dict[str, Any] | None = None


def serialize_channel(channel: Channel, service: ChannelService | None = None) -> dict[str, Any]:
    safe_config = (
        service.sanitize_channel_config(channel.config)
        if service is not None
        else ChannelService(None).sanitize_channel_config(channel.config) if hasattr(ChannelService, "sanitize_channel_config") else (channel.config or {})
    )
    return {
        "id": str(channel.id),
        "tenant_id": str(channel.tenant_id),
        "name": channel.name,
        "channel_type": channel.channel_type,
        "provider": channel.provider,
        "status": channel.status,
        "config": safe_config,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
        "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
    }



def _require_admin(user: User):
    user_role = (user.role or "").strip().lower()
    is_admin = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Forbidden: Admin or Owner role required")


@router.post("", status_code=status.HTTP_201_CREATED)
def register_channel(
    payload: ChannelRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    service = ChannelService(db)
    try:
        channel = service.register_channel(
            tenant_id=current_user.tenant_id,
            name=payload.name,
            channel_type=payload.channel_type,
            provider=payload.provider,
            config=payload.config,
        )
        db.commit()
        db.refresh(channel)
        return serialize_channel(channel)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_channels(
    status: str | None = Query(default=None),
    channel_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChannelService(db)
    try:
        channels = service.list_channels(
            tenant_id=current_user.tenant_id,
            status=status,
            channel_type=channel_type,
        )
        return [serialize_channel(ch) for ch in channels]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{channel_id}")
def get_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ChannelService(db)
    channel = service.get_channel(current_user.tenant_id, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return serialize_channel(channel)


@router.patch("/{channel_id}")
def update_channel(
    channel_id: UUID,
    payload: ChannelUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    service = ChannelService(db)
    try:
        channel = service.update_channel(
            tenant_id=current_user.tenant_id,
            channel_id=channel_id,
            name=payload.name,
            status=payload.status,
            provider=payload.provider,
            config=payload.config,
        )
        db.commit()
        db.refresh(channel)
        return serialize_channel(channel)
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.delete("/{channel_id}")
def delete_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    service = ChannelService(db)
    try:
        service.delete_channel(current_user.tenant_id, channel_id)
        db.commit()
        return {"status": "success", "message": "Channel deleted"}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


class ChannelSendMessageRequest(BaseModel):
    recipient: str
    content: str
    options: dict[str, Any] | None = None


@router.post("/{channel_id}/test")
def test_channel_connection(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Probes channel connectivity and credentials."""
    service = ChannelService(db)
    try:
        result = service.test_channel_connection(current_user.tenant_id, channel_id)
        db.commit()
        return result.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{channel_id}/send")
def send_channel_message(
    channel_id: UUID,
    payload: ChannelSendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sends a message to an external recipient via the configured channel."""
    service = ChannelService(db)
    try:
        opts = payload.options or {}
        result = service.send_channel_message(
            tenant_id=current_user.tenant_id,
            channel_id=channel_id,
            recipient=payload.recipient,
            content=payload.content,
            **opts,
        )
        db.commit()
        if not result.success:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result.error)
        return result.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
