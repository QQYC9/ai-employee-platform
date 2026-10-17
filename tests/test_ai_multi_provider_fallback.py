from __future__ import annotations

import time
from typing import Any
import uuid
import pytest
from sqlalchemy.orm import Session

from packages.ai_providers.base import (
    AIBadRequestError,
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
from packages.ai_providers.resilient_provider import CircuitBreaker, ResilientAIProvider
from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.services.ai_provider_service import AIProviderService


class DummyProvider:
    def __init__(
        self,
        name: str,
        response: str = "Dummy response",
        fail_errors: list[Exception] | None = None,
        json_response: dict[str, Any] | None = None,
    ):
        self.name = name
        self.model = f"{name}-model-v1"
        self.provider_name = name
        self.response = response
        self.json_response = json_response or {"reply": response}
        self.fail_errors = list(fail_errors or [])
        self.calls: list[str] = []
        self.last_usage: dict[str, Any] | None = {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40}

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(prompt)
        if self.fail_errors:
            err = self.fail_errors.pop(0)
            raise err
        return self.response

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append(prompt)
        if self.fail_errors:
            err = self.fail_errors.pop(0)
            raise err
        return self.json_response

    def test_connection(self) -> dict[str, Any]:
        if self.fail_errors:
            return {"success": False, "error": str(self.fail_errors[0])}
        return {"success": True, "provider": self.name}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db: Session):
    t = Tenant(name="Fallback Tenant", slug=f"fallback-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.commit()
    return t


def test_classify_ai_error():
    assert classify_ai_error(AIProviderTimeoutError("Deadline exceeded")) == "TRANSIENT_NETWORK"
    assert classify_ai_error(AIConnectionError("Socket closed")) == "TRANSIENT_NETWORK"
    assert classify_ai_error(AIRateLimitError("Rate limit 429")) == "RATE_LIMIT"
    assert classify_ai_error(AIAuthenticationError("401 Unauthorized")) == "AUTHENTICATION_ERROR"
    assert classify_ai_error(AIBadRequestError("400 Bad Request")) == "BAD_REQUEST"
    assert classify_ai_error(AIContentFilterError("Safety block")) == "CONTENT_FILTER"
    assert classify_ai_error(AIModelNotFoundError("404 Model not found")) == "MODEL_NOT_FOUND"


def test_primary_provider_success_no_fallback():
    p1 = DummyProvider("groq", response="Response from Primary Groq")
    p2 = DummyProvider("openai", response="Response from Fallback OpenAI")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        base_backoff_seconds=0.01,
    )

    result = resilient.generate_text("Hello")
    assert result == "Response from Primary Groq"
    assert len(p1.calls) == 1
    assert len(p2.calls) == 0
    assert resilient.last_used_provider == "groq"
    assert resilient.last_fallback_reason is None


def test_transient_network_error_retries_and_falls_back():
    # Primary fails with transient timeout on all attempts
    p1 = DummyProvider(
        "groq",
        fail_errors=[
            AIProviderTimeoutError("Timeout 1"),
            AIProviderTimeoutError("Timeout 2"),
            AIProviderTimeoutError("Timeout 3"),
        ],
    )
    p2 = DummyProvider("openai", response="Fallback response after retry")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        max_retries_per_provider=2,
        base_backoff_seconds=0.01,
    )

    result = resilient.generate_text("Test query")
    assert result == "Fallback response after retry"
    assert len(p1.calls) == 3  # Initial + 2 retries
    assert len(p2.calls) == 1
    assert resilient.last_used_provider == "openai"
    assert "Exhausted retries" in (resilient.last_fallback_reason or "")


def test_rate_limit_429_immediately_falls_back():
    # Rate limit error on primary switches to secondary immediately
    p1 = DummyProvider(
        "groq",
        fail_errors=[AIRateLimitError("429 Too Many Requests: Rate limit reached")],
    )
    p2 = DummyProvider("openai", response="OpenAI handling rate limited query")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        max_retries_per_provider=2,
        base_backoff_seconds=0.01,
    )

    result = resilient.generate_text("Summarize status")
    assert result == "OpenAI handling rate limited query"
    # p1 should NOT have wasted useless retries
    assert len(p1.calls) == 1
    assert len(p2.calls) == 1
    assert resilient.last_used_provider == "openai"
    assert "Rate limit (429)" in resilient.last_fallback_reason


def test_auth_error_does_not_retry_primary_switches_to_fallback():
    # 401 Auth error: do not retry primary, switch directly to fallback
    p1 = DummyProvider("groq", fail_errors=[AIAuthenticationError("401 Invalid API key")])
    p2 = DummyProvider("gemini", response="Gemini saved the day")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("gemini", p2)],
        max_retries_per_provider=2,
        base_backoff_seconds=0.01,
    )

    result = resilient.generate_text("Action prompt")
    assert result == "Gemini saved the day"
    assert len(p1.calls) == 1
    assert len(p2.calls) == 1
    assert resilient.last_used_provider == "gemini"


def test_bad_request_or_content_filter_fails_fast_no_switch():
    # Permanent error must fail fast and NOT switch to fallback
    p1 = DummyProvider("groq", fail_errors=[AIBadRequestError("400 Bad parameter schema")])
    p2 = DummyProvider("openai", response="Should never be reached")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        base_backoff_seconds=0.01,
    )

    with pytest.raises(AIBadRequestError, match="400 Bad parameter schema"):
        resilient.generate_text("Bad query")

    assert len(p1.calls) == 1
    assert len(p2.calls) == 0


