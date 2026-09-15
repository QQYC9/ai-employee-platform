from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from packages.services.audit_service import AuditService
from packages.services.decision_engine import DecisionEngine
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
    ):
        self.db = db
        self.tool_service = ToolService(db)
        self.decision_engine = DecisionEngine(db)
        self.audit_service = AuditService(db)
        self.handlers = handlers or {}

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
        parameters: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
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
        )

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
                    "resource": resource,
                    "decision": decision.decision,
                    "status": "blocked",
                },
            )

            return ToolExecutionResult(
                status="blocked",
                tool_id=tool.id,
                tool_slug=tool.slug,
                decision=decision.decision,
                reason=decision.reason,
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

            raise ValueError(
                f"No execution handler registered for tool '{tool.slug}'"
            )

        try:
            output = handler(**(parameters or {}))
        except Exception as exc:
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

        return ToolExecutionResult(
            status="executed",
            tool_id=tool.id,
            tool_slug=tool.slug,
            decision=decision.decision,
            reason=decision.reason,
            output=output,
        )
