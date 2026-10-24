from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import ExecutionStep, ExecutionTrace

logger = logging.getLogger(__name__)

# Patterns for sensitive data redaction
REDACT_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{15,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"AIza[0-9A-Za-z-_]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{15,}", re.IGNORECASE), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"(password|passwd|secret|api_key|token|access_token|private_key)\s*[:=]\s*['\"]?[^\s,'\"}]+['\"]?", re.IGNORECASE), r"\1: [REDACTED]"),
]

SENSITIVE_KEYS = {
    "password", "secret", "token", "access_token", "api_key",
    "authorization", "jwt", "private_key", "credentials", "auth_token",
    "jwt_secret_key", "secrets_encryption_key",
}

SAFE_KEY_TERMS = {
    "tokens", "tokencount", "prompttokens", "completiontokens", "totaltokens",
    "tokenusage", "primarykey", "publickey", "keyid", "author", "authority", "authtype",
}


def is_sensitive_key(key: str) -> bool:
    """
    Classify whether a dictionary key represents sensitive credentials.
    Normalizes casing (camelCase, snake_case, kebab-case, uppercase) before matching,
    while explicitly excluding harmless structural or analytical keys like
    'primary_key', 'token_count', 'prompt_tokens', etc.
    """
    k_lower = str(key).lower()
    k_norm = re.sub(r"[-_.\s]+", "", k_lower)

    if k_norm in SAFE_KEY_TERMS:
        return False

    if k_norm in {
        "password", "passwd", "secret", "token", "apikey", "accesstoken",
        "authtoken", "refreshtoken", "clientsecret", "privatekey",
        "credentials", "credential", "authorization", "jwt",
        "jwtsecret", "jwtsecretkey", "secretsencryptionkey",
    }:
        return True

    if "password" in k_norm or "passwd" in k_norm or "secret" in k_norm:
        return True

    if "apikey" in k_norm or "privatekey" in k_norm or "credential" in k_norm or "authorization" in k_norm:
        return True

    if k_norm.endswith("token") or k_norm.startswith("token"):
        return True

    return False


def sanitize_value(val: Any, max_text_len: int = 120) -> Any:
    """
    Recursively sanitize input/output payloads:
    1. Redacts secrets, tokens, API keys (including Google AIza and OpenAI sk-), and credentials.
    2. Truncates long raw customer texts or prompt strings.
    3. Normalizes and strips sensitive dictionary keys (camelCase, kebab-case, snake_case).
    """
    if val is None:
        return None
    if isinstance(val, (int, float, bool)):
        return val
    if isinstance(val, str):
        cleaned = val
        for pattern, replacement in REDACT_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        if len(cleaned) > max_text_len:
            return f"{cleaned[:max_text_len]}... [truncated {len(cleaned)} chars]"
        return cleaned
    if isinstance(val, dict):
        sanitized_dict = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if is_sensitive_key(k):
                sanitized_dict[k] = "[REDACTED]"
            elif k_lower in ("system_instruction", "system_prompt", "full_prompt"):
                sanitized_dict[k] = "[REDACTED_SYSTEM_PROMPT]"
            else:
                sanitized_dict[k] = sanitize_value(v, max_text_len=max_text_len)
        return sanitized_dict
    if isinstance(val, (list, tuple)):
        return [sanitize_value(item, max_text_len=max_text_len) for item in val[:20]]
    if isinstance(val, UUID):
        return str(val)
    return str(val)[:max_text_len]


