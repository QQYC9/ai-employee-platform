from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable
from uuid import UUID

from packages.ai_providers.base import (
    AIBadRequestError,
    AIBudgetExceededError,
    AIContentFilterError,
    AIProvider,
    AIProviderError,
    AllAIProvidersFailedError,
    classify_ai_error,
)

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    In-memory Circuit Breaker per AI provider to prevent repeated calls to failing upstream services.

    States:
      - CLOSED: Normal operation. All calls allowed.
      - OPEN: Failure threshold exceeded. Fast-fails requests to fallback without hitting upstream.
      - HALF_OPEN: Probe state after recovery timeout. Allows 1 probe call to test if upstream recovered.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
    ):
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_seconds = max(0.01, recovery_timeout_seconds)
        self._failures: dict[str, int] = {}
        self._last_failure_time: dict[str, float] = {}
        self._state: dict[str, str] = {}  # "CLOSED", "OPEN", "HALF_OPEN"

    def get_state(self, provider_name: str) -> str:
        clean = provider_name.strip().lower()
        state = self._state.get(clean, "CLOSED")
        if state == "OPEN":
            last_fail = self._last_failure_time.get(clean, 0.0)
            if time.time() - last_fail >= self.recovery_timeout_seconds:
                self._state[clean] = "HALF_OPEN"
                return "HALF_OPEN"
        return state

    def can_execute(self, provider_name: str) -> bool:
        clean = provider_name.strip().lower()
        state = self.get_state(clean)
        return state in ("CLOSED", "HALF_OPEN")

    def record_success(self, provider_name: str) -> None:
        clean = provider_name.strip().lower()
        self._failures[clean] = 0
        self._state[clean] = "CLOSED"

    def record_failure(self, provider_name: str) -> None:
        clean = provider_name.strip().lower()
        now = time.time()
        count = self._failures.get(clean, 0) + 1
        self._failures[clean] = count
        self._last_failure_time[clean] = now
        if count >= self.failure_threshold:
            self._state[clean] = "OPEN"
            logger.warning(
                "Circuit breaker tripped OPEN for AI provider '%s' (%d failures)",
                clean,
                count,
            )

    def reset(self, provider_name: str | None = None) -> None:
        if provider_name:
            clean = provider_name.strip().lower()
            self._failures.pop(clean, None)
            self._last_failure_time.pop(clean, None)
            self._state.pop(clean, None)
        else:
            self._failures.clear()
            self._last_failure_time.clear()
            self._state.clear()


