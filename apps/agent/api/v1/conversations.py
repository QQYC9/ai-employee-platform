from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import Conversation, Message, User
from packages.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


class ConversationStartRequest(BaseModel):
    customer_id: UUID | None = None
    channel_id: UUID | None = None
    subject: str | None = None
    external_id: str | None = None
    metadata_json: dict[str, Any] | None = None


class ConversationStatusRequest(BaseModel):
    status: str


class MessageSendRequest(BaseModel):
    sender_type: str
    content: str | None = None
    sender_id: UUID | None = None
    customer_id: UUID | None = None
    message_type: str = "text"
    external_id: str | None = None
    metadata_json: dict[str, Any] | None = None


def serialize_conversation(conv: Conversation) -> dict[str, Any]:
    return {
        "id": str(conv.id),
        "tenant_id": str(conv.tenant_id),
        "customer_id": str(conv.customer_id) if conv.customer_id else None,
        "channel_id": str(conv.channel_id) if conv.channel_id else None,
        "subject": conv.subject,
        "external_id": conv.external_id,
        "status": conv.status,
        "metadata_json": conv.metadata_json or {},
        "started_at": conv.started_at.isoformat() if conv.started_at else None,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "closed_at": conv.closed_at.isoformat() if conv.closed_at else None,
    }


def serialize_message(msg: Message) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "tenant_id": str(msg.tenant_id),
        "conversation_id": str(msg.conversation_id),
        "customer_id": str(msg.customer_id) if msg.customer_id else None,
        "sender_type": msg.sender_type,
        "sender_id": str(msg.sender_id) if msg.sender_id else None,
        "message_type": msg.message_type,
        "content": msg.content,
        "external_id": msg.external_id,
        "metadata_json": msg.metadata_json or {},
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def start_conversation(
    payload: ConversationStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    try:
        conv = service.start_conversation(
            tenant_id=current_user.tenant_id,
            customer_id=payload.customer_id,
            channel_id=payload.channel_id,
            subject=payload.subject,
            external_id=payload.external_id,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        db.refresh(conv)
        return serialize_conversation(conv)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_conversations(
    customer_id: UUID | None = Query(default=None),
    channel_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    try:
        conversations = service.list_conversations(
            tenant_id=current_user.tenant_id,
            customer_id=customer_id,
            channel_id=channel_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [serialize_conversation(c) for c in conversations]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    conv = service.get_conversation(current_user.tenant_id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return serialize_conversation(conv)


@router.patch("/{conversation_id}/status")
def update_conversation_status(
    conversation_id: UUID,
    payload: ConversationStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    try:
        conv = service.update_status(
            tenant_id=current_user.tenant_id,
            conversation_id=conversation_id,
            status=payload.status,
        )
        db.commit()
        db.refresh(conv)
        return serialize_conversation(conv)
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
def send_message(
    conversation_id: UUID,
    payload: MessageSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    try:
        # Default sender_id to current_user.id if sender_type is 'user' and sender_id not provided
        sender_id = payload.sender_id
        if payload.sender_type == "user" and sender_id is None:
            sender_id = current_user.id

        msg = service.send_message(
            tenant_id=current_user.tenant_id,
            conversation_id=conversation_id,
            sender_type=payload.sender_type,
            content=payload.content,
            sender_id=sender_id,
            customer_id=payload.customer_id,
            message_type=payload.message_type,
            external_id=payload.external_id,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        db.refresh(msg)
        return serialize_message(msg)
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ConversationService(db)
    try:
        messages = service.list_messages(
            tenant_id=current_user.tenant_id,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
        return [serialize_message(m) for m in messages]
    except ValueError as exc:
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)
