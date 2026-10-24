from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from typing import Any

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session


from packages.models.domain import (
    Agent,
    Approval,
    AuditEvent,
    Capability,
    CapabilityVersion,
    DevelopmentRequest,
    DevelopmentRun,
    Tool,
    User,
)
from packages.self_development.dynamic_tool import DynamicCapabilityTool
from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.specification import (
    CapabilitySpecification,
    validate_and_classify_specification,
)
from packages.self_development.verifier import CapabilitySecurityVerifier
from packages.services.approval_service import ApprovalService
from packages.services.audit_service import AuditService
from packages.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SelfDevelopmentEngine:
    """
    Core self-development lifecycle engine managing need discovery, specification,
    sandboxed development/testing, risk-based approvals, version activation, and rollback.
    """

    def __init__(
        self,
        db: Session,
        tool_registry: ToolRegistry | None = None,
        verifier: CapabilitySecurityVerifier | None = None,
        sandbox: ExecutionSandbox | None = None,
        approval_service: ApprovalService | None = None,
        audit_service: AuditService | None = None,
        require_container_isolation: bool | None = None,
    ):
        self.db = db
        self.tool_registry = tool_registry
        self.sandbox = sandbox or ExecutionSandbox()
        self.verifier = verifier or CapabilitySecurityVerifier(sandbox=self.sandbox)
        self.approval_service = approval_service or ApprovalService(db)
        self.audit_service = audit_service or AuditService(db)
        if require_container_isolation is None:
            require_container_isolation = os.environ.get("REQUIRE_CONTAINER_ISOLATION", "").lower() in ("1", "true", "yes")
        self.require_container_isolation = require_container_isolation


    # -------------------------------------------------------------------------
    # 1. Need Discovery & Duplicate Prevention
    # -------------------------------------------------------------------------

    def create_development_request(
        self,
        tenant_id: UUID,
        title: str,
        reason: str,
        requirements: dict[str, Any] | None = None,
        expected_benefit: str | None = None,
        requested_from: str = "agent",
        agent_id: UUID | None = None,
        priority: str = "normal",
        risk_level: str = "medium",
    ) -> tuple[DevelopmentRequest, bool]:
        """
        Registers a development request after scanning existing tools and active capabilities.
        Returns: (DevelopmentRequest, is_duplicate)
        """
        clean_title = (title or "").strip()
        clean_reason = (reason or "").strip()
        if not clean_title or not clean_reason:
            raise ValueError("Development request title and reason cannot be empty")

        if agent_id is not None:
            agent = self.db.scalar(
                select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
            )
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' does not exist or does not belong to tenant")

        req_data = dict(requirements or {})

        proposed_slug = req_data.get("slug") or clean_title.lower().replace(" ", "_")

        # Duplicate check against existing active capabilities
        existing_cap = self.db.scalar(
            select(Capability).where(
                (Capability.slug == proposed_slug)
                & ((Capability.tenant_id == tenant_id) | (Capability.tenant_id.is_(None)))
                & (Capability.is_active.is_(True))
            )
        )

        # Duplicate check against existing platform tools
        existing_tool = self.db.scalar(
            select(Tool).where(
                (Tool.slug == proposed_slug)
                & ((Tool.tenant_id == tenant_id) | (Tool.tenant_id.is_(None)))
                & (Tool.is_active.is_(True))
            )
        )

        is_duplicate = False
        duplicate_ref = None

        if existing_cap is not None:
            is_duplicate = True
            duplicate_ref = f"capability:{existing_cap.slug}"
        elif existing_tool is not None:
            is_duplicate = True
            duplicate_ref = f"tool:{existing_tool.slug}"
        elif self.tool_registry and self.tool_registry.get(proposed_slug) is not None:
            is_duplicate = True
            duplicate_ref = f"tool_registry:{proposed_slug}"

        req_data["priority"] = priority
        req_data["risk_level"] = risk_level
        req_data["reviewed_existing_capabilities"] = True
        if is_duplicate:
            req_data["is_duplicate"] = True
            req_data["already_satisfied_by"] = duplicate_ref

        req = DevelopmentRequest(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            request_type="capability",
            title=clean_title,
            reason=clean_reason,
            requirements=req_data,
            expected_benefit=expected_benefit,
            requested_from=requested_from,
            status="already_satisfied" if is_duplicate else "requested",
        )
        self.db.add(req)
        self.db.commit()
        self.db.refresh(req)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            agent_id=agent_id,
            event_type="self_development.request.created",
            action="create_request",
            description=f"Development request '{clean_title}' registered with status '{req.status}'.",
            event_metadata={
                "request_id": str(req.id),
                "is_duplicate": is_duplicate,
                "already_satisfied_by": duplicate_ref,
            },
        )
        self.db.commit()

        return req, is_duplicate

    # -------------------------------------------------------------------------
    # 2. Specification Preparation & Validation
    # -------------------------------------------------------------------------

    def prepare_specification(
        self,
        tenant_id: UUID,
        request_id: UUID,
        spec_data: dict[str, Any],
        user: User | None = None,
    ) -> CapabilityVersion:
        """
        Validates specification schema, evaluates risk level, updates request status,
        and initializes draft CapabilityVersion.
        """
        req = self.db.scalar(
            select(DevelopmentRequest).where(
                DevelopmentRequest.id == request_id,
                DevelopmentRequest.tenant_id == tenant_id,
            )
        )
        if req is None:
            raise ValueError("Development request not found")

        # Validate & classify specification
        spec = validate_and_classify_specification(spec_data)

        # Check existing versions count for this slug
        prev_versions_count = self.db.scalar(
            select(func.count(CapabilityVersion.id)).where(
                CapabilityVersion.tenant_id == tenant_id,
                CapabilityVersion.slug == spec.slug,
            )
        ) or 0
        version_number = prev_versions_count + 1

        version = CapabilityVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            request_id=req.id,
            version_number=version_number,
            slug=spec.slug,
            name=spec.name,
            description=spec.description,
            specification=spec.model_dump(),
            risk_level=spec.risk_level,
            status="specified",
            created_by_user_id=user.id if user else None,
        )
        self.db.add(version)

        req.status = "specified"
        self.db.commit()
        self.db.refresh(version)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user.id if user else None,
            event_type="self_development.specification.prepared",
            action="prepare_spec",
            description=f"Specification prepared for capability '{spec.name}' (v{version_number}, risk: {spec.risk_level}).",
            event_metadata={
                "version_id": str(version.id),
                "slug": spec.slug,
                "risk_level": spec.risk_level,
            },
        )
        self.db.commit()

        return version

    # -------------------------------------------------------------------------
    # 3. Contained Sandboxed Development & Testing
    # -------------------------------------------------------------------------

    def develop_and_test(
        self,
        tenant_id: UUID,
        version_id: UUID,
        implementation_code: str,
    ) -> tuple[CapabilityVersion, DevelopmentRun]:
        """
        Executes AST static security verification and isolated acceptance tests in sandbox.
        Advances state based on pass/fail and risk policy.
        """
        version = self.db.scalar(
            select(CapabilityVersion).where(
                CapabilityVersion.id == version_id,
                CapabilityVersion.tenant_id == tenant_id,
            )
        )
        if version is None:
            raise ValueError("Capability version not found")

        if version.status not in ("specified", "developing", "failed"):
            raise ValueError(f"Cannot develop version in status '{version.status}'")

        clean_code = (implementation_code or "").strip()
        if not clean_code:
            raise ValueError("Implementation code cannot be empty")

        content_hash = hashlib.sha256(clean_code.encode("utf-8")).hexdigest()

        version.status = "developing"
        self.db.flush()

        spec = CapabilitySpecification(**version.specification)

        # Run full verification (AST + Sandboxed test runner)
        overall_success, test_summary, security_verdict = self.verifier.full_verification(
            clean_code, spec
        )

        test_summary["content_hash"] = content_hash
        security_verdict["content_hash"] = content_hash
        spec_dict = dict(version.specification or {})
        spec_dict["content_hash"] = content_hash
        version.specification = spec_dict

        version.implementation_code = clean_code
        version.test_results = test_summary

        # Create DevelopmentRun record
        run = DevelopmentRun(
            id=uuid4(),
            tenant_id=tenant_id,
            request_id=version.request_id,
            capability_version_id=version.id,
            run_type="sandbox_test",
            status="passed" if overall_success else "failed",
            test_summary=test_summary,
            security_verdict=security_verdict,
            logs=json.dumps(test_summary.get("details", [])) if test_summary.get("details") else None,
            error_message=test_summary.get("error"),

            duration_ms=sum(d.get("execution_time_ms", 0) for d in test_summary.get("details", [])),
        )
        self.db.add(run)

        # State transition according to test outcome and risk level
        if overall_success:
            version.status = "awaiting_approval"

            # Create approval record for medium/high risk or policy enforcement
            approval = self.approval_service.create_approval(
                tenant_id=tenant_id,
                requested_for="tenant_admin",
                action="activate_capability",
                description=(
                    f"Approval requested for dynamic capability '{version.name}' "
                    f"(v{version.version_number}, risk: {version.risk_level}) [hash:{content_hash}]"
                ),
            )
            version.approval_id = approval.id
        else:
            version.status = "failed"

        self.db.commit()
        self.db.refresh(version)
        self.db.refresh(run)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="self_development.test_run.completed",
            action="test_run",
            description=f"Development test run completed for '{version.name}' with verdict '{run.status}'.",
            event_metadata={
                "version_id": str(version.id),
                "run_id": str(run.id),
                "overall_success": overall_success,
                "status": version.status,
            },
        )
        self.db.commit()

        return version, run

    # -------------------------------------------------------------------------
    # 4. Review & Approval (Policy-Enforced)
    # -------------------------------------------------------------------------

    def review_and_approve(
        self,
        tenant_id: UUID,
        version_id: UUID,
        user: User,
        approved: bool,
        reason: str | None = None,
    ) -> CapabilityVersion:
        """
        Evaluates review decision. High-risk capabilities strictly require human
        admin review; agents are barred from approving their own development requests.
        """
        version = self.db.scalar(
            select(CapabilityVersion).where(
                CapabilityVersion.id == version_id,
                CapabilityVersion.tenant_id == tenant_id,
            )
        )
        if version is None:
            raise ValueError("Capability version not found")

        if version.status != "awaiting_approval":
            raise ValueError(f"Version status must be 'awaiting_approval' to review (current: '{version.status}')")

        user_role = (user.role or "").strip().lower()
        is_human_admin = user_role in ("tenant_owner", "owner", "tenant_admin", "admin", "platform_admin", "superadmin")

        # Agent cannot approve its own request
        if version.request_id:
            req = self.db.scalar(select(DevelopmentRequest).where(DevelopmentRequest.id == version.request_id))
            if req and req.agent_id:
                if user.id == req.agent_id or user_role == "agent":
                    raise PermissionError("Agents cannot approve their own self-development requests")

        if not is_human_admin:
            raise PermissionError(f"User role '{user.role}' lacks permission to approve capabilities")

        # Content hash verification against tested candidate
        if version.implementation_code:
            current_hash = hashlib.sha256(version.implementation_code.strip().encode("utf-8")).hexdigest()
            tested_hash = (version.test_results or {}).get("content_hash") or (version.specification or {}).get("content_hash")
            if tested_hash and current_hash != tested_hash:
                raise ValueError(
                    f"Integrity check failed: implementation code has been modified (current: {current_hash}, tested: {tested_hash})"
                )


        # Update approval record if exists
        if version.approval_id:
            if approved:
                self.approval_service.approve(
                    tenant_id=tenant_id,
                    approval_id=version.approval_id,
                    decision_by_user_id=user.id,
                    reason=reason,
                    user_role=user.role,
                )
            else:
                self.approval_service.reject(
                    tenant_id=tenant_id,
                    approval_id=version.approval_id,
                    decision_by_user_id=user.id,
                    reason=reason,
                    user_role=user.role,
                )

        version.status = "approved" if approved else "rejected"
        self.db.commit()
        self.db.refresh(version)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user.id,
            event_type="self_development.capability_version.reviewed",
            action="approve" if approved else "reject",
            description=f"User '{user.email}' {'approved' if approved else 'rejected'} capability '{version.name}' (v{version.version_number}).",
            event_metadata={
                "version_id": str(version.id),
                "approved": approved,
                "reason": reason,
                "status": version.status,
            },
        )
        self.db.commit()

        return version

    # -------------------------------------------------------------------------
    # 5. Registration & Activation
    # -------------------------------------------------------------------------

    def activate_version(
        self,
        tenant_id: UUID,
        version_id: UUID,
        user: User,
    ) -> CapabilityVersion:
        """
        Activates an approved capability version, archives prior versions,
        registers in capability catalog, and registers dynamic tool in ToolRegistry.
        """
        version = self.db.scalar(
            select(CapabilityVersion).where(
                CapabilityVersion.id == version_id,
                CapabilityVersion.tenant_id == tenant_id,
            )
        )
        if version is None:
            raise ValueError("Capability version not found")

        user_role = (user.role or "").strip().lower()
        is_human_admin = user_role in ("tenant_owner", "owner", "tenant_admin", "admin", "platform_admin", "superadmin")
        if not is_human_admin:
            raise PermissionError(f"User role '{user.role}' lacks permission to activate capabilities")

        if self.require_container_isolation and not self.sandbox.is_containerized:
            raise PermissionError(
                "Activation blocked: Dynamic capability cannot be activated without verified container isolation (restricted Docker container with --network none)."
            )

        if version.status != "approved":
            raise ValueError(f"Only approved capability versions can be activated (current status: '{version.status}')")

        # Content hash verification before activation
        if version.implementation_code:
            current_hash = hashlib.sha256(version.implementation_code.strip().encode("utf-8")).hexdigest()
            tested_hash = (version.test_results or {}).get("content_hash") or (version.specification or {}).get("content_hash")
            if tested_hash and current_hash != tested_hash:
                raise ValueError(
                    f"Activation blocked: code tampering detected. Current hash {current_hash} != tested hash {tested_hash}."
                )

        # Verify test results are passing
        test_results = version.test_results or {}
        if not test_results.get("all_passed"):
            raise ValueError("Cannot activate capability version with failing tests")


        now = datetime.now(timezone.utc)

        # 1. Register or update Capability record in database
        cap = self.db.scalar(
            select(Capability).where(
                Capability.slug == version.slug,
                Capability.tenant_id == tenant_id,
            )
        )
        if cap is None:
            cap = Capability(
                id=uuid4(),
                tenant_id=tenant_id,
                name=version.name,
                slug=version.slug,
                description=version.description,
                config=version.specification,
                is_active=True,
            )
            self.db.add(cap)
            self.db.flush()
        else:
            cap.is_active = True
            cap.config = version.specification
            self.db.flush()

        # 2. Deactivate any previously active versions of this capability
        prev_active_stmt = select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant_id,
            CapabilityVersion.slug == version.slug,
            CapabilityVersion.status == "active",
            CapabilityVersion.id != version.id,
        )
        for prev_v in self.db.scalars(prev_active_stmt).all():
            prev_v.status = "disabled"

        # 3. Activate current version
        version.capability_id = cap.id
        version.status = "active"
        version.activated_at = now
        self.db.commit()
        self.db.refresh(version)

        # 4. Register dynamic tool in registry if available
        if self.tool_registry is not None and version.implementation_code:
            spec = CapabilitySpecification(**version.specification)
            dyn_tool = DynamicCapabilityTool(
                tenant_id=tenant_id,
                slug=version.slug,
                name=version.name,
                description=version.description or version.name,
                implementation_code=version.implementation_code,
                spec=spec,
                sandbox=self.sandbox,
                require_container_isolation=self.require_container_isolation,
            )
            self.tool_registry.register(dyn_tool)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user.id,
            event_type="self_development.capability_version.activated",
            action="activate",
            description=f"Capability '{version.name}' (v{version.version_number}) activated by '{user.email}'.",
            event_metadata={
                "capability_id": str(cap.id),
                "version_id": str(version.id),
                "slug": version.slug,
            },
        )
        self.db.commit()

        return version

    # -------------------------------------------------------------------------
    # 6. Disabling & Rollback
    # -------------------------------------------------------------------------

    def disable_or_rollback(
        self,
        tenant_id: UUID,
        slug: str,
        user: User,
        reason: str | None = None,
        rollback_to_version_number: int | None = None,
    ) -> CapabilityVersion:
        """
        Disables current active version or rolls back to a previous approved version,
        preserving complete audit and version history.
        """
        user_role = (user.role or "").strip().lower()
        is_human_admin = user_role in ("tenant_owner", "owner", "tenant_admin", "admin", "platform_admin", "superadmin")
        if not is_human_admin:
            raise PermissionError(f"User role '{user.role}' lacks permission to rollback or disable capabilities")

        clean_slug = (slug or "").strip().lower()

        # Find current active version
        active_version = self.db.scalar(
            select(CapabilityVersion).where(
                CapabilityVersion.tenant_id == tenant_id,
                CapabilityVersion.slug == clean_slug,
                CapabilityVersion.status == "active",
            )
        )
        if active_version is None:
            raise ValueError(f"No active version found for capability slug '{clean_slug}'")

        now = datetime.now(timezone.utc)

        if rollback_to_version_number is not None:
            # Locate target version
            target_version = self.db.scalar(
                select(CapabilityVersion).where(
                    CapabilityVersion.tenant_id == tenant_id,
                    CapabilityVersion.slug == clean_slug,
                    CapabilityVersion.version_number == rollback_to_version_number,
                )
            )
            if target_version is None:
                raise ValueError(f"Target rollback version {rollback_to_version_number} does not exist")

            # Must have been approved
            target_test_summary = target_version.test_results or {}
            if not target_test_summary.get("all_passed"):
                raise ValueError(f"Cannot rollback to version {rollback_to_version_number} because tests did not pass")

            active_version.status = "rolled_back"
            active_version.rolled_back_at = now
            active_version.rollback_reason = reason or f"Rolled back to v{rollback_to_version_number}"

            target_version.status = "active"
            target_version.activated_at = now
            self.db.commit()
            self.db.refresh(target_version)

            result_version = target_version
            action_desc = f"Rolled back capability '{clean_slug}' from v{active_version.version_number} to v{target_version.version_number}."
            event_type = "self_development.capability_version.rolled_back"
        else:
            active_version.status = "disabled"
            active_version.rollback_reason = reason or "Manually disabled"
            self.db.commit()
            self.db.refresh(active_version)

            result_version = active_version
            action_desc = f"Disabled capability '{clean_slug}' (v{active_version.version_number})."
            event_type = "self_development.capability_version.disabled"

        # Synchronize runtime ToolRegistry
        if self.tool_registry is not None:
            if rollback_to_version_number is not None and result_version.implementation_code:
                if self.require_container_isolation and not self.sandbox.is_containerized:
                    raise PermissionError(
                        "Activation blocked: Dynamic capability cannot be rolled back or activated without verified container isolation (restricted Docker container with --network none)."
                    )
                # Content hash verification on target rollback version
                cur_hash = hashlib.sha256(result_version.implementation_code.strip().encode("utf-8")).hexdigest()
                tested_hash = (result_version.test_results or {}).get("content_hash") or (result_version.specification or {}).get("content_hash")
                if tested_hash and cur_hash != tested_hash:
                    raise ValueError(
                        f"Rollback blocked: code tampering detected in rollback version (current: {cur_hash}, tested: {tested_hash})."
                    )

                spec = CapabilitySpecification(**result_version.specification)
                dyn_tool = DynamicCapabilityTool(
                    tenant_id=tenant_id,
                    slug=clean_slug,
                    name=result_version.name,
                    description=result_version.description or result_version.name,
                    implementation_code=result_version.implementation_code,
                    spec=spec,
                    sandbox=self.sandbox,
                    require_container_isolation=self.require_container_isolation,
                )
                self.tool_registry.register(dyn_tool)
            else:
                self.tool_registry.unregister(clean_slug)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user.id,
            event_type=event_type,
            action="rollback" if rollback_to_version_number else "disable",
            description=f"{action_desc} Reason: '{reason or 'N/A'}'.",
            event_metadata={
                "slug": clean_slug,
                "current_status": result_version.status,
                "reason": reason,
            },
        )
        self.db.commit()

        return result_version


    # -------------------------------------------------------------------------
    # 7. Queries & Inspection
    # -------------------------------------------------------------------------

    def list_requests(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[DevelopmentRequest]:
        query = select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == tenant_id)
        if status:
            query = query.where(DevelopmentRequest.status == status)
        query = query.order_by(DevelopmentRequest.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(query).all())

    def get_request(self, tenant_id: UUID, request_id: UUID) -> DevelopmentRequest | None:
        return self.db.scalar(
            select(DevelopmentRequest).where(
                DevelopmentRequest.id == request_id,
                DevelopmentRequest.tenant_id == tenant_id,
            )
        )

    def get_version(self, tenant_id: UUID, version_id: UUID) -> CapabilityVersion | None:
        return self.db.scalar(
            select(CapabilityVersion).where(
                CapabilityVersion.id == version_id,
                CapabilityVersion.tenant_id == tenant_id,
            )
        )

    def list_versions_for_slug(self, tenant_id: UUID, slug: str) -> list[CapabilityVersion]:
        clean_slug = (slug or "").strip().lower()
        query = (
            select(CapabilityVersion)
            .where(
                CapabilityVersion.tenant_id == tenant_id,
                CapabilityVersion.slug == clean_slug,
            )
            .order_by(CapabilityVersion.version_number.desc())
        )
        return list(self.db.scalars(query).all())

    def list_runs_for_version(self, tenant_id: UUID, version_id: UUID) -> list[DevelopmentRun]:
        query = (
            select(DevelopmentRun)
            .where(
                DevelopmentRun.tenant_id == tenant_id,
                DevelopmentRun.capability_version_id == version_id,
            )
            .order_by(DevelopmentRun.created_at.desc())
        )
        return list(self.db.scalars(query).all())

