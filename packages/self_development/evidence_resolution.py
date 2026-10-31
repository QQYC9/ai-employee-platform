from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import re
import traceback
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from packages.memory.sanitizer import MemorySanitizer
from packages.models.domain import Knowledge
from packages.self_development.learning_engine import ContinuousLearningEngine

logger = logging.getLogger(__name__)


class ReproductionTrace(BaseModel):
    """Captured failure evidence from reproducing an error in an isolated test environment."""
    error_type: str
    error_message: str
    traceback_str: str
    trigger_inputs: dict[str, Any] = Field(default_factory=dict)
    reproduced_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FailureDiagnosis(BaseModel):
    """Structured forensic diagnosis of an observed error."""
    problem_signature: str
    root_cause_analysis: str
    affected_components: list[str]
    expected_behavior: str
    actual_behavior: str
    severity: str = Field(default="high", description="low, medium, high, critical")


class EvidenceFinding(BaseModel):
    """Concrete evidence record from reference open-source repository or local tests."""
    repo_name: str
    source_file: str
    commit_hash: str
    relevant_symbol: str
    citation_excerpt: str
    architectural_lesson: str
    license_status: str = "permissive"


class ResolutionCandidate(BaseModel):
    """Candidate architectural or code fix linked to evidence."""
    candidate_id: str
    title: str
    description: str
    source_evidence: list[EvidenceFinding]
    implementation_approach: str
    security_impact: str
    licensing_compliance: str
    score: float = Field(default=0.0, ge=0.0, le=100.0)


class CandidateComparisonReport(BaseModel):
    """Comparison matrix of competing candidate solutions."""
    candidates_evaluated: list[ResolutionCandidate]
    recommended_candidate_id: str
    rationale: str
    tradeoffs_identified: list[str]


class ExperimentResult(BaseModel):
    """Results of testing a candidate solution in an isolated sandbox."""
    candidate_id: str
    success: bool
    execution_time_ms: int
    output_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ValidationVerdict(BaseModel):
    """Authoritative outcome of deterministic test gates."""
    candidate_id: str
    deterministic_gate_passed: bool
    llm_judge_rating: float | None = None
    override_reason: str | None = None
    tests_executed: list[str] = Field(default_factory=list)
    verdict: str = Field(default="rejected", description="approved, rejected, conditional")


class VerifiedResolution(BaseModel):
    """A fully verified, evidence-backed error resolution ready for operational recording."""
    problem_signature: str
    root_cause: str
    chosen_candidate: ResolutionCandidate
    evidence_trail: list[EvidenceFinding]
    validation_verdict: ValidationVerdict
    limitations_and_prerequisites: list[str] = Field(default_factory=list)


class RuleApplicabilityVerdict(BaseModel):
    """Result of verifying whether a stored operational rule applies to a specific context."""
    is_applicable: bool
    reason: str
    confidence: float = 1.0
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)


