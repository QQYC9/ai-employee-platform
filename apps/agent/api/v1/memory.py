from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.memory.models import MemoryStatus, MemoryType
from packages.memory.sanitizer import SecretDetectedError
from packages.memory.service import MemoryService
from packages.models.domain import Memory, User

router = APIRouter(prefix="/memories", tags=["Memories"])


class MemoryCreateRequest(BaseModel):
    content: str
    memory_type: str = MemoryType.GENERAL
    importance: int = 50
    confidence: int = 50
    agent_id: UUID | None = None
    customer_id: UUID | None = None
    conversation_id: UUID | None = None
    task_id: UUID | None = None
    source: str = "manual"
    metadata_json: dict[str, Any] | None = None
    expires_at: datetime | None = None


class MemoryUpdateRequest(BaseModel):
    content: str | None = None
    importance: int | None = None
    confidence: int | None = None
    status: str | None = None
    expires_at: datetime | None = None
    metadata_json: dict[str, Any] | None = None


class MemorySupersedeRequest(BaseModel):
    new_content: str
    reason: str | None = None
    importance: int | None = None
    confidence: int | None = None


class MemoryInvalidateRequest(BaseModel):
    reason: str


def serialize_memory(memory: Memory) -> dict[str, Any]:
    return {
        "id": str(memory.id),
        "tenant_id": str(memory.tenant_id),
        "agent_id": str(memory.agent_id) if memory.agent_id else None,
        "user_id": str(memory.user_id) if memory.user_id else None,
        "memory_type": memory.memory_type,
        "content": memory.content,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "status": memory.status,
        "metadata_json": memory.metadata_json or {},
        "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def _require_admin(user: User):
    user_role = (user.role or "").strip().lower()
    is_admin = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Forbidden: Admin or Owner role required")


@router.get("/status")
def memories_status():
    return {
        "status": "ok",
        "service": "memories",
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: MemoryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MemoryService(db)
    try:
        memory = service.create_memory(
            tenant_id=current_user.tenant_id,
            content=payload.content,
            memory_type=payload.memory_type,
            importance=payload.importance,
            confidence=payload.confidence,
            agent_id=payload.agent_id,
            user_id=current_user.id,
            customer_id=payload.customer_id,
            conversation_id=payload.conversation_id,
            task_id=payload.task_id,
            source=payload.source,
            metadata_json=payload.metadata_json,
            expires_at=payload.expires_at,
        )
        db.commit()
        db.refresh(memory)
        return serialize_memory(memory)
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_memories(
    status: str | None = Query(default=None),
    memory_type: str | None = Query(default=None),
    customer_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    include_expired: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MemoryService(db)
    try:
        memories = service.list_memories(
            tenant_id=current_user.tenant_id,
            status=status,
            memory_type=memory_type,
            customer_id=customer_id,
            agent_id=agent_id,
            search=search,
            include_expired=include_expired,
            limit=limit,
            offset=offset,
        )
        return [serialize_memory(m) for m in memories]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{memory_id}")
def get_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MemoryService(db)
    memory = service.get_memory(current_user.tenant_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return serialize_memory(memory)


@router.patch("/{memory_id}")
def update_memory(
    memory_id: UUID,
    payload: MemoryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MemoryService(db)
    try:
        memory = service.update_memory(
            tenant_id=current_user.tenant_id,
            memory_id=memory_id,
            content=payload.content,
            importance=payload.importance,
            confidence=payload.confidence,
            status=payload.status,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata_json,
        )
        db.commit()
        db.refresh(memory)
        return serialize_memory(memory)
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.post("/{memory_id}/supersede")
def supersede_memory(
    memory_id: UUID,
    payload: MemorySupersedeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MemoryService(db)
    try:
        new_memory = service.supersede_memory(
            tenant_id=current_user.tenant_id,
            old_memory_id=memory_id,
            new_content=payload.new_content,
            reason=payload.reason,
            importance=payload.importance,
            confidence=payload.confidence,
        )
        db.commit()
        db.refresh(new_memory)
        return serialize_memory(new_memory)
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.post("/{memory_id}/invalidate")
def invalidate_memory(
    memory_id: UUID,
    payload: MemoryInvalidateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MemoryService(db)
    try:
        memory = service.invalidate_memory(
            tenant_id=current_user.tenant_id,
            memory_id=memory_id,
            reason=payload.reason,
        )
        db.commit()
        db.refresh(memory)
        return serialize_memory(memory)
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=404, detail=detail_msg)
        raise HTTPException(status_code=400, detail=detail_msg)


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user)
    service = MemoryService(db)
    try:
        service.delete_memory(current_user.tenant_id, memory_id)
        db.commit()
        return {"status": "success", "message": "Memory deleted"}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