class ResilientAIProvider:
    """
    Centralized resilient wrapper for AIProvider protocol with:
      - Primary provider + prioritized fallback provider chain.
      - Error taxonomy-based switching (no blind or silent fallbacks).
      - Permanent error fast-fail (400 validation, content filters, budget violations).
      - Exponential backoff with jitter for transient retries.
      - Integrated Circuit Breaker.
      - Comprehensive attempt auditing (latencies, switch reasons, provider names).
      - Transparent token usage extraction and budget enforcement.
    """

    NON_FALLBACK_CATEGORIES = {
        "BAD_REQUEST",
        "CONTENT_FILTER",
        "QUOTA_EXCEEDED",
    }

    def __init__(
        self,
        providers: list[tuple[str, AIProvider]],
        *,
        tenant_id: UUID | None = None,
        db_session_factory: Callable[[], Any] | None = None,
        max_retries_per_provider: int = 2,
        base_backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 10.0,
        circuit_breaker: CircuitBreaker | None = None,
        task_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ):
        if not providers:
            raise ValueError("ResilientAIProvider requires at least one provider")

        self.providers = providers
        self.primary_name, self.primary_provider = providers[0]
        self.fallback_chain = providers[1:]
        self.tenant_id = tenant_id
        self.db_session_factory = db_session_factory
        self.max_retries_per_provider = max(0, max_retries_per_provider)
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.task_id = task_id
        self.conversation_id = conversation_id

        self.last_used_provider: str | None = None
        self.last_fallback_reason: str | None = None
        self.last_attempts_audit: list[dict[str, Any]] = []
        self.last_usage: dict[str, Any] | None = None

    def _calculate_backoff(self, attempt: int) -> float:
        backoff = min(self.max_backoff_seconds, self.base_backoff_seconds * (2 ** attempt))
        jitter = random.uniform(0.0, backoff * 0.2)
        return backoff + jitter

    def _check_budget(self) -> None:
        """Check if tenant has exceeded AI budget limits."""
        if self.tenant_id is not None and self.db_session_factory is not None:
            from packages.services.ai_usage_service import AIUsageService
            with self.db_session_factory() as session:
                service = AIUsageService(session)
                service.check_budget_available(self.tenant_id)

    def _record_usage_log(
        self,
        provider_name: str,
        model_name: str,
        duration_ms: int,
        status: str,
        error_category: str | None = None,
        error_message: str | None = None,
        fallback_from: str | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        """Persist AI call usage and metric record."""
        if self.tenant_id is None or self.db_session_factory is None:
            return

        try:
            from packages.services.ai_usage_service import AIUsageService
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

            if self.last_usage and isinstance(self.last_usage, dict):
                prompt_tokens = int(self.last_usage.get("prompt_tokens") or 0)
                completion_tokens = int(self.last_usage.get("completion_tokens") or 0)
                total_tokens = int(self.last_usage.get("total_tokens") or (prompt_tokens + completion_tokens))

            with self.db_session_factory() as session:
                service = AIUsageService(session)
                service.record_usage(
                    tenant_id=self.tenant_id,
                    provider=provider_name,
                    model=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    duration_ms=duration_ms,
                    status=status,
                    error_category=error_category,
                    error_message=error_message,
                    fallback_from_provider=fallback_from,
                    fallback_reason=fallback_reason,
                    task_id=self.task_id,
                    conversation_id=self.conversation_id,
                )
                session.commit()
        except Exception as exc:
            logger.warning("Failed to record AI usage metrics: %s", exc)

    def _execute_with_resilience(
        self,
        operation_name: str,
        execute_fn: Callable[[AIProvider], Any],
    ) -> Any:
        self._check_budget()

        attempts_audit: list[dict[str, Any]] = []
        self.last_attempts_audit = attempts_audit
        self.last_used_provider = None
        self.last_fallback_reason = None
        self.last_usage = None

        fallback_from_provider: str | None = None
        fallback_reason: str | None = None

        for idx, (p_name, provider) in enumerate(self.providers):
            is_primary = (idx == 0)
            model_name = getattr(provider, "model", "default")

            if not self.circuit_breaker.can_execute(p_name):
                logger.warning(
                    "ResilientAI: Skipping provider '%s' (circuit breaker is OPEN)",
                    p_name,
                )
                attempts_audit.append({
                    "provider": p_name,
                    "model": model_name,
                    "attempt": 0,
                    "status": "circuit_open_skipped",
                    "duration_ms": 0,
                    "error": "Circuit breaker is OPEN",
                })
                fallback_from_provider = p_name
                fallback_reason = "Circuit breaker OPEN"
                continue

            # Retry loop for current provider
            for attempt in range(self.max_retries_per_provider + 1):
                t0 = time.perf_counter()
                try:
                    logger.debug(
                        "ResilientAI: Executing %s via provider '%s' (attempt %d)",
                        operation_name,
                        p_name,
                        attempt + 1,
                    )
                    result = execute_fn(provider)
                    duration_ms = int((time.perf_counter() - t0) * 1000)

                    # Extract usage metadata from provider instance
                    self.last_usage = getattr(provider, "last_usage", None)
                    self.circuit_breaker.record_success(p_name)
                    self.last_used_provider = p_name
                    self.last_fallback_reason = fallback_reason

                    status = "fallback" if not is_primary else "success"
                    attempts_audit.append({
                        "provider": p_name,
                        "model": model_name,
                        "attempt": attempt + 1,
                        "status": status,
                        "duration_ms": duration_ms,
                        "fallback_from": fallback_from_provider,
                        "fallback_reason": fallback_reason,
                    })

                    self._record_usage_log(
                        provider_name=p_name,
                        model_name=model_name,
                        duration_ms=duration_ms,
                        status=status,
                        fallback_from=fallback_from_provider,
                        fallback_reason=fallback_reason,
                    )

                    if not is_primary:
                        logger.info(
                            "ResilientAI: Fallback to '%s' succeeded (primary '%s' failed: %s)",
                            p_name,
                            self.primary_name,
                            fallback_reason,
                        )

                    return result

                except Exception as exc:
                    duration_ms = int((time.perf_counter() - t0) * 1000)
                    category = classify_ai_error(exc)
                    err_msg = str(exc)

                    attempts_audit.append({
                        "provider": p_name,
                        "model": model_name,
                        "attempt": attempt + 1,
                        "status": "error",
                        "error_category": category,
                        "error": err_msg,
                        "duration_ms": duration_ms,
                    })

                    self.circuit_breaker.record_failure(p_name)

                    # 1. Permanent non-fallback errors: abort immediately without switching!
                    if category in self.NON_FALLBACK_CATEGORIES:
                        logger.error(
                            "ResilientAI: Permanent non-fallback error (%s) on provider '%s': %s",
                            category,
                            p_name,
                            err_msg,
                        )
                        self._record_usage_log(
                            provider_name=p_name,
                            model_name=model_name,
                            duration_ms=duration_ms,
                            status="error",
                            error_category=category,
                            error_message=err_msg,
                        )
                        raise

                    # 2. Authentication failure: do not retry same provider; switch to next fallback if available
                    if category == "AUTHENTICATION_ERROR":
                        logger.warning(
                            "ResilientAI: Authentication failed on provider '%s'. Bypassing retries and switching to fallback: %s",
                            p_name,
                            err_msg,
                        )
                        fallback_from_provider = p_name
                        fallback_reason = f"Auth error: {err_msg[:100]}"
                        break

                    # 3. Rate limit (429): switch to fallback immediately rather than wasting long retry delays
                    if category == "RATE_LIMIT":
                        logger.warning(
                            "ResilientAI: Rate limit on provider '%s'. Switching to next fallback: %s",
                            p_name,
                            err_msg,
                        )
                        fallback_from_provider = p_name
                        fallback_reason = f"Rate limit (429): {err_msg[:100]}"
                        break

                    # 4. Transient network / 5xx server error: retry with backoff on current provider
                    if attempt < self.max_retries_per_provider:
                        sleep_s = self._calculate_backoff(attempt)
                        logger.info(
                            "ResilientAI: Transient error on provider '%s' (%s). Retrying in %.2fs (attempt %d/%d)...",
                            p_name,
                            category,
                            sleep_s,
                            attempt + 1,
                            self.max_retries_per_provider,
                        )
                        time.sleep(sleep_s)
                    else:
                        logger.warning(
                            "ResilientAI: Provider '%s' exhausted max retries (%d). Switching to fallback...",
                            p_name,
                            self.max_retries_per_provider,
                        )
                        fallback_from_provider = p_name
                        fallback_reason = f"Exhausted retries ({category}): {err_msg[:100]}"

        # All providers exhausted
        summary_lines = [
            f"- {a.get('provider')} (attempt {a.get('attempt')}): {a.get('error', a.get('status'))}"
            for a in attempts_audit
        ]
        msg = f"All {len(self.providers)} AI provider(s) failed for {operation_name}:\n" + "\n".join(summary_lines)
        logger.error("ResilientAI: %s", msg)
        raise AllAIProvidersFailedError(msg, errors=attempts_audit)

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        def _call_text(p: AIProvider) -> str:
            import inspect
            kw: dict[str, Any] = {
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
            if max_tokens is not None:
                kw["max_tokens"] = max_tokens
            sig = inspect.signature(p.generate_text)
            has_var = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())
            if not has_var:
                kw = {k: v for k, v in kw.items() if k in sig.parameters}
            return p.generate_text(prompt, **kw)

        return self._execute_with_resilience("generate_text", _call_text)

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        def _call_json(p: AIProvider) -> dict[str, Any]:
            import inspect
            kw: dict[str, Any] = {
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
            if max_tokens is not None:
                kw["max_tokens"] = max_tokens
            sig = inspect.signature(p.generate_json)
            has_var = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())
            if not has_var:
                kw = {k: v for k, v in kw.items() if k in sig.parameters}
            return p.generate_json(prompt, **kw)

        return self._execute_with_resilience("generate_json", _call_json)

    def test_connection(self) -> dict[str, Any]:
        """Test health of primary and all fallback providers."""
        results: list[dict[str, Any]] = []
        overall_success = True
        for name, provider in self.providers:
            try:
                res = provider.test_connection()
                res["provider_name"] = name
                results.append(res)
                if not res.get("success"):
                    overall_success = False
            except Exception as exc:
                overall_success = False
                results.append({
                    "provider_name": name,
                    "success": False,
                    "error": str(exc),
                })
        return {
            "success": overall_success,
            "primary": self.primary_name,
            "providers": results,
        }