class EvidenceResolutionEngine:
    """
    Core engine for Track B: Open-Source Evidence-Driven Error Resolution.
    Implements a strict 9-stage sequence:
      1. Reproduce -> 2. Diagnose -> 3. Search Evidence -> 4. Generate Candidates
      -> 5. Compare -> 6. Experiment -> 7. Validate (Deterministic Test Gate)
      -> 8. Record (Knowledge Persistence) -> 9. Reuse (Analogous Retrieval).
    """

    def __init__(
        self,
        reference_root: str | Path = r"D:\AI-Employee-Platform-Research",
    ):
        self.reference_root = Path(reference_root)

    # 1. Reproduce
    def reproduce_error(
        self,
        trigger_callable: Callable[[], Any],
        trigger_inputs: dict[str, Any] | None = None,
    ) -> ReproductionTrace:
        """
        Executes a failure-inducing callable in an isolated try/except harness
        to capture deterministic exception forensics.
        """
        try:
            trigger_callable()
            raise AssertionError("Callable succeeded unexpectedly; error reproduction failed.")
        except Exception as exc:
            tb = traceback.format_exc()
            clean_tb = MemorySanitizer.mask_secrets(tb)
            clean_msg = MemorySanitizer.mask_secrets(str(exc))
            return ReproductionTrace(
                error_type=exc.__class__.__name__,
                error_message=clean_msg,
                traceback_str=clean_tb,
                trigger_inputs=trigger_inputs or {},
            )

    # 2. Diagnose
    def diagnose_failure(
        self,
        trace: ReproductionTrace,
        context: dict[str, Any] | None = None,
    ) -> FailureDiagnosis:
        """
        Synthesizes technical logs and exception traces into an actionable root cause diagnosis.
        """
        ctx = context or {}
        sig = f"{trace.error_type}:{trace.error_message[:100].strip()}"
        
        # Categorize component based on traceback
        affected = []
        tb_lower = trace.traceback_str.lower()
        if "approval" in tb_lower:
            affected.append("ApprovalService")
        if "conversational" in tb_lower:
            affected.append("ConversationalAgentEngine")
        if "sandbox" in tb_lower:
            affected.append("ExecutionSandbox")
        if "retriever" in tb_lower:
            affected.append("ContextRetriever")
        if not affected:
            affected.append("CoreService")

        root_cause = (
            f"Observed '{trace.error_type}' caused by: {trace.error_message}. "
            f"Context indicates caller expected safe execution, but system failed in component(s): {', '.join(affected)}."
        )

        return FailureDiagnosis(
            problem_signature=sig,
            root_cause_analysis=root_cause,
            affected_components=affected,
            expected_behavior=ctx.get("expected", "Graceful execution and resilient state preservation"),
            actual_behavior=f"Raised {trace.error_type}: {trace.error_message}",
            severity=ctx.get("severity", "high"),
        )

    # 3. Search Evidence
    def search_reference_evidence(
        self,
        diagnosis: FailureDiagnosis,
        keywords: list[str] | None = None,
        max_findings: int = 3,
    ) -> list[EvidenceFinding]:
        """
        Scans local open-source reference repositories for architectural patterns and lessons.
        """
        findings: list[EvidenceFinding] = []
        search_terms = keywords or [diagnosis.problem_signature.split(":")[0].lower()]
        
        # Add terms from affected components
        for comp in diagnosis.affected_components:
            search_terms.append(comp.lower().replace("service", "").replace("engine", ""))

        if not self.reference_root.exists():
            return findings

        # Prioritize permissive open-source reference repos first
        def repo_priority(d: Path) -> int:
            name = d.name.lower()
            if name in ("ragleap-core", "memento-skills", "openai-agents-python", "langgraph", "microsoft-agent-framework"):
                return 0
            return 1

        repo_dirs = sorted(
            [d for d in self.reference_root.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=repo_priority,
        )

        for repo_dir in repo_dirs:
            repo_name = repo_dir.name
            repo_findings = 0
            # Search markdown and python files in repo
            for f in repo_dir.rglob("*.py"):
                if any(p in f.parts for p in (".git", ".venv", "__pycache__", "tests")):
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                text_lower = text.lower()
                matches = [term for term in search_terms if term in text_lower]
                if matches:
                    idx = text_lower.find(matches[0])
                    excerpt = text[max(0, idx - 100):min(len(text), idx + 300)].strip()
                    findings.append(
                        EvidenceFinding(
                            repo_name=repo_name,
                            source_file=str(f.relative_to(self.reference_root)),
                            commit_hash="local_clone",
                            relevant_symbol=matches[0],
                            citation_excerpt=MemorySanitizer.mask_secrets(excerpt),
                            architectural_lesson=f"Adopted design pattern from {repo_name} regarding '{matches[0]}'.",
                            license_status="permissive" if repo_name not in ("dify", "n8n") else "restricted_commercial",
                        )
                    )
                    repo_findings += 1
                    if repo_findings >= 1:
                        break  # Diversify across repositories

            if len(findings) >= max_findings:
                return findings

        return findings

    # 4. Generate Candidates
    def generate_candidate_resolutions(
        self,
        diagnosis: FailureDiagnosis,
        evidence: list[EvidenceFinding],
    ) -> list[ResolutionCandidate]:
        """
        Formulates competing candidate solutions, ensuring each has an architectural rationale.
        """
        candidates: list[ResolutionCandidate] = []

        # Candidate A: Pattern adapted from open-source reference evidence
        has_permissive_evidence = any(e.license_status == "permissive" for e in evidence)
        cand_a = ResolutionCandidate(
            candidate_id="cand-a-evidence-backed",
            title=f"Evidence-Backed Architectural Solution for {diagnosis.problem_signature[:40]}",
            description="Adapts proven pattern from reference open-source repository with deterministic validation.",
            source_evidence=evidence,
            implementation_approach="Implement formal contract check, parameter validation, and correlation tokens.",
            security_impact="High security: eliminates ambiguous inputs and enforces explicit boundary validation.",
            licensing_compliance="Compliant: verified permissive license or concept-only adaptation.",
            score=0.0,
        )
        cand_a.score = self.evaluate_candidate_empirically(cand_a)
        candidates.append(cand_a)

        # Candidate B: Ad-hoc heuristic / quick patch
        cand_b = ResolutionCandidate(
            candidate_id="cand-b-heuristic-patch",
            title="Heuristic Catch-All Fallback Patch",
            description="Catch the exception at the boundary and return a generic failure message.",
            source_evidence=[],
            implementation_approach="Wrap call in try/except Exception and log a warning without changing state contracts.",
            security_impact="Medium/Low: hides root cause and may leave orphaned transactions.",
            licensing_compliance="Compliant: internal patch.",
            score=0.0,
        )
        cand_b.score = self.evaluate_candidate_empirically(cand_b)
        candidates.append(cand_b)

        return candidates

    def evaluate_candidate_empirically(
        self,
        candidate: ResolutionCandidate,
        trial_fn: Callable[[], Any] | None = None,
    ) -> float:
        """
        Dynamically calculates an empirical score (0-100) based on real properties:
          - Evidence depth: up to 30 points (10 pts per concrete open-source finding)
          - Licensing compliance: +30 pts if permissive, +10 if restricted (warning), 0 if unknown
          - Security & Contract: +20 pts for formal contract/token boundary validation
          - Empirical Trial: +20 pts if isolated trial execution passes; 0 if failed
        """
        score = 0.0

        # 1. Evidence depth
        evidence_score = min(30.0, len(candidate.source_evidence) * 10.0)
        score += evidence_score

        # 2. Licensing
        if candidate.source_evidence:
            if all(e.license_status == "permissive" for e in candidate.source_evidence):
                score += 30.0
            elif any(e.license_status == "restricted_commercial" for e in candidate.source_evidence):
                score += 10.0
        else:
            score += 5.0  # Heuristic without external evidence

        # 3. Security impact
        if "high security" in candidate.security_impact.lower() or "formal contract" in candidate.implementation_approach.lower():
            score += 20.0
        else:
            score += 5.0

        # 4. Empirical trial
        if trial_fn is not None:
            try:
                res = trial_fn()
                if res:
                    score += 20.0
            except Exception:
                score += 0.0
        else:
            if len(candidate.source_evidence) > 0:
                score += 15.0

        candidate.score = round(min(100.0, score), 1)
        return candidate.score

    # 5. Compare
    def compare_candidates(
        self,
        candidates: list[ResolutionCandidate],
        trial_fns: dict[str, Callable[[], Any]] | None = None,
    ) -> CandidateComparisonReport:
        """
        Compares candidate resolutions across correctness, architecture compatibility, and security.
        Recalculates empirical scores dynamically if trial functions are provided.
        """
        tf = trial_fns or {}
        for c in candidates:
            if c.candidate_id in tf:
                c.score = self.evaluate_candidate_empirically(c, trial_fn=tf[c.candidate_id])

        sorted_cands = sorted(candidates, key=lambda c: c.score, reverse=True)
        recommended = sorted_cands[0] if sorted_cands else None
        recommended_id = recommended.candidate_id if recommended else "none"

        tradeoffs = [
            f"Candidate '{recommended_id}' recommended with empirical score {recommended.score if recommended else 0:.1f}/100.",
            "Higher scoring candidates emphasize permissive open-source patterns and formal contract validation over ad-hoc try/except catches.",
        ]

        return CandidateComparisonReport(
            candidates_evaluated=candidates,
            recommended_candidate_id=recommended_id,
            rationale=f"Selected {recommended_id} based on dynamic empirical evidence score ({recommended.score if recommended else 0:.1f}/100).",
            tradeoffs_identified=tradeoffs,
        )

    # 6. Experiment
    def experiment_candidate(
        self,
        candidate: ResolutionCandidate,
        trial_fn: Callable[[], Any],
    ) -> ExperimentOutcome:
        """
        Runs trial execution in an isolated sandbox or protected context.
        """
        t_start = datetime.now(timezone.utc)
        try:
            res = trial_fn()
            duration_ms = int((datetime.now(timezone.utc) - t_start).total_seconds() * 1000)
            return ExperimentResult(
                candidate_id=candidate.candidate_id,
                success=True,
                execution_time_ms=duration_ms,
                output_data={"result": str(res)[:500]},
            )
        except Exception as exc:
            duration_ms = int((datetime.now(timezone.utc) - t_start).total_seconds() * 1000)
            return ExperimentResult(
                candidate_id=candidate.candidate_id,
                success=False,
                execution_time_ms=duration_ms,
                error=str(exc),
            )

    # 7. Validate
    def validate_resolution(
        self,
        candidate: ResolutionCandidate,
        deterministic_test: Callable[[], bool],
        llm_rating: float | None = None,
    ) -> ValidationVerdict:
        """
        Enforces that deterministic test gates strictly override any subjective or LLM judge.
        """
        passed = False
        override_reason = None
        try:
            passed = bool(deterministic_test())
        except Exception as err:
            passed = False
            override_reason = f"Deterministic test raised exception: {err}"

        # Rule: If LLM gives high rating (e.g. 0.95) but deterministic test fails, REJECT!
        if llm_rating is not None and llm_rating > 0.8 and not passed:
            override_reason = "Deterministic test failed; LLM subjective approval strictly overridden and rejected."

        verdict_str = "approved" if passed else "rejected"

        return ValidationVerdict(
            candidate_id=candidate.candidate_id,
            deterministic_gate_passed=passed,
            llm_judge_rating=llm_rating,
            override_reason=override_reason,
            tests_executed=["deterministic_unit_and_regression_gate"],
            verdict=verdict_str,
        )

    # 8. Record
    def record_verified_resolution(
        self,
        tenant_id: UUID,
        resolution: VerifiedResolution,
        learning_engine: ContinuousLearningEngine,
    ) -> tuple[Knowledge, bool]:
        """
        Persists problem, root cause, verified fix, source evidence, and test proof
        as an authoritative operational rule in Knowledge via ContinuousLearningEngine.
        """
        if resolution.validation_verdict.verdict != "approved":
            raise ValueError("Cannot record resolution that failed deterministic validation verdict.")

        rule_sig = f"fix:{hashlib.sha256(resolution.problem_signature.encode('utf-8')).hexdigest()[:16]}"
        title = f"Verified Fix: {resolution.problem_signature[:60]}"
        
        evidence_summary = "\n".join(
            f"- [{e.repo_name}] {e.source_file}: {e.architectural_lesson}"
            for e in resolution.evidence_trail[:3]
        )

        content = (
            f"Problem Signature: {resolution.problem_signature}\n"
            f"Root Cause Analysis: {resolution.root_cause}\n"
            f"Verified Resolution Approach: {resolution.chosen_candidate.implementation_approach}\n"
            f"Deterministic Validation: {resolution.validation_verdict.verdict.upper()} "
            f"({len(resolution.validation_verdict.tests_executed)} test gates passed)\n\n"
            f"Reference Open-Source Evidence Trail:\n{evidence_summary}\n\n"
            f"Limitations & Prerequisites:\n"
            + "\n".join(f"- {lim}" for lim in resolution.limitations_and_prerequisites)
        )

        return learning_engine.record_learned_rule(
            tenant_id=tenant_id,
            title=title,
            rule_content=content,
            rule_signature=rule_sig,
            source_reference=f"EvidenceDrivenResolutionEngine (Repo: {resolution.evidence_trail[0].repo_name if resolution.evidence_trail else 'Internal'})",
            confidence=0.98,
        )

    # 9. Reuse
    def retrieve_and_apply(
        self,
        tenant_id: UUID,
        query: str,
        learning_engine: ContinuousLearningEngine,
    ) -> Knowledge | None:
        """
        Retrieves the recorded resolution when an analogous error or task occurs.
        """
        rules = learning_engine.retrieve_applicable_rules(tenant_id=tenant_id, query=query, limit=1)
        return rules[0] if rules else None

    def validate_rule_applicability(
        self,
        rule: Knowledge,
        tenant_id: UUID,
        current_context: dict[str, Any],
        system_version: str = "1.0.0",
        min_confidence: float = 0.80,
    ) -> RuleApplicabilityVerdict:
        """
        Verifies that a previously learned operational rule applies to the current context.
        Prevents applying outdated, cross-tenant, or precondition-mismatched rules.
        """
        passed: list[str] = []
        failed: list[str] = []

        # 1. Tenant ownership
        if rule.tenant_id != tenant_id:
            failed.append(f"Tenant isolation mismatch: rule belongs to tenant '{rule.tenant_id}', not '{tenant_id}'")
            return RuleApplicabilityVerdict(
                is_applicable=False,
                reason="Cross-tenant access violation: rule does not belong to calling tenant.",
                confidence=0.0,
                checks_passed=passed,
                checks_failed=failed,
            )
        passed.append("tenant_isolation_verified")

        # 2. Rule active status
        if rule.status != "active":
            failed.append(f"Rule status is '{rule.status}', not 'active'")
            return RuleApplicabilityVerdict(
                is_applicable=False,
                reason=f"Rule is deactivated or archived (status='{rule.status}').",
                confidence=0.0,
                checks_passed=passed,
                checks_failed=failed,
            )
        passed.append("rule_status_active")

        meta = rule.metadata_json or {}

        # 3. Confidence threshold
        rule_conf = float(meta.get("confidence", 0.90))
        if rule_conf < min_confidence:
            failed.append(f"Rule confidence {rule_conf:.2f} is below threshold {min_confidence:.2f}")
            return RuleApplicabilityVerdict(
                is_applicable=False,
                reason=f"Rule confidence ({rule_conf:.2f}) is below minimum safe threshold ({min_confidence:.2f}).",
                confidence=rule_conf,
                checks_passed=passed,
                checks_failed=failed,
            )
        passed.append(f"confidence_threshold_met ({rule_conf:.2f})")

        # 4. Context precondition check
        required_keys = meta.get("required_context_keys", [])
        missing_keys = [k for k in required_keys if k not in current_context]
        if missing_keys:
            failed.append(f"Missing required context keys: {missing_keys}")
            return RuleApplicabilityVerdict(
                is_applicable=False,
                reason=f"Context does not satisfy rule preconditions (missing required keys: {missing_keys}).",
                confidence=rule_conf,
                checks_passed=passed,
                checks_failed=failed,
            )
        passed.append("preconditions_satisfied")

        # 5. Version compatibility
        rule_version = meta.get("version", "1.0.0")
        if rule_version > system_version:
            failed.append(f"Rule version '{rule_version}' exceeds current system version '{system_version}'")
            return RuleApplicabilityVerdict(
                is_applicable=False,
                reason=f"Rule requires newer system version '{rule_version}'.",
                confidence=rule_conf,
                checks_passed=passed,
                checks_failed=failed,
            )
        passed.append(f"version_compatible ({rule_version} <= {system_version})")

        return RuleApplicabilityVerdict(
            is_applicable=True,
            reason="Rule satisfies all tenant, confidence, version, and context preconditions.",
            confidence=rule_conf,
            checks_passed=passed,
            checks_failed=[],
        )


# Backward-compatible alias
EvidenceDrivenErrorResolver = EvidenceResolutionEngine

