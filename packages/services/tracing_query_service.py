from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from packages.models.domain import ExecutionStep, ExecutionTrace
from packages.services.execution_tracing_service import sanitize_value

logger = logging.getLogger(__name__)


def serialize_trace(trace: ExecutionTrace, step_count: int | None = None) -> dict[str, Any]:
    """Serialize ExecutionTrace with thorough field sanitization and ISO datetime strings."""
    return {
        "id": str(trace.id),
        "trace_id": str(trace.trace_id),
        "tenant_id": str(trace.tenant_id),
        "trigger_type": trace.trigger_type,
        "conversation_id": str(trace.conversation_id) if trace.conversation_id else None,
        "inbound_message_id": str(trace.inbound_message_id) if trace.inbound_message_id else None,
        "reply_message_id": str(trace.reply_message_id) if trace.reply_message_id else None,
        "task_id": str(trace.task_id) if trace.task_id else None,
        "agent_id": str(trace.agent_id) if trace.agent_id else None,
        "status": trace.status,
        "started_at": trace.started_at.isoformat() if trace.started_at else None,
        "completed_at": trace.completed_at.isoformat() if trace.completed_at else None,
        "duration_ms": trace.duration_ms,
        "error_summary": sanitize_value(trace.error_summary) if trace.error_summary else None,
        "metadata_json": sanitize_value(trace.metadata_json) if trace.metadata_json else {},
        "step_count": step_count,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
        "updated_at": trace.updated_at.isoformat() if trace.updated_at else None,
    }


def serialize_step(step: ExecutionStep) -> dict[str, Any]:
    """Serialize ExecutionStep with thorough payload sanitization and ISO datetime strings."""
    return {
        "id": str(step.id),
        "tenant_id": str(step.tenant_id),
        "trace_id": str(step.trace_id),
        "parent_step_id": str(step.parent_step_id) if step.parent_step_id else None,
        "task_id": str(step.task_id) if step.task_id else None,
        "approval_id": str(step.approval_id) if step.approval_id else None,
        "outbox_event_id": str(step.outbox_event_id) if step.outbox_event_id else None,
        "step_order": step.step_order,
        "step_type": step.step_type,
        "step_name": step.step_name,
        "status": step.status,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "duration_ms": step.duration_ms,
        "attempt_count": step.attempt_count,
        "attempts_history": sanitize_value(step.attempts_history) if step.attempts_history else [],
        "input_summary": sanitize_value(step.input_summary) if step.input_summary else {},
        "output_summary": sanitize_value(step.output_summary) if step.output_summary else {},
        "error_info": sanitize_value(step.error_info) if step.error_info else None,
        "idempotency_key": step.idempotency_key,
        "created_at": step.created_at.isoformat() if step.created_at else None,
        "updated_at": step.updated_at.isoformat() if step.updated_at else None,
    }


def parse_iso_datetime(dt_val: datetime | str | None) -> datetime | None:
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    val_str = str(dt_val).strip()
    if not val_str:
        return None
    # Fix URL-decoded space instead of '+' for timezone offset
    if " " in val_str and "+" not in val_str and "T" in val_str:
        # e.g. 2026-10-23T02:56:02.123 00:00 -> 2026-10-23T02:56:02.123+00:00
        val_str = val_str.rsplit(" ", 1)[0] + "+" + val_str.rsplit(" ", 1)[1]
    return datetime.fromisoformat(val_str)


