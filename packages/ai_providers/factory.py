from __future__ import annotations

import logging
from typing import Any, Type
from uuid import UUID

from sqlalchemy.orm import Session

from packages.ai_providers.base import (
    AIProvider,
    AIProviderError,
)
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.ai_providers.openai_compatible_provider import OpenAICompatibleProvider
from packages.core.config import settings

logger = logging.getLogger(__name__)


class AIProviderFactory:
    """
    Factory for instantiating and configuring AIProvider instances.

    Responsibilities:
      - Maps provider names ('groq', 'openai', 'gemini') to provider classes.
      - Resolves configuration hierarchy:
          1. Explicit arguments
          2. Tenant-scoped database integration (if db and tenant_id provided)
          3. Platform-wide database integration (if db provided)
          4. Central settings / environment variables (.env fallback)
      - Extensible provider registry pattern for future models.
      - Provides clear, actionable error messages for unsupported providers or missing keys.
    """

    _registry: dict[str, Type[AIProvider]] = {
        "gemini": GeminiProvider,
        "groq": OpenAICompatibleProvider,
        "openai": OpenAICompatibleProvider,
    }

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[AIProvider]) -> None:
        """Register a new provider class dynamically."""
        clean_name = name.strip().lower()
        cls._registry[clean_name] = provider_class
        logger.info("Registered AI provider '%s' with %s", clean_name, provider_class.__name__)

    @classmethod
    def supported_providers(cls) -> list[str]:
        """Return list of supported provider names."""
        return sorted(list(cls._registry.keys()))

    @classmethod
    def create_provider(
        cls,
        provider_name: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        tenant_id: UUID | None = None,
        db: Session | None = None,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> AIProvider:
        """
        Create a fully-configured AIProvider instance based on active configuration.
        """
        resolved_provider = (provider_name or "").strip().lower()
        resolved_model = (model or "").strip()
        resolved_api_key = api_key.strip() if api_key and api_key.strip() else None
        resolved_base_url = base_url.strip() if base_url and base_url.strip() else None

        # 1. Database resolution if session provided
        if db is not None:
            from packages.services.ai_provider_service import AIProviderService
            provider_service = AIProviderService(db)
            db_cfg = provider_service.get_active_config(tenant_id=tenant_id, provider=resolved_provider or None)
            if db_cfg is not None:
                if not resolved_provider:
                    resolved_provider = db_cfg.get("provider", "")
                if not resolved_model:
                    resolved_model = db_cfg.get("model", "")
                if not resolved_api_key:
                    resolved_api_key = db_cfg.get("decrypted_api_key")
                if not resolved_base_url:
                    resolved_base_url = db_cfg.get("base_url")

        # 2. Central settings / environment fallback
        if not resolved_provider:
            resolved_provider = (settings.ai_provider or "").strip().lower()

        if not resolved_provider:
            raise ValueError(
                "No AI provider configured. Please configure an AI provider for this tenant or set AI_PROVIDER in environment."
            )

        if resolved_provider not in cls._registry:
            raise ValueError(
                f"Unsupported AI provider: '{resolved_provider}'. Supported: {', '.join(cls.supported_providers())}"
            )

        # Provider-specific default resolution from settings
        if resolved_provider == "gemini":
            if not resolved_api_key:
                resolved_api_key = settings.gemini_api_key
            if not resolved_model:
                resolved_model = settings.gemini_model
            timeout = timeout_seconds if timeout_seconds is not None else settings.gemini_timeout_seconds

            return GeminiProvider(
                api_key=resolved_api_key,
                model=resolved_model,
                timeout_seconds=timeout,
            )

        elif resolved_provider == "groq":
            if not resolved_api_key:
                resolved_api_key = settings.groq_api_key
            if not resolved_model:
                resolved_model = settings.groq_model or "openai/gpt-oss-120b"
            if not resolved_base_url:
                resolved_base_url = settings.groq_base_url or "https://api.groq.com/openai/v1"
            timeout = timeout_seconds if timeout_seconds is not None else settings.groq_timeout_seconds

            return OpenAICompatibleProvider(
                api_key=resolved_api_key,
                model=resolved_model,
                base_url=resolved_base_url,
                provider_name="groq",
                timeout_seconds=timeout,
                **kwargs,
            )

        elif resolved_provider == "openai":
            if not resolved_api_key:
                resolved_api_key = settings.openai_api_key
            if not resolved_model:
                resolved_model = settings.openai_model or "gpt-4o-mini"
            if not resolved_base_url:
                resolved_base_url = settings.openai_base_url or "https://api.openai.com/v1"
            timeout = timeout_seconds if timeout_seconds is not None else settings.openai_timeout_seconds

            return OpenAICompatibleProvider(
                api_key=resolved_api_key,
                model=resolved_model,
                base_url=resolved_base_url,
                provider_name="openai",
                timeout_seconds=timeout,
                **kwargs,
            )

        provider_cls = cls._registry[resolved_provider]
        return provider_cls(
            api_key=resolved_api_key,
            model=resolved_model,
            base_url=resolved_base_url,
            timeout_seconds=timeout_seconds or 30.0,
            **kwargs,
        )
