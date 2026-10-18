from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import GeneratedDocument, User
from packages.tools.document_tool import DocumentGeneratorInput, DocumentGeneratorTool
from packages.tools.contract import ToolExecutionContext

router = APIRouter(prefix="/documents", tags=["Documents"])


class DocumentGenerateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    document_type: str = Field(default="report", max_length=50)
    format: str = Field(default="html")
    content: str | dict[str, Any]
    language: str = Field(default="ar")
    metadata: dict[str, Any] | None = None


def serialize_document(doc: GeneratedDocument) -> dict[str, Any]:
    return {
        "id": str(doc.id),
        "tenant_id": str(doc.tenant_id),
        "title": doc.title,
        "document_type": doc.document_type,
        "format": doc.format,
        "filename": doc.filename,
        "file_size": doc.file_size,
        "mime_type": doc.mime_type,
        "sha256_hash": doc.sha256_hash,
        "created_by_agent_id": str(doc.created_by_agent_id) if doc.created_by_agent_id else None,
        "metadata": doc.metadata_json or {},
        "download_url": f"/api/v1/documents/{doc.id}/download",
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.get("")
def list_documents(
    document_type: str | None = Query(default=None),
    format: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """List all documents generated for the current tenant."""
    stmt = select(GeneratedDocument).where(GeneratedDocument.tenant_id == current_user.tenant_id)
    if document_type:
        stmt = stmt.where(GeneratedDocument.document_type == document_type.strip().lower())
    if format:
        stmt = stmt.where(GeneratedDocument.format == format.strip().lower())

    stmt = stmt.order_by(GeneratedDocument.created_at.desc()).limit(limit)
    docs = db.scalars(stmt).all()
    return {"items": [serialize_document(d) for d in docs]}


@router.get("/{document_id}")
def get_document(
    document_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """Get metadata for a specific document scoped to tenant."""
    doc = db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == document_id,
            GeneratedDocument.tenant_id == current_user.tenant_id,
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return serialize_document(doc)


@router.get("/{document_id}/download")
def download_document(
    document_id: UUID,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """Download the actual document file with strict tenant isolation verification."""
    doc = db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == document_id,
            GeneratedDocument.tenant_id == current_user.tenant_id,
        )
    )
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    file_path = Path(doc.file_path).resolve()
    tenant_dir = file_path.parent
    if tenant_dir.name != str(current_user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: document path escapes tenant boundary",
        )
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Physical document file missing on server")

    return FileResponse(
        path=str(file_path),
        media_type=doc.mime_type,
        filename=doc.filename,
    )


@router.post("/generate", status_code=status.HTTP_201_CREATED)
def generate_document(
    payload: DocumentGenerateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """Generate a document directly using the DocumentGeneratorTool."""
    tool = DocumentGeneratorTool(db)
    ctx = ToolExecutionContext(tenant_id=current_user.tenant_id)

    try:
        result = tool.run(
            ctx,
            title=payload.title,
            document_type=payload.document_type,
            format=payload.format,
            content=payload.content,
            language=payload.language,
            metadata=payload.metadata,
        )
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
