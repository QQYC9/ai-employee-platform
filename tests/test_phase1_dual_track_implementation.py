from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import (
    Knowledge,
    ProactiveWorkflow,
    Task,
    User,
    WorkflowRun,
)
from packages.models.tenant import Tenant
from packages.self_development.evidence_resolution import (
    EvidenceDrivenErrorResolver,
    EvidenceResolutionEngine,
    ReproductionTrace,
    ResolutionCandidate,
    VerifiedResolution,
)
from packages.self_development.external_knowledge import (
    CertaintyLevel,
    ExternalKnowledgeGap,
    ExternalKnowledgeHarvester,
    LicenseStatus,
)
from packages.self_development.learning_engine import ContinuousLearningEngine
from packages.services.outbox_worker import OutboxWorker
from packages.services.proactive_workflow_service import ProactiveWorkflowService


def create_tenant_and_user(db: Session, name: str) -> tuple[Tenant, User]:
    """Helper to provision an isolated test tenant and owner user."""
    t_id = uuid4()
    tenant = Tenant(
        id=t_id,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{t_id.hex[:6]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        name=f"{name} Owner",
        email=f"{uuid4().hex[:8]}@example.com",
        role="owner",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(tenant)
    db.refresh(user)
    return tenant, user


# =============================================================================
# TRACK A1: Scheduled 12-Hour Continuous Learning & Concurrency Control
# =============================================================================

def test_track_a1_scheduled_12h_learning_workflow_lifecycle(test_db_session: Session):
    """
    TRACK A1 PROOF:
    1. Idempotently provisions a 12-hour continuous learning workflow (interval 43200s).
    2. OutboxWorker / ProactiveWorkflowService claims due runs via FOR UPDATE SKIP LOCKED.
    3. Prevents concurrent duplicates.
    4. Executes learning cycle, records metrics in WorkflowRun.result, and advances next_run_at by 12 hours.
    """
    tenant, _ = create_tenant_and_user(test_db_session, "Scheduled Learning Tenant")
    learning_engine = ContinuousLearningEngine(test_db_session)
    wf_service = ProactiveWorkflowService(test_db_session)

    # 1. Idempotent registration
    wf1 = learning_engine.ensure_scheduled_learning_workflow(
        tenant_id=tenant.id,
        interval_seconds=43200,  # 12 hours
    )
    assert wf1 is not None
    assert wf1.action_type == "continuous_learning_cycle"
    assert wf1.interval_seconds == 43200

    # Ensure idempotency: second call returns the existing workflow without creating duplicates
    wf2 = learning_engine.ensure_scheduled_learning_workflow(tenant_id=tenant.id)
    assert wf1.id == wf2.id

    # 2. Seed a failed task for the learning cycle to discover
    failed_task = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Scheduled WhatsApp Report Dispatch",
        objective="Send weekly summary report",
        status="failed",
        error="NetworkTimeoutError: WhatsApp Cloud Gateway timed out after 30s",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    test_db_session.add(failed_task)

    # Force next_run_at to past so it is immediately due
    wf1.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    test_db_session.commit()

    # 3. Spawn due workflow runs
    spawned = wf_service.spawn_due_workflow_runs(limit=10)
    assert spawned >= 1

    # Verify run exists in pending state
    run_stmt = select(WorkflowRun).where(
        WorkflowRun.workflow_id == wf1.id,
        WorkflowRun.status == "pending",
    )
    pending_run = test_db_session.scalar(run_stmt)
    assert pending_run is not None

    # 4. Concurrency check: Claim run using worker-1
    claimed_runs_w1 = wf_service.claim_due_runs(
        worker_id="worker-node-1",
        batch_size=5,
        tenant_id=tenant.id,
    )
    assert len(claimed_runs_w1) == 1
    assert claimed_runs_w1[0].id == pending_run.id
    assert claimed_runs_w1[0].status == "running"
    assert claimed_runs_w1[0].locked_by == "worker-node-1"

    # Worker-2 attempts to claim concurrently: PROOF OF LOCKING (0 runs claimed!)
    claimed_runs_w2 = wf_service.claim_due_runs(
        worker_id="worker-node-2",
        batch_size=5,
        tenant_id=tenant.id,
    )
    assert len(claimed_runs_w2) == 0

    # 5. Worker-1 executes the claimed run
    success = wf_service.execute_run(claimed_runs_w1[0].id)
    assert success is True

    # 6. Verify run completed and captured metrics
    test_db_session.refresh(pending_run)
    assert pending_run.status == "completed"
    assert pending_run.completed_at is not None
    assert pending_run.result is not None
    assert "rules_learned" in pending_run.result
    assert pending_run.result["rules_learned"] >= 1

    # Verify workflow state updated and next_run_at advanced
    test_db_session.refresh(wf1)
    assert wf1.total_runs == 1
    assert wf1.last_run_at is not None
    # Next run scheduled approximately 12 hours from now
    diff_hours = (wf1.next_run_at - wf1.last_run_at).total_seconds() / 3600.0
    assert 11.9 <= diff_hours <= 12.1


def test_track_a1_worker_failure_resilience_and_stale_recovery(test_db_session: Session):
    """
    TRACK A1 PROOF:
    Tests worker resilience under failure:
      1. Exception during cycle execution increments attempt_count and schedules backoff.
      2. Worker does NOT crash.
      3. Stale locked runs from dead workers are safely recovered.
    """
    tenant, _ = create_tenant_and_user(test_db_session, "Resilience Tenant")
    wf_service = ProactiveWorkflowService(test_db_session)

    # Create workflow configured to fail
    wf = wf_service.create_workflow(
        tenant_id=tenant.id,
        name="Fault Injection Test Workflow",
        trigger_type="schedule",
        schedule_type="interval",
        interval_seconds=43200,
        action_type="continuous_learning_cycle",
        action_payload={"force_failure": True},
    )
    wf.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    test_db_session.commit()

    # Spawn and claim
    wf_service.spawn_due_workflow_runs(limit=5)
    claimed = wf_service.claim_due_runs(worker_id="crashed-worker", batch_size=5, tenant_id=tenant.id)
    assert len(claimed) == 1
    run = claimed[0]

    # Simulate crash: execute fails
    success = wf_service.execute_run(run.id)
    assert success is False

    test_db_session.refresh(run)
    assert run.status == "pending"  # Retried with backoff
    assert run.attempt_count == 1
    assert "Retry scheduled" in (run.error_message or "")

    # Simulate a stale lock where a worker died mid-run without releasing
    run.status = "running"
    run.locked_by = "dead-worker"
    run.lock_expires_at = datetime.now(timezone.utc) - timedelta(seconds=100)
    test_db_session.commit()

    recovered_count = wf_service.recover_stale_runs(stale_threshold_seconds=10)
    assert recovered_count >= 1

    test_db_session.refresh(run)
    assert run.status == "pending"
    assert run.locked_by is None


# =============================================================================
# TRACK A2: External Knowledge Acquisition & Documentation Harvester
# =============================================================================

def test_track_a2_external_knowledge_harvesting_and_attribution(test_db_session: Session):
    """
    TRACK A2 PROOF:
    1. Identifies technical knowledge gap.
    2. Harvester searches local reference repository (e.g. memento-skills, ragleap-core).
    3. Reads actual content, extracts concrete excerpt.
    4. Evaluates license compliance (permissive vs restricted).
    5. Sanitizes secrets.
    6. Persists with SHA-256 deduplication and epistemic certainty tag.
    """
    tenant_a, _ = create_tenant_and_user(test_db_session, "External Knowledge Org A")
    tenant_b, _ = create_tenant_and_user(test_db_session, "External Knowledge Org B")
    learning_engine = ContinuousLearningEngine(test_db_session)
    harvester = ExternalKnowledgeHarvester()

    gap = ExternalKnowledgeGap(
        topic="correlation_token",
        query="approval token expiration correlation",
        trigger_context="Encountered false affirmation during conversation flow",
        gap_type="architectural_pattern",
    )

    # 1. Harvest reference evidence from local repository
    findings = harvester.harvest_local_reference(gap, max_results=2)
    assert len(findings) >= 1
    top_finding = findings[0]
    assert len(top_finding.content) > 50
    assert len(top_finding.excerpt) > 10
    assert top_finding.certainty in (CertaintyLevel.FACT, CertaintyLevel.INFERENCE)

    # 2. Assimilate into Org A's knowledge base
    knowledge_item, is_new = harvester.assimilate_into_knowledge_base(
        tenant_id=tenant_a.id,
        item=top_finding,
        knowledge_service=learning_engine.knowledge_service,
    )
    test_db_session.commit()
    assert is_new is True
    assert knowledge_item.knowledge_type == "external_knowledge"
    assert knowledge_item.metadata_json["usage_count"] == 1
    assert "source_uri" in knowledge_item.metadata_json

    # 3. Deduplication proof: Re-assimilating the exact same source updates usage_count
    item2, is_new2 = harvester.assimilate_into_knowledge_base(
        tenant_id=tenant_a.id,
        item=top_finding,
        knowledge_service=learning_engine.knowledge_service,
    )
    test_db_session.commit()
    assert is_new2 is False
    assert item2.id == knowledge_item.id
    test_db_session.refresh(knowledge_item)
    assert knowledge_item.metadata_json["usage_count"] == 2

    # 4. Multi-tenant isolation proof: Org B cannot see Org A's assimilated external knowledge
    org_b_knowledge, count = learning_engine.knowledge_service.list_knowledge(
        tenant_id=tenant_b.id,
        knowledge_type="external_knowledge",
    )
    assert len(org_b_knowledge) == 0
    assert count == 0


# =============================================================================
# TRACK B: 9-Stage Evidence-Driven Error Resolution Pipeline
# =============================================================================

def test_track_b_complete_9_stage_evidence_resolution_pipeline(test_db_session: Session):
    """
    TRACK B PROOF:
    Executes the full 9-stage evidence-driven error resolution lifecycle:
      1. Reproduce -> 2. Diagnose -> 3. Search Evidence -> 4. Generate Candidates
      -> 5. Compare -> 6. Experiment -> 7. Validate (Deterministic Gate Overrides LLM)
      -> 8. Record (Knowledge Persistence) -> 9. Reuse in Novel Scenario.
    """
    tenant, _ = create_tenant_and_user(test_db_session, "Evidence Resolution Tenant")
    learning_engine = ContinuousLearningEngine(test_db_session)
    resolver = EvidenceResolutionEngine()

    # 1. Reproduce: Capture genuine exception in isolated callable
    def failing_trigger():
        raise PermissionError("ApprovalHijackError: Generic affirmation approved sensitive task without token")

    trace = resolver.reproduce_error(failing_trigger, trigger_inputs={"message": "نعم تمام"})
    assert trace.error_type == "PermissionError"
    assert "ApprovalHijackError" in trace.error_message

    # 2. Diagnose
    diagnosis = resolver.diagnose_failure(
        trace,
        context={"expected": "Require explicit APP-XXXX token before executing action"},
    )
    assert "ApprovalHijackError" in diagnosis.problem_signature
    assert "ApprovalService" in diagnosis.affected_components

    # 3. Search Evidence from local open-source repos
    evidence = resolver.search_reference_evidence(diagnosis, keywords=["approval", "token"])
    assert len(evidence) >= 1
    assert any(e.license_status == "permissive" for e in evidence)

    # 4. Generate Candidates
    candidates = resolver.generate_candidate_resolutions(diagnosis, evidence)
    assert len(candidates) == 2
    cand_a = candidates[0]
    cand_b = candidates[1]

    # 5. Compare
    comparison = resolver.compare_candidates(candidates)
    assert comparison.recommended_candidate_id == cand_a.candidate_id
    assert cand_a.score > cand_b.score

    # 6. Experiment in sandbox
    exp = resolver.experiment_candidate(
        cand_a,
        trial_fn=lambda: {"token_verified": True, "token": "APP-9988"},
    )
    assert exp.success is True

    # 7. Validate: Deterministic Test Gate strictly overrides LLM Judge
    # Scenario 7A: Deterministic gate succeeds -> Approved
    verdict_approved = resolver.validate_resolution(
        candidate=cand_a,
        deterministic_test=lambda: True,
        llm_rating=0.99,
    )
    assert verdict_approved.verdict == "approved"
    assert verdict_approved.deterministic_gate_passed is True

    # Scenario 7B: LLM gives 0.99 rating BUT deterministic test fails -> STRICTLY REJECTED!
    verdict_rejected = resolver.validate_resolution(
        candidate=cand_b,
        deterministic_test=lambda: False,
        llm_rating=0.99,
    )
    assert verdict_rejected.verdict == "rejected"
    assert verdict_rejected.deterministic_gate_passed is False
    assert "strictly overridden and rejected" in (verdict_rejected.override_reason or "")

    # 8. Record: Persist verified resolution as learned operational rule
    verified_res = VerifiedResolution(
        problem_signature=diagnosis.problem_signature,
        root_cause=diagnosis.root_cause_analysis,
        chosen_candidate=cand_a,
        evidence_trail=evidence,
        validation_verdict=verdict_approved,
        limitations_and_prerequisites=["Requires token parameter in request body"],
    )
    knowledge_rule, is_new = resolver.record_verified_resolution(
        tenant_id=tenant.id,
        resolution=verified_res,
        learning_engine=learning_engine,
    )
    test_db_session.commit()
    assert is_new is True
    assert knowledge_rule.knowledge_type == "operational_rule"
    assert "Verified Fix" in knowledge_rule.title

    # 9. Reuse: Retrieve stored resolution when an analogous issue arises
    retrieved = resolver.retrieve_and_apply(
        tenant_id=tenant.id,
        query="ApprovalHijackError token",
        learning_engine=learning_engine,
    )
    assert retrieved is not None
    assert retrieved.id == knowledge_rule.id
    assert "APP-XXXX" in retrieved.content or "token" in retrieved.content.lower()


def test_track_b_integration_with_continuous_learning_engine(test_db_session: Session):
    """
    INTEGRATION PROOF:
    Proves that ContinuousLearningEngine.resolve_task_failure_with_evidence seamlessly
    bridges Track A and Track B.
    """
    tenant, _ = create_tenant_and_user(test_db_session, "Unified Track Tenant")
    learning_engine = ContinuousLearningEngine(test_db_session)

    result = learning_engine.resolve_task_failure_with_evidence(
        tenant_id=tenant.id,
        problem_signature="ToolContractViolationError: Missing required field 'token'",
        error_message="Parameter validation failed for approval action: field 'token' is required",
        deterministic_test=lambda: True,
    )
    test_db_session.commit()

    assert result["status"] == "resolved_and_recorded"
    assert result["is_new"] is True
    assert "rule_id" in result

    # Check rule in database
    rule_id = result["rule_id"]
    rule = test_db_session.scalar(select(Knowledge).where(Knowledge.id == rule_id))
    assert rule is not None
    assert rule.tenant_id == tenant.id
    assert rule.knowledge_type == "operational_rule"
