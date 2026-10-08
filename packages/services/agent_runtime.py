from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from packages.models.domain import Task
from packages.services.task_service import TaskService


class AgentRuntime:
    """
    Foundation of the Digital Employee brain.

    This layer receives a business request and converts it
    into a structured Task.

    LLM planning will be added above this layer later.
    """

    def __init__(self, db: Session):
        self.db = db
        self.task_service = TaskService(db)

    def receive_request(
        self,
        tenant_id: UUID,
        request: str,
        agent_id: UUID | None = None,
        requested_by_user_id: UUID | None = None,
        priority: str = "normal",
    ) -> Task:
        request = request.strip()

        if not request:
            raise ValueError("Request cannot be empty")

        title = self._build_task_title(request)

        return self.task_service.create_task(
            tenant_id=tenant_id,
            title=title,
            objective=request,
            agent_id=agent_id,
            requested_by_user_id=requested_by_user_id,
            priority=priority,
        )

    @staticmethod
    def _build_task_title(request: str) -> str:
        words = request.split()

        if len(words) <= 8:
            return request

        return " ".join(words[:8]) + "..."
