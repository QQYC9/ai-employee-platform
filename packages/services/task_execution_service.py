from __future__ import annotations

import hashlib
import inspect
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Task, User
from packages.services.agent_capability_service import AgentCapabilityService
from packages.services.approval_service import ApprovalService
from packages.services.audit_service import AuditService
from packages.services.capability_tool_service import CapabilityToolService
from packages.tools.executor import ToolExecutor


class TaskExecutionService:
    def __init__(
        self,
        db: Session,
        approval_service: ApprovalService | None = None,
        audit_service: AuditService | None = None,
        agent_capability_service: AgentCapabilityService | None = None,
        capability_tool_service: CapabilityToolService | None = None,
    ):
        self.db = db
        self.approval_service = approval_service or ApprovalService(db)
        self.audit_service = audit_service or AuditService(db)
        self.agent_capability_service = (
            agent_capability_service or AgentCapabilityService(db)
        )
        self.capability_tool_service = (
            capability_tool_service or CapabilityToolService(db)
        )

    def _get_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
    ) -> Task:
        task = (
            self.db.query(Task)
            .filter(
                Task.id == task_id,
                Task.tenant_id == tenant_id,
            )
            .first()
        )

        if task is None:
            raise ValueError("Task not found")

        return task

    def start_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
    ) -> Task:
        task = self._get_task(tenant_id, task_id)

        if task.status != "pending":
            raise ValueError(
                f"Task cannot be started from status: {task.status}"
            )

        task.status = "running"
        self.db.flush()

        return task

    def complete_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        result: dict,
    ) -> Task:
        task = self._get_task(tenant_id, task_id)

        if task.status != "running":
            raise ValueError(
                f"Task cannot be completed from status: {task.status}"
            )

        task.status = "completed"
        task.result = result
        task.error = None
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=task.agent_id,
            event_type="task_completed",
            action="complete_task",
            description=f"Task '{task.title}' completed successfully",
            event_metadata={
                "task_id": str(task.id),
                "status": "completed",
            },
        )

        return task

    def fail_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        error: str,
        record_audit: bool = True,
    ) -> Task:
        task = self._get_task(tenant_id, task_id)

        if task.status != "running":
            raise ValueError(
                f"Task cannot be failed from status: {task.status}"
            )

        if not error.strip():
            raise ValueError("Task error cannot be empty")

        task.status = "failed"
        task.error = error
        self.db.flush()

        if record_audit:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                agent_id=task.agent_id,
                event_type="task_failed",
                action="fail_task",
                description=error,
                event_metadata={
                    "task_id": str(task.id),
                    "status": "failed",
                    "error": error,
                },
            )

        return task

    def request_approval(
        self,
        tenant_id: UUID,
        task_id: UUID,
        action: str,
        description: str,
        requested_for: str = "tenant_owner",
    ) -> Task:
        task = self._get_task(tenant_id, task_id)

        if task.status != "running":
            raise ValueError(
                f"Task cannot request approval from status: {task.status}"
            )

        approval = self.approval_service.create_approval(
            tenant_id=tenant_id,
            requested_for=requested_for,
            action=action,
            description=description,
            task_id=task.id,
            requested_by_agent_id=task.agent_id,
        )

        task.status = "waiting_approval"
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=task.agent_id,
            event_type="approval_requested",
            action=action,
            description=description,
            event_metadata={
                "task_id": str(task.id),
                "approval_id": str(approval.id),
                "requested_for": requested_for,
                "status": "waiting_approval",
            },
        )

        return task

    def resume_approved_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        approval_id: UUID,
    ) -> Task:
        task = self._get_task(tenant_id, task_id)

        if task.status != "waiting_approval":
            raise ValueError(
                f"Task cannot be resumed from status: {task.status}"
            )

        approval = self.approval_service.get_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
        )

        if approval is None:
            raise ValueError("Approval not found")

        if approval.task_id != task.id:
            raise ValueError("Approval does not belong to task")

        if approval.status != "approved":
            raise ValueError(
                f"Task approval is not approved: {approval.status}"
            )

        # Verify approver authority
        if getattr(approval, "decision_by_user_id", None) is not None:
            try:
                approver = self.db.scalar(
                    select(User).where(User.id == approval.decision_by_user_id)
                )
                if approver is not None and not ApprovalService.is_role_authorized(
                    getattr(approver, "role", None), approval.requested_for
                ):
                    raise ValueError(
                        f"Approval was granted by unauthorized user role: '{getattr(approver, 'role', None)}'"
                    )
            except Exception as exc:
                if isinstance(exc, ValueError):
                    raise

        task.status = "running"
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=task.agent_id,
            event_type="task_resumed",
            action="resume_approved_task",
            description=f"Task '{task.title}' resumed after approval",
            event_metadata={
                "task_id": str(task.id),
                "approval_id": str(approval.id),
                "status": "running",
            },
        )

        return task

    def _ensure_tool_assigned_to_agent(
        self,
        tenant_id: UUID,
        agent_id: UUID | None,
        tool_id: UUID,
    ) -> None:
        if agent_id is None:
            return

        capabilities = self.agent_capability_service.list_capabilities(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        for capability in capabilities:
            tools = self.capability_tool_service.list_tools(
                tenant_id=tenant_id,
                capability_id=capability.id,
            )
            if any(tool.id == tool_id for tool in tools):
                return

        raise ValueError(
            "Tool is not assigned to a capability of this agent"
        )

    def execute_tool(
        self,
        tenant_id: UUID,
        task_id: UUID,
        tool_id: UUID,
        action: str,
        resource: str,
        parameters: dict | None = None,
        executor: ToolExecutor | None = None,
        task_already_running: bool = False,
        idempotency_key: str | None = None,
    ) -> Task:
        if executor is None:
            executor = ToolExecutor(self.db)

        task = self._get_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        if task_already_running:
            if task.status != "running":
                raise ValueError(
                    "Task must be running when task_already_running is true"
                )
        else:
            if task.status != "pending":
                raise ValueError(
                    f"Task cannot be executed from status: {task.status}"
                )

            self.start_task(
                tenant_id=tenant_id,
                task_id=task_id,
            )

        try:
            self._ensure_tool_assigned_to_agent(
                tenant_id=tenant_id,
                agent_id=task.agent_id,
                tool_id=tool_id,
            )

            execute_kwargs = {
                "tenant_id": tenant_id,
                "tool_id": tool_id,
                "action": action,
                "resource": resource,
                "parameters": parameters,
                "agent_id": task.agent_id,
            }
            try:
                sig = inspect.signature(executor.execute)
                if "task_id" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                ):
                    execute_kwargs["task_id"] = task_id
                if "idempotency_key" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                ):
                    execute_kwargs["idempotency_key"] = idempotency_key
            except (ValueError, TypeError):
                execute_kwargs["task_id"] = task_id
                execute_kwargs["idempotency_key"] = idempotency_key

            execution = executor.execute(**execute_kwargs)

            if execution.status == "blocked":
                if execution.decision == "APPROVAL_REQUIRED":
                    params_hash = hashlib.sha256(
                        json.dumps(parameters or {}, sort_keys=True).encode()
                    ).hexdigest()
                    context_payload = {
                        "tool_id": str(tool_id),
                        "tool_slug": execution.tool_slug,
                        "resource": resource or "",
                        "parameters_hash": params_hash,
                    }
                    approval_desc = (
                        f"Approval required to execute tool: {execution.tool_slug}\n"
                        f"[context:{json.dumps(context_payload, sort_keys=True)}]"
                    )
                    self.request_approval(
                        tenant_id=tenant_id,
                        task_id=task_id,
                        action=action,
                        description=approval_desc,
                    )
                    return task

                self.fail_task(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    error=execution.reason,
                )
                return task

            if execution.status != "executed":
                self.fail_task(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    error=execution.reason,
                )
                return task

            if task_already_running:
                task.result = execution.output
                task.error = None
                self.db.flush()
                return task

            return self.complete_task(
                tenant_id=tenant_id,
                task_id=task_id,
                result=execution.output,
            )

        except Exception as exc:
            current_task = self._get_task(
                tenant_id=tenant_id,
                task_id=task_id,
            )

            if current_task.status == "running":
                self.fail_task(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    error=str(exc),
                    record_audit=not isinstance(exc, ValueError),
                )

            if isinstance(exc, ValueError):
                self.audit_service.record_event(
                    tenant_id=tenant_id,
                    agent_id=task.agent_id,
                    event_type="tool_execution_blocked",
                    action=action,
                    description=str(exc),
                    event_metadata={
                        "tool_id": str(tool_id),
                        "task_id": str(task_id),
                        "resource": resource,
                        "decision": "DENY",
                        "status": "blocked",
                    },
                )

            raise
