from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIBudgetExceededError
from packages.models.domain import AIUsageLog, TenantAIBudget

logger = logging.getLogger(__name__)


class AIUsageService:
    """
    Service for tracking AI model token consumption, latencies, provider fallbacks,
    and enforcing tenant-level daily and monthly quota budgets.
    """

    def __init__(self, db: Session):
        self.db = db

    def _sync_budget_reset(self, budget: TenantAIBudget, now: datetime) -> None:
        """Reset daily or monthly counters if the calendar day or month has rolled over."""
        if budget.last_reset_date is None:
            budget.last_reset_date = now
            return

        last = budget.last_reset_date
        # Check day rollover
        if last.date() != now.date():
            budget.current_day_tokens = 0

        # Check month rollover
        if (last.year, last.month) != (now.year, now.month):
            budget.current_month_tokens = 0

        budget.last_reset_date = now

    def check_budget_available(
        self,
        tenant_id: UUID,
        estimated_tokens: int = 500,
    ) -> None:
        """
        Verify tenant has not exceeded their daily or monthly token quotas.
        Raises AIBudgetExceededError if hard limit is active and exceeded.
        """
        stmt = select(TenantAIBudget).where(TenantAIBudget.tenant_id == tenant_id)
        budget = self.db.scalar(stmt)
        if budget is None:
            return  # No custom budget restrictions configured for this tenant

        now = datetime.now(timezone.utc)
        self._sync_budget_reset(budget, now)

        if not budget.is_hard_limit:
            return

        if budget.daily_token_limit is not None and budget.daily_token_limit > 0:
            if budget.current_day_tokens + estimated_tokens > budget.daily_token_limit:
                raise AIBudgetExceededError(
                    f"Daily AI token limit exceeded ({budget.current_day_tokens}/{budget.daily_token_limit})"
                )

        if budget.monthly_token_limit is not None and budget.monthly_token_limit > 0:
            if budget.current_month_tokens + estimated_tokens > budget.monthly_token_limit:
                raise AIBudgetExceededError(
                    f"Monthly AI token limit exceeded ({budget.current_month_tokens}/{budget.monthly_token_limit})"
                )

    def record_usage(
        self,
        tenant_id: UUID,
        provider: str,
        model: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int = 0,
        status: str = "success",
        error_category: str | None = None,
        error_message: str | None = None,
        fallback_from_provider: str | None = None,
        fallback_reason: str | None = None,
        task_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> AIUsageLog:
        """Record an AI invocation log and update the tenant's token budget usage."""
        clean_provider = (provider or "").strip().lower()
        clean_model = (model or "").strip()
        calculated_total = total_tokens if total_tokens > 0 else (prompt_tokens + completion_tokens)

        log = AIUsageLog(
            id=uuid4(),
            tenant_id=tenant_id,
            provider=clean_provider,
            model=clean_model,
            prompt_tokens=max(0, prompt_tokens),
            completion_tokens=max(0, completion_tokens),
            total_tokens=max(0, calculated_total),
            duration_ms=max(0, duration_ms),
            status=status,
            error_category=error_category,
            error_message=error_message[:2000] if error_message else None,
            fallback_from_provider=fallback_from_provider,
            fallback_reason=fallback_reason[:255] if fallback_reason else None,
            task_id=task_id,
            conversation_id=conversation_id,
        )
        self.db.add(log)

        # Update budget counter if tokens were consumed
        if calculated_total > 0:
            stmt = select(TenantAIBudget).where(TenantAIBudget.tenant_id == tenant_id)
            budget = self.db.scalar(stmt)
            if budget is not None:
                now = datetime.now(timezone.utc)
                self._sync_budget_reset(budget, now)
                budget.current_day_tokens += calculated_total
                budget.current_month_tokens += calculated_total

        self.db.flush()
        return log

    def set_budget(
        self,
        tenant_id: UUID,
        *,
        daily_token_limit: int | None = None,
        monthly_token_limit: int | None = None,
        is_hard_limit: bool = True,
    ) -> TenantAIBudget:
        """Create or update quota limits for a tenant."""
        stmt = select(TenantAIBudget).where(TenantAIBudget.tenant_id == tenant_id)
        budget = self.db.scalar(stmt)
        if budget is None:
            budget = TenantAIBudget(
                tenant_id=tenant_id,
                daily_token_limit=daily_token_limit,
                monthly_token_limit=monthly_token_limit,
                is_hard_limit=is_hard_limit,
                current_day_tokens=0,
                current_month_tokens=0,
                last_reset_date=datetime.now(timezone.utc),
            )
            self.db.add(budget)
        else:
            budget.daily_token_limit = daily_token_limit
            budget.monthly_token_limit = monthly_token_limit
            budget.is_hard_limit = is_hard_limit

        self.db.flush()
        return budget

    def get_budget_status(self, tenant_id: UUID) -> dict[str, Any]:
        """Fetch current budget and remaining tokens for tenant."""
        stmt = select(TenantAIBudget).where(TenantAIBudget.tenant_id == tenant_id)
        budget = self.db.scalar(stmt)
        if budget is None:
            return {
                "tenant_id": str(tenant_id),
                "configured": False,
                "daily_limit": None,
                "monthly_limit": None,
                "current_day_tokens": 0,
                "current_month_tokens": 0,
                "daily_remaining": None,
                "monthly_remaining": None,
                "is_hard_limit": True,
            }

        now = datetime.now(timezone.utc)
        self._sync_budget_reset(budget, now)
        self.db.flush()

        daily_rem = (
            max(0, budget.daily_token_limit - budget.current_day_tokens)
            if budget.daily_token_limit is not None
            else None
        )
        monthly_rem = (
            max(0, budget.monthly_token_limit - budget.current_month_tokens)
            if budget.monthly_token_limit is not None
            else None
        )

        return {
            "tenant_id": str(tenant_id),
            "configured": True,
            "daily_limit": budget.daily_token_limit,
            "monthly_limit": budget.monthly_token_limit,
            "current_day_tokens": budget.current_day_tokens,
            "current_month_tokens": budget.current_month_tokens,
            "daily_remaining": daily_rem,
            "monthly_remaining": monthly_rem,
            "is_hard_limit": budget.is_hard_limit,
            "last_reset_date": budget.last_reset_date.isoformat() if budget.last_reset_date else None,
        }

    def get_usage_summary(
        self,
        tenant_id: UUID,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate AI metrics for tenant across a time period."""
        stmt = select(AIUsageLog).where(AIUsageLog.tenant_id == tenant_id)
        if start_time is not None:
            stmt = stmt.where(AIUsageLog.created_at >= start_time)
        if end_time is not None:
            stmt = stmt.where(AIUsageLog.created_at <= end_time)

        logs = list(self.db.scalars(stmt).all())

        total_requests = len(logs)
        successful_requests = 0
        fallback_requests = 0
        error_requests = 0
        total_tokens = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        by_provider: dict[str, dict[str, int]] = {}

        for log in logs:
            total_tokens += log.total_tokens
            total_prompt_tokens += log.prompt_tokens
            total_completion_tokens += log.completion_tokens

            is_fallback = bool(log.status == "fallback" or log.fallback_from_provider)
            if is_fallback:
                fallback_requests += 1

            if log.status == "success" or is_fallback:
                successful_requests += 1
            elif log.status == "error":
                error_requests += 1

            p_stats = by_provider.setdefault(
                log.provider,
                {"requests": 0, "tokens": 0, "errors": 0, "fallbacks": 0},
            )
            p_stats["requests"] += 1
            p_stats["tokens"] += log.total_tokens
            if log.status == "error":
                p_stats["errors"] += 1
            if is_fallback:
                p_stats["fallbacks"] += 1

        return {
            "tenant_id": str(tenant_id),
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "fallback_requests": fallback_requests,
            "error_requests": error_requests,
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "by_provider": by_provider,
        }

    def list_usage_logs(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch paginated AI usage logs."""
        stmt = (
            select(AIUsageLog)
            .where(AIUsageLog.tenant_id == tenant_id)
            .order_by(AIUsageLog.created_at.desc())
            .offset(offset)
            .limit(min(100, limit))
        )
        logs = self.db.scalars(stmt).all()
        return [
            {
                "id": str(l.id),
                "provider": l.provider,
                "model": l.model,
                "prompt_tokens": l.prompt_tokens,
                "completion_tokens": l.completion_tokens,
                "total_tokens": l.total_tokens,
                "duration_ms": l.duration_ms,
                "status": l.status,
                "error_category": l.error_category,
                "fallback_from_provider": l.fallback_from_provider,
                "fallback_reason": l.fallback_reason,
                "task_id": str(l.task_id) if l.task_id else None,
                "conversation_id": str(l.conversation_id) if l.conversation_id else None,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ]
