from __future__ import annotations

from typing import Any

from packages.ai_providers.base import (
    AIAuthenticationError,
    AIConnectionError,
    AIModelNotFoundError,
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
    AIRateLimitError,
)
from packages.ai_providers.factory import AIProviderFactory
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.ai_providers.openai_compatible_provider import OpenAICompatibleProvider


def get_ai_provider(
    provider_name: str | None = None,
    **kwargs: Any,
) -> AIProvider:
    """Convenience wrapper delegating to AIProviderFactory."""
    return AIProviderFactory.create_provider(provider_name=provider_name, **kwargs)


__all__ = [
    "AIAuthenticationError",
    "AIConnectionError",
    "AIModelNotFoundError",
    "AIProvider",
    "AIProviderError",
    "AIProviderFactory",
    "AIProviderTimeoutError",
    "AIRateLimitError",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "get_ai_provider",
]
