from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select

from packages.models.domain import User
from packages.services.approval_service import ApprovalService
from packages.services.permission_service import PermissionService
from packages.services.action_policy_service import ActionPolicyService


@dataclass(frozen=True)
class DecisionResult:
    decision: str
    reason: str
    requires_approval: bool = False
    approval_for: str | None = None


class DecisionEngine:
    """
    Central decision layer for agent actions.

    Decisions:
    - ALLOW
    - APPROVAL_REQUIRED
    - DENY
    """

    OWNER_MANAGEMENT_ACTIONS = {
        "task_create",
        "execute:task_create",
        "task_query",
        "execute:task_query",
    }

    OWNER_ADMIN_ROLES = {
        "tenant_owner",
        "owner",
        "tenant_admin",
        "admin",
        "platform_admin",
        "superadmin",
    }

    def __init__(self, db):
        self.db = db
        self.permission_service = PermissionService(db)
        self.action_policy_service = ActionPolicyService(db)
        self.approval_service = ApprovalService(db)

    def decide(
        self,
        *,
        tenant_id: UUID,
        action: str,
        resource: str | None = None,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
        tool_id: UUID | None = None,
        parameters: dict[str, Any] | None = None,
        actor_id: UUID | None = None,
        is_owner: bool = False,
    ) -> DecisionResult:
        # Standard permission evaluation
        allowed = self.permission_service.is_allowed(
            tenant_id=tenant_id,
            action=action,
            resource=resource or "",
            agent_id=agent_id,
        )

        is_owner_authorized = False
        explicit_deny = False

        # Phase 1: Limited and safe delegation for authenticated human owner.
        # Strict security rules:
        # 1. is_owner must be True, actor_id must be provided, and agent_id must be None
        #    (distinguishes human owner direct execution from delegated digital agent execution).
        # 2. Action is strictly constrained to the allowed owner management whitelist (task_create, task_query).
        # 3. actor_id must correspond to a verified, active user with an administrative/owner role in the SAME tenant.
        # 4. Explicit deny records in Permission table are strictly respected and override owner delegation.
        clean_action = action.strip()
        if is_owner and actor_id is not None and agent_id is None:
            if clean_action in self.OWNER_MANAGEMENT_ACTIONS:
                try:
                    owner_user = self.db.scalar(
                        select(User).where(
                            User.id == actor_id,
                            User.tenant_id == tenant_id,
                            User.status == "active",
                        )
                    )
                    user_role = (owner_user.role or "").strip().lower() if owner_user else ""
                    if owner_user is not None and user_role in self.OWNER_ADMIN_ROLES:
                        # Differentiate explicit deny from absence of permission using existing PermissionService interface
                        tenant_perms = self.permission_service.list_permissions(tenant_id)
                        matching_actions = {
                            clean_action,
                            f"execute:{clean_action}",
                            clean_action.removeprefix("execute:"),
                        }
                        explicit_deny = self.permission_service.has_tenant_explicit_deny(
                            tenant_id=tenant_id,
                            actions=matching_actions,
                            resource=resource,
                            tenant_permissions=tenant_perms,
                        )
                        if not explicit_deny:
                            is_owner_authorized = True
                except Exception:
                    is_owner_authorized = False

        if not allowed and not is_owner_authorized:
            return DecisionResult(
                decision="DENY",
                reason="Action is explicitly denied for this tenant." if explicit_deny else "Action is not permitted.",
            )

        policy = self.action_policy_service.resolve_policy(
            tenant_id=tenant_id,
            action=action,
            resource=resource,
        )

        if policy is None:
            return DecisionResult(
                decision="ALLOW",
                reason="Action is permitted and no approval policy applies.",
            )

        if not policy.requires_approval:
            return DecisionResult(
                decision="ALLOW",
                reason="Action is permitted and approval is not required.",
            )

        if task_id is not None:
            approvals = self.approval_service.list_approvals(
                tenant_id=tenant_id,
                task_id=task_id,
            )
            matching_approvals = []
            for a in approvals:
                if a.action != action:
                    continue
                # If approval contains structured execution context, verify integrity
                if "[context:" in a.description:
                    try:
                        ctx_str = a.description.split("[context:", 1)[1].rsplit("]", 1)[0]
                        ctx = json.loads(ctx_str)
                        if tool_id and ctx.get("tool_id") and ctx.get("tool_id") != str(tool_id):
                            continue
                        if resource and ctx.get("resource") and ctx.get("resource") != resource:
                            continue
                        if ctx.get("parameters_hash"):
                            curr_hash = hashlib.sha256(
                                json.dumps(parameters or {}, sort_keys=True).encode()
                            ).hexdigest()
                            if ctx.get("parameters_hash") != curr_hash:
                                continue
                    except Exception:
                        pass
                matching_approvals.append(a)

            if matching_approvals:
                if any(a.status == "approved" for a in matching_approvals):
                    return DecisionResult(
                        decision="ALLOW",
                        reason="Action is permitted and approval has been approved.",
                    )
                if matching_approvals[0].status == "rejected":
                    return DecisionResult(
                        decision="DENY",
                        reason=f"Approval for action '{action}' was rejected.",
                    )

        return DecisionResult(
            decision="APPROVAL_REQUIRED",
            reason="Action is permitted but requires approval.",
            requires_approval=True,
            approval_for=policy.approval_for,
        )

    def request_approval(
        self,
        *,
        tenant_id: UUID,
        action: str,
        description: str,
        requested_for: str,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
        resource: str | None = None,
    ):
        decision = self.decide(
            tenant_id=tenant_id,
            action=action,
            resource=resource,
            agent_id=agent_id,
        )

        if decision.decision != "APPROVAL_REQUIRED":
            raise ValueError(
                "Approval is not required for this action"
            )

        return self.approval_service.create_approval(
            tenant_id=tenant_id,
            requested_for=requested_for,
            action=action,
            description=description,
            task_id=task_id,
            requested_by_agent_id=agent_id,
        )
