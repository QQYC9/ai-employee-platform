from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.context.retriever import ContextRetriever
from packages.models.domain import Knowledge, Task
from packages.self_development.continuous_improvement import ContinuousImprovementService
from packages.self_development.sandbox import ExecutionSandbox
from packages.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class ContinuousLearningEngine:
    """
    Core continuous learning and self-evolution engine (Track A).
    Implements a 12-hour continuous evolution cycle:
      1. Discovers operational gaps from execution traces and failed tasks.
      2. Formulates evidence-based operational rules and skills.
      3. Retains learned knowledge with deduplication fingerprints (preventing redundant bloating).
      4. Retrieves and applies learned procedures to novel operational scenarios.
    """

    def __init__(
        self,
        db: Session,
        knowledge_service: KnowledgeService | None = None,
        retriever: ContextRetriever | None = None,
        sandbox: ExecutionSandbox | None = None,
    ):
        self.db = db
        self.knowledge_service = knowledge_service or KnowledgeService(db)
        self.retriever = retriever or ContextRetriever(db)
        self.sandbox = sandbox or ExecutionSandbox(backend="subprocess")
        self.improvement_service = ContinuousImprovementService(db)

    def compute_rule_fingerprint(self, tenant_id: UUID, rule_signature: str) -> str:
        """Computes a deterministic SHA-256 fingerprint for rule deduplication."""
        payload = f"{tenant_id}:{rule_signature.strip().lower()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def find_learned_rule_by_fingerprint(
        self,
        tenant_id: UUID,
        fingerprint: str,
    ) -> Knowledge | None:
        """Looks up existing learned rule by its deduplication fingerprint."""
        # Query active operational_rule knowledge items
        stmt = (
            select(Knowledge)
            .where(
                Knowledge.tenant_id == tenant_id,
                Knowledge.knowledge_type == "operational_rule",
                Knowledge.status == "active",
            )
        )
        items = list(self.db.scalars(stmt).all())
        for item in items:
            meta = item.metadata_json or {}
            if meta.get("rule_fingerprint") == fingerprint:
                return item
        return None

    def record_learned_rule(
        self,
        tenant_id: UUID,
        title: str,
        rule_content: str,
        rule_signature: str,
        source_reference: str,
        *,
        confidence: float = 0.95,
        version: str = "1.0.0",
        user_id: UUID | None = None,
    ) -> tuple[Knowledge, bool]:
        """
        Persists an authoritative operational rule with deduplication checks.
        Returns (Knowledge, is_new: bool).
        If the rule already exists, updates last_applied_at and returns (existing, False).
        """
        fingerprint = self.compute_rule_fingerprint(tenant_id, rule_signature)
        existing = self.find_learned_rule_by_fingerprint(tenant_id, fingerprint)

        if existing is not None:
            # Update last applied timestamp and usage counter to avoid redundant re-creation
            meta = dict(existing.metadata_json or {})
            meta["usage_count"] = int(meta.get("usage_count", 0)) + 1
            meta["last_evaluated_at"] = datetime.now(timezone.utc).isoformat()
            existing.metadata_json = meta
            self.db.flush()
            return existing, False

        # Create new knowledge artifact
        meta = {
            "rule_fingerprint": fingerprint,
            "rule_signature": rule_signature,
            "source_reference": source_reference,
            "version": version,
            "confidence": max(0.0, min(1.0, confidence)),
            "usage_count": 1,
            "learning_cycle": "12h_continuous_evolution",
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }

        created = self.knowledge_service.create_knowledge(
            tenant_id=tenant_id,
            title=title,
            content=rule_content,
            knowledge_type="operational_rule",
            status="active",
            metadata_json=meta,
            user_id=user_id,
        )
        self.db.flush()
        return created, True

    def run_12h_learning_cycle(
        self,
        tenant_id: UUID,
        *,
        lookback_days: int = 1,
    ) -> dict[str, Any]:
        """
        Executes the 12-hour continuous learning cycle:
          1. Generates operational diagnostics from failed tasks and requests.
          2. Synthesizes lessons learned and stores them without duplication.
          3. Returns structured metrics of the cycle execution.
        """
        cycle_id = f"cycle-{uuid4().hex[:8]}"
        t_start = datetime.now(timezone.utc)

        # 1. Gather diagnostics from ContinuousImprovementService
        report = self.improvement_service.generate_improvement_report(
            tenant_id=tenant_id,
            is_platform_admin=False,
            lookback_days=lookback_days,
        )

        recommendations = report.get("recommendations", [])
        rules_learned = 0
        duplicates_skipped = 0
        learned_artifacts: list[dict[str, Any]] = []

        # 2. Transform actionable diagnostics into persistent learned rules
        for rec in recommendations:
            problem = rec.get("problem", "")
            proposed = rec.get("proposed_improvement", "")
            if not problem or not proposed:
                continue

            sig = f"err:{problem[:80]}"
            title = f"Learned Rule: Resolution for {problem[:60]}"
            content = (
                f"Problem Signature: {problem}\n"
                f"Resolution Procedure: {proposed}\n"
                f"Expected Benefit: {rec.get('expected_benefit', 'Operational stability')}\n"
                f"Required Test: {rec.get('required_test_plan', 'Automated sandbox verification')}"
            )

            _, is_new = self.record_learned_rule(
                tenant_id=tenant_id,
                title=title,
                rule_content=content,
                rule_signature=sig,
                source_reference="Diagnostic: ContinuousImprovementService",
                confidence=0.90,
            )

            if is_new:
                rules_learned += 1
                learned_artifacts.append({"title": title, "status": "newly_persisted"})
            else:
                duplicates_skipped += 1
                learned_artifacts.append({"title": title, "status": "deduplicated_existing"})

        self.db.commit()

        return {
            "cycle_id": cycle_id,
            "tenant_id": str(tenant_id),
            "status": "completed",
            "lookback_days": lookback_days,
            "diagnostics_analyzed": len(recommendations),
            "rules_learned": rules_learned,
            "duplicates_skipped": duplicates_skipped,
            "artifacts": learned_artifacts,
            "duration_ms": int((datetime.now(timezone.utc) - t_start).total_seconds() * 1000),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def retrieve_applicable_rules(
        self,
        tenant_id: UUID,
        query: str,
        limit: int = 5,
    ) -> list[Knowledge]:
        """
        Retrieves active learned operational rules for a given query or context.
        Enforces strict tenant isolation.
        """
        items = self.retriever.get_knowledge(
            tenant_id=tenant_id,
            query=query,
            limit=limit,
        )
        return [k for k in items if k.knowledge_type == "operational_rule"]

    def ensure_scheduled_learning_workflow(
        self,
        tenant_id: UUID,
        *,
        interval_seconds: int = 43200,  # 12 hours
        agent_id: UUID | None = None,
        lookback_days: int = 1,
    ):
        """
        Idempotently registers or retrieves the tenant's 12-hour continuous learning workflow.
        Executed in the background by OutboxWorker via PostgreSQL FOR UPDATE SKIP LOCKED.
        """
        from packages.models.domain import ProactiveWorkflow
        from packages.services.proactive_workflow_service import ProactiveWorkflowService

        stmt = (
            select(ProactiveWorkflow)
            .where(
                ProactiveWorkflow.tenant_id == tenant_id,
                ProactiveWorkflow.action_type == "continuous_learning_cycle",
            )
        )
        existing = self.db.scalar(stmt)
        if existing is not None:
            return existing

        wf_service = ProactiveWorkflowService(self.db)
        try:
            sp = self.db.begin_nested()
            wf = wf_service.create_workflow(
                tenant_id=tenant_id,
                name="12-Hour Continuous Learning & Self-Evolution",
                trigger_type="schedule",
                schedule_type="interval",
                interval_seconds=interval_seconds,
                action_type="continuous_learning_cycle",
                action_payload={"lookback_days": lookback_days},
                agent_id=agent_id,
                description="Autonomous periodic diagnostic and procedural learning cycle running every 12 hours.",
            )
            sp.commit()
            return wf
        except IntegrityError:
            sp.rollback()
            # Concurrently created by parallel provisioning or worker
            concurrent = self.db.scalar(stmt)
            if concurrent is not None:
                return concurrent
            raise

    def assimilate_external_knowledge(
        self,
        tenant_id: UUID,
        gap_topic: str,
        query: str,
        trigger_context: str = "",
    ):
        """
        Discovers and assimilates verified external technical knowledge into the tenant's base (Track A2).
        Enforces secret sanitization, licensing constraints, and SHA-256 deduplication.
        """
        from packages.self_development.external_knowledge import (
            ExternalKnowledgeGap,
            ExternalKnowledgeHarvester,
        )

        harvester = ExternalKnowledgeHarvester()
        gap = ExternalKnowledgeGap(
            topic=gap_topic,
            query=query,
            trigger_context=trigger_context or "Identified technical gap during operation",
        )
        findings = harvester.harvest_local_reference(gap, max_results=1)
        if not findings:
            return None, False

        best_item = findings[0]
        return harvester.assimilate_into_knowledge_base(
            tenant_id=tenant_id,
            item=best_item,
            knowledge_service=self.knowledge_service,
            learning_engine=self,
        )

    def resolve_task_failure_with_evidence(
        self,
        tenant_id: UUID,
        problem_signature: str,
        error_message: str,
        deterministic_test,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Executes the 9-stage Track B evidence-driven error resolution pipeline and records
        the verified resolution into the tenant's knowledge base.
        """
        from packages.self_development.evidence_resolution import (
            EvidenceResolutionEngine,
            ReproductionTrace,
            VerifiedResolution,
        )

        engine = EvidenceResolutionEngine()
        trace = ReproductionTrace(
            error_type=problem_signature.split(":")[0] if ":" in problem_signature else "TaskExecutionError",
            error_message=error_message,
            traceback_str=error_message,
            trigger_inputs=context or {},
        )
        diagnosis = engine.diagnose_failure(trace, context)
        evidence = engine.search_reference_evidence(diagnosis)
        candidates = engine.generate_candidate_resolutions(diagnosis, evidence)
        comparison = engine.compare_candidates(candidates)

        chosen = next((c for c in candidates if c.candidate_id == comparison.recommended_candidate_id), candidates[0])
        validation = engine.validate_resolution(chosen, deterministic_test)

        if validation.verdict == "approved":
            res = VerifiedResolution(
                problem_signature=diagnosis.problem_signature,
                root_cause=diagnosis.root_cause_analysis,
                chosen_candidate=chosen,
                evidence_trail=evidence,
                validation_verdict=validation,
                limitations_and_prerequisites=["Requires valid tenant context and deterministic verification."],
            )
            rule, is_new = engine.record_verified_resolution(tenant_id, res, self)
            return {
                "status": "resolved_and_recorded",
                "problem_signature": diagnosis.problem_signature,
                "chosen_candidate": chosen.candidate_id,
                "rule_id": str(rule.id),
                "is_new": is_new,
            }
        else:
            return {
                "status": "validation_failed",
                "problem_signature": diagnosis.problem_signature,
                "chosen_candidate": chosen.candidate_id,
                "reason": validation.override_reason or "Deterministic tests rejected resolution.",
            }

    def validate_rule_applicability(
        self,
        rule: Knowledge,
        tenant_id: UUID,
        current_context: dict[str, Any],
        system_version: str = "1.0.0",
        min_confidence: float = 0.80,
    ):
        """
        Verifies that a previously learned operational rule applies to the current context.
        Prevents applying outdated, cross-tenant, or precondition-mismatched rules.
        """
        from packages.self_development.evidence_resolution import EvidenceResolutionEngine
        engine = EvidenceResolutionEngine()
        return engine.validate_rule_applicability(
            rule=rule,
            tenant_id=tenant_id,
            current_context=current_context,
            system_version=system_version,
            min_confidence=min_confidence,
        )



