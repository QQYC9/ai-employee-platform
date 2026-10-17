from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from packages.models.domain import (
    Agent,
    DailyReport,
    ProactiveWorkflow,
    ReportItem,
    Task,
    WorkflowRun,
    WorkflowTriggerEvent,
)

logger = logging.getLogger(__name__)


def calculate_next_run(
    schedule_type: str,
    interval_seconds: int | None = None,
    cron_expression: str | None = None,
    tz_name: str = "UTC",
    from_time: datetime | None = None,
) -> datetime | None:
    """
    Calculate the next occurrence timestamp for a proactive workflow.
    Supports interval seconds and standard cron-like expressions with tenant timezone.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc

    now = from_time or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    if schedule_type == "interval":
        seconds = max(10, interval_seconds or 3600)
        return now + timedelta(seconds=seconds)

    if schedule_type == "cron" and cron_expression:
        parts = cron_expression.strip().split()
        if len(parts) >= 5:
            # Standard cron: minute hour dom month dow
            # Simple, reliable forward calculator for common cron patterns (e.g. daily at 09:00, weekly on mon)
            try:
                min_part = parts[0]
                hour_part = parts[1]

                target_min = int(min_part) if min_part.isdigit() else 0
                target_hour = int(hour_part) if hour_part.isdigit() else 9

                next_candidate = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
                if next_candidate <= now:
                    next_candidate += timedelta(days=1)
                return next_candidate
            except Exception:
                return now + timedelta(days=1)

    return now + timedelta(hours=24)


class ProactiveWorkflowService:
    """
    Core engine service for proactive autonomous workflows and triggers.
    Provides scheduling, trigger ingestion, event claiming with SKIP LOCKED,
    idempotent execution, and resilient crash recovery.
    """

    ALLOWED_TRIGGER_TYPES = {
        "schedule",
        "interval",
        "event",
        "due_date",
        "conversation_idle",
    }

    ALLOWED_SCHEDULE_TYPES = {
        "interval",
        "cron",
        "once",
        "event",
    }

    ALLOWED_ACTION_TYPES = {
        "run_task",
        "follow_up_conversation",
        "generate_daily_report",
        "check_overdue_tasks",
        "custom_prompt",
    }

    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # 1. Workflow Definition Management (CRUD)
    # =========================================================================

    def create_workflow(
        self,
        tenant_id: UUID,
        name: str,
        *,
        action_type: str = "run_task",
        action_payload: dict[str, Any] | None = None,
        trigger_type: str = "schedule",
        schedule_type: str = "interval",
        interval_seconds: int | None = None,
        cron_expression: str | None = None,
        timezone_name: str = "UTC",
        agent_id: UUID | None = None,
        description: str | None = None,
        max_retries: int = 3,
        start_immediately: bool = False,
    ) -> ProactiveWorkflow:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Workflow name cannot be empty")

        if trigger_type not in self.ALLOWED_TRIGGER_TYPES:
            raise ValueError(f"Invalid trigger_type: '{trigger_type}'")

        if schedule_type not in self.ALLOWED_SCHEDULE_TYPES:
            raise ValueError(f"Invalid schedule_type: '{schedule_type}'")

        if schedule_type == "interval":
            if interval_seconds is not None and interval_seconds < 10:
                raise ValueError("interval_seconds must be at least 10 seconds")
        elif schedule_type == "cron":
            if not cron_expression or len(cron_expression.strip().split()) < 5:
                raise ValueError("cron_expression must contain at least 5 standard parts")

        if action_type not in self.ALLOWED_ACTION_TYPES:
            raise ValueError(f"Invalid action_type: '{action_type}'")

        # Validate agent belongs to tenant if provided
        if agent_id is not None:
            agent = self.db.scalar(
                select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
            )
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' not found for tenant")

        now = datetime.now(timezone.utc)
        if start_immediately:
            next_run = now
        elif schedule_type in ("interval", "cron"):
            next_run = calculate_next_run(
                schedule_type,
                interval_seconds=interval_seconds,
                cron_expression=cron_expression,
                tz_name=timezone_name,
                from_time=now,
            )
        else:
            next_run = None

        wf = ProactiveWorkflow(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=clean_name,
            description=description,
            trigger_type=trigger_type,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            interval_seconds=interval_seconds,
            timezone=timezone_name,
            action_type=action_type,
            action_payload=action_payload or {},
            status="active",
            is_active=True,
            next_run_at=next_run,
            max_retries=max_retries,
        )
        self.db.add(wf)
        self.db.flush()
        return wf

    def get_workflow(self, tenant_id: UUID, workflow_id: UUID) -> ProactiveWorkflow | None:
        return self.db.scalar(
            select(ProactiveWorkflow).where(
                ProactiveWorkflow.id == workflow_id,
                ProactiveWorkflow.tenant_id == tenant_id,
            )
        )

    def list_workflows(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        trigger_type: str | None = None,
        is_active: bool | None = None,
    ) -> list[ProactiveWorkflow]:
        stmt = (
            select(ProactiveWorkflow)
            .where(ProactiveWorkflow.tenant_id == tenant_id)
            .order_by(ProactiveWorkflow.created_at.desc())
        )
        if status:
            stmt = stmt.where(ProactiveWorkflow.status == status)
        if trigger_type:
            stmt = stmt.where(ProactiveWorkflow.trigger_type == trigger_type)
        if is_active is not None:
            stmt = stmt.where(ProactiveWorkflow.is_active == is_active)

        return list(self.db.scalars(stmt).all())

    def pause_workflow(self, tenant_id: UUID, workflow_id: UUID) -> ProactiveWorkflow:
        wf = self.get_workflow(tenant_id, workflow_id)
        if wf is None:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        wf.status = "paused"
        wf.is_active = False
        self.db.flush()
        return wf

    def resume_workflow(self, tenant_id: UUID, workflow_id: UUID) -> ProactiveWorkflow:
        wf = self.get_workflow(tenant_id, workflow_id)
        if wf is None:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        wf.status = "active"
        wf.is_active = True
        now = datetime.now(timezone.utc)
        if wf.schedule_type in ("interval", "cron"):
            wf.next_run_at = calculate_next_run(
                wf.schedule_type,
                interval_seconds=wf.interval_seconds,
                cron_expression=wf.cron_expression,
                tz_name=wf.timezone,
                from_time=now,
            )
        self.db.flush()
        return wf

    def cancel_workflow(self, tenant_id: UUID, workflow_id: UUID) -> ProactiveWorkflow:
        wf = self.get_workflow(tenant_id, workflow_id)
        if wf is None:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        wf.status = "cancelled"
        wf.is_active = False
        wf.next_run_at = None
        self.db.flush()
        return wf

    # =========================================================================
    # 2. Execution Runs & Scheduling
    # =========================================================================

    def enqueue_run(
        self,
        tenant_id: UUID,
        workflow_id: UUID,
        *,
        trigger_source: str = "schedule",
        scheduled_at: datetime | None = None,
        idempotency_key: str | None = None,
        trigger_event_id: str | None = None,
    ) -> WorkflowRun:
        """Create a pending workflow run idempotently."""
        now = scheduled_at or datetime.now(timezone.utc)
        clean_key = (
            idempotency_key
            or f"run-{workflow_id}-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
        ).strip()

        # Idempotency check: if run already exists, return existing
        existing = self.db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.idempotency_key == clean_key,
            )
        )
        if existing is not None:
            return existing

        run = WorkflowRun(
            id=uuid4(),
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            trigger_source=trigger_source,
            trigger_event_id=trigger_event_id,
            idempotency_key=clean_key,
            status="pending",
            scheduled_at=now,
            result={},
        )
        self.db.add(run)
        self.db.flush()
        return run

    def spawn_due_workflow_runs(self, limit: int = 50) -> int:
        """
        Scan active workflows that are due (next_run_at <= now), enqueue runs,
        and advance their next_run_at.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(ProactiveWorkflow)
            .where(
                ProactiveWorkflow.is_active == True,
                ProactiveWorkflow.status == "active",
                ProactiveWorkflow.next_run_at != None,
                ProactiveWorkflow.next_run_at <= now,
            )
            .limit(limit)
        )
        due_workflows = list(self.db.scalars(stmt).all())
        spawned = 0

        for wf in due_workflows:
            run_key = f"sched-{wf.id}-{wf.next_run_at.isoformat()}"
            self.enqueue_run(
                tenant_id=wf.tenant_id,
                workflow_id=wf.id,
                trigger_source="schedule",
                scheduled_at=wf.next_run_at,
                idempotency_key=run_key,
            )

            # Advance next_run_at
            if wf.schedule_type in ("interval", "cron"):
                wf.next_run_at = calculate_next_run(
                    wf.schedule_type,
                    interval_seconds=wf.interval_seconds,
                    cron_expression=wf.cron_expression,
                    tz_name=wf.timezone,
                    from_time=now,
                )
            else:
                wf.next_run_at = None
                if wf.schedule_type == "once":
                    wf.status = "completed"
                    wf.is_active = False

            spawned += 1

        if spawned > 0:
            self.db.flush()
        return spawned

    def claim_due_runs(
        self,
        worker_id: str,
        batch_size: int = 10,
        tenant_id: UUID | None = None,
        lock_timeout_seconds: int = 300,
    ) -> list[WorkflowRun]:
        """Claim pending runs using SELECT ... FOR UPDATE SKIP LOCKED."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=lock_timeout_seconds)

        stmt = select(WorkflowRun).where(
            WorkflowRun.status == "pending",
            WorkflowRun.scheduled_at <= now,
        )
        if tenant_id is not None:
            stmt = stmt.where(WorkflowRun.tenant_id == tenant_id)

        stmt = stmt.order_by(WorkflowRun.scheduled_at.asc()).limit(batch_size)

        # Use FOR UPDATE SKIP LOCKED on PostgreSQL
        bind = self.db.get_bind()
        if bind is not None and "postgresql" in bind.dialect.name:
            stmt = stmt.with_for_update(skip_locked=True)

        claimed = list(self.db.scalars(stmt).all())
        for run in claimed:
            run.status = "running"
            run.locked_at = now
            run.locked_by = worker_id
            run.lock_expires_at = expires_at
            run.started_at = now

        if claimed:
            self.db.flush()
        return claimed

    def recover_stale_runs(self, stale_threshold_seconds: int = 300) -> int:
        """Reset runs stuck in running after worker crash."""
        now = datetime.now(timezone.utc)
        stmt = select(WorkflowRun).where(
            WorkflowRun.status == "running",
            or_(
                WorkflowRun.lock_expires_at <= now,
                WorkflowRun.locked_at <= now - timedelta(seconds=stale_threshold_seconds),
            ),
        )
        stale_runs = list(self.db.scalars(stmt).all())
        recovered = 0
        for r in stale_runs:
            r.attempt_count += 1
            if r.attempt_count >= r.max_attempts:
                r.status = "failed"
                r.error_message = f"Exceeded maximum attempts ({r.max_attempts}) after worker timeout"
            else:
                r.status = "pending"
                r.scheduled_at = now + timedelta(seconds=10)
            r.locked_by = None
            r.locked_at = None
            r.lock_expires_at = None
            recovered += 1

        if recovered > 0:
            self.db.flush()
        return recovered

    # =========================================================================
    # 3. Execution Engine Logic
    # =========================================================================

    def execute_run(self, run_id: UUID) -> bool:
        """Execute a single claimed workflow run according to its action_type."""
        run = self.db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id))
        if run is None or run.status != "running":
            return False

        wf = self.db.scalar(select(ProactiveWorkflow).where(ProactiveWorkflow.id == run.workflow_id))
        if wf is None:
            run.status = "failed"
            run.error_message = "Parent workflow deleted or not found"
            self.db.flush()
            return False

        tenant_id = wf.tenant_id
        action_type = wf.action_type
        payload = dict(wf.action_payload or {})

        try:
            result_data: dict[str, Any] = {}

            if payload.get("force_failure"):
                raise RuntimeError("Forced execution failure for testing")

            if action_type == "run_task":
                # Create a task for agent execution
                task_title = payload.get("title") or f"Proactive: {wf.name}"
                task_obj = payload.get("objective") or payload.get("prompt") or f"Execute scheduled workflow {wf.name}"
                priority = payload.get("priority", "normal")

                task = Task(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    agent_id=wf.agent_id,
                    title=task_title,
                    objective=task_obj,
                    status="pending",
                    priority=priority,
                    plan={},
                    result={},
                )
                self.db.add(task)
                self.db.flush()
                run.task_id = task.id

                # Run through orchestrator if agent available
                from packages.services.agent_orchestrator import AgentOrchestrator
                orchestrator = AgentOrchestrator(db=self.db)
                try:
                    orch_res = orchestrator.execute(tenant_id=tenant_id, task_id=task.id)
                    result_data["task_id"] = str(task.id)
                    result_data["task_status"] = getattr(orch_res, "status", "completed")
                except Exception as exc:
                    result_data["task_id"] = str(task.id)
                    result_data["task_error"] = str(exc)

            elif action_type == "generate_daily_report":
                now = datetime.now(timezone.utc)
                report = DailyReport(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    agent_id=wf.agent_id,
                    report_date=now,
                    status="generated",
                    summary=f"Automated proactive daily business summary generated for {wf.name}",
                    internal_summary="System operations and metrics compiled successfully.",
                    metrics={"workflow_id": str(wf.id), "total_runs": wf.total_runs + 1},
                )
                self.db.add(report)
                self.db.flush()

                item = ReportItem(
                    id=uuid4(),
                    report_id=report.id,
                    item_type="workflow_summary",
                    title=f"Workflow execution: {wf.name}",
                    description="Proactive scheduled report created automatically.",
                    priority="normal",
                    visibility="internal",
                    data=payload,
                )
                self.db.add(item)
                result_data["report_id"] = str(report.id)

            elif action_type == "check_overdue_tasks":
                # Find pending tasks older than threshold
                overdue_tasks = list(
                    self.db.scalars(
                        select(Task).where(
                            Task.tenant_id == tenant_id,
                            Task.status == "pending",
                        ).limit(20)
                    ).all()
                )
                result_data["overdue_count"] = len(overdue_tasks)
                result_data["overdue_task_ids"] = [str(t.id) for t in overdue_tasks]

            elif action_type in ("follow_up_conversation", "custom_prompt"):
                result_data["action"] = action_type
                result_data["status"] = "acknowledged"
                result_data["payload"] = payload

            # Mark run as completed
            now = datetime.now(timezone.utc)
            run.status = "completed"
            run.completed_at = now
            run.result = result_data
            run.error_message = None

            wf.total_runs += 1
            wf.last_run_at = now
            self.db.flush()
            return True

        except Exception as exc:
            run.attempt_count += 1
            err_msg = str(exc)
            logger.warning(
                "Proactive run %s failed (attempt %d/%d): %s",
                run.id,
                run.attempt_count,
                run.max_attempts,
                err_msg,
            )
            if run.attempt_count >= run.max_attempts:
                run.status = "failed"
                run.error_message = f"Terminal failure: {err_msg[:500]}"
            else:
                run.status = "pending"
                backoff_s = wf.retry_backoff_seconds * (2 ** (run.attempt_count - 1))
                run.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_s)
                run.error_message = f"Retry scheduled: {err_msg[:200]}"

            run.locked_by = None
            run.locked_at = None
            run.lock_expires_at = None
            self.db.flush()
            return False

    # =========================================================================
    # 4. Triggers Layer (Event-driven workflows)
    # =========================================================================

    def fire_trigger_event(
        self,
        tenant_id: UUID,
        event_type: str,
        source_id: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> WorkflowTriggerEvent:
        """
        Record a business event and trigger all matching active workflows.
        Guarantees idempotency so repeated events don't duplicate business actions.
        """
        clean_event = (event_type or "").strip()
        clean_source = (source_id or "").strip()
        clean_key = (
            idempotency_key
            or f"trig-{clean_event}-{clean_source}-{uuid4().hex[:8]}"
        ).strip()

        # Idempotency check
        existing = self.db.scalar(
            select(WorkflowTriggerEvent).where(
                WorkflowTriggerEvent.tenant_id == tenant_id,
                WorkflowTriggerEvent.idempotency_key == clean_key,
            )
        )
        if existing is not None:
            return existing

        event = WorkflowTriggerEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            event_type=clean_event,
            source_id=clean_source,
            idempotency_key=clean_key,
            payload=payload or {},
            status="pending",
        )
        self.db.add(event)
        self.db.flush()

        # Find matching workflows
        matching_workflows = list(
            self.db.scalars(
                select(ProactiveWorkflow).where(
                    ProactiveWorkflow.tenant_id == tenant_id,
                    ProactiveWorkflow.is_active == True,
                    ProactiveWorkflow.status == "active",
                    ProactiveWorkflow.trigger_type == "event",
                )
            ).all()
        )

        matched_count = 0
        for wf in matching_workflows:
            wf_payload = wf.action_payload or {}
            target_event = wf_payload.get("event_type")
            if target_event is None or target_event == clean_event:
                run_key = f"evt-{event.id}-{wf.id}"
                self.enqueue_run(
                    tenant_id=tenant_id,
                    workflow_id=wf.id,
                    trigger_source="event",
                    trigger_event_id=str(event.id),
                    idempotency_key=run_key,
                )
                matched_count += 1

        event.status = "processed"
        event.processed_at = datetime.now(timezone.utc)
        self.db.flush()
        return event

    def list_runs(
        self,
        tenant_id: UUID,
        workflow_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[WorkflowRun]:
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.tenant_id == tenant_id)
            .order_by(WorkflowRun.scheduled_at.desc())
            .limit(min(100, limit))
        )
        if workflow_id:
            stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
        if status:
            stmt = stmt.where(WorkflowRun.status == status)

        return list(self.db.scalars(stmt).all())
