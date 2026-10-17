from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
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

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """
    Unified AIProvider for OpenAI-compatible chat completion APIs
    (Groq, OpenAI, Ollama, DeepSeek, vLLM, etc.).

    Features:
      - Clean HTTP protocol over standard library urllib (zero external dependencies).
      - Cloudflare-safe headers (custom User-Agent).
      - Structured JSON generation with code fence fallback.
      - Fine-grained exception mapping (401/403 -> Auth, 404 -> Model, 429 -> RateLimit, 504 -> Timeout).
      - Non-intrusive connection test with latency measurement.
      - Automatic secret sanitization in logs and exceptions.
    """

    DEFAULT_BASE_URLS = {
        "groq": "https://api.groq.com/openai/v1",
        "openai": "https://api.openai.com/v1",
    }

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai",
        timeout_seconds: float = 30.0,
        default_temperature: float = 0.2,
        max_tokens: int | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        if not api_key or not api_key.strip():
            raise ValueError(f"{provider_name.upper()}_API_KEY cannot be empty")
        if not model or not model.strip():
            raise ValueError("Model name cannot be empty")

        self.api_key = api_key.strip()
        self.model = model.strip()
        self.provider_name = provider_name.strip().lower()

        resolved_base = base_url or self.DEFAULT_BASE_URLS.get(self.provider_name, "https://api.openai.com/v1")
        self.base_url = resolved_base.strip().rstrip("/")
        self.chat_endpoint = f"{self.base_url}/chat/completions"

        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.default_temperature = default_temperature
        self.max_tokens = max_tokens
        self.extra_headers = extra_headers or {}
        self.last_usage: dict[str, Any] | None = None

    def _sanitize(self, message: str) -> str:
        """Strip sensitive credentials, keys, or bearer tokens from error strings."""
        if not message:
            return ""
        sanitized = message.replace(self.api_key, "[REDACTED_KEY]")
        sanitized = re.sub(r"gsk_[A-Za-z0-9_-]+", "[REDACTED_KEY]", sanitized)
        sanitized = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED_KEY]", sanitized)
        sanitized = re.sub(r"AIza[0-9A-Za-z-_]{20,}", "[REDACTED_KEY]", sanitized)
        sanitized = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED_TOKEN]", sanitized)
        sanitized = re.sub(r"(key|api_key|secret)\s*[:=]\s*([^\s&\"']+)", r"\1=[REDACTED]", sanitized, flags=re.IGNORECASE)
        return sanitized

    @staticmethod
    def _strip_markdown_code_fences(text: str) -> str:
        """Strip markdown code fence wrappers (```json ... ```) from JSON responses."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def _execute_chat_request(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a POST request to the OpenAI-compatible chat completions endpoint."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        effective_max = max_tokens or self.max_tokens
        if effective_max is not None and effective_max > 0:
            payload["max_tokens"] = effective_max

        if response_format is not None:
            payload["response_format"] = response_format

        data_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "ai-employee-platform/1.0",
        }
        headers.update(self.extra_headers)

        req = urllib.request.Request(
            self.chat_endpoint,
            data=data_bytes,
            headers=headers,
            method="POST",
        )

        effective_timeout = timeout or self.timeout_seconds
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                body = resp.read().decode("utf-8")
                parsed = json.loads(body)
                self.last_usage = parsed.get("usage")
                return parsed
        except urllib.error.HTTPError as he:
            status_code = he.code
            raw_err = he.read().decode("utf-8", errors="replace")
            sanitized_err = self._sanitize(raw_err)

            if status_code in (401, 403):
                raise AIAuthenticationError(
                    f"{self.provider_name.capitalize()} authentication failed ({status_code}): {sanitized_err}"
                ) from he
            if status_code == 404:
                raise AIModelNotFoundError(
                    f"{self.provider_name.capitalize()} model '{self.model}' not found (404): {sanitized_err}"
                ) from he
            if status_code == 429:
                raise AIRateLimitError(
                    f"{self.provider_name.capitalize()} rate limit or quota exceeded (429): {sanitized_err}"
                ) from he
            if status_code in (408, 504):
                raise AIProviderTimeoutError(
                    f"{self.provider_name.capitalize()} request timed out ({status_code}): {sanitized_err}"
                ) from he

            raise AIProviderError(
                f"{self.provider_name.capitalize()} HTTP error ({status_code}): {sanitized_err}"
            ) from he
        except (urllib.error.URLError, TimeoutError) as ue:
            err_msg = self._sanitize(str(ue))
            is_timeout = (
                isinstance(ue, TimeoutError)
                or "timeout" in err_msg.lower()
                or "timed out" in err_msg.lower()
            )
            if is_timeout:
                raise AIProviderTimeoutError(
                    f"{self.provider_name.capitalize()} network timeout: {err_msg}"
                ) from ue
            raise AIConnectionError(
                f"{self.provider_name.capitalize()} network connection failed: {err_msg}"
            ) from ue
        except Exception as exc:
            if isinstance(exc, AIProviderError):
                raise
            sanitized_err = self._sanitize(str(exc))
            raise AIProviderError(
                f"{self.provider_name.capitalize()} provider error: {sanitized_err}"
            ) from exc

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Generate text completion from prompt."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        messages: list[dict[str, str]] = []
        if system_instruction and system_instruction.strip():
            messages.append({"role": "system", "content": system_instruction.strip()})
        messages.append({"role": "user", "content": prompt.strip()})

        resp_data = self._execute_chat_request(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choices = resp_data.get("choices", [])
        if not choices:
            raise ValueError(f"{self.provider_name.capitalize()} returned no choices")

        msg = choices[0].get("message", {})
        content = msg.get("content")

        # Fallback for reasoning models where answer may be in reasoning content if content is empty
        if not content or not content.strip():
            content = msg.get("reasoning")

        if not content or not content.strip():
            raise ValueError(f"{self.provider_name.capitalize()} returned an empty response")

        return content.strip()

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Generate and parse structured JSON object."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

        # Instruction reinforcement for JSON
        augmented_system = (system_instruction or "").strip()
        if augmented_system:
            augmented_system += "\nYou MUST return only a valid, parseable JSON object."
        else:
            augmented_system = "You are a precise JSON generator. Return only a valid, parseable JSON object."

        messages = [
            {"role": "system", "content": augmented_system},
            {"role": "user", "content": prompt.strip()},
        ]

        try:
            # First try with native json_object mode
            resp_data = self._execute_chat_request(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Fallback without explicit response_format for models that don't support it
            resp_data = self._execute_chat_request(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        choices = resp_data.get("choices", [])
        if not choices:
            raise ValueError(f"{self.provider_name.capitalize()} returned no choices")

        raw_content = choices[0].get("message", {}).get("content", "")
        if not raw_content or not raw_content.strip():
            raise ValueError(f"{self.provider_name.capitalize()} returned an empty JSON response")

        cleaned = self._strip_markdown_code_fences(raw_content)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode JSON from %s response: %s", self.provider_name, cleaned[:100])
            raise ValueError(f"{self.provider_name.capitalize()} returned invalid JSON") from exc

        if not isinstance(parsed, dict):
            raise ValueError(f"{self.provider_name.capitalize()} response must be a JSON object")

        return parsed

    def test_connection(self) -> dict[str, Any]:
        """
        Verify network connectivity, API key validity, and model availability.
        Never leaks raw API keys.
        """
        t0 = time.perf_counter()
        messages = [{"role": "user", "content": "Respond with only the word OK"}]

        try:
            resp_data = self._execute_chat_request(
                messages,
                temperature=0.0,
                max_tokens=20,
                timeout=min(self.timeout_seconds, 15.0),
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            choices = resp_data.get("choices", [])
            reply = ""
            if choices:
                msg = choices[0].get("message", {})
                reply = (msg.get("content") or msg.get("reasoning") or "").strip()

            return {
                "success": True,
                "provider": self.provider_name,
                "model": self.model,
                "latency_ms": latency_ms,
                "reply": reply[:50],
                "error_type": None,
                "error_message": None,
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            err_type = type(exc).__name__
            sanitized_msg = self._sanitize(str(exc))
            return {
                "success": False,
                "provider": self.provider_name,
                "model": self.model,
                "latency_ms": latency_ms,
                "reply": None,
                "error_type": err_type,
                "error_message": sanitized_msg[:300],
            }
