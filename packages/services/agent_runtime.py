from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from packages.models.domain import Task
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.task_planner import TaskPlanner
from packages.services.task_service import TaskService


class AgentRuntime:
    """
    Foundation of the Digital Employee brain.

    This layer receives a business request and converts it
    into a structured Task.

    The runtime then plans and orchestrates the task.
    LLM planning will be added above this layer later.
    """

    def __init__(self, db: Session):
        self.db = db
        self.task_service = TaskService(db)
        self.task_planner = TaskPlanner()
        self.agent_orchestrator = AgentOrchestrator(db)

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

    def process_request(
        self,
        tenant_id: UUID,
        request: str,
        agent_id: UUID | None = None,
        requested_by_user_id: UUID | None = None,
        priority: str = "normal",
    ) -> Task:
        """
        Full Digital Employee request lifecycle:

        Request
            ?
        Task
            ?
        Plan
            ?
        Orchestrate
            ?
        Persisted Task Result
        """

        task = self.receive_request(
            tenant_id=tenant_id,
            request=request,
            agent_id=agent_id,
            requested_by_user_id=requested_by_user_id,
            priority=priority,
        )

        self.task_planner.create_basic_plan(task)

        self.agent_orchestrator.execute_task(
            tenant_id=tenant_id,
            task_id=task.id,
        )

        return self.task_service.get_task(
            tenant_id=tenant_id,
            task_id=task.id,
        )

    @staticmethod
    def _build_task_title(request: str) -> str:
        words = request.split()

        if len(words) <= 8:
            return request

        return " ".join(words[:8]) + "..."