class ExecutionTracingService:
    """
    Dedicated service for orchestrating multi-tenant ExecutionTrace and ExecutionStep lifecycle.

    Guarantees:
      1. Complete tenant isolation on all traces and steps.
      2. Non-disruptive execution: Tracing failures are safely logged and never bubble up
         to fail or re-trigger business operations.
      3. Strict data sanitization: Secrets, system prompts, and full customer PII are redacted.
      4. Accurate latency and lifecycle timing tracking.
    """

    def __init__(self, db: Session):
        self.db = db

    def start_trace(
        self,
        *,
        tenant_id: UUID,
        trigger_type: str = "inbound_message",
        conversation_id: UUID | None = None,
        inbound_message_id: UUID | None = None,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        trace_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTrace | None:
        """
        Initializes and persists a new execution trace for an interaction cycle.
        Returns the created ExecutionTrace or None if persistence fails safely.
        """
        try:
            tid = trace_id or uuid4()
            sanitized_meta = sanitize_value(metadata or {})

            with self.db.begin_nested():
                trace = ExecutionTrace(
                    id=tid,
                    tenant_id=tenant_id,
                    trace_id=tid,
                    trigger_type=trigger_type,
                    conversation_id=conversation_id,
                    inbound_message_id=inbound_message_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    status="running",
                    started_at=datetime.now(timezone.utc),
                    metadata_json=sanitized_meta if isinstance(sanitized_meta, dict) else {},
                )
                self.db.add(trace)
                self.db.flush()
            return trace
        except Exception as exc:
            logger.warning("ExecutionTracingService.start_trace failed safely: %s", exc)
            return None

    def record_step(
        self,
        *,
        tenant_id: UUID,
        trace_id: UUID,
        step_name: str,
        step_type: str,
        step_order: int = 1,
        status: str = "completed",
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: int | None = None,
        task_id: UUID | None = None,
        approval_id: UUID | None = None,
        outbox_event_id: UUID | None = None,
        parent_step_id: UUID | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        attempt_count: int = 1,
        attempts_history: list[dict[str, Any]] | None = None,
    ) -> ExecutionStep | None:
        """
        Records an execution step within an existing trace.
        """
        try:
            now = datetime.now(timezone.utc)
            start_ts = started_at or now
            end_ts = completed_at or (now if status in ("completed", "failed", "blocked") else None)

            calculated_duration = duration_ms
            if calculated_duration is None and start_ts and end_ts:
                calculated_duration = int((end_ts - start_ts).total_seconds() * 1000)

            sanitized_input = sanitize_value(input_summary or {})
            sanitized_output = sanitize_value(output_summary or {})
            sanitized_error = sanitize_value(error_info) if error_info else None
            sanitized_attempts = sanitize_value(attempts_history or [])

            with self.db.begin_nested():
                step = ExecutionStep(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    parent_step_id=parent_step_id,
                    task_id=task_id,
                    approval_id=approval_id,
                    outbox_event_id=outbox_event_id,
                    step_order=step_order,
                    step_type=step_type,
                    step_name=step_name,
                    status=status,
                    started_at=start_ts,
                    completed_at=end_ts,
                    duration_ms=calculated_duration,
                    attempt_count=attempt_count,
                    attempts_history=sanitized_attempts if isinstance(sanitized_attempts, list) else [],
                    input_summary=sanitized_input if isinstance(sanitized_input, dict) else {},
                    output_summary=sanitized_output if isinstance(sanitized_output, dict) else {},
                    error_info=sanitized_error if isinstance(sanitized_error, dict) else None,
                    idempotency_key=idempotency_key,
                )
                self.db.add(step)
                self.db.flush()
            return step
        except Exception as exc:
            logger.warning("ExecutionTracingService.record_step failed safely: %s", exc)
            return None

    def complete_trace(
        self,
        *,
        tenant_id: UUID,
        trace_id: UUID,
        reply_message_id: UUID | None = None,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTrace | None:
        """
        Marks an execution trace as completed, recording duration and optional reply message linkage.
        """
        try:
            with self.db.begin_nested():
                trace = self.db.scalar(
                    select(ExecutionTrace).where(
                        ExecutionTrace.id == trace_id,
                        ExecutionTrace.tenant_id == tenant_id,
                    )
                )
                if trace is None:
                    return None

                now = datetime.now(timezone.utc)
                trace.status = status
                trace.completed_at = now
                if trace.started_at:
                    trace.duration_ms = int((now - trace.started_at).total_seconds() * 1000)

                if reply_message_id:
                    trace.reply_message_id = reply_message_id

                if metadata:
                    sanitized_meta = sanitize_value(metadata)
                    existing = dict(trace.metadata_json or {})
                    if isinstance(sanitized_meta, dict):
                        existing.update(sanitized_meta)
                    trace.metadata_json = existing

                self.db.flush()
            return trace
        except Exception as exc:
            logger.warning("ExecutionTracingService.complete_trace failed safely: %s", exc)
            return None

    def fail_trace(
        self,
        *,
        tenant_id: UUID,
        trace_id: UUID,
        error_summary: dict[str, Any] | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTrace | None:
        """
        Marks an execution trace as failed with a sanitized error summary.
        """
        try:
            with self.db.begin_nested():
                trace = self.db.scalar(
                    select(ExecutionTrace).where(
                        ExecutionTrace.id == trace_id,
                        ExecutionTrace.tenant_id == tenant_id,
                    )
                )
                if trace is None:
                    return None

                now = datetime.now(timezone.utc)
                trace.status = "failed"
                trace.completed_at = now
                if trace.started_at:
                    trace.duration_ms = int((now - trace.started_at).total_seconds() * 1000)

                if error_summary:
                    if isinstance(error_summary, str):
                        err_dict = {"error": sanitize_value(error_summary)}
                    else:
                        err_dict = sanitize_value(error_summary)
                    trace.error_summary = err_dict if isinstance(err_dict, dict) else {"error": str(err_dict)}

                if metadata:
                    sanitized_meta = sanitize_value(metadata)
                    existing = dict(trace.metadata_json or {})
                    if isinstance(sanitized_meta, dict):
                        existing.update(sanitized_meta)
                    trace.metadata_json = existing

                self.db.flush()
            return trace
        except Exception as exc:
            logger.warning("ExecutionTracingService.fail_trace failed safely: %s", exc)
            return None

    def get_trace(self, tenant_id: UUID, trace_id: UUID) -> ExecutionTrace | None:
        """Fetches an execution trace strictly scoped by tenant."""
        return self.db.scalar(
            select(ExecutionTrace).where(
                ExecutionTrace.id == trace_id,
                ExecutionTrace.tenant_id == tenant_id,
            )
        )

    def list_steps(self, tenant_id: UUID, trace_id: UUID) -> list[ExecutionStep]:
        """Lists all execution steps for a trace strictly scoped by tenant, ordered by step_order."""
        return list(
            self.db.scalars(
                select(ExecutionStep)
                .where(
                    ExecutionStep.trace_id == trace_id,
                    ExecutionStep.tenant_id == tenant_id,
                )
                .order_by(ExecutionStep.step_order.asc(), ExecutionStep.started_at.asc())
            ).all()
        )
