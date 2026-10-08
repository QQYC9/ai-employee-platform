from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Task


class TaskService:
    """
    Business logic for Task management.

    All operations are explicitly tenant-scoped.
    """

    ALLOWED_STATUSES = {
        "pending",
        "running",
        "waiting_approval",
        "completed",
        "failed",
    }

    ALLOWED_PRIORITIES = {
        "low",
        "normal",
        "high",
        "urgent",
    }

    def __init__(self, db: Session):
        self.db = db

    def create_task(
        self,
        tenant_id: UUID,
        title: str,
        objective: str,
        agent_id: UUID | None = None,
        requested_by_user_id: UUID | None = None,
        priority: str = "normal",
    ) -> Task:
        title = title.strip()
        objective = objective.strip()
        priority = priority.strip()

        if not title:
            raise ValueError("Task title cannot be empty")

        if not objective:
            raise ValueError("Task objective cannot be empty")

        if priority not in self.ALLOWED_PRIORITIES:
            raise ValueError("Invalid task priority")

        task = Task(
            tenant_id=tenant_id,
            agent_id=agent_id,
            requested_by_user_id=requested_by_user_id,
            title=title,
            objective=objective,
            status="pending",
            priority=priority,
            plan={},
            result={},
        )

        self.db.add(task)
        self.db.flush()

        return task

    def get_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
    ) -> Task | None:
        return self.db.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.tenant_id == tenant_id,
            )
        )

    def list_tasks(
        self,
        tenant_id: UUID,
        status: str | None = None,
        agent_id: UUID | None = None,
    ) -> list[Task]:
        statement = (
            select(Task)
            .where(Task.tenant_id == tenant_id)
            .order_by(Task.created_at.desc())
        )

        if status is not None:
            if status not in self.ALLOWED_STATUSES:
                raise ValueError("Invalid task status")

            statement = statement.where(Task.status == status)

        if agent_id is not None:
            statement = statement.where(Task.agent_id == agent_id)

        return list(self.db.scalars(statement).all())

    def update_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        title: str | None = None,
        objective: str | None = None,
        priority: str | None = None,
        plan: dict | None = None,
    ) -> Task:
        task = self.get_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        if task is None:
            raise ValueError("Task not found")

        if title is not None:
            title = title.strip()

            if not title:
                raise ValueError("Task title cannot be empty")

            task.title = title

        if objective is not None:
            objective = objective.strip()

            if not objective:
                raise ValueError("Task objective cannot be empty")

            task.objective = objective

        if priority is not None:
            priority = priority.strip()

            if priority not in self.ALLOWED_PRIORITIES:
                raise ValueError("Invalid task priority")

            task.priority = priority

        if plan is not None:
            task.plan = plan

        self.db.flush()

        return task
