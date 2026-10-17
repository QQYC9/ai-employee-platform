from __future__ import annotations

from typing import Any

from packages.ai_providers.base import (
    AIBadRequestError,
    AIBudgetExceededError,
    AIContentFilterError,
    AIAuthenticationError,
    AIConnectionError,
    AIModelNotFoundError,
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
    AIRateLimitError,
    AllAIProvidersFailedError,
    classify_ai_error,
)
from packages.ai_providers.factory import AIProviderFactory
from packages.ai_providers.gemini_provider import GeminiProvider
from packages.ai_providers.openai_compatible_provider import OpenAICompatibleProvider
from packages.ai_providers.resilient_provider import CircuitBreaker, ResilientAIProvider


def get_ai_provider(
    provider_name: str | None = None,
    **kwargs: Any,
) -> AIProvider:
    """Convenience wrapper delegating to AIProviderFactory."""
    return AIProviderFactory.create_provider(provider_name=provider_name, **kwargs)


__all__ = [
    "AIBadRequestError",
    "AIBudgetExceededError",
    "AIContentFilterError",
    "AIAuthenticationError",
    "AIConnectionError",
    "AIModelNotFoundError",
    "AIProvider",
    "AIProviderError",
    "AIProviderFactory",
    "AIProviderTimeoutError",
    "AIRateLimitError",
    "AllAIProvidersFailedError",
    "CircuitBreaker",
    "GeminiProvider",
    "OpenAICompatibleProvider",
    "ResilientAIProvider",
    "classify_ai_error",
    "get_ai_provider",
]
