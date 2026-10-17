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


class AIBudgetExceededError(AIProviderError):
    """Raised when a tenant has exhausted their daily or monthly token/cost budget."""
    pass


class AIContentFilterError(AIProviderError):
    """Raised when prompt or response violates safety, policy, or content moderation filters."""
    pass


class AIBadRequestError(AIProviderError):
    """Raised when the request is malformed, invalid, or rejected by schema validation (HTTP 400/422)."""
    pass


class AllAIProvidersFailedError(AIProviderError):
    """Raised when primary and all configured fallback providers fail."""
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


def classify_ai_error(error: Exception | str) -> str:
    """
    Classify an AI error into standardized categories for fallback and retry routing:
      - 'TRANSIENT_NETWORK': timeouts, connection errors, socket failures
      - 'RATE_LIMIT': 429 rate limit or quota throttle
      - 'SERVER_ERROR': 5xx internal server or bad gateway errors
      - 'AUTHENTICATION_ERROR': 401/403 invalid key or unauthorized
      - 'QUOTA_EXCEEDED': budget limit reached
      - 'BAD_REQUEST': 400/422 invalid parameter (permanent)
      - 'CONTENT_FILTER': safety block (permanent)
      - 'MODEL_NOT_FOUND': 404 model not found
      - 'UNKNOWN': unclassified error
    """
    if isinstance(error, (AIProviderTimeoutError, TimeoutError)):
        return "TRANSIENT_NETWORK"
    if isinstance(error, AIConnectionError):
        return "TRANSIENT_NETWORK"
    if isinstance(error, AIRateLimitError):
        return "RATE_LIMIT"
    if isinstance(error, AIAuthenticationError):
        return "AUTHENTICATION_ERROR"
    if isinstance(error, AIBudgetExceededError):
        return "QUOTA_EXCEEDED"
    if isinstance(error, AIContentFilterError):
        return "CONTENT_FILTER"
    if isinstance(error, AIBadRequestError):
        return "BAD_REQUEST"
    if isinstance(error, AIModelNotFoundError):
        return "MODEL_NOT_FOUND"

    msg = str(error).lower()
    if "budget" in msg or "quota exceeded" in msg or "insufficient_quota" in msg:
        return "QUOTA_EXCEEDED"
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return "RATE_LIMIT"
    if "401" in msg or "403" in msg or "unauthorized" in msg or "invalid api key" in msg or "invalid_api_key" in msg:
        return "AUTHENTICATION_ERROR"
    if "content filter" in msg or "safety" in msg or "moderation" in msg or "blocked by safety" in msg:
        return "CONTENT_FILTER"
    if "400" in msg or "422" in msg or "bad request" in msg or "invalid parameter" in msg:
        return "BAD_REQUEST"
    if "404" in msg or "not found" in msg:
        return "MODEL_NOT_FOUND"
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg or "internal server" in msg or "service unavailable" in msg:
        return "SERVER_ERROR"
    if "timeout" in msg or "timed out" in msg or "connection reset" in msg or "connection refused" in msg or "connection error" in msg:
        return "TRANSIENT_NETWORK"

    return "UNKNOWN"



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