class TracingQueryService:
    def __init__(self, db: Session):
        self.db = db

    def list_traces(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        trigger_type: str | None = None,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        conversation_id: UUID | None = None,
        started_after: datetime | str | None = None,
        started_before: datetime | str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_order: str = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List execution traces for a tenant with filtering, pagination, and total count.
        Enforces strict limits (1 to 100) and tenant isolation.
        """
        limit = max(1, min(limit, 100))
        offset = max(0, offset)

        filters = [ExecutionTrace.tenant_id == tenant_id]

        if status:
            filters.append(ExecutionTrace.status == status.strip().lower())
        if trigger_type:
            filters.append(ExecutionTrace.trigger_type == trigger_type.strip())
        if task_id:
            filters.append(ExecutionTrace.task_id == task_id)
        if agent_id:
            filters.append(ExecutionTrace.agent_id == agent_id)
        if conversation_id:
            filters.append(ExecutionTrace.conversation_id == conversation_id)

        dt_after = parse_iso_datetime(started_after)
        if dt_after:
            filters.append(ExecutionTrace.started_at >= dt_after)

        dt_before = parse_iso_datetime(started_before)
        if dt_before:
            filters.append(ExecutionTrace.started_at <= dt_before)

        # Count total
        count_stmt = select(func.count(ExecutionTrace.id)).where(*filters)
        total_count = self.db.scalar(count_stmt) or 0

        # Query items with step counts via subquery
        order_clause = desc(ExecutionTrace.started_at) if sort_order.lower() == "desc" else asc(ExecutionTrace.started_at)

        step_count_subq = (
            select(
                ExecutionStep.trace_id,
                func.count(ExecutionStep.id).label("step_count"),
            )
            .where(ExecutionStep.tenant_id == tenant_id)
            .group_by(ExecutionStep.trace_id)
            .subquery()
        )

        query = (
            select(
                ExecutionTrace,
                func.coalesce(step_count_subq.c.step_count, 0).label("step_count"),
            )
            .outerjoin(step_count_subq, ExecutionTrace.id == step_count_subq.c.trace_id)
            .where(*filters)
            .order_by(order_clause)
            .offset(offset)
            .limit(limit)
        )

        rows = self.db.execute(query).all()
        results = []
        for trace_obj, step_cnt in rows:
            results.append(serialize_trace(trace_obj, step_count=step_cnt))

        return results, total_count

    def get_trace(self, tenant_id: UUID, trace_id_or_pk: UUID) -> dict[str, Any] | None:
        """
        Get trace details by either its PK `id` or `trace_id`, strictly scoped to `tenant_id`.
        """
        stmt = select(ExecutionTrace).where(
            ExecutionTrace.tenant_id == tenant_id,
            (ExecutionTrace.id == trace_id_or_pk) | (ExecutionTrace.trace_id == trace_id_or_pk),
        )
        trace = self.db.scalar(stmt)
        if trace is None:
            return None

        # Count steps
        step_cnt = self.db.scalar(
            select(func.count(ExecutionStep.id)).where(
                ExecutionStep.tenant_id == tenant_id,
                ExecutionStep.trace_id == trace.id,
            )
        ) or 0

        return serialize_trace(trace, step_count=step_cnt)

    def get_trace_steps(
        self,
        tenant_id: UUID,
        trace_id_or_pk: UUID,
        *,
        format: str = "tree",
    ) -> list[dict[str, Any]] | None:
        """
        Get steps for a trace.
        If format == 'flat', returns flat ordered list.
        If format == 'tree', returns hierarchical parent-child step tree.
        Returns None if trace is not found in this tenant.
        """
        trace = self.db.scalar(
            select(ExecutionTrace).where(
                ExecutionTrace.tenant_id == tenant_id,
                (ExecutionTrace.id == trace_id_or_pk) | (ExecutionTrace.trace_id == trace_id_or_pk),
            )
        )
        if trace is None:
            return None

        steps_stmt = (
            select(ExecutionStep)
            .where(
                ExecutionStep.tenant_id == tenant_id,
                ExecutionStep.trace_id == trace.id,
            )
            .order_by(ExecutionStep.step_order.asc(), ExecutionStep.started_at.asc())
        )
        step_objs = list(self.db.scalars(steps_stmt).all())

        if format.lower() == "flat":
            return [serialize_step(s) for s in step_objs]

        # Build hierarchical tree
        return self._build_step_tree(step_objs)

    def _build_step_tree(self, step_objs: list[ExecutionStep]) -> list[dict[str, Any]]:
        """
        Assemble ExecutionStep instances into a hierarchical parent-child tree.
        Child steps are nested in `children: [...]`.
        Orphan steps whose parent is missing are attached to root.
        """
        step_map: dict[str, dict[str, Any]] = {}
        for s in step_objs:
            serialized = serialize_step(s)
            serialized["children"] = []
            step_map[str(s.id)] = serialized

        root_steps: list[dict[str, Any]] = []

        for s in step_objs:
            step_id_str = str(s.id)
            node = step_map[step_id_str]
            if s.parent_step_id:
                parent_id_str = str(s.parent_step_id)
                if parent_id_str in step_map and parent_id_str != step_id_str:
                    step_map[parent_id_str]["children"].append(node)
                else:
                    # Parent step not in trace (orphan) or self-referential
                    root_steps.append(node)
            else:
                root_steps.append(node)

        return root_steps

    def get_trace_summary(self, tenant_id: UUID, trace_id_or_pk: UUID) -> dict[str, Any] | None:
        """
        Get high-level summary metrics of a trace and its steps.
        """
        trace_data = self.get_trace(tenant_id, trace_id_or_pk)
        if trace_data is None:
            return None

        # Fetch step status counts
        status_counts_stmt = (
            select(ExecutionStep.status, func.count(ExecutionStep.id))
            .where(
                ExecutionStep.tenant_id == tenant_id,
                ExecutionStep.trace_id == UUID(trace_data["id"]),
            )
            .group_by(ExecutionStep.status)
        )
        status_counts = dict(self.db.execute(status_counts_stmt).all())

        type_counts_stmt = (
            select(ExecutionStep.step_type, func.count(ExecutionStep.id))
            .where(
                ExecutionStep.tenant_id == tenant_id,
                ExecutionStep.trace_id == UUID(trace_data["id"]),
            )
            .group_by(ExecutionStep.step_type)
        )
        type_counts = dict(self.db.execute(type_counts_stmt).all())

        return {
            "trace_id": trace_data["id"],
            "business_trace_id": trace_data["trace_id"],
            "status": trace_data["status"],
            "trigger_type": trace_data["trigger_type"],
            "started_at": trace_data["started_at"],
            "completed_at": trace_data["completed_at"],
            "duration_ms": trace_data["duration_ms"],
            "total_steps": trace_data["step_count"],
            "status_breakdown": status_counts,
            "step_type_breakdown": type_counts,
            "has_error": bool(trace_data.get("error_summary")),
            "error_summary": trace_data.get("error_summary"),
        }
