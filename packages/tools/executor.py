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
from packages.services.permission_service import PermissionService
from packages.services.tool_service import ToolService
from packages.tools.contract import ToolContract, ToolRiskLevel


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
        self.permission_service = PermissionService(db)
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
        *,
        contract: ToolContract | None = None,
        required_permissions: list[tuple[str, str]] | None = None,
        risk_level: ToolRiskLevel | str | None = None,
        operation_type: str | None = None,
        resource: str | None = None,
    ) -> None:
        tool_slug = tool_slug.strip().lower()

        if not tool_slug:
            raise ValueError("Tool slug cannot be empty")

        if contract is not None:
            handler.contract = contract
        if required_permissions is not None:
            handler.required_permissions = required_permissions
        if risk_level is not None:
            handler.risk_level = risk_level
        if operation_type is not None:
            handler.operation_type = operation_type
        if resource is not None:
            handler.resource = resource

        self.handlers[tool_slug] = handler

    def _extract_contract_permissions(
        self,
        tool: Any,
        handler: Callable[..., Any] | None = None,
        action: str | None = None,
        resource: str | None = None,
    ) -> tuple[list[tuple[str, str]], str | None]:
        """
        Extract required domain permissions declared by the tool contract.
        Classification hierarchy:
        1. Explicit contract on handler or tool (ToolContract).
        2. Explicit required_permissions on handler.
        3. Explicit required_permissions in Tool DB config.
        4. Explicit READ-ONLY declaration (risk_level == read_only or operation_type == read).
        5. WRITE / Mutating operation (operation_type == write, risk_level != read_only, or is_write):
           Requires explicit declared resource; fails closed if resource cannot be determined reliably.
        6. Legacy unclassified tool: returns empty permissions to preserve historical behavior.
        """
        perms: list[tuple[str, str]] = []

        # 1. From handler contract / tool
        if handler is not None:
            contract = getattr(handler, "contract", None) or getattr(handler, "tool_contract", None)
            if contract and hasattr(contract, "required_permissions"):
                for p in contract.required_permissions:
                    if isinstance(p, (tuple, list)) and len(p) >= 2:
                        perms.append((str(p[0]).strip(), str(p[1]).strip()))
                return perms, None
            elif hasattr(handler, "required_permissions"):
                raw_perms = getattr(handler, "required_permissions") or []
                for p in raw_perms:
                    if isinstance(p, (tuple, list)) and len(p) >= 2:
                        perms.append((str(p[0]).strip(), str(p[1]).strip()))
                    elif isinstance(p, dict) and "action" in p and "resource" in p:
                        perms.append((str(p["action"]).strip(), str(p["resource"]).strip()))
                if perms:
                    return perms, None

        # 2. From Tool record config
        if tool is not None and getattr(tool, "config", None) and isinstance(tool.config, dict):
            raw = tool.config.get("required_permissions") or []
            for item in raw:
                if isinstance(item, dict) and "action" in item and "resource" in item:
                    perms.append((str(item["action"]).strip(), str(item["resource"]).strip()))
                elif isinstance(item, (tuple, list)) and len(item) >= 2:
                    perms.append((str(item[0]).strip(), str(item[1]).strip()))
            if perms:
                return perms, None

        # 3. Check if explicitly defined as a READ-ONLY tool
        is_explicit_read_only = False
        if handler is not None:
            risk = getattr(handler, "risk_level", None)
            op = getattr(handler, "operation_type", None)
            if (risk and str(risk).lower() in ("read_only", "toolrisklevel.read_only")) or (op and str(op).lower() == "read"):
                is_explicit_read_only = True
        if not is_explicit_read_only and tool is not None and getattr(tool, "config", None) and isinstance(tool.config, dict):
            risk = tool.config.get("risk_level")
            op = tool.config.get("operation_type")
            if (risk and str(risk).lower() in ("read_only", "toolrisklevel.read_only")) or (op and str(op).lower() == "read"):
                is_explicit_read_only = True

        if is_explicit_read_only:
            # Verified read-only: does not require domain write permissions
            return [], None

        # 4. Check if defined as a WRITE / MUTATING tool
        is_write_tool = False
        declared_resource = None

        if handler is not None:
            if getattr(handler, "operation_type", None) == "write" or getattr(handler, "is_write", None) is True:
                is_write_tool = True
            risk = getattr(handler, "risk_level", None)
            if risk and str(risk).lower() not in ("read_only", "toolrisklevel.read_only"):
                is_write_tool = True
            if getattr(handler, "resource", None):
                declared_resource = str(handler.resource).strip()

        if not is_write_tool and tool is not None and getattr(tool, "config", None) and isinstance(tool.config, dict):
            if tool.config.get("operation_type") == "write" or tool.config.get("is_write") is True:
                is_write_tool = True
            risk = tool.config.get("risk_level")
            if risk and str(risk).lower() not in ("read_only", "toolrisklevel.read_only"):
                is_write_tool = True
            if tool.config.get("resource"):
                declared_resource = str(tool.config.get("resource")).strip()

        # Check explicit action write format (e.g. action="write")
        clean_act = (action or "").lower().removeprefix("execute:")
        if clean_act in ("write", "create", "update", "delete"):
            is_write_tool = True

        if is_write_tool:
            # For a write tool lacking an explicit contract:
            # If a specific domain resource is explicitly declared, enforce write:<declared_resource>
            if declared_resource:
                return [("write", declared_resource)], None

            # Check if caller passed a specific domain resource (not generic tools:slug)
            clean_res = (resource or "").strip()
            slug = getattr(tool, "slug", "")
            if clean_res and clean_res != f"tools:{slug}" and not clean_res.startswith("tools:"):
                return [("write", clean_res)], None

            # If the write tool has no reliable declared resource: fail closed!
            slug_name = getattr(tool, "slug", "unknown")
            return [], f"Write tool '{slug_name}' lacks explicit contract or permission definition (resource cannot be determined reliably)"

        # 5. Legacy unclassified tool without write attributes: returns empty to preserve backward compatibility
        return [], None

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
        actor_id: UUID | None = None,
        is_owner: bool = False,
    ) -> ToolExecutionResult:
        from datetime import datetime, timezone
        t_start = datetime.now(timezone.utc)

        effective_trace_id = trace_id
        # Strict authorization context: actor_id and is_owner MUST be passed via trusted explicit kwargs.
        # parameters["_context"] is NEVER trusted for authorization decisions.
        effective_actor_id = actor_id
        effective_is_owner = bool(is_owner) if actor_id is not None else False

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
            actor_id=effective_actor_id,
            is_owner=effective_is_owner,
        )

        effective_idem_key = idempotency_key or (parameters.get("idempotency_key") if parameters else None)
        cache_key = f"{tenant_id}:{tool.id}:{effective_idem_key}" if effective_idem_key else None

        if decision.decision != "ALLOW":
            self.audit_service.record_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=effective_actor_id if effective_is_owner else None,
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
                    "is_owner": effective_is_owner,
                    "actor_id": str(effective_actor_id) if effective_actor_id else None,
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

        # Mandatory Contract Permission Enforcement Gate
        handler = self.handlers.get(tool.slug)
        req_perms, contract_error = self._extract_contract_permissions(tool, handler, action=action, resource=resource)

        if contract_error:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=effective_actor_id if effective_is_owner else None,
                event_type="tool_execution_blocked",
                action=action,
                description=contract_error,
                event_metadata={
                    "tool_id": str(tool.id),
                    "tool_slug": tool.slug,
                    "task_id": str(task_id) if task_id else None,
                    "resource": resource,
                    "decision": "DENY",
                    "status": "blocked",
                    "is_owner": effective_is_owner,
                    "actor_id": str(effective_actor_id) if effective_actor_id else None,
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
                        error_info={"decision": "DENY", "reason": contract_error},
                        idempotency_key=effective_idem_key,
                    )
                except Exception:
                    pass

            return ToolExecutionResult(
                status="blocked",
                tool_id=tool.id,
                tool_slug=tool.slug,
                decision="DENY",
                reason=contract_error,
            )

        if req_perms:
            tenant_perms = self.permission_service.list_permissions(tenant_id)

            for req_act, req_res in req_perms:
                is_contract_denied = False
                contract_deny_reason = ""

                if effective_is_owner and agent_id is None:
                    # Human owner direct execution: check for tenant-level explicit deny on the domain permission
                    has_explicit_deny = self.permission_service.has_tenant_explicit_deny(
                        tenant_id=tenant_id,
                        actions=req_act,
                        resource=req_res,
                        tenant_permissions=tenant_perms,
                    )
                    if has_explicit_deny:
                        is_contract_denied = True
                        contract_deny_reason = f"Explicit deny on contract permission '{req_act}:{req_res}'"
                else:
                    # Digital agent execution: agent must have permission for domain operation and not be explicitly denied
                    is_allowed = self.permission_service.is_allowed(
                        tenant_id=tenant_id,
                        action=req_act,
                        resource=req_res,
                        agent_id=agent_id,
                    )
                    if not is_allowed:
                        is_contract_denied = True
                        contract_deny_reason = f"Contract permission not permitted: '{req_act}:{req_res}'"

                if is_contract_denied:
                    self.audit_service.record_event(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        user_id=effective_actor_id if effective_is_owner else None,
                        event_type="tool_execution_blocked",
                        action=action,
                        description=contract_deny_reason,
                        event_metadata={
                            "tool_id": str(tool.id),
                            "tool_slug": tool.slug,
                            "task_id": str(task_id) if task_id else None,
                            "resource": resource,
                            "contract_action": req_act,
                            "contract_resource": req_res,
                            "decision": "DENY",
                            "status": "blocked",
                            "is_owner": effective_is_owner,
                            "actor_id": str(effective_actor_id) if effective_actor_id else None,
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
                                error_info={"decision": "DENY", "reason": contract_deny_reason},
                                idempotency_key=effective_idem_key,
                            )
                        except Exception:
                            pass

                    return ToolExecutionResult(
                        status="blocked",
                        tool_id=tool.id,
                        tool_slug=tool.slug,
                        decision="DENY",
                        reason=contract_deny_reason,
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
                user_id=effective_actor_id if effective_is_owner else None,
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
                    "is_owner": effective_is_owner,
                    "actor_id": str(effective_actor_id) if effective_actor_id else None,
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
                user_id=effective_actor_id if effective_is_owner else None,
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
                    "is_owner": effective_is_owner,
                    "actor_id": str(effective_actor_id) if effective_actor_id else None,
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
            user_id=effective_actor_id if effective_is_owner else None,
            event_type="tool_execution",
            action=action,
            description=f"Tool '{tool.slug}' executed successfully",
            event_metadata={
                "tool_id": str(tool.id),
                "tool_slug": tool.slug,
                "resource": resource,
                "decision": decision.decision,
                "status": "executed",
                "is_owner": effective_is_owner,
                "actor_id": str(effective_actor_id) if effective_actor_id else None,
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

