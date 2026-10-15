from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.config import settings
from packages.auth.dependencies import get_current_user, get_db
from packages.auth.rate_limiter import rate_limit_dependency
from packages.models.domain import Approval, Task, User
from packages.services.agent_orchestrator import AgentOrchestrator
from packages.services.agent_runtime import AgentRuntime
from packages.services.approval_service import ApprovalService
from packages.services.idempotency_service import (
    ConcurrencyConflictError,
    IdempotencyTamperingError,
    ReconciliationRequiredError,
)
from packages.services.task_execution_service import TaskExecutionService
from packages.services.task_planner import PlanStep
from packages.services.task_service import TaskService


router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    agent_id: UUID | None = None
    priority: str = "normal"


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    objective: str | None = Field(default=None, min_length=1)
    priority: str | None = None
    plan: dict | None = None


class AgentRequest(BaseModel):
    request: str = Field(min_length=1)
    agent_id: UUID | None = None
    priority: str = "normal"


def serialize_task(task: Task) -> dict:
    return {
        "id": str(task.id),
        "tenant_id": str(task.tenant_id),
        "agent_id": str(task.agent_id) if task.agent_id else None,
        "requested_by_user_id": (
            str(task.requested_by_user_id)
            if task.requested_by_user_id
            else None
        ),
        "title": task.title,
        "objective": task.objective,
        "status": task.status,
        "priority": task.priority,
        "plan": task.plan,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


@router.get("/status")
def tasks_status():
    return {
        "status": "ok",
        "service": "tasks",
    }


@router.post("", status_code=201)
def create_task(
    payload: TaskCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)

    try:
        task = service.create_task(
            tenant_id=current_user.tenant_id,
            title=payload.title,
            objective=payload.objective,
            agent_id=payload.agent_id,
            requested_by_user_id=current_user.id,
            priority=payload.priority,
        )
        db.commit()
        db.refresh(task)

        return serialize_task(task)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@router.post("/request", status_code=201)
def receive_agent_request(
    payload: AgentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    runtime = AgentRuntime(db)

    try:
        task = runtime.receive_request(
            tenant_id=current_user.tenant_id,
            request=payload.request,
            agent_id=payload.agent_id,
            requested_by_user_id=current_user.id,
            priority=payload.priority,
        )
        db.commit()
        db.refresh(task)

        return serialize_task(task)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@router.get("")
def list_tasks(
    status: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)

    try:
        tasks = service.list_tasks(
            tenant_id=current_user.tenant_id,
            status=status,
            agent_id=agent_id,
        )

        return [serialize_task(task) for task in tasks]

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )


@router.get("/{task_id}")
def get_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)

    task = service.get_task(
        tenant_id=current_user.tenant_id,
        task_id=task_id,
    )

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return serialize_task(task)


@router.patch("/{task_id}")
def update_task(
    task_id: UUID,
    payload: TaskUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)

    task = service.get_task(current_user.tenant_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    user_role = (current_user.role or "").strip().lower()
    is_admin_or_owner = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    is_task_requester = getattr(task, "requested_by_user_id", None) == current_user.id
    if not (is_admin_or_owner or is_task_requester):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: User lacks permissions to update this task",
        )

    try:
        task = service.update_task(
            tenant_id=current_user.tenant_id,
            task_id=task_id,
            title=payload.title,
            objective=payload.objective,
            priority=payload.priority,
            plan=payload.plan,
        )

        db.commit()
        db.refresh(task)

        return serialize_task(task)

    except ValueError as exc:
        status_code = 404 if str(exc) == "Task not found" else 400

        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        )


class TaskPlanRequest(BaseModel):
    steps: list[dict[str, Any]] | None = None


class TaskResumeRequest(BaseModel):
    approval_id: UUID | None = None


