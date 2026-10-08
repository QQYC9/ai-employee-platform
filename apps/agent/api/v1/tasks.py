from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import Task, User
from packages.services.agent_runtime import AgentRuntime
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
