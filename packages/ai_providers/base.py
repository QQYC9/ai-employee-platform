from __future__ import annotations

from typing import Any, Protocol


class AIProviderError(ValueError):
    """Base exception for AI provider failures."""
    pass


class AIProviderTimeoutError(AIProviderError, TimeoutError):
    """Raised when an AI provider call times out."""
    pass


class AIProvider(Protocol):
    """Common interface for AI model providers."""

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        """Generate text from a prompt."""
        ...

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Generate and parse a JSON object."""
        ...
