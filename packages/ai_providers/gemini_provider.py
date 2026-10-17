from __future__ import annotations

import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types

from packages.ai_providers.base import (
    AIProvider,
    AIProviderError,
    AIProviderTimeoutError,
)
from packages.core.config import settings

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini implementation of the AIProvider interface."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        resolved_api_key = api_key or settings.gemini_api_key
        if not resolved_api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        self.api_key = resolved_api_key
        self.model = model or settings.gemini_model
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.gemini_timeout_seconds
        )

        http_options = None
        if self.timeout_seconds and self.timeout_seconds > 0:
            try:
                http_options = types.HttpOptions(
                    timeout=int(self.timeout_seconds * 1000)
                )
            except Exception:
                http_options = None

        if http_options:
            self.client = genai.Client(
                api_key=self.api_key,
                http_options=http_options,
            )
        else:
            self.client = genai.Client(api_key=self.api_key)

        self.last_usage: dict[str, Any] | None = None

    def _sanitize(self, message: str) -> str:
        """Mask sensitive keys, tokens, or credentials from error logs and exceptions."""
        if not message:
            return ""
        sanitized = message
        if self.api_key:
            sanitized = sanitized.replace(self.api_key, "[REDACTED_KEY]")
        if settings.gemini_api_key:
            sanitized = sanitized.replace(
                settings.gemini_api_key, "[REDACTED_KEY]"
            )
        sanitized = re.sub(
            r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_KEY]", sanitized
        )
        sanitized = re.sub(
            r"AQ\.[0-9A-Za-z-_]{20,}", "[REDACTED_KEY]", sanitized
        )
        sanitized = re.sub(
            r"(key|api_key)=([^\s&\"']+)", r"\1=[REDACTED_KEY]", sanitized
        )
        sanitized = re.sub(
            r"Bearer\s+([A-Za-z0-9_\-\.]+)", "Bearer [REDACTED_TOKEN]", sanitized
        )
        return sanitized

    @staticmethod
    def _strip_markdown_code_fences(text: str) -> str:
        """Strip markdown code fence wrappers from model JSON output."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": temperature,
        }
        if max_tokens is not None and max_tokens > 0:
            config_kwargs["max_output_tokens"] = max_tokens

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            err_str = str(exc)
            is_timeout = (
                isinstance(exc, TimeoutError)
                or "timeout" in err_str.lower()
                or "timed out" in err_str.lower()
                or "deadline exceeded" in err_str.lower()
            )
            sanitized_err = self._sanitize(err_str)
            logger.error(
                "Gemini generate_text failed (timeout=%s, model=%s): %s",
                is_timeout,
                self.model,
                sanitized_err,
            )
            if is_timeout:
                raise AIProviderTimeoutError(
                    f"Gemini request timed out: {sanitized_err}"
                ) from exc
            raise AIProviderError(
                f"Gemini provider error: {sanitized_err}"
            ) from exc

        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            self.last_usage = {
                "prompt_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
            }
        else:
            self.last_usage = None

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise ValueError("Gemini returned an empty response")

        return text.strip()

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": temperature,
            "response_mime_type": "application/json",
        }
        if max_tokens is not None and max_tokens > 0:
            config_kwargs["max_output_tokens"] = max_tokens

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            err_str = str(exc)
            is_timeout = (
                isinstance(exc, TimeoutError)
                or "timeout" in err_str.lower()
                or "timed out" in err_str.lower()
                or "deadline exceeded" in err_str.lower()
            )
            sanitized_err = self._sanitize(err_str)
            logger.error(
                "Gemini generate_json failed (timeout=%s, model=%s): %s",
                is_timeout,
                self.model,
                sanitized_err,
            )
            if is_timeout:
                raise AIProviderTimeoutError(
                    f"Gemini request timed out: {sanitized_err}"
                ) from exc
            raise AIProviderError(
                f"Gemini provider error: {sanitized_err}"
            ) from exc

        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            self.last_usage = {
                "prompt_tokens": getattr(usage_meta, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(usage_meta, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(usage_meta, "total_token_count", 0) or 0,
            }
        else:
            self.last_usage = None

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise ValueError("Gemini returned an empty JSON response")

        cleaned_text = self._strip_markdown_code_fences(text)

        try:
            result = json.loads(cleaned_text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Gemini returned invalid JSON (response length: %d)",
                len(text),
            )
            raise ValueError("Gemini returned invalid JSON") from exc

        if not isinstance(result, dict):
            raise ValueError("Gemini response must be a JSON object")

        return result

    def test_connection(self) -> dict[str, Any]:
        """Test connection and model availability without exposing secrets."""
        import time
        t0 = time.perf_counter()
        try:
            reply = self.generate_text("Respond with only the word OK", temperature=0.0)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "success": True,
                "provider": "gemini",
                "model": self.model,
                "latency_ms": latency_ms,
                "reply": reply[:50],
                "error_type": None,
                "error_message": None,
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            err_type = type(exc).__name__
            sanitized = self._sanitize(str(exc))
            return {
                "success": False,
                "provider": "gemini",
                "model": self.model,
                "latency_ms": latency_ms,
                "reply": None,
                "error_type": err_type,
                "error_message": sanitized[:300],
            }