def test_content_filter_fails_fast_no_switch():
    p1 = DummyProvider("groq", fail_errors=[AIContentFilterError("Safety violation")])
    p2 = DummyProvider("openai", response="Should never be reached")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        base_backoff_seconds=0.01,
    )

    with pytest.raises(AIContentFilterError, match="Safety violation"):
        resilient.generate_text("Filtered query")

    assert len(p2.calls) == 0


def test_all_providers_failing_raises_all_ai_providers_failed_error():
    p1 = DummyProvider("groq", fail_errors=[AIProviderTimeoutError("Groq down")])
    p2 = DummyProvider("openai", fail_errors=[AIConnectionError("OpenAI connection refused")])

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        max_retries_per_provider=0,
        base_backoff_seconds=0.01,
    )

    with pytest.raises(AllAIProvidersFailedError) as exc_info:
        resilient.generate_text("Critical command")

    err = exc_info.value
    assert len(err.errors) == 2
    assert err.errors[0]["provider"] == "groq"
    assert err.errors[1]["provider"] == "openai"


def test_circuit_breaker_trips_open_and_resets():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=0.1)

    assert cb.can_execute("groq") is True

    cb.record_failure("groq")
    cb.record_failure("groq")
    assert cb.can_execute("groq") is True

    cb.record_failure("groq")
    # Tripped OPEN
    assert cb.get_state("groq") == "OPEN"
    assert cb.can_execute("groq") is False

    # Wait for recovery timeout
    time.sleep(0.15)
    assert cb.get_state("groq") == "HALF_OPEN"
    assert cb.can_execute("groq") is True

    # Success closes the circuit
    cb.record_success("groq")
    assert cb.get_state("groq") == "CLOSED"


def test_audit_trail_and_switch_reason_logging():
    p1 = DummyProvider("groq", fail_errors=[AIRateLimitError("429 Quota exhausted")])
    p2 = DummyProvider("openai", response="Success after 429")

    resilient = ResilientAIProvider(
        providers=[("groq", p1), ("openai", p2)],
        base_backoff_seconds=0.01,
    )

    res = resilient.generate_text("Audit check")
    assert res == "Success after 429"

    audit = resilient.last_attempts_audit
    assert len(audit) == 2
    assert audit[0]["provider"] == "groq"
    assert audit[0]["status"] == "error"
    assert audit[0]["error_category"] == "RATE_LIMIT"
    assert audit[1]["provider"] == "openai"
    assert audit[1]["status"] == "fallback"
    assert audit[1]["fallback_from"] == "groq"


def test_factory_create_resilient_provider_with_tenant_configs(db: Session, tenant: Tenant):
    # Save original factory creators if any
    orig_groq = AIProviderFactory._registry.get("groq")
    orig_openai = AIProviderFactory._registry.get("openai")

    AIProviderFactory.register_provider("groq", lambda **kw: DummyProvider("groq", response="Primary Resp"))
    AIProviderFactory.register_provider("openai", lambda **kw: DummyProvider("openai", response="Secondary Resp"))

    try:
        service = AIProviderService(db)
        # Add primary config
        service.register_or_update_config(
            tenant_id=tenant.id,
            name="Tenant Primary",
            provider="groq",
            model="llama-3.3-70b-versatile",
            is_default=True,
        )
        # Add fallback config
        service.register_or_update_config(
            tenant_id=tenant.id,
            name="Tenant Secondary",
            provider="openai",
            model="gpt-4o-mini",
            is_default=False,
        )
        db.commit()

        provider = AIProviderFactory.create_resilient_provider(tenant_id=tenant.id, db=db)
        assert isinstance(provider, ResilientAIProvider)
        assert len(provider.providers) == 2
        assert provider.primary_name == "groq"

        reply = provider.generate_text("Hello factory")
        assert reply == "Primary Resp"
    finally:
        if orig_groq:
            AIProviderFactory._registry["groq"] = orig_groq
        if orig_openai:
            AIProviderFactory._registry["openai"] = orig_openai


def test_idempotency_prevents_duplicate_business_action_on_ai_retry(db: Session, tenant: Tenant):
    """
    Verify that an AI retry does not cause an already executed tool or external side effect to re-run.
    """
    from packages.services.idempotency_service import IdempotencyService
    idemp_service = IdempotencyService(db)

    tool_call_count = 0

    def business_side_effect():
        nonlocal tool_call_count
        tool_call_count += 1
        return {"action": "invoice_sent", "status": "ok"}

    action_key = f"action-quote-888-{tenant.id}"

    # First attempt: acquire lock, execute, and mark complete
    status1, res1 = idemp_service.acquire_or_check(
        tenant_id=tenant.id,
        idempotency_key=action_key,
        action="invoice_action",
    )
    assert status1 == "acquired"

    res = business_side_effect()
    idemp_service.complete(tenant_id=tenant.id, idempotency_key=action_key, result=res)
    db.commit()

    assert tool_call_count == 1

    # Simulated AI retry executing same tool step: must return saved result without executing side effect again
    status2, res2 = idemp_service.acquire_or_check(
        tenant_id=tenant.id,
        idempotency_key=action_key,
        action="invoice_action",
    )
    assert status2 == "completed"
    assert res2.get("action") == "invoice_sent"
    assert tool_call_count == 1  # Still 1, side effect was NOT repeated!
