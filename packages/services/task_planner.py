from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
from uuid import UUID

from packages.context.models import AgentContext
from packages.models.domain import Task


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    step_type: str
    description: str
    action: str | None = None
    resource: str | None = None
    tool_id: UUID | None = None
    parameters: dict[str, Any] | None = None
    requires_approval: bool = False
    approval_for: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    objective: str
    steps: list[PlanStep]

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "steps": [
                {
                    **asdict(step),
                    "tool_id": str(step.tool_id) if step.tool_id else None,
                }
                for step in self.steps
            ],
        }


class TaskPlanner:
    """
    Provider-independent task planner.

    Accepts optional task context so future planning strategies
    can use business information, memory, and knowledge.
    """

    def create_plan(
        self,
        task: Task,
        steps: list[PlanStep],
        context: AgentContext | None = None,
    ) -> ExecutionPlan:
        if not task.objective.strip():
            raise ValueError("Task objective cannot be empty")

        if not steps:
            raise ValueError("Execution plan must contain at least one step")

        if context is not None and context.tenant_id != task.tenant_id:
            raise ValueError("Context tenant does not match task tenant")

        normalized_steps: list[PlanStep] = []

        for step in steps:
            if not step.step_id.strip():
                raise ValueError("Plan step id cannot be empty")

            if not step.step_type.strip():
                raise ValueError("Plan step type cannot be empty")

            if not step.description.strip():
                raise ValueError("Plan step description cannot be empty")

            normalized_steps.append(
                PlanStep(
                    step_id=step.step_id,
                    step_type=step.step_type,
                    description=step.description,
                    action=step.action,
                    resource=step.resource,
                    tool_id=step.tool_id,
                    parameters=step.parameters or {},
                    requires_approval=getattr(step, "requires_approval", False),
                    approval_for=getattr(step, "approval_for", None),
                )
            )

        return ExecutionPlan(
            objective=task.objective,
            steps=normalized_steps,
        )

    def create_basic_plan(
        self,
        task: Task,
        context: AgentContext | None = None,
    ) -> ExecutionPlan:
        """
        Creates a safe initial plan without inventing tools or actions.

        Context is accepted for future planning strategies but does not
        currently change the generated plan.
        """
        if context is not None and context.tenant_id != task.tenant_id:
            raise ValueError("Context tenant does not match task tenant")

        return ExecutionPlan(
            objective=task.objective,
            steps=[
                PlanStep(
                    step_id="understand",
                    step_type="analysis",
                    description="Understand the task objective",
                ),
                PlanStep(
                    step_id="execute",
                    step_type="execution",
                    description="Execute the required task actions",
                ),
                PlanStep(
                    step_id="verify",
                    step_type="verification",
                    description="Verify the task result",
                ),
            ],
        )
