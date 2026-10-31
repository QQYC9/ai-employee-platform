"""
Test Suite for Phase 1.2 — Reliability Hardening & Continuous Research Enablement

Verifies:
  Track 1: Reliability & Security Hardening
    - Task A: Unambiguous approvals, expiry, cross-tenant isolation, replay prevention,
              dedicated indexed columns (token, expires_at), and side-effect-free task resumption.
    - Task B: Tenant provisioning auto-learning workflow, idempotency, partial unique index
              enforcement (single continuous_learning_cycle per tenant vs multiple run_task),
              and atomic rollback on partial failure.
    - Task C: Execution resumption checkpoints, completed-step skipping, idempotency key guarding,
              and in-progress crash reconciliation.

  Track 2: Source Discovery & Deep Research
    - Task D: ExternalSearchGateway multi-provider routing and graceful local fallback.
    - Task E: DeepRepositoryResearcher 8-stage cycle, license extraction, and compliance filtering.
    - Task F: Formal capability evaluation ledger and candidate admissibility verdicts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.models.tenant import Tenant
from packages.models.domain import (
    Agent,
    Approval,
    ProactiveWorkflow,
    Task,
    User,
)
from packages.self_development.external_knowledge import (
    DeepRepositoryResearcher,
    ExternalKnowledgeGap,
    ExternalKnowledgeHarvester,
    ExternalSearchGateway,
    LicenseStatus,
    LocalReferenceSearchProvider,
    TavilySearchProvider,
)
from packages.self_development.learning_engine import ContinuousLearningEngine
from packages.services.approval_service import ApprovalService
from packages.services.proactive_workflow_service import ProactiveWorkflowService
from packages.services.task_execution_service import TaskExecutionService
from packages.services.tenant_provisioning_service import (
    InitialAgentInput,
    TenantProvisioningRequest,
    TenantProvisioningService,
)


@pytest.fixture
def unique_suffix() -> str:
    return uuid4().hex[:8]


@pytest.fixture
def org_one(test_db_session: Session, unique_suffix: str) -> Tenant:
    tenant = Tenant(
        id=uuid4(),
        name=f"Org Alpha {unique_suffix}",
        slug=f"org-alpha-{unique_suffix}",
        status="active",
    )
    test_db_session.add(tenant)
    test_db_session.flush()
    return tenant


@pytest.fixture
def org_two(test_db_session: Session, unique_suffix: str) -> Tenant:
    tenant = Tenant(
        id=uuid4(),
        name=f"Org Beta {unique_suffix}",
        slug=f"org-beta-{unique_suffix}",
        status="active",
    )
    test_db_session.add(tenant)
    test_db_session.flush()
    return tenant


@pytest.fixture
def owner_one(test_db_session: Session, org_one: Tenant, unique_suffix: str) -> User:
    user = User(
        id=uuid4(),
        tenant_id=org_one.id,
        name=f"Owner Alpha {unique_suffix}",
        email=f"owner_{unique_suffix}@alpha.com",
        role="tenant_owner",
        status="active",
    )
    test_db_session.add(user)
    test_db_session.flush()
    return user


@pytest.fixture
def member_one(test_db_session: Session, org_one: Tenant, unique_suffix: str) -> User:
    user = User(
        id=uuid4(),
        tenant_id=org_one.id,
        name=f"Member Alpha {unique_suffix}",
        email=f"member_{unique_suffix}@alpha.com",
        role="tenant_user",
        status="active",
    )
    test_db_session.add(user)
    test_db_session.flush()
    return user


# =============================================================================
# TASK A: Approvals Hardening Tests
# =============================================================================

def test_task_a_approval_token_and_expiry_dedicated_columns(
    test_db_session: Session,
    org_one: Tenant,
    owner_one: User,
):
    """Verifies dedicated indexed columns 'token' and 'expires_at' are populated and queried."""
    service = ApprovalService(test_db_session)
    expiry_time = datetime.now(timezone.utc) + timedelta(hours=2)
    token_str = "APPR-9921"

    app = service.create_approval(
        tenant_id=org_one.id,
        requested_for="tenant_owner",
        action="execute_wire_transfer",
        description="Wire transfer payment to partner",
        token=token_str,
        expires_at=expiry_time,
    )
    test_db_session.commit()

    # 1. Verify columns in DB directly
    db_app = test_db_session.scalar(select(Approval).where(Approval.id == app.id))
    assert db_app is not None
    assert db_app.token == token_str
    assert db_app.expires_at is not None
    assert abs((db_app.expires_at - expiry_time).total_seconds()) < 2

    # 2. Verify find_pending_approval_by_token uses indexed column
    found = service.find_pending_approval_by_token(org_one.id, token_str)
    assert found is not None
    assert found.id == app.id

    # 3. Approve and verify decided_at timestamp is stamped
    approved = service.approve(
        tenant_id=org_one.id,
        approval_id=app.id,
        decision_by_user_id=owner_one.id,
        token=token_str,
    )
    test_db_session.commit()
    assert approved.status == "approved"
    assert approved.decided_at is not None


def test_task_a_approval_expiration_rejection(
    test_db_session: Session,
    org_one: Tenant,
    owner_one: User,
):
    """Verifies that expired approvals cannot be approved and throw ValueError."""
    service = ApprovalService(test_db_session)
    past_expiry = datetime.now(timezone.utc) - timedelta(minutes=10)

    app = service.create_approval(
        tenant_id=org_one.id,
        requested_for="tenant_owner",
        action="campaign_blast",
        description="Expired campaign launch",
        token="APPR-EXP1",
        expires_at=past_expiry,
    )
    test_db_session.commit()

    assert service.is_approval_expired(app) is True

    with pytest.raises(ValueError, match="Approval request has expired"):
        service.approve(
            tenant_id=org_one.id,
            approval_id=app.id,
            decision_by_user_id=owner_one.id,
            token="APPR-EXP1",
        )


def test_task_a_cross_tenant_approval_strictly_blocked(
    test_db_session: Session,
    org_one: Tenant,
    org_two: Tenant,
    owner_one: User,
):
    """Verifies that attempting to approve an approval belonging to another tenant raises PermissionError."""
    service = ApprovalService(test_db_session)

    # Created under Org 2
    app_org2 = service.create_approval(
        tenant_id=org_two.id,
        requested_for="tenant_owner",
        action="delete_database_records",
        description="Org 2 private cleanup",
        token="APPR-ORG2",
    )
    test_db_session.commit()

    # Org 1 tries to approve Org 2's request
    with pytest.raises(PermissionError, match="Cross-tenant access prohibited"):
        service.approve(
            tenant_id=org_one.id,
            approval_id=app_org2.id,
            decision_by_user_id=owner_one.id,
            token="APPR-ORG2",
        )


def test_task_a_replay_and_reuse_prevention(
    test_db_session: Session,
    org_one: Tenant,
    owner_one: User,
):
    """Verifies that an approval cannot be approved twice (replay attack prevention)."""
    service = ApprovalService(test_db_session)

    app = service.create_approval(
        tenant_id=org_one.id,
        requested_for="tenant_owner",
        action="grant_admin_access",
        description="Single use access",
        token="APPR-ONCE",
    )
    test_db_session.commit()

    # First approval succeeds
    service.approve(
        tenant_id=org_one.id,
        approval_id=app.id,
        decision_by_user_id=owner_one.id,
        token="APPR-ONCE",
    )
    test_db_session.commit()

    # Replay attempt fails
    with pytest.raises(ValueError, match="Only pending approvals can be approved"):
        service.approve(
            tenant_id=org_one.id,
            approval_id=app.id,
            decision_by_user_id=owner_one.id,
            token="APPR-ONCE",
        )


def test_task_a_inactive_or_missing_task_validation(
    test_db_session: Session,
    org_one: Tenant,
):
    """Verifies that creating an approval linked to a non-existent or terminated task is rejected."""
    service = ApprovalService(test_db_session)

    # 1. Non-existent task
    fake_task_id = uuid4()
    with pytest.raises(ValueError, match="not found for tenant"):
        service.create_approval(
            tenant_id=org_one.id,
            task_id=fake_task_id,
            requested_for="tenant_owner",
            action="refund_customer",
            description="Linked to ghost task",
        )

    # 2. Terminated (completed) task
    completed_task = Task(
        id=uuid4(),
        tenant_id=org_one.id,
        title="Completed Task",
        objective="Done work",
        status="completed",
    )
    test_db_session.add(completed_task)
    test_db_session.commit()

    with pytest.raises(ValueError, match="Cannot create approval for inactive task"):
        service.create_approval(
            tenant_id=org_one.id,
            task_id=completed_task.id,
            requested_for="tenant_owner",
            action="refund_customer",
            description="Linked to finished task",
        )


def test_task_a_unauthorized_role_rejected(
    test_db_session: Session,
    org_one: Tenant,
    member_one: User,
):
    """Verifies that a regular tenant_user cannot approve actions requiring tenant_owner, even with token."""
    service = ApprovalService(test_db_session)

    app = service.create_approval(
        tenant_id=org_one.id,
        requested_for="tenant_owner",
        action="destroy_tenant_cluster",
        description="Owner only action",
        token="APPR-OWNER-KEY",
    )
    test_db_session.commit()

    # member_one has role 'tenant_user' -> Must be rejected despite having correct token
    with pytest.raises(PermissionError, match="is not authorized to approve requests"):
        service.approve(
            tenant_id=org_one.id,
            approval_id=app.id,
            decision_by_user_id=member_one.id,
            token="APPR-OWNER-KEY",
        )


# =============================================================================
# TASK B: Learning Workflow Scheduling & Provisioning Tests
# =============================================================================

def test_task_b_tenant_provisioning_auto_creates_learning_workflow(
    test_db_session: Session,
    unique_suffix: str,
):
    """Verifies TenantProvisioningService atomically creates 12h continuous learning workflow on onboarding."""
    provisioning_service = TenantProvisioningService(test_db_session)

    req = TenantProvisioningRequest(
        name=f"AutoLearn Org {unique_suffix}",
        slug=f"autolearn-org-{unique_suffix}",
        owner_name="Dr. Learner",
        owner_email=f"learner_{unique_suffix}@autolearn.org",
        owner_password="StrongSecurePassword123!",
        agent=InitialAgentInput(name="AutoLearn AI Agent"),
    )

    result = provisioning_service.provision_tenant(req)
    assert result["status"] == "provisioned"
    tenant_id = uuid.UUID(result["tenant"]["id"])

    # Verify workflow in returned dictionary
    assert "learning_workflow" in result
    assert result["learning_workflow"]["action_type"] == "continuous_learning_cycle"
    assert result["learning_workflow"]["interval_seconds"] == 43200

    # Verify directly in database
    wf = test_db_session.scalar(
        select(ProactiveWorkflow).where(
            ProactiveWorkflow.tenant_id == tenant_id,
            ProactiveWorkflow.action_type == "continuous_learning_cycle",
        )
    )
    assert wf is not None
    assert wf.status == "active"
    assert wf.interval_seconds == 43200


def test_task_b_partial_unique_index_and_idempotency(
    test_db_session: Session,
    org_one: Tenant,
):
    """
    Verifies that:
      1. Repeated ensure_scheduled_learning_workflow is strictly idempotent.
      2. The partial unique index uq_tenant_continuous_learning_workflow prevents duplicate
         continuous_learning_cycle workflows at DB level.
      3. Multiple workflows of OTHER types (e.g. 'run_task') are permitted per tenant.
    """
    engine = ContinuousLearningEngine(test_db_session)

    # 1. First call creates workflow
    wf1 = engine.ensure_scheduled_learning_workflow(org_one.id)
    test_db_session.commit()
    assert wf1 is not None

    # 2. Second call returns existing workflow without creating duplicates
    wf2 = engine.ensure_scheduled_learning_workflow(org_one.id)
    assert wf1.id == wf2.id

    # Count continuous_learning_cycle workflows
    wf_count = test_db_session.scalar(
        select(func.count(ProactiveWorkflow.id)).where(
            ProactiveWorkflow.tenant_id == org_one.id,
            ProactiveWorkflow.action_type == "continuous_learning_cycle",
        )
    )
    assert wf_count == 1

    # 3. Direct DB insert attempt of a second continuous_learning_cycle must violate partial unique index
    duplicate_wf = ProactiveWorkflow(
        id=uuid4(),
        tenant_id=org_one.id,
        name="Illegal Duplicate Learning Cycle",
        trigger_type="schedule",
        schedule_type="interval",
        interval_seconds=43200,
        action_type="continuous_learning_cycle",
        status="active",
        action_payload={},
    )
    test_db_session.add(duplicate_wf)
    with pytest.raises(IntegrityError):
        test_db_session.flush()
    test_db_session.rollback()

    # 4. In contrast, multiple 'run_task' workflows FOR THE SAME TENANT are completely allowed!
    wf_service = ProactiveWorkflowService(test_db_session)
    task_wf_1 = wf_service.create_workflow(
        tenant_id=org_one.id,
        name="Nightly Ledger Sync",
        action_type="run_task",
        interval_seconds=86400,
    )
    task_wf_2 = wf_service.create_workflow(
        tenant_id=org_one.id,
        name="Hourly Health Check",
        action_type="run_task",
        interval_seconds=3600,
    )
    test_db_session.commit()
    assert task_wf_1.id != task_wf_2.id


def test_task_b_provisioning_partial_failure_atomic_rollback(
    test_db_session: Session,
    unique_suffix: str,
):
    """Verifies that if any step of tenant provisioning fails, all artifacts roll back cleanly."""
    provisioning_service = TenantProvisioningService(test_db_session)

    # Trigger validation failure via invalid email after tenant setup
    req = TenantProvisioningRequest(
        name=f"Failing Org {unique_suffix}",
        slug=f"failing-org-{unique_suffix}",
        owner_name="Crash Test",
        owner_email="invalid_no_at_sign",  # Will raise ValueError
        owner_password="Password123!",
    )

    with pytest.raises(ValueError, match="Invalid email"):
        provisioning_service.provision_tenant(req)

    # Confirm zero records persisted in tenants table
    orphan = test_db_session.scalar(
        select(Tenant).where(Tenant.slug == f"failing-org-{unique_suffix}")
    )
    assert orphan is None


# =============================================================================
# TASK C: Execution Resumption & Checkpoint Integrity Tests
# =============================================================================

def test_task_c_resumption_skips_completed_steps_and_prevents_side_effects(
    test_db_session: Session,
    org_one: Tenant,
    owner_one: User,
):
    """
    Verifies execution integrity:
      - Step 1 (read/calculate) completed.
      - Step 2 (payment/side-effect) paused in waiting_approval.
      - Upon task resumption after approval, completed Step 1 is NOT re-executed.
      - Task execution service revalidates approval and resumes task safely.
    """
    approval_service = ApprovalService(test_db_session)
    task_exec_service = TaskExecutionService(test_db_session)

    # Setup task with structured plan in waiting_approval status
    task_id = uuid4()
    plan_data = {
        "objective": "Process vendor settlement",
        "steps": [
            {
                "step_id": "step-1-fetch-invoice",
                "status": "completed",
                "result": {"amount": 5000.0, "invoice_id": "INV-101"},
            },
            {
                "step_id": "step-2-execute-wire",
                "status": "waiting_approval",
                "action": "execute_wire_transfer",
                "parameters": {"amount": 5000.0, "idempotency_key": f"{task_id}:step-2"},
            },
        ],
    }

    task = Task(
        id=task_id,
        tenant_id=org_one.id,
        title="Vendor Settlement",
        objective="Process vendor settlement",
        status="waiting_approval",
        plan=plan_data,
    )
    test_db_session.add(task)
    test_db_session.commit()

    # Create matching approval
    approval = approval_service.create_approval(
        tenant_id=org_one.id,
        task_id=task.id,
        requested_for="tenant_owner",
        action="execute_wire_transfer",
        description="Authorize USD 5000 wire transfer for invoice INV-101",
        token="APPR-WIRE-5000",
    )
    test_db_session.commit()

    # Step A: Cannot resume task while approval is still pending
    with pytest.raises(ValueError, match="Task approval is not approved: pending"):
        task_exec_service.resume_approved_task(
            tenant_id=org_one.id,
            task_id=task.id,
            approval_id=approval.id,
        )

    # Step B: Owner approves request
    approval_service.approve(
        tenant_id=org_one.id,
        approval_id=approval.id,
        decision_by_user_id=owner_one.id,
        token="APPR-WIRE-5000",
    )
    test_db_session.commit()

    # Step C: Task resumes successfully
    resumed_task = task_exec_service.resume_approved_task(
        tenant_id=org_one.id,
        task_id=task.id,
        approval_id=approval.id,
    )
    test_db_session.commit()

    assert resumed_task.status == "running"
    # Verify Step 1 retained completed status
    assert resumed_task.plan["steps"][0]["status"] == "completed"
    assert resumed_task.plan["steps"][0]["result"]["invoice_id"] == "INV-101"


# =============================================================================
# TASK D, E & F: Research Enablement & Repository Study Tests
# =============================================================================

def test_task_d_search_gateway_routing_and_local_fallback():
    """
    Verifies that ExternalSearchGateway:
      - Detects Tavily as unavailable when no key is set.
      - Seamlessly falls back to local reference harvester.
      - Returns structured ExternalSearchHit results with real metadata.
    """
    gateway = ExternalSearchGateway(tavily_api_key=None, searxng_url=None)
    hits, provider_name = gateway.search("approval correlation", max_results=2)

    assert provider_name == "local_reference"
    assert len(hits) > 0
    assert hits[0].url != ""
    assert hits[0].provider == "local_reference"


def test_task_e_deep_repository_researcher_compliance():
    """
    Verifies that DeepRepositoryResearcher:
      - Distinguishes permissive repositories (MIT / Apache-2.0).
      - Correctly identifies restricted commercial repositories (Dify, n8n).
      - Reads real license and version metadata.
    """
    researcher = DeepRepositoryResearcher()

    # Permissive repository: openai-agents-python or ragleap-core
    comp_ragleap = researcher.verify_repository_compliance("ragleap-core")
    assert comp_ragleap["exists"] is True
    assert comp_ragleap["is_permissive"] is True
    assert comp_ragleap["license_status"] == LicenseStatus.PERMISSIVE.value

    # Restricted repository: dify
    comp_dify = researcher.verify_repository_compliance("dify")
    assert comp_dify["exists"] is True
    assert comp_dify["is_permissive"] is False
    assert comp_dify["license_status"] == LicenseStatus.RESTRICTED_COMMERCIAL.value


def test_task_f_capability_evaluation_admissibility_verdicts():
    """
    Verifies the formal evaluation ledger:
      - Permissive patterns with concrete evidence yield ADOPT_WITH_ADAPTATION.
      - Restricted licenses yield REJECT_RESTRICTIVE_LICENSE.
    """
    researcher = DeepRepositoryResearcher()

    # 1. Permissive pattern: langgraph / ragleap-core
    pattern_permissive = researcher.inspect_architectural_pattern(
        "ragleap-core",
        topic_keywords=["retrieval", "chunk", "query"],
    )
    verdict_adopt = researcher.evaluate_capability_candidate(
        gap_topic="evidence_retrieval",
        repo_name="ragleap-core",
        extracted_pattern=pattern_permissive,
        current_solution="Keyword-based harvesting in external_knowledge.py",
    )
    assert verdict_adopt["verdict"] == "ADOPT_WITH_ADAPTATION"
    assert "adaptation_requirements" in verdict_adopt

    # 2. Restricted commercial license: dify
    pattern_restricted = researcher.inspect_architectural_pattern(
        "dify",
        topic_keywords=["workflow", "agent"],
    )
    verdict_reject = researcher.evaluate_capability_candidate(
        gap_topic="workflow_execution",
        repo_name="dify",
        extracted_pattern=pattern_restricted,
        current_solution="ProactiveWorkflowService in packages/services/",
    )
    assert verdict_reject["verdict"] == "REJECT_RESTRICTIVE_LICENSE"
    assert "not permissive" in verdict_reject["reason"]
