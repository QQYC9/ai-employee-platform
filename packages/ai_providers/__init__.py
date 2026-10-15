from __future__ import annotations

from typing import Any

from packages.ai_providers.base import (
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
)
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.core.config import settings


def get_ai_provider(
    provider_name: str | None = None,
    **kwargs: Any,
) -> AIProvider:
    name = (provider_name or settings.ai_provider).strip().lower()
    if name == "gemini":
        return GeminiProvider(**kwargs)
    raise ValueError(f"Unsupported AI provider: {name}")


__all__ = [
    "AIProvider",
    "AIProviderError",
    "AIProviderTimeoutError",
    "GeminiProvider",
    "get_ai_provider",
]
