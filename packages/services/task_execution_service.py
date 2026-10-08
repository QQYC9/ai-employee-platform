from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from packages.models.domain import Task
from packages.services.approval_service import ApprovalService
from packages.tools.executor import ToolExecutor


class TaskExecutionService:
    def __init__(self, db: Session):
        self.db = db
        self.approval_service = ApprovalService(db)

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

        return task

    def fail_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        error: str,
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

        self.approval_service.create_approval(
            tenant_id=tenant_id,
            requested_for=requested_for,
            action=action,
            description=description,
            task_id=task.id,
            requested_by_agent_id=task.agent_id,
        )

        task.status = "waiting_approval"
        self.db.flush()

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

        task.status = "running"
        self.db.flush()

        return task

    def execute_tool(
        self,
        tenant_id: UUID,
        task_id: UUID,
        tool_id: UUID,
        action: str,
        resource: str,
        parameters: dict | None = None,
        executor: ToolExecutor | None = None,
    ) -> Task:
        if executor is None:
            executor = ToolExecutor(self.db)

        task = self._get_task(tenant_id, task_id)

        if task.status != "pending":
            raise ValueError(
                f"Task cannot be executed from status: {task.status}"
            )

        self.start_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        try:
            execution = executor.execute(
                tenant_id=tenant_id,
                tool_id=tool_id,
                action=action,
                resource=resource,
                parameters=parameters,
                agent_id=task.agent_id,
            )

            if execution.status == "blocked":
                if execution.decision == "APPROVAL_REQUIRED":
                    self.request_approval(
                        tenant_id=tenant_id,
                        task_id=task_id,
                        action=action,
                        description=(
                            f"Approval required to execute tool: "
                            f"{execution.tool_slug}"
                        ),
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

            return self.complete_task(
                tenant_id=tenant_id,
                task_id=task_id,
                result=execution.output,
            )

        except Exception as exc:
            self.fail_task(
                tenant_id=tenant_id,
                task_id=task_id,
                error=str(exc),
            )
            raise
