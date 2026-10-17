from __future__ import annotations

from typing import Any, Protocol


class AIProviderError(ValueError):
    """Base exception for AI provider failures."""
    pass


class AIProviderTimeoutError(AIProviderError, TimeoutError):
    """Raised when an AI provider call times out or exceeds deadline."""
    pass


class AIAuthenticationError(AIProviderError):
    """Raised when an API key is invalid, unauthorized, or expired (HTTP 401/403)."""
    pass


class AIModelNotFoundError(AIProviderError):
    """Raised when the specified model does not exist or is deprecated (HTTP 404)."""
    pass


class AIRateLimitError(AIProviderError):
    """Raised when API rate limits or quota are exhausted (HTTP 429)."""
    pass


class AIConnectionError(AIProviderError):
    """Raised when network connectivity or socket connection fails."""
    pass


class AIProvider(Protocol):
    """Common interface for AI model providers."""

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text from a prompt."""
        ...

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Generate and parse a JSON object."""
        ...

    def test_connection(self) -> dict[str, Any]:
        """Test connection and access to the provider model without leaking secrets."""
        ...
