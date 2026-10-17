from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
from packages.services.proactive_workflow_service import ProactiveWorkflowService

router = APIRouter(prefix="/workflows", tags=["Proactive Workflows"])


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str = Field(default="schedule", description="schedule, interval, event, due_date, conversation_idle")
    schedule_type: str = Field(default="interval", description="interval, cron, once, event")
    interval_seconds: int | None = Field(default=None, ge=10)
    cron_expression: str | None = None
    timezone_name: str = "UTC"
    action_type: str = Field(default="run_task", description="run_task, follow_up_conversation, generate_daily_report, check_overdue_tasks, custom_prompt")
    action_payload: dict[str, Any] = Field(default_factory=dict)
    agent_id: UUID | None = None
    max_retries: int = Field(default=3, ge=0, le=10)
    start_immediately: bool = False


class TriggerEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=100)
    source_id: str = Field(..., min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


def _serialize_workflow(wf: Any) -> dict[str, Any]:
    return {
        "id": str(wf.id),
        "tenant_id": str(wf.tenant_id),
        "agent_id": str(wf.agent_id) if wf.agent_id else None,
        "name": wf.name,
        "description": wf.description,
        "trigger_type": wf.trigger_type,
        "schedule_type": wf.schedule_type,
        "interval_seconds": wf.interval_seconds,
        "cron_expression": wf.cron_expression,
        "timezone": wf.timezone,
        "action_type": wf.action_type,
        "action_payload": wf.action_payload,
        "status": wf.status,
        "is_active": wf.is_active,
        "next_run_at": wf.next_run_at.isoformat() if wf.next_run_at else None,
        "last_run_at": wf.last_run_at.isoformat() if wf.last_run_at else None,
        "total_runs": wf.total_runs,
        "max_retries": wf.max_retries,
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
    }


def _serialize_run(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "tenant_id": str(r.tenant_id),
        "workflow_id": str(r.workflow_id),
        "task_id": str(r.task_id) if r.task_id else None,
        "trigger_source": r.trigger_source,
        "trigger_event_id": r.trigger_event_id,
        "idempotency_key": r.idempotency_key,
        "status": r.status,
        "attempt_count": r.attempt_count,
        "max_attempts": r.max_attempts,
        "scheduled_at": r.scheduled_at.isoformat() if r.scheduled_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "result": r.result,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    try:
        wf = service.create_workflow(
            tenant_id=current_user.tenant_id,
            name=payload.name,
            action_type=payload.action_type,
            action_payload=payload.action_payload,
            trigger_type=payload.trigger_type,
            schedule_type=payload.schedule_type,
            interval_seconds=payload.interval_seconds,
            cron_expression=payload.cron_expression,
            timezone_name=payload.timezone_name,
            agent_id=payload.agent_id,
            description=payload.description,
            max_retries=payload.max_retries,
            start_immediately=payload.start_immediately,
        )
        db.commit()
        return _serialize_workflow(wf)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("")
def list_workflows(
    status: str | None = Query(None),
    trigger_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    workflows = service.list_workflows(
        tenant_id=current_user.tenant_id,
        status=status,
        trigger_type=trigger_type,
        is_active=is_active,
    )
    return [_serialize_workflow(w) for w in workflows]


@router.get("/{workflow_id}")
def get_workflow(
    workflow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    wf = service.get_workflow(current_user.tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _serialize_workflow(wf)


@router.post("/{workflow_id}/pause")
def pause_workflow(
    workflow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    try:
        wf = service.pause_workflow(current_user.tenant_id, workflow_id)
        db.commit()
        return _serialize_workflow(wf)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{workflow_id}/resume")
def resume_workflow(
    workflow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    try:
        wf = service.resume_workflow(current_user.tenant_id, workflow_id)
        db.commit()
        return _serialize_workflow(wf)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{workflow_id}")
def cancel_workflow(
    workflow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    try:
        wf = service.cancel_workflow(current_user.tenant_id, workflow_id)
        db.commit()
        return _serialize_workflow(wf)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{workflow_id}/trigger")
def trigger_manual_run(
    workflow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    wf = service.get_workflow(current_user.tenant_id, workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = service.enqueue_run(
        tenant_id=current_user.tenant_id,
        workflow_id=workflow_id,
        trigger_source="manual",
    )
    db.commit()
    return _serialize_run(run)


@router.get("/{workflow_id}/runs")
def list_workflow_runs(
    workflow_id: UUID,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    runs = service.list_runs(
        tenant_id=current_user.tenant_id,
        workflow_id=workflow_id,
        status=status,
        limit=limit,
    )
    return [_serialize_run(r) for r in runs]


@router.post("/events")
def ingest_trigger_event(
    payload: TriggerEventRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.tenant_id is None:
        raise HTTPException(status_code=400, detail="User has no tenant association")
    service = ProactiveWorkflowService(db)
    event = service.fire_trigger_event(
        tenant_id=current_user.tenant_id,
        event_type=payload.event_type,
        source_id=payload.source_id,
        payload=payload.payload,
        idempotency_key=payload.idempotency_key,
    )
    db.commit()
    return {
        "event_id": str(event.id),
        "tenant_id": str(event.tenant_id),
        "event_type": event.event_type,
        "source_id": event.source_id,
        "status": event.status,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
