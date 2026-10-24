from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_db, require_platform_admin
from packages.models.domain import User
from packages.services.ai_provider_service import AIProviderService

router = APIRouter(
    prefix="/admin/integrations",
    tags=["Admin - Platform Integrations"],
)


class PlatformIntegrationCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Reference name, e.g. 'groq-global'")
    provider: str = Field(..., description="Provider name: 'groq', 'openai', or 'gemini'")
    model: str = Field(..., min_length=1, max_length=100, description="Model identifier, e.g. 'openai/gpt-oss-120b'")
    api_key: str | None = Field(default=None, description="Secret API key (will be encrypted at rest using AES-256-GCM)")
    base_url: str | None = Field(default=None, description="Optional custom base URL endpoint")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    is_default: bool = Field(default=False, description="Set as platform global default provider")
    extra_params: dict[str, Any] | None = None


class PlatformIntegrationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    api_key: str | None = Field(default=None, description="New secret API key (will be encrypted if provided)")
    base_url: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    is_default: bool | None = None
    status: str | None = Field(default=None, description="'active', 'inactive', 'disabled', or 'deleted'")
    extra_params: dict[str, Any] | None = None


@router.get("", status_code=status.HTTP_200_OK)
def list_platform_integrations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    List all platform-level AI integrations and provider configs.
    Guarded strictly for Platform Superadmins. All API keys are masked.
    """
    service = AIProviderService(db)
    return service.list_configs(tenant_id=None)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_platform_integration(
    payload: PlatformIntegrationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Register or configure a global platform-level AI provider.
    Encrypts the API key with AES-256-GCM at rest and sets tenant_id=None.
    """
    service = AIProviderService(db)
    try:
        dto = service.register_or_update_config(
            tenant_id=None,
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{integration_id}", status_code=status.HTTP_200_OK)
def get_platform_integration(
    integration_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Retrieve a specific platform-level integration by ID. Keys are masked.
    """
    service = AIProviderService(db)
    dto = service.get_config(tenant_id=None, integration_id=integration_id)
    if dto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Platform integration '{integration_id}' not found",
        )
    return dto


@router.patch("/{integration_id}", status_code=status.HTTP_200_OK)
def update_platform_integration(
    integration_id: UUID,
    payload: PlatformIntegrationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Update a platform-level integration's model, base URL, status, or encrypt a new API key.
    """
    service = AIProviderService(db)
    try:
        dto = service.update_config(
            tenant_id=None,
            integration_id=integration_id,
            name=payload.name,
            model=payload.model,
            api_key=payload.api_key,
            base_url=payload.base_url,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            is_default=payload.is_default,
            status=payload.status,
            extra_params=payload.extra_params,
        )
        db.commit()
        return dto
    except ValueError as exc:
        db.rollback()
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail_msg)


@router.post("/{integration_id}/test", status_code=status.HTTP_200_OK)
def test_platform_integration(
    integration_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Test live connectivity and authentication for a platform-level AI provider.
    Verifies credentials in memory without leaking keys into logs or response bodies.
    """
    service = AIProviderService(db)
    try:
        test_result = service.test_config(tenant_id=None, integration_id=integration_id)
        db.commit()
        return test_result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/{integration_id}", status_code=status.HTTP_200_OK)
def delete_platform_integration(
    integration_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Soft-delete a platform integration (marks status as 'deleted').
    """
    service = AIProviderService(db)
    try:
        service.delete_config(tenant_id=None, integration_id=integration_id)
        db.commit()
        return {"status": "deleted", "id": str(integration_id)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
