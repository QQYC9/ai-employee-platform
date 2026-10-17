from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.ai_providers.factory import AIProviderFactory
from packages.auth.dependencies import get_current_user, get_db, require_tenant_admin
from packages.models.domain import User
from packages.services.ai_provider_service import AIProviderService

router = APIRouter(prefix="/ai-providers", tags=["AI Providers"])


class AIProviderConfigCreateRequest(BaseModel):
    name: str = Field(..., description="Reference name, e.g. 'groq-production'")
    provider: str = Field(..., description="Provider name: 'groq', 'openai', or 'gemini'")
    model: str = Field(..., description="Model identifier, e.g. 'openai/gpt-oss-120b'")
    api_key: str | None = Field(default=None, description="Secret API key (will be encrypted at rest)")
    base_url: str | None = Field(default=None, description="Optional custom base URL endpoint")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    is_default: bool = Field(default=False, description="Set as default provider for this tenant")
    is_platform_level: bool = Field(default=False, description="Configure as platform global default (platform admin only)")
    extra_params: dict[str, Any] | None = Field(default=None)


@router.get("/supported")
def get_supported_providers():
    """List all supported AI provider connectors in the platform."""
    return {
        "supported_providers": AIProviderFactory.supported_providers(),
    }


@router.get("/configs")
def list_provider_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List AI provider configurations visible to this tenant with masked keys."""
    service = AIProviderService(db)
    return service.list_configs(tenant_id=current_user.tenant_id)


@router.post("/configs", status_code=status.HTTP_201_CREATED)
def create_provider_config(
    payload: AIProviderConfigCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant_admin),
):
    """Register or update an AI provider configuration with AES-256-GCM encrypted API key."""
    target_tenant_id = current_user.tenant_id
    if payload.is_platform_level:
        user_role = (current_user.role or "").strip().lower()
        if user_role not in ("platform_admin", "superadmin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only platform administrators can configure platform-level AI providers",
            )
        target_tenant_id = None

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


@router.get("/configs/{config_id}")
def get_provider_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve an AI provider configuration by ID (keys are masked)."""
    service = AIProviderService(db)
    cfg = service.get_config(tenant_id=current_user.tenant_id, integration_id=config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="AI Provider configuration not found")
    return cfg


@router.post("/configs/{config_id}/test")
def test_provider_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant_admin),
):
    """
    Test live connectivity and authentication for this configuration.
    Records test latency and status without leaking API keys.
    """
    service = AIProviderService(db)
    try:
        test_result = service.test_config(tenant_id=current_user.tenant_id, integration_id=config_id)
        db.commit()
        return test_result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
