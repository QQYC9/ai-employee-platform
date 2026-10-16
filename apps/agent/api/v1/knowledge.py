from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.memory.sanitizer import SecretDetectedError
from packages.models.domain import User
from packages.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


class KnowledgeCreateRequest(BaseModel):
    title: str
    content: str
    knowledge_type: str = "general"
    status: str = "active"
    metadata_json: dict[str, Any] | None = None
    provenance_id: UUID | None = None
    source_id: UUID | None = None


class KnowledgeUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    knowledge_type: str | None = None
    status: str | None = None
    metadata_json: dict[str, Any] | None = None
    provenance_id: UUID | None = None


class KnowledgeDeactivateRequest(BaseModel):
    reason: str | None = None


class KnowledgeConflictFlagRequest(BaseModel):
    conflicting_knowledge_id: UUID
    reason: str


class KnowledgeConflictResolveRequest(BaseModel):
    loser_knowledge_id: UUID
    resolution_reason: str


def _require_admin(user: User) -> None:
    user_role = (user.role or "").strip().lower()
    is_admin = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin or Owner role required",
        )


def _require_knowledge_writer(user: User) -> None:
    user_role = (user.role or "").strip().lower()
    is_allowed = user_role in (
        "owner",
        "tenant_owner",
        "admin",
        "tenant_admin",
        "manager",
        "superadmin",
        "platform_admin",
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Manager, Admin, or Owner role required to mutate knowledge",
        )


@router.get("/status")
def knowledge_status():
    return {
        "status": "ok",
        "service": "knowledge",
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_knowledge(
    payload: KnowledgeCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    _require_knowledge_writer(current_user)

    service = KnowledgeService(db)
    try:
        item = service.create_knowledge(
            tenant_id=current_user.tenant_id,
            title=payload.title,
            content=payload.content,
            knowledge_type=payload.knowledge_type,
            status=payload.status,
            metadata_json=payload.metadata_json,
            provenance_id=payload.provenance_id,
            source_id=payload.source_id,
            user_id=current_user.id,
        )
        db.commit()
        return service.serialize_knowledge(item)
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("")
def list_knowledge(
    knowledge_type: str | None = Query(None),
    item_status: str | None = Query(None, alias="status"),
    customer_id: UUID | None = Query(None),
    query: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    service = KnowledgeService(db)
    items, total = service.list_knowledge(
        tenant_id=current_user.tenant_id,
        knowledge_type=knowledge_type,
        status=item_status,
        customer_id=customer_id,
        query=query,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [service.serialize_knowledge(k) for k in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/search")
def search_knowledge(
    query: str = Query(..., min_length=1),
    knowledge_type: str | None = Query(None),
    customer_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    service = KnowledgeService(db)
    items = service.search_knowledge(
        tenant_id=current_user.tenant_id,
        query=query,
        knowledge_type=knowledge_type,
        customer_id=customer_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [service.serialize_knowledge(k) for k in items],
        "query": query,
        "total": len(items),
    }


@router.get("/{knowledge_id}")
def get_knowledge_item(
    knowledge_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    service = KnowledgeService(db)
    item = service.get_knowledge(current_user.tenant_id, knowledge_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")

    return service.serialize_knowledge(item)


@router.patch("/{knowledge_id}")
def update_knowledge_item(
    knowledge_id: UUID,
    payload: KnowledgeUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    _require_knowledge_writer(current_user)

    service = KnowledgeService(db)
    try:
        item = service.update_knowledge(
            tenant_id=current_user.tenant_id,
            knowledge_id=knowledge_id,
            title=payload.title,
            content=payload.content,
            knowledge_type=payload.knowledge_type,
            status=payload.status,
            metadata_json=payload.metadata_json,
            provenance_id=payload.provenance_id,
            user_id=current_user.id,
        )
        db.commit()
        return service.serialize_knowledge(item)
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{knowledge_id}/activate")
def activate_knowledge_item(
    knowledge_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    _require_knowledge_writer(current_user)

    service = KnowledgeService(db)
    try:
        item = service.activate_knowledge(
            tenant_id=current_user.tenant_id,
            knowledge_id=knowledge_id,
            user_id=current_user.id,
        )
        db.commit()
        return service.serialize_knowledge(item)
    except ValueError as exc:
        db.rollback()
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{knowledge_id}/deactivate")
def deactivate_knowledge_item(
    knowledge_id: UUID,
    payload: KnowledgeDeactivateRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    _require_knowledge_writer(current_user)

    service = KnowledgeService(db)
    reason = payload.reason if payload else None
    try:
        item = service.deactivate_knowledge(
            tenant_id=current_user.tenant_id,
            knowledge_id=knowledge_id,
            reason=reason,
            user_id=current_user.id,
        )
        db.commit()
        return service.serialize_knowledge(item)
    except ValueError as exc:
        db.rollback()
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{knowledge_id}/flag-conflict")
def flag_knowledge_conflict(
    knowledge_id: UUID,
    payload: KnowledgeConflictFlagRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    _require_knowledge_writer(current_user)

    service = KnowledgeService(db)
    try:
        item_a, item_b = service.flag_conflict(
            tenant_id=current_user.tenant_id,
            knowledge_id=knowledge_id,
            conflicting_knowledge_id=payload.conflicting_knowledge_id,
            reason=payload.reason,
            user_id=current_user.id,
        )
        db.commit()
        return {
            "status": "conflict_flagged",
            "item_a": service.serialize_knowledge(item_a),
            "item_b": service.serialize_knowledge(item_b),
        }
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{knowledge_id}/resolve-conflict")
def resolve_knowledge_conflict(
    knowledge_id: UUID,
    payload: KnowledgeConflictResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    _require_knowledge_writer(current_user)

    service = KnowledgeService(db)
    try:
        winner, loser = service.resolve_conflict(
            tenant_id=current_user.tenant_id,
            winner_id=knowledge_id,
            loser_id=payload.loser_knowledge_id,
            resolution_reason=payload.resolution_reason,
            user_id=current_user.id,
        )
        db.commit()
        return {
            "status": "conflict_resolved",
            "winner": service.serialize_knowledge(winner),
            "loser": service.serialize_knowledge(loser),
        }
    except SecretDetectedError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{knowledge_id}")
def delete_knowledge_item(
    knowledge_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has no tenant")

    # Access control: deletion is restricted to tenant owners and administrators
    _require_admin(current_user)

    service = KnowledgeService(db)
    try:
        service.delete_knowledge(current_user.tenant_id, knowledge_id, user_id=current_user.id)
        db.commit()
        return {"status": "deleted", "id": str(knowledge_id)}
    except ValueError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge item not found")
