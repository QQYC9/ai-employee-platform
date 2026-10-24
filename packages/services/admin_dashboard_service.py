from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, or_, select, text
from sqlalchemy.orm import Session

from packages.models.domain import (
    Agent,
    AIUsageLog,
    AuditEvent,
    Capability,
    CapabilityVersion,
    Channel,
    ExecutionTrace,
    OutboxEvent,
    Task,
    TenantAIBudget,
    User,
)
from packages.models.tenant import Tenant
from packages.services.ai_provider_service import AIProviderService
from packages.services.ai_usage_service import AIUsageService
from packages.services.audit_service import AuditService
from packages.services.channel_service import ChannelService
from packages.services.task_service import TaskService

logger = logging.getLogger(__name__)


class AdminDashboardService:
    """
    Centralized administrative dashboard, metrics aggregation, operational monitoring,
    and SaaS hardening management service.
    """

    def __init__(self, db: Session):
        self.db = db
        self.ai_usage_service = AIUsageService(db)
        self.audit_service = AuditService(db)
        self.channel_service = ChannelService(db)
        self.task_service = TaskService(db)
        self.ai_provider_service = AIProviderService(db)

    # -------------------------------------------------------------------------
    # 1. Platform-Level Summaries (Platform Admin Only)
    # -------------------------------------------------------------------------

    def get_platform_summary(self) -> dict[str, Any]:
        """
        Aggregate systemic platform-wide overview metrics across all tenants,
        agents, tasks, outbox events, channels, and AI consumption.
        """
        # 1. Tenant counts by status
        tenant_status_stmt = select(Tenant.status, func.count(Tenant.id)).group_by(Tenant.status)
        tenant_status_counts = dict(self.db.execute(tenant_status_stmt).all())
        total_tenants = sum(tenant_status_counts.values())

        # 2. Agent counts by status
        agent_status_stmt = select(Agent.status, func.count(Agent.id)).group_by(Agent.status)
        agent_status_counts = dict(self.db.execute(agent_status_stmt).all())
        total_agents = sum(agent_status_counts.values())

        # 3. Tasks counts and success/failure rates (deduplicated by distinct Task.id)
        task_status_stmt = select(Task.status, func.count(distinct(Task.id))).group_by(Task.status)
        task_status_counts = dict(self.db.execute(task_status_stmt).all())
        total_tasks = sum(task_status_counts.values())
        completed_tasks = task_status_counts.get("completed", 0)
        failed_tasks = task_status_counts.get("failed", 0)
        pending_tasks = task_status_counts.get("pending", 0)
        in_progress_tasks = task_status_counts.get("in_progress", 0)

        finished_tasks = completed_tasks + failed_tasks
        success_rate = round((completed_tasks / finished_tasks) * 100, 2) if finished_tasks > 0 else 0.0
        failure_rate = round((failed_tasks / finished_tasks) * 100, 2) if finished_tasks > 0 else 0.0

        # Tasks with recorded errors
        tasks_with_error_stmt = select(func.count(distinct(Task.id))).where(Task.error.is_not(None))
        tasks_with_errors = self.db.scalar(tasks_with_error_stmt) or 0

        # 4. Outbox events summary
        outbox_status_stmt = select(OutboxEvent.status, func.count(OutboxEvent.id)).group_by(OutboxEvent.status)
        outbox_status_counts = dict(self.db.execute(outbox_status_stmt).all())
        total_outbox = sum(outbox_status_counts.values())
        dead_letter_count = outbox_status_counts.get("dead_letter", 0)

        # Stuck outbox events (processing and locked > 5 min ago, or pending > 30 min)
        now = datetime.now(timezone.utc)
        stuck_cutoff_processing = now - timedelta(minutes=5)
        stuck_outbox_stmt = select(func.count(OutboxEvent.id)).where(
            (OutboxEvent.status == "processing") & (OutboxEvent.locked_at < stuck_cutoff_processing)
        )
        stuck_outbox_count = self.db.scalar(stuck_outbox_stmt) or 0

        # 5. Connected channels summary
        channel_status_stmt = select(Channel.status, func.count(Channel.id)).group_by(Channel.status)
        channel_status_counts = dict(self.db.execute(channel_status_stmt).all())
        total_channels = sum(channel_status_counts.values())

        channel_type_stmt = select(Channel.channel_type, func.count(Channel.id)).group_by(Channel.channel_type)
        channel_type_counts = dict(self.db.execute(channel_type_stmt).all())

        # 6. Global AI usage aggregation
        ai_agg_stmt = select(
            func.count(AIUsageLog.id),
            func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.completion_tokens), 0),
            func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
            func.coalesce(func.avg(AIUsageLog.duration_ms), 0),
        )
        ai_res = self.db.execute(ai_agg_stmt).one()
        ai_total_requests = ai_res[0] or 0
        ai_prompt_tokens = int(ai_res[1] or 0)
        ai_completion_tokens = int(ai_res[2] or 0)
        ai_total_tokens = int(ai_res[3] or 0)
        ai_avg_duration_ms = round(float(ai_res[4] or 0), 2)

        # AI Fallbacks & Errors count
        ai_errors_stmt = select(func.count(AIUsageLog.id)).where(AIUsageLog.status == "error")
        ai_errors_count = self.db.scalar(ai_errors_stmt) or 0

        ai_fallbacks_stmt = select(func.count(AIUsageLog.id)).where(
            (AIUsageLog.status == "fallback") | (AIUsageLog.fallback_from_provider.is_not(None))
        )
        ai_fallbacks_count = self.db.scalar(ai_fallbacks_stmt) or 0

        # 7. Audit events in last 24h
        since_24h = now - timedelta(hours=24)
        audit_count_stmt = select(func.count(AuditEvent.id)).where(AuditEvent.created_at >= since_24h)
        audit_events_24h = self.db.scalar(audit_count_stmt) or 0

        return {
            "tenants": {
                "total": total_tenants,
                "by_status": tenant_status_counts,
            },
            "agents": {
                "total": total_agents,
                "by_status": agent_status_counts,
            },
            "tasks": {
                "total": total_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "pending": pending_tasks,
                "in_progress": in_progress_tasks,
                "tasks_with_errors": tasks_with_errors,
                "success_rate_pct": success_rate,
                "failure_rate_pct": failure_rate,
            },
            "channels": {
                "total": total_channels,
                "by_status": channel_status_counts,
                "by_type": channel_type_counts,
            },
            "outbox": {
                "total": total_outbox,
                "by_status": outbox_status_counts,
                "dead_letter": dead_letter_count,
                "stuck_processing": stuck_outbox_count,
            },
            "ai_usage": {
                "total_requests": ai_total_requests,
                "prompt_tokens": ai_prompt_tokens,
                "completion_tokens": ai_completion_tokens,
                "total_tokens": ai_total_tokens,
                "avg_duration_ms": ai_avg_duration_ms,
                "error_requests": ai_errors_count,
                "fallback_requests": ai_fallbacks_count,
            },
            "audit": {
                "recent_events_24h": audit_events_24h,
            },
            "generated_at": now.isoformat(),
        }

    def list_tenants_overview(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch paginated overview of all tenants with operational and usage stats.
        """
        clamped_limit = max(1, min(100, limit))
        clamped_offset = max(0, offset)

        query = select(Tenant)
        if status:
            query = query.where(Tenant.status == status.strip().lower())
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.where(or_(Tenant.name.ilike(term), Tenant.slug.ilike(term)))

        total_stmt = select(func.count(Tenant.id))
        if status:
            total_stmt = total_stmt.where(Tenant.status == status.strip().lower())
        if search and search.strip():
            term = f"%{search.strip()}%"
            total_stmt = total_stmt.where(or_(Tenant.name.ilike(term), Tenant.slug.ilike(term)))
        total_count = self.db.scalar(total_stmt) or 0

        tenants = list(
            self.db.scalars(
                query.order_by(Tenant.created_at.desc())
                .offset(clamped_offset)
                .limit(clamped_limit)
            ).all()
        )

        items = []
        for t in tenants:
            # Agent count
            ag_count = self.db.scalar(
                select(func.count(Agent.id)).where(Agent.tenant_id == t.id)
            ) or 0

            # Task count
            tk_count = self.db.scalar(
                select(func.count(Task.id)).where(Task.tenant_id == t.id)
            ) or 0
            tk_failed = self.db.scalar(
                select(func.count(Task.id)).where(
                    Task.tenant_id == t.id, Task.status == "failed"
                )
            ) or 0

            # Budget status
            budget_info = self.ai_usage_service.get_budget_status(t.id)
            alert_level = self._compute_budget_alert_level(budget_info)

            items.append({
                "id": str(t.id),
                "name": t.name,
                "slug": t.slug,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "agent_count": ag_count,
                "task_count": tk_count,
                "failed_task_count": tk_failed,
                "budget": {
                    "configured": budget_info["configured"],
                    "daily_limit": budget_info["daily_limit"],
                    "monthly_limit": budget_info["monthly_limit"],
                    "current_day_tokens": budget_info["current_day_tokens"],
                    "current_month_tokens": budget_info["current_month_tokens"],
                    "alert_level": alert_level,
                },
            })

        return {
            "total": total_count,
            "limit": clamped_limit,
            "offset": clamped_offset,
            "tenants": items,
        }

    def get_platform_metrics(
        self,
        time_window_days: int = 30,
    ) -> dict[str, Any]:
        """
        Global AI token consumption and operational latency metrics across all tenants.
        """
        days = max(1, min(90, time_window_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        logs_stmt = (
            select(AIUsageLog)
            .where(AIUsageLog.created_at >= cutoff)
            .order_by(AIUsageLog.created_at.asc())
        )
        logs = list(self.db.scalars(logs_stmt).all())

        total_requests = len(logs)
        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        total_duration_ms = 0
        successful_requests = 0
        error_requests = 0
        fallback_requests = 0

        by_provider: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        by_tenant: dict[str, dict[str, int]] = {}
        daily_trends: dict[str, dict[str, int]] = {}

        for log in logs:
            total_tokens += log.total_tokens
            prompt_tokens += log.prompt_tokens
            completion_tokens += log.completion_tokens
            total_duration_ms += log.duration_ms

            is_fallback = bool(log.status == "fallback" or log.fallback_from_provider)
            if is_fallback:
                fallback_requests += 1

            if log.status == "success" or is_fallback:
                successful_requests += 1
            elif log.status == "error":
                error_requests += 1

            # Provider rollup
            p_entry = by_provider.setdefault(
                log.provider,
                {"requests": 0, "tokens": 0, "errors": 0, "fallbacks": 0},
            )
            p_entry["requests"] += 1
            p_entry["tokens"] += log.total_tokens
            if log.status == "error":
                p_entry["errors"] += 1
            if is_fallback:
                p_entry["fallbacks"] += 1

            # Model rollup
            m_entry = by_model.setdefault(
                log.model,
                {"provider": log.provider, "requests": 0, "tokens": 0, "errors": 0},
            )
            m_entry["requests"] += 1
            m_entry["tokens"] += log.total_tokens
            if log.status == "error":
                m_entry["errors"] += 1

            # Tenant rollup
            t_str = str(log.tenant_id)
            t_entry = by_tenant.setdefault(
                t_str,
                {"requests": 0, "tokens": 0},
            )
            t_entry["requests"] += 1
            t_entry["tokens"] += log.total_tokens

            # Daily trend rollup
            if log.created_at:
                day_str = log.created_at.strftime("%Y-%m-%d")
                d_entry = daily_trends.setdefault(
                    day_str,
                    {"requests": 0, "tokens": 0, "errors": 0},
                )
                d_entry["requests"] += 1
                d_entry["tokens"] += log.total_tokens
                if log.status == "error":
                    d_entry["errors"] += 1

        avg_duration_ms = round(total_duration_ms / total_requests, 2) if total_requests > 0 else 0.0

        return {
            "time_window_days": days,
            "period_start": cutoff.isoformat(),
            "period_end": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "error_requests": error_requests,
                "fallback_requests": fallback_requests,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "avg_duration_ms": avg_duration_ms,
                "active_tenants_with_usage": len(by_tenant),
            },
            "by_provider": by_provider,
            "by_model": by_model,
            "by_tenant": by_tenant,
            "daily_trends": [
                {"date": d, **stats} for d, stats in sorted(daily_trends.items())
            ],
        }

    # -------------------------------------------------------------------------
    # 2. Tenant-Level Dashboard & Metrics (Strict Multi-Tenant Isolation)
    # -------------------------------------------------------------------------

    def get_tenant_dashboard(self, tenant_id: UUID) -> dict[str, Any]:
        """
        Generate detailed, strictly isolated dashboard for a single tenant.
        Masks all channel credentials, aggregates real task/agent metrics,
        outbox events, and evaluates quota consumption.
        """
        tenant = self.db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            raise ValueError("Tenant not found")

        # 1. Tasks breakdown (deduplicated by Task.id)
        task_status_stmt = (
            select(Task.status, func.count(distinct(Task.id)))
            .where(Task.tenant_id == tenant_id)
            .group_by(Task.status)
        )
        task_status_counts = dict(self.db.execute(task_status_stmt).all())
        total_tasks = sum(task_status_counts.values())
        completed_tasks = task_status_counts.get("completed", 0)
        failed_tasks = task_status_counts.get("failed", 0)
        pending_tasks = task_status_counts.get("pending", 0)
        in_progress_tasks = task_status_counts.get("in_progress", 0)

        finished_tasks = completed_tasks + failed_tasks
        success_rate = round((completed_tasks / finished_tasks) * 100, 2) if finished_tasks > 0 else 0.0
        failure_rate = round((failed_tasks / finished_tasks) * 100, 2) if finished_tasks > 0 else 0.0

        # Calculate average execution latency from completed tasks (updated_at - created_at)
        completed_tasks_records = list(
            self.db.scalars(
                select(Task)
                .where(Task.tenant_id == tenant_id, Task.status == "completed")
                .limit(100)
            ).all()
        )
        durations = [
            (t.updated_at - t.created_at).total_seconds()
            for t in completed_tasks_records
            if t.updated_at and t.created_at and t.updated_at >= t.created_at
        ]
        avg_task_latency_sec = round(sum(durations) / len(durations), 2) if durations else 0.0

        # 2. Agents
        agents = list(
            self.db.scalars(
                select(Agent)
                .where(Agent.tenant_id == tenant_id)
                .order_by(Agent.created_at.desc())
            ).all()
        )
        agent_list = [
            {
                "id": str(a.id),
                "name": a.name,
                "agent_type": a.agent_type,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in agents
        ]

        # 3. Connected Channels with masked secrets
        channels = list(
            self.db.scalars(
                select(Channel)
                .where(Channel.tenant_id == tenant_id)
                .order_by(Channel.created_at.desc())
            ).all()
        )
        sanitized_channels = [
            {
                "id": str(c.id),
                "name": c.name,
                "channel_type": c.channel_type,
                "provider": c.provider,
                "status": c.status,
                "config": self.channel_service.sanitize_channel_config(c.config),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in channels
        ]

        # 4. Outbox events summary
        outbox_stmt = (
            select(OutboxEvent.status, func.count(OutboxEvent.id))
            .where(OutboxEvent.tenant_id == tenant_id)
            .group_by(OutboxEvent.status)
        )
        outbox_counts = dict(self.db.execute(outbox_stmt).all())

        # 5. Budget and Quota
        budget_info = self.ai_usage_service.get_budget_status(tenant_id)
        alert_level = self._compute_budget_alert_level(budget_info)

        # 6. Recent Audit Events for tenant
        recent_audits = list(
            self.db.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(10)
            ).all()
        )
        audit_list = [
            {
                "id": str(aud.id),
                "event_type": aud.event_type,
                "action": aud.action,
                "description": aud.description,
                "user_id": str(aud.user_id) if aud.user_id else None,
                "agent_id": str(aud.agent_id) if aud.agent_id else None,
                "created_at": aud.created_at.isoformat() if aud.created_at else None,
            }
            for aud in recent_audits
        ]

        return {
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "status": tenant.status,
            },
            "tasks": {
                "total": total_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "pending": pending_tasks,
                "in_progress": in_progress_tasks,
                "success_rate_pct": success_rate,
                "failure_rate_pct": failure_rate,
                "avg_execution_latency_sec": avg_task_latency_sec,
            },
            "agents": {
                "total": len(agent_list),
                "items": agent_list,
            },
            "channels": {
                "total": len(sanitized_channels),
                "items": sanitized_channels,
            },
            "outbox": {
                "total": sum(outbox_counts.values()),
                "by_status": outbox_counts,
                "dead_letter": outbox_counts.get("dead_letter", 0),
            },
            "budget": {
                **budget_info,
                "alert_level": alert_level,
            },
            "recent_audit_events": audit_list,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_tenant_metrics(
        self,
        tenant_id: UUID,
        time_window_days: int = 30,
    ) -> dict[str, Any]:
        """
        Fetch time-windowed AI and operational metrics for a specific tenant,
        preventing double-counting and aggregating token usage by model and provider.
        """
        days = max(1, min(90, time_window_days))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # 1. AI usage query within time window
        logs_stmt = (
            select(AIUsageLog)
            .where(AIUsageLog.tenant_id == tenant_id, AIUsageLog.created_at >= cutoff)
            .order_by(AIUsageLog.created_at.asc())
        )
        logs = list(self.db.scalars(logs_stmt).all())

        total_requests = len(logs)
        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        total_duration_ms = 0
        successful_requests = 0
        error_requests = 0
        fallback_requests = 0

        by_provider: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        daily_trends: dict[str, dict[str, int]] = {}

        # Track tokens per unique task to deduplicate retry distortion
        task_token_usage: dict[str, int] = {}

        for log in logs:
            total_tokens += log.total_tokens
            prompt_tokens += log.prompt_tokens
            completion_tokens += log.completion_tokens
            total_duration_ms += log.duration_ms

            is_fallback = bool(log.status == "fallback" or log.fallback_from_provider)
            if is_fallback:
                fallback_requests += 1

            if log.status == "success" or is_fallback:
                successful_requests += 1
            elif log.status == "error":
                error_requests += 1

            # Provider rollup
            p_entry = by_provider.setdefault(
                log.provider,
                {"requests": 0, "tokens": 0, "errors": 0, "fallbacks": 0},
            )
            p_entry["requests"] += 1
            p_entry["tokens"] += log.total_tokens
            if log.status == "error":
                p_entry["errors"] += 1
            if is_fallback:
                p_entry["fallbacks"] += 1

            # Model rollup
            m_entry = by_model.setdefault(
                log.model,
                {"provider": log.provider, "requests": 0, "tokens": 0, "errors": 0},
            )
            m_entry["requests"] += 1
            m_entry["tokens"] += log.total_tokens
            if log.status == "error":
                m_entry["errors"] += 1

            # Daily trend rollup
            if log.created_at:
                day_str = log.created_at.strftime("%Y-%m-%d")
                d_entry = daily_trends.setdefault(
                    day_str,
                    {"requests": 0, "tokens": 0, "errors": 0},
                )
                d_entry["requests"] += 1
                d_entry["tokens"] += log.total_tokens
                if log.status == "error":
                    d_entry["errors"] += 1

            # Task association
            if log.task_id:
                tid_str = str(log.task_id)
                task_token_usage[tid_str] = task_token_usage.get(tid_str, 0) + log.total_tokens

        avg_duration_ms = round(total_duration_ms / total_requests, 2) if total_requests > 0 else 0.0

        # Budget status
        budget_info = self.ai_usage_service.get_budget_status(tenant_id)
        alert_level = self._compute_budget_alert_level(budget_info)

        return {
            "tenant_id": str(tenant_id),
            "time_window_days": days,
            "period_start": cutoff.isoformat(),
            "period_end": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_requests": total_requests,
                "successful_requests": successful_requests,
                "error_requests": error_requests,
                "fallback_requests": fallback_requests,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "avg_duration_ms": avg_duration_ms,
                "unique_tasks_invoked": len(task_token_usage),
            },
            "by_provider": by_provider,
            "by_model": by_model,
            "daily_trends": [
                {"date": d, **stats} for d, stats in sorted(daily_trends.items())
            ],
            "budget": {
                **budget_info,
                "alert_level": alert_level,
            },
        }

    def get_tenant_tasks(
        self,
        tenant_id: UUID,
        status: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Fetch paginated tasks strictly scoped to a specific tenant.
        """
        clamped_limit = max(1, min(100, limit))
        clamped_offset = max(0, offset)
        tasks = self.task_service.list_tasks(
            tenant_id=tenant_id,
            status=status,
            agent_id=agent_id,
            limit=clamped_limit,
            offset=clamped_offset,
        )
        total = self.task_service.count_tasks(
            tenant_id=tenant_id,
            status=status,
            agent_id=agent_id,
        )
        return {
            "total": total,
            "limit": clamped_limit,
            "offset": clamped_offset,
            "tasks": [
                {
                    "id": str(t.id),
                    "tenant_id": str(t.tenant_id),
                    "agent_id": str(t.agent_id) if t.agent_id else None,
                    "requested_by_user_id": str(t.requested_by_user_id) if t.requested_by_user_id else None,
                    "title": t.title,
                    "objective": t.objective,
                    "status": t.status,
                    "priority": t.priority,
                    "plan": t.plan or {},
                    "result": t.result or {},
                    "error": t.error,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in tasks
            ],
        }

    def get_tenant_capabilities(self, tenant_id: UUID) -> dict[str, Any]:
        """
        Fetch capabilities visible to this tenant with strict logical separation:
        - tenant_capabilities: Custom capabilities belonging specifically to this tenant.
        - shared_capabilities: Approved global library capabilities (tenant_id is None).
        - self_development_versions: Evolved skills and self-development proposals for this tenant.
        """
        tenant_caps = list(
            self.db.scalars(
                select(Capability)
                .where(Capability.tenant_id == tenant_id)
                .order_by(Capability.name.asc())
            ).all()
        )

        shared_caps = list(
            self.db.scalars(
                select(Capability)
                .where(Capability.tenant_id.is_(None), Capability.is_active.is_(True))
                .order_by(Capability.name.asc())
            ).all()
        )

        versions = list(
            self.db.scalars(
                select(CapabilityVersion)
                .where(CapabilityVersion.tenant_id == tenant_id)
                .order_by(CapabilityVersion.version_number.desc())
            ).all()
        )

        return {
            "tenant_id": str(tenant_id),
            "tenant_capabilities": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "description": c.description,
                    "config": c.config or {},
                    "is_active": c.is_active,
                    "scope": "tenant_custom",
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in tenant_caps
            ],
            "shared_capabilities": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "description": c.description,
                    "config": c.config or {},
                    "is_active": c.is_active,
                    "scope": "global_shared",
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in shared_caps
            ],
            "self_development_versions": [
                {
                    "id": str(v.id),
                    "capability_id": str(v.capability_id) if v.capability_id else None,
                    "request_id": str(v.request_id) if v.request_id else None,
                    "version_number": v.version_number,
                    "slug": v.slug,
                    "name": v.name,
                    "description": v.description,
                    "risk_level": v.risk_level,
                    "status": v.status,
                    "approval_id": str(v.approval_id) if v.approval_id else None,
                    "activated_at": v.activated_at.isoformat() if v.activated_at else None,
                    "rolled_back_at": v.rolled_back_at.isoformat() if v.rolled_back_at else None,
                    "rollback_reason": v.rollback_reason,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ],
        }

    def get_tenant_integrations(self, tenant_id: UUID) -> list[dict[str, Any]]:
        """
        List AI integrations visible to this tenant:
        Includes both tenant-specific configured integrations and platform global fallback.
        API keys are always masked.
        """
        configs = self.ai_provider_service.list_configs(tenant_id=tenant_id)
        for cfg in configs:
            cfg["scope"] = "tenant" if cfg.get("tenant_id") else "platform_global"
        return configs

    def get_tenant_errors(self, tenant_id: UUID, limit: int = 50) -> dict[str, Any]:
        """
        Diagnostic center: aggregates real failure and error records across
        tasks, execution traces, AI telemetry, and outbox delivery.
        """
        clamped_limit = max(1, min(100, limit))

        failed_tasks = list(
            self.db.scalars(
                select(Task)
                .where(
                    Task.tenant_id == tenant_id,
                    or_(Task.status == "failed", Task.error.is_not(None)),
                )
                .order_by(Task.updated_at.desc())
                .limit(clamped_limit)
            ).all()
        )

        failed_traces = list(
            self.db.scalars(
                select(ExecutionTrace)
                .where(
                    ExecutionTrace.tenant_id == tenant_id,
                    or_(ExecutionTrace.status == "failed", ExecutionTrace.error_summary.is_not(None)),
                )
                .order_by(ExecutionTrace.started_at.desc())
                .limit(clamped_limit)
            ).all()
        )

        ai_errors = list(
            self.db.scalars(
                select(AIUsageLog)
                .where(
                    AIUsageLog.tenant_id == tenant_id,
                    AIUsageLog.status == "error",
                )
                .order_by(AIUsageLog.created_at.desc())
                .limit(clamped_limit)
            ).all()
        )

        outbox_errors = list(
            self.db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == tenant_id,
                    OutboxEvent.status.in_(["dead_letter", "failed"]),
                )
                .order_by(OutboxEvent.created_at.desc())
                .limit(clamped_limit)
            ).all()
        )

        total_error_count = len(failed_tasks) + len(failed_traces) + len(ai_errors) + len(outbox_errors)

        return {
            "tenant_id": str(tenant_id),
            "total_errors": total_error_count,
            "tasks_errors": [
                {
                    "id": str(t.id),
                    "task_title": t.title,
                    "status": t.status,
                    "error_message": t.error,
                    "agent_id": str(t.agent_id) if t.agent_id else None,
                    "occurred_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in failed_tasks
            ],
            "traces_errors": [
                {
                    "id": str(tr.id),
                    "trace_id": str(tr.trace_id),
                    "trigger_type": tr.trigger_type,
                    "task_id": str(tr.task_id) if tr.task_id else None,
                    "agent_id": str(tr.agent_id) if tr.agent_id else None,
                    "error_summary": tr.error_summary,
                    "occurred_at": tr.completed_at.isoformat() if tr.completed_at else tr.started_at.isoformat(),
                }
                for tr in failed_traces
            ],
            "ai_errors": [
                {
                    "id": str(log.id),
                    "provider": log.provider,
                    "model": log.model,
                    "error_category": log.error_category,
                    "error_message": log.error_message,
                    "task_id": str(log.task_id) if log.task_id else None,
                    "occurred_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in ai_errors
            ],
            "outbox_errors": [
                {
                    "id": str(oe.id),
                    "event_type": oe.event_type,
                    "status": oe.status,
                    "retry_count": oe.attempt_count,
                    "error_message": oe.error_message,
                    "occurred_at": oe.created_at.isoformat() if oe.created_at else None,
                }
                for oe in outbox_errors
            ],
        }

    # -------------------------------------------------------------------------
    # 3. Operational Monitoring & Diagnostics
    # -------------------------------------------------------------------------

    def get_operational_monitoring(
        self,
        target_tenant_id: UUID | None = None,
        is_platform_admin: bool = True,
    ) -> dict[str, Any]:
        """
        Evaluate real-time operational health of background queues, database,
        AI providers, and stalled tasks. Follows the principle of never reporting
        'healthy' if a component status cannot be verified.
        Ensures tenant admins only see diagnostics and samples for their own tenant.
        """
        now = datetime.now(timezone.utc)
        components: dict[str, Any] = {}

        # 1. Database Health Check
        try:
            self.db.execute(text("SELECT 1")).scalar()
            db_status = "healthy"
            db_details = {"connected": True}
        except Exception as exc:
            logger.error("Operational monitoring database check failed: %s", exc)
            db_status = "unhealthy"
            db_details = {"connected": False, "error": str(exc)}
        components["database"] = {"status": db_status, "details": db_details}

        # 2. Outbox Queue Health Check
        try:
            outbox_query = select(OutboxEvent.status, func.count(OutboxEvent.id))
            if not is_platform_admin and target_tenant_id is not None:
                outbox_query = outbox_query.where(OutboxEvent.tenant_id == target_tenant_id)
            outbox_counts = dict(self.db.execute(outbox_query.group_by(OutboxEvent.status)).all())

            dead_letter = outbox_counts.get("dead_letter", 0)
            pending = outbox_counts.get("pending", 0)
            processing = outbox_counts.get("processing", 0)

            # Stuck processing events (> 5 min lock)
            stuck_cutoff = now - timedelta(minutes=5)
            stuck_stmt = select(func.count(OutboxEvent.id)).where(
                (OutboxEvent.status == "processing")
                & (OutboxEvent.locked_at < stuck_cutoff)
            )
            if not is_platform_admin and target_tenant_id is not None:
                stuck_stmt = stuck_stmt.where(OutboxEvent.tenant_id == target_tenant_id)
            stuck_count = self.db.scalar(stuck_stmt) or 0

            if dead_letter > 0 or stuck_count > 0:
                outbox_status = "degraded"
            else:
                outbox_status = "healthy"

            components["outbox"] = {
                "status": outbox_status,
                "details": {
                    "pending": pending,
                    "processing": processing,
                    "dead_letter": dead_letter,
                    "stuck_processing": stuck_count,
                    "total": sum(outbox_counts.values()),
                },
            }
        except Exception as exc:
            logger.error("Outbox health check failed: %s", exc)
            components["outbox"] = {
                "status": "unknown",
                "details": {"error": "Could not query outbox events table"},
            }

        # 3. Stalled / Stuck Tasks Check
        try:
            stalled_cutoff = now - timedelta(hours=1)
            stalled_tasks_stmt = (
                select(Task)
                .where(
                    Task.status.in_(["in_progress", "pending"]),
                    Task.updated_at < stalled_cutoff,
                )
            )
            if not is_platform_admin and target_tenant_id is not None:
                stalled_tasks_stmt = stalled_tasks_stmt.where(Task.tenant_id == target_tenant_id)

            stalled_tasks = list(self.db.scalars(stalled_tasks_stmt.limit(20)).all())
            stalled_count = len(stalled_tasks)

            task_monitor_status = "degraded" if stalled_count > 0 else "healthy"
            components["stalled_tasks"] = {
                "status": task_monitor_status,
                "details": {
                    "count": stalled_count,
                    "sample": [
                        {
                            "id": str(t.id),
                            "tenant_id": str(t.tenant_id),
                            "title": t.title,
                            "status": t.status,
                            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                        }
                        for t in stalled_tasks[:5]
                    ],
                },
            }
        except Exception as exc:
            logger.error("Stalled tasks check failed: %s", exc)
            components["stalled_tasks"] = {
                "status": "unknown",
                "details": {"error": "Could not query tasks table"},
            }

        # 4. AI Providers Diagnostic (24-Hour Window)
        try:
            since_24h = now - timedelta(hours=24)
            ai_logs_stmt = select(AIUsageLog).where(AIUsageLog.created_at >= since_24h)
            if not is_platform_admin and target_tenant_id is not None:
                ai_logs_stmt = ai_logs_stmt.where(AIUsageLog.tenant_id == target_tenant_id)

            recent_logs = list(self.db.scalars(ai_logs_stmt).all())

            if not recent_logs:
                ai_status = "unknown"  # No telemetry data in window
                ai_details: dict[str, Any] = {
                    "message": "No AI telemetry logs recorded in the last 24 hours",
                    "providers": {},
                }
            else:
                total_ai = len(recent_logs)
                error_ai = sum(1 for l in recent_logs if l.status == "error")
                error_rate_pct = round((error_ai / total_ai) * 100, 2)

                provider_stats: dict[str, dict[str, Any]] = {}
                for l in recent_logs:
                    ps = provider_stats.setdefault(
                        l.provider, {"total": 0, "errors": 0}
                    )
                    ps["total"] += 1
                    if l.status == "error":
                        ps["errors"] += 1

                for prov, stats in provider_stats.items():
                    stats["error_rate_pct"] = round(
                        (stats["errors"] / stats["total"]) * 100, 2
                    )

                ai_status = "degraded" if error_rate_pct >= 10.0 else "healthy"
                ai_details = {
                    "total_invocations": total_ai,
                    "error_invocations": error_ai,
                    "error_rate_pct": error_rate_pct,
                    "providers": provider_stats,
                }

            components["ai_providers"] = {
                "status": ai_status,
                "details": ai_details,
            }
        except Exception as exc:
            logger.error("AI providers health check failed: %s", exc)
            components["ai_providers"] = {
                "status": "unknown",
                "details": {"error": "Could not query AI usage logs"},
            }


        # 5. Overall Platform Status Computation
        statuses = [comp["status"] for comp in components.values()]
        if any(s == "unhealthy" for s in statuses):
            overall_status = "unhealthy"
        elif any(s == "degraded" for s in statuses):
            overall_status = "degraded"
        elif any(s == "unknown" for s in statuses):
            overall_status = "unknown"
        else:
            overall_status = "healthy"

        return {
            "overall_status": overall_status,
            "components": components,
            "checked_at": now.isoformat(),
        }

    # -------------------------------------------------------------------------
    # 4. Administrative Actions with Mandatory Audit Logging
    # -------------------------------------------------------------------------

    def update_tenant_budget(
        self,
        tenant_id: UUID,
        admin_user: User,
        *,
        daily_token_limit: int | None = None,
        monthly_token_limit: int | None = None,
        is_hard_limit: bool = True,
    ) -> dict[str, Any]:
        """
        Update tenant AI token quota with administrative audit recording.
        """
        old_status = self.ai_usage_service.get_budget_status(tenant_id)

        budget = self.ai_usage_service.set_budget(
            tenant_id=tenant_id,
            daily_token_limit=daily_token_limit,
            monthly_token_limit=monthly_token_limit,
            is_hard_limit=is_hard_limit,
        )

        new_status = self.ai_usage_service.get_budget_status(tenant_id)

        # Record audit event
        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=admin_user.id,
            event_type="admin.tenant_budget.updated",
            action="update_budget",
            description=f"Platform admin '{admin_user.email}' updated AI budget quotas for tenant '{tenant_id}'.",
            event_metadata={
                "admin_id": str(admin_user.id),
                "admin_role": admin_user.role,
                "old_budget": {
                    "daily_limit": old_status.get("daily_limit"),
                    "monthly_limit": old_status.get("monthly_limit"),
                    "is_hard_limit": old_status.get("is_hard_limit"),
                },
                "new_budget": {
                    "daily_limit": daily_token_limit,
                    "monthly_limit": monthly_token_limit,
                    "is_hard_limit": is_hard_limit,
                },
            },
        )
        self.db.commit()

        return new_status

    def update_tenant_status(
        self,
        tenant_id: UUID,
        admin_user: User,
        new_status: str,
    ) -> dict[str, Any]:
        """
        Update tenant operational status (e.g. active, suspended) with audit logging.
        """
        clean_status = (new_status or "").strip().lower()
        if clean_status not in ("active", "suspended", "archived"):
            raise ValueError(f"Invalid tenant status: '{new_status}'")

        tenant = self.db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            raise ValueError("Tenant not found")

        old_status = tenant.status
        tenant.status = clean_status
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=admin_user.id,
            event_type="admin.tenant_status.updated",
            action="update_status",
            description=f"Platform admin '{admin_user.email}' transitioned tenant '{tenant.name}' from '{old_status}' to '{clean_status}'.",
            event_metadata={
                "admin_id": str(admin_user.id),
                "admin_role": admin_user.role,
                "old_status": old_status,
                "new_status": clean_status,
            },
        )
        self.db.commit()

        return {
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "old_status": old_status,
            "new_status": clean_status,
        }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _compute_budget_alert_level(budget_info: dict[str, Any]) -> str:
        """
        Compute quota alert status:
        - 'normal': usage < 80%
        - 'warning': usage >= 80% and < 100%
        - 'exceeded': usage >= 100%
        """
        if not budget_info.get("configured"):
            return "normal"

        daily_limit = budget_info.get("daily_limit")
        current_day = budget_info.get("current_day_tokens", 0)
        daily_ratio = (current_day / daily_limit) if (daily_limit and daily_limit > 0) else 0.0

        monthly_limit = budget_info.get("monthly_limit")
        current_month = budget_info.get("current_month_tokens", 0)
        monthly_ratio = (current_month / monthly_limit) if (monthly_limit and monthly_limit > 0) else 0.0

        max_ratio = max(daily_ratio, monthly_ratio)
        if max_ratio >= 1.0:
            return "exceeded"
        if max_ratio >= 0.8:
            return "warning"
        return "normal"