@router.post(
    "/{task_id}/plan",
    dependencies=[
        Depends(
            rate_limit_dependency(
                max_requests=settings.rate_limit_planning_per_minute,
                window_seconds=60,
                key_prefix="tasks:plan",
            )
        )
    ],
)
def plan_task(
    task_id: UUID,
    payload: TaskPlanRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(current_user.tenant_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    user_role = (current_user.role or "").strip().lower()
    is_admin_or_owner = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    is_task_requester = getattr(task, "requested_by_user_id", None) == current_user.id
    if not (is_admin_or_owner or is_task_requester):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: User lacks permissions to plan this task",
        )

    plan_steps = None
    if payload and payload.steps:
        plan_steps = [
            PlanStep(
                step_id=s.get("step_id") or f"step_{i+1}",
                step_type=s.get("step_type", "tool"),
                description=s.get("description", ""),
                action=s.get("action"),
                resource=s.get("resource"),
                tool_id=UUID(str(s["tool_id"])) if s.get("tool_id") else None,
                parameters=s.get("parameters"),
            )
            for i, s in enumerate(payload.steps)
        ]

    try:
        orchestrator = AgentOrchestrator(db)
        orchestrator.plan_task(
            tenant_id=current_user.tenant_id,
            task_id=task_id,
            steps=plan_steps,
        )
        db.commit()
        task = service.get_task(current_user.tenant_id, task_id)
        return serialize_task(task)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{task_id}/execute")
def execute_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(current_user.tenant_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    user_role = (current_user.role or "").strip().lower()
    is_admin_or_owner = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    is_task_requester = getattr(task, "requested_by_user_id", None) == current_user.id
    if not (is_admin_or_owner or is_task_requester):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: User lacks permissions to execute this task",
        )

    try:
        orchestrator = AgentOrchestrator(db)
        orch_result = orchestrator.execute_task(
            tenant_id=current_user.tenant_id,
            task_id=task_id,
        )
        db.commit()
        db.refresh(task)
        return {
            "task": serialize_task(task),
            "orchestration": {
                "status": orch_result.status,
                "error": orch_result.error,
                "result": orch_result.result,
            },
        }
    except ConcurrencyConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except (ReconciliationRequiredError, IdempotencyTamperingError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{task_id}/resume")
def resume_task(
    task_id: UUID,
    payload: TaskResumeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(current_user.tenant_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "waiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Task is in status '{task.status}', expected 'waiting_approval'",
        )

    exec_service = TaskExecutionService(db)
    approval_service = ApprovalService(db)

    approval_id = payload.approval_id if payload else None
    if approval_id is None:
        approvals = approval_service.list_approvals(
            tenant_id=current_user.tenant_id,
            task_id=task_id,
            status="approved",
        )
        if not approvals:
            raise HTTPException(
                status_code=400,
                detail="No approved approval record found for this task",
            )
        approval_id = approvals[0].id

    approval = approval_service.get_approval(current_user.tenant_id, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    # Explicit user authorization verification
    user_role = (current_user.role or "").strip().lower()
    is_admin_or_owner = user_role in ("owner", "tenant_owner", "admin", "tenant_admin", "superadmin", "platform_admin")
    is_task_requester = getattr(task, "requested_by_user_id", None) == current_user.id
    is_approver = getattr(approval, "decision_by_user_id", None) == current_user.id

    if not (is_admin_or_owner or is_task_requester or is_approver):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: User lacks permissions to resume this task",
        )

    try:
        task = exec_service.resume_approved_task(
            tenant_id=current_user.tenant_id,
            task_id=task_id,
            approval_id=approval_id,
        )
        orchestrator = AgentOrchestrator(db)
        orch_result = orchestrator.execute_task(
            tenant_id=current_user.tenant_id,
            task_id=task_id,
        )
        db.commit()
        db.refresh(task)
        return {
            "task": serialize_task(task),
            "orchestration": {
                "status": orch_result.status,
                "error": orch_result.error,
                "result": orch_result.result,
            },
        }
    except ConcurrencyConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except (ReconciliationRequiredError, IdempotencyTamperingError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

