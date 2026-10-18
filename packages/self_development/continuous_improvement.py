from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.models.domain import (
    Capability,
    CapabilityVersion,
    DevelopmentRequest,
    DevelopmentRun,
    Task,
)

logger = logging.getLogger(__name__)


class ContinuousImprovementService:
    """
    Analyzes task execution failures, failed development runs, and recurring capability requests
    to synthesize actionable continuous improvement reports without modifying production automatically.
    """

    def __init__(self, db: Session):
        self.db = db

    def generate_improvement_report(
        self,
        tenant_id: UUID | None = None,
        is_platform_admin: bool = False,
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        """
        Generates a continuous improvement report.
        For platform admin: system-wide technical diagnostics across all tenants.
        For tenant admin: strictly scoped and sanitized for tenant_id.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=max(1, min(30, lookback_days)))

        # 1. Identify failing tasks
        task_query = (
            select(Task)
            .where(Task.status == "failed", Task.updated_at >= since)
        )
        if not is_platform_admin and tenant_id is not None:
            task_query = task_query.where(Task.tenant_id == tenant_id)

        failed_tasks = list(self.db.scalars(task_query.limit(50)).all())

        # 2. Identify failed development runs
        run_query = (
            select(DevelopmentRun)
            .where(DevelopmentRun.status == "failed", DevelopmentRun.created_at >= since)
        )
        if not is_platform_admin and tenant_id is not None:
            run_query = run_query.where(DevelopmentRun.tenant_id == tenant_id)

        failed_runs = list(self.db.scalars(run_query.limit(50)).all())

        # 3. Identify pending or recurring development requests
        req_query = (
            select(DevelopmentRequest)
            .where(DevelopmentRequest.created_at >= since)
        )
        if not is_platform_admin and tenant_id is not None:
            req_query = req_query.where(DevelopmentRequest.tenant_id == tenant_id)

        recent_requests = list(self.db.scalars(req_query.limit(50)).all())

        # 4. Synthesize proposed improvement recommendations
        recommendations = []

        # A. Analyze recurring task failures
        error_clusters: dict[str, list[str]] = {}
        for t in failed_tasks:
            err_snippet = (t.error or "Unknown failure").strip()[:100]
            error_clusters.setdefault(err_snippet, []).append(t.title)

        for err, titles in error_clusters.items():
            recommendations.append({
                "problem": f"Recurring failure encountered in {len(titles)} task(s): '{err}'",
                "affected_component": "Task Execution Engine",
                "evidence": [t[:60] for t in titles[:3]],
                "proposed_improvement": (
                    f"Create or augment dedicated tool capability to handle operation gracefully "
                    f"instead of failing with '{err}'."
                ),
                "expected_benefit": "Eliminate recurring task errors and improve operational reliability.",
                "estimated_risk": "low" if not is_platform_admin else "medium",
                "required_test_plan": "Unit test error recovery and verify graceful fallback.",
                "status": "candidate_for_development",
            })

        # B. Analyze failed development test runs
        for r in failed_runs:
            verdict_violations = r.security_verdict.get("violations", []) if r.security_verdict else []
            recommendations.append({
                "problem": f"Development run '{r.id}' failed during {r.run_type}",
                "affected_component": f"Capability Version {r.capability_version_id or 'New'}",
                "evidence": verdict_violations or [r.error_message or "Test harness assertion failure"],
                "proposed_improvement": "Refactor implementation code to satisfy static security checks and pass input validation tests.",
                "expected_benefit": "Permit capability to meet security threshold and proceed to approval.",
                "estimated_risk": "low",
                "required_test_plan": "Re-run automated sandbox verification until all tests pass.",
                "status": "remediation_needed",
            })

        # C. Analyze repeated requests
        req_titles = [r.title for r in recent_requests]
        if len(req_titles) > 2:
            recommendations.append({
                "problem": f"Elevated volume of capability requests ({len(req_titles)} requests in {lookback_days} days)",
                "affected_component": "Capability Catalog",
                "evidence": req_titles[:5],
                "proposed_improvement": "Standardize capability template library to accelerate automated specification and testing.",
                "expected_benefit": "Reduce capability turnaround time and standardize schemas.",
                "estimated_risk": "low",
                "required_test_plan": "Verify standard capability templates against specification schema.",
                "status": "strategic_proposal",
            })

        # Sanitize report if tenant admin
        target_tenant = str(tenant_id) if tenant_id else ("global" if is_platform_admin else "unknown")

        return {
            "audience": "platform_admin" if is_platform_admin else "tenant_admin",
            "tenant_id": target_tenant,
            "period_days": lookback_days,
            "metrics": {
                "failed_tasks_analyzed": len(failed_tasks),
                "failed_runs_analyzed": len(failed_runs),
                "recent_requests_analyzed": len(recent_requests),
                "recommendations_count": len(recommendations),
            },
            "recommendations": recommendations,
            "generated_at": now.isoformat(),
        }

    def generate_tenant_report(self, tenant_id: UUID, days: int = 30) -> dict[str, Any]:
        report = self.generate_improvement_report(
            tenant_id=tenant_id,
            is_platform_admin=False,
            lookback_days=days,
        )
        report["report_type"] = "tenant_scoped"
        report["metrics"]["failed_tasks_count"] = report["metrics"]["failed_tasks_analyzed"]
        report["metrics"]["failed_development_runs"] = report["metrics"]["failed_runs_analyzed"]
        return report

    def generate_platform_report(self, days: int = 30) -> dict[str, Any]:
        report = self.generate_improvement_report(
            tenant_id=None,
            is_platform_admin=True,
            lookback_days=days,
        )
        report["report_type"] = "platform_wide"
        report["metrics"]["failed_tasks_count"] = report["metrics"]["failed_tasks_analyzed"]
        report["metrics"]["failed_development_runs"] = report["metrics"]["failed_runs_analyzed"]
        report["cross_tenant_failure_patterns"] = report["recommendations"]
        return report

