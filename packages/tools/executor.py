from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from packages.services.audit_service import AuditService
from packages.services.decision_engine import DecisionEngine
from packages.services.execution_tracing_service import ExecutionTracingService
from packages.services.idempotency_service import (
    ConcurrencyConflictError,
    IdempotencyService,
    IdempotencyTamperingError,
    ReconciliationRequiredError,
)
from packages.services.tool_service import ToolService


@dataclass(frozen=True)
class ToolExecutionResult:
    status: str
    tool_id: UUID
    tool_slug: str
    decision: str
    reason: str
    output: Any = None


class ToolExecutor:
    """
    Executes registered tools after authorization and approval checks.
    """

    def __init__(
        self,
        db: Session,
        handlers: dict[str, Callable[..., Any]] | None = None,
        idempotency_service: IdempotencyService | None = None,
        execution_tracing_service: ExecutionTracingService | None = None,
    ):
        self.db = db
        self.tool_service = ToolService(db)
        self.decision_engine = DecisionEngine(db)
        self.audit_service = AuditService(db)
        self.tracing_service = execution_tracing_service or ExecutionTracingService(db)
        self.handlers = handlers or {}
        self._idempotency_cache: dict[str, Any] = {}
        try:
            self.idempotency_service = idempotency_service or IdempotencyService(db)
        except Exception:
            self.idempotency_service = None

    def tool_supports_idempotency(self, tool_slug: str) -> bool:
        handler = self.handlers.get(tool_slug)
        if handler is None:
            return False
        if getattr(handler, "supports_idempotency", False):
            return True
        if getattr(handler, "can_verify", False):
            return True
        if hasattr(handler, "verify_status") or hasattr(handler, "check_status"):
            return True
        return False

    def check_idempotent_result(
        self,
        tenant_id: UUID,
        tool_id: UUID,
        idempotency_key: str,
    ) -> Any | None:
        if self.idempotency_service is not None:
            try:
                record = self.idempotency_service.get_record(tenant_id, idempotency_key)
                if record is not None and record.status == "completed":
                    return record.result
            except Exception:
                pass

        cache_key = f"{tenant_id}:{tool_id}:{idempotency_key}"
        return self._idempotency_cache.get(cache_key)

    def register_handler(
        self,
        tool_slug: str,
        handler: Callable[..., Any],
    ) -> None:
        tool_slug = tool_slug.strip().lower()

        if not tool_slug:
            raise ValueError("Tool slug cannot be empty")

        self.handlers[tool_slug] = handler

    def execute(
        self,
        *,
        tenant_id: UUID,
        tool_id: UUID,
        action: str,
        resource: str | None = None,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        parameters: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        trace_id: UUID | None = None,
    ) -> ToolExecutionResult:
        from datetime import datetime, timezone
        t_start = datetime.now(timezone.utc)

        effective_trace_id = trace_id
        if effective_trace_id is None and parameters:
            ctx = parameters.get("_context")
            if ctx and hasattr(ctx, "trace_id"):
                effective_trace_id = ctx.trace_id

        tool = self.tool_service.get_tool(
            tenant_id=tenant_id,
            tool_id=tool_id,
        )

        if tool is None:
            raise ValueError("Tool not found")

        decision = self.decision_engine.decide(
            tenant_id=tenant_id,
            action=action,
            resource=resource,
            agent_id=agent_id,
            task_id=task_id,
            tool_id=tool_id,
            parameters=parameters,
        )

        effective_idem_key = idempotency_key or (parameters.get("idempotency_key") if parameters else None)
        cache_key = f"{tenant_id}:{tool.id}:{effective_idem_key}" if effective_idem_key else None

        if decision.decision != "ALLOW":
            self.audit_service.record_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                event_type="tool_execution_blocked",
                action=action,
                description=decision.reason,
                event_metadata={
                    "tool_id": str(tool.id),
                    "tool_slug": tool.slug,
                    "task_id": str(task_id) if task_id else None,
                    "resource": resource,
                    "decision": decision.decision,
                    "status": "blocked",
                },
            )

            if effective_trace_id:
                try:
                    self.tracing_service.record_step(
                        tenant_id=tenant_id,
                        trace_id=effective_trace_id,
                        step_name=f"tool:{tool.slug}",
                        step_type="tool_call",
                        status="blocked",
                        started_at=t_start,
                        task_id=task_id,
                        input_summary=parameters,
                        error_info={"decision": decision.decision, "reason": decision.reason},
                        idempotency_key=effective_idem_key,
                    )
                except Exception:
                    pass

            return ToolExecutionResult(
                status="blocked",
                tool_id=tool.id,
                tool_slug=tool.slug,
                decision=decision.decision,
                reason=decision.reason,
            )

        if effective_idem_key:
            if cache_key in self._idempotency_cache:
                cached_output = self._idempotency_cache[cache_key]
                if effective_trace_id:
                    try:
                        self.tracing_service.record_step(
                            tenant_id=tenant_id,
                            trace_id=effective_trace_id,
                            step_name=f"tool:{tool.slug}",
                            step_type="tool_call",
                            status="completed",
                            started_at=t_start,
                            task_id=task_id,
                            input_summary=parameters,
                            output_summary={"source": "idempotency_cache", "output": cached_output},
                            idempotency_key=effective_idem_key,
                        )
                    except Exception:
                        pass
                return ToolExecutionResult(
                    status="executed",
                    tool_id=tool.id,
                    tool_slug=tool.slug,
                    decision=decision.decision,
                    reason="Result returned from idempotency cache",
                    output=cached_output,
                )

            if self.idempotency_service is not None:
                status, cached_output = self.idempotency_service.acquire_or_check(
                    tenant_id=tenant_id,
                    idempotency_key=effective_idem_key,
                    action=action,
                    resource=resource,
                    tool_id=tool.id,
                    parameters=parameters,
                )
                if status == "completed":
                    if cache_key:
                        self._idempotency_cache[cache_key] = cached_output
                    if effective_trace_id:
                        try:
                            self.tracing_service.record_step(
                                tenant_id=tenant_id,
                                trace_id=effective_trace_id,
                                step_name=f"tool:{tool.slug}",
                                step_type="tool_call",
                                status="completed",
                                started_at=t_start,
                                task_id=task_id,
                                input_summary=parameters,
                                output_summary={"source": "persistent_idempotency", "output": cached_output},
                                idempotency_key=effective_idem_key,
                            )
                        except Exception:
                            pass
                    return ToolExecutionResult(
                        status="executed",
                        tool_id=tool.id,
                        tool_slug=tool.slug,
                        decision=decision.decision,
                        reason="Result returned from persistent idempotency store",
                        output=cached_output,
                    )

        handler = self.handlers.get(tool.slug)

        if handler is None:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                event_type="tool_execution_error",
                action=action,
                description=(
                    f"No execution handler registered for tool '{tool.slug}'"
                ),
                event_metadata={
                    "tool_id": str(tool.id),
                    "tool_slug": tool.slug,
                    "resource": resource,
                    "decision": decision.decision,
                    "status": "error",
                },
            )
            if effective_trace_id:
                try:
                    self.tracing_service.record_step(
                        tenant_id=tenant_id,
                        trace_id=effective_trace_id,
                        step_name=f"tool:{tool.slug}",
                        step_type="tool_call",
                        status="failed",
                        started_at=t_start,
                        task_id=task_id,
                        input_summary=parameters,
                        error_info={"error": f"No execution handler registered for tool '{tool.slug}'"},
                        idempotency_key=effective_idem_key,
                    )
                except Exception:
                    pass

            raise ValueError(
                f"No execution handler registered for tool '{tool.slug}'"
            )

        try:
            output = handler(**(parameters or {}))
            if effective_idem_key:
                if cache_key:
                    self._idempotency_cache[cache_key] = output
                if self.idempotency_service is not None:
                    try:
                        self.idempotency_service.complete(
                            tenant_id=tenant_id,
                            idempotency_key=effective_idem_key,
                            result=output,
                        )
                    except Exception:
                        pass
        except Exception as exc:
            if effective_idem_key and self.idempotency_service is not None:
                try:
                    can_verify = self.tool_supports_idempotency(tool.slug)
                    if not can_verify:
                        self.idempotency_service.mark_reconciliation_required(
                            tenant_id=tenant_id,
                            idempotency_key=effective_idem_key,
                            error=f"Execution interrupted or failed; status unverified: {str(exc)}",
                        )
                    else:
                        self.idempotency_service.fail(
                            tenant_id=tenant_id,
                            idempotency_key=effective_idem_key,
                            error=str(exc),
                        )
                except Exception:
                    pass

            self.audit_service.record_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                event_type="tool_execution_error",
                action=action,
                description=str(exc),
                event_metadata={
                    "tool_id": str(tool.id),
                    "tool_slug": tool.slug,
                    "resource": resource,
                    "decision": decision.decision,
                    "status": "error",
                    "error_type": type(exc).__name__,
                },
            )

            if effective_trace_id:
                try:
                    self.tracing_service.record_step(
                        tenant_id=tenant_id,
                        trace_id=effective_trace_id,
                        step_name=f"tool:{tool.slug}",
                        step_type="tool_call",
                        status="failed",
                        started_at=t_start,
                        task_id=task_id,
                        input_summary=parameters,
                        error_info={"error": str(exc), "error_type": type(exc).__name__},
                        idempotency_key=effective_idem_key,
                    )
                except Exception:
                    pass

            raise

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=agent_id,
            event_type="tool_execution",
            action=action,
            description=f"Tool '{tool.slug}' executed successfully",
            event_metadata={
                "tool_id": str(tool.id),
                "tool_slug": tool.slug,
                "resource": resource,
                "decision": decision.decision,
                "status": "executed",
            },
        )

        if effective_trace_id:
            try:
                self.tracing_service.record_step(
                    tenant_id=tenant_id,
                    trace_id=effective_trace_id,
                    step_name=f"tool:{tool.slug}",
                    step_type="tool_call",
                    status="completed",
                    started_at=t_start,
                    task_id=task_id,
                    input_summary=parameters,
                    output_summary={"output": output},
                    idempotency_key=effective_idem_key,
                )
            except Exception:
                pass

        return ToolExecutionResult(
            status="executed",
            tool_id=tool.id,
            tool_slug=tool.slug,
            decision=decision.decision,
            reason=decision.reason,
            output=output,
        )

