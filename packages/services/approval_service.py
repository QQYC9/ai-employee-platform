from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.models.domain import Approval, Task, User


class ApprovalService:
    VALID_STATUSES = {
        "pending",
        "approved",
        "rejected",
        "cancelled",
    }

    def __init__(self, db: Session):
        self.db = db

    def list_approvals(
        self,
        tenant_id: UUID,
        status: str | None = None,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> list[Approval]:
        statement = (
            select(Approval)
            .where(
                Approval.tenant_id == tenant_id,
            )
            .order_by(Approval.created_at.desc())
        )

        if status is not None:
            status = status.strip().lower()

            if status not in self.VALID_STATUSES:
                raise ValueError(
                    "Invalid approval status"
                )

            statement = statement.where(
                Approval.status == status
            )

        if task_id is not None:
            statement = statement.where(
                Approval.task_id == task_id
            )

        if agent_id is not None:
            statement = statement.where(
                Approval.requested_by_agent_id == agent_id
            )

        return list(
            self.db.scalars(statement).all()
        )

    def get_approval(
        self,
        tenant_id: UUID,
        approval_id: UUID,
    ) -> Approval | None:
        return self.db.scalar(
            select(Approval).where(
                Approval.id == approval_id,
                Approval.tenant_id == tenant_id,
            )
        )

    def create_approval(
        self,
        tenant_id: UUID,
        requested_for: str,
        action: str,
        description: str,
        task_id: UUID | None = None,
        requested_by_agent_id: UUID | None = None,
        *,
        token: str | None = None,
        expires_at: datetime | None = None,
        expires_in_hours: int | None = None,
    ) -> Approval:
        requested_for = requested_for.strip()
        action = action.strip()
        description = description.strip()

        if not requested_for:
            raise ValueError(
                "Approval requested_for cannot be empty"
            )

        if not action:
            raise ValueError(
                "Approval action cannot be empty"
            )

        if not description:
            raise ValueError(
                "Approval description cannot be empty"
            )

        # Build correlation tags if token or expiration requested
        meta_prefix = ""
        if token:
            clean_token = token.strip().upper()
            meta_prefix += f"[TOKEN: {clean_token}] "

        calc_expiry = expires_at
        if calc_expiry is None and expires_in_hours is not None and expires_in_hours > 0:
            calc_expiry = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)

        if calc_expiry:
            if calc_expiry.tzinfo is None:
                calc_expiry = calc_expiry.replace(tzinfo=timezone.utc)
            meta_prefix += f"[EXPIRES: {calc_expiry.isoformat()}] "

        # Validate linked task if provided
        if task_id is not None:
            task = self.db.scalar(
                select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
            )
            if task is None:
                raise ValueError(f"Task '{task_id}' not found for tenant")
            if getattr(task, "status", None) in ("completed", "failed", "cancelled"):
                raise ValueError(
                    f"Cannot create approval for inactive task in status '{task.status}'"
                )

        effective_description = f"{meta_prefix}{description}".strip()

        approval = Approval(
            tenant_id=tenant_id,
            task_id=task_id,
            requested_by_agent_id=requested_by_agent_id,
            requested_for=requested_for,
            action=action,
            description=effective_description,
            status="pending",
            token=clean_token if token else None,
            expires_at=calc_expiry,
        )

        self.db.add(approval)
        self.db.flush()

        return approval

    @staticmethod
    def get_approval_token(approval: Approval | None) -> str | None:
        """Extract correlation token from dedicated column or description if present."""
        if not approval:
            return None
        col_token = getattr(approval, "token", None)
        if col_token:
            return str(col_token).strip()
        if not approval.description:
            return None
        m = re.search(r"\[TOKEN:\s*([A-Za-z0-9_-]+)\]", approval.description)
        return m.group(1).strip() if m else None

    @staticmethod
    def get_approval_expiry(approval: Approval | None) -> datetime | None:
        """Extract expiration timestamp from dedicated column or description if present."""
        if not approval:
            return None
        col_expiry = getattr(approval, "expires_at", None)
        if col_expiry is not None:
            return col_expiry
        if not approval.description:
            return None
        m = re.search(r"\[EXPIRES:\s*([^\]]+)\]", approval.description)
        if not m:
            return None
        try:
            return datetime.fromisoformat(m.group(1).strip())
        except Exception:
            return None

    @staticmethod
    def is_approval_expired(approval: Approval | None) -> bool:
        """Check if approval has passed its expiration timestamp."""
        expiry = ApprovalService.get_approval_expiry(approval)
        if expiry is None:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expiry

    def find_pending_approval_by_token(self, tenant_id: UUID, token: str) -> Approval | None:
        """Find pending approval by its correlation token within tenant scope."""
        if not token:
            return None
        clean_token = token.strip().upper()
        # Fast-path: query dedicated indexed token column
        indexed_app = self.db.scalar(
            select(Approval).where(
                Approval.tenant_id == tenant_id,
                func.upper(Approval.token) == clean_token,
                Approval.status == "pending",
            )
        )
        if indexed_app is not None:
            return indexed_app

        # Fallback: scan pending approvals with tokens in description
        pending = self.list_approvals(tenant_id, status="pending")
        for app in pending:
            app_token = self.get_approval_token(app)
            if app_token and app_token.upper() == clean_token:
                return app
        return None

    @staticmethod
    def is_role_authorized(role: str | None, requested_for: str) -> bool:
        norm_role = (role or "").strip().lower()
        norm_req = (requested_for or "").strip().lower()

        # Routine tenant commercial approvals: strictly reserved for tenant owner/owner
        if norm_req in ("owner", "tenant_owner"):
            return norm_role in ("owner", "tenant_owner")

        if norm_role in ("owner", "tenant_owner"):
            return True

        if norm_req in ("superadmin", "platform_admin"):
            return norm_role in ("superadmin", "platform_admin", "owner", "tenant_owner")

        if norm_req in ("tenant_admin", "admin"):
            return norm_role in ("admin", "tenant_admin", "owner", "tenant_owner")

        if norm_req in ("tenant_user", "user", "member", ""):
            return True

        return False

    def approve(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        decision_by_user_id: UUID,
        reason: str | None = None,
        user_role: str | None = None,
        *,
        token: str | None = None,
    ) -> Approval:
        # Row-level lock to prevent concurrent duplicate approval executions
        approval = self.db.scalar(
            select(Approval)
            .where(
                Approval.id == approval_id,
                Approval.tenant_id == tenant_id,
            )
            .with_for_update()
        )

        if approval is None:
            # Check for cross-tenant access attempt
            try:
                cross_tenant = self.db.scalar(
                    select(Approval).where(Approval.id == approval_id)
                )
                if cross_tenant is not None:
                    raise PermissionError(
                        "Cross-tenant access prohibited: approval belongs to another tenant"
                    )
            except Exception as e:
                if isinstance(e, PermissionError):
                    raise
            raise ValueError(
                "Approval not found"
            )

        if approval.status != "pending":
            raise ValueError(
                "Only pending approvals can be approved"
            )

        # Check expiration
        if self.is_approval_expired(approval):
            raise ValueError("Approval request has expired")

        # Check token correlation if approval was token-gated
        expected_token = self.get_approval_token(approval)
        if expected_token:
            if not token or token.strip().upper() != expected_token.upper():
                raise ValueError(
                    f"Approval token mismatch: token '{expected_token}' is required to authorize this request"
                )

        # Enforce role authorization
        if user_role is None:
            try:
                user = self.db.scalar(
                    select(User).where(User.id == decision_by_user_id)
                )
                if user is not None:
                    user_role = user.role
            except Exception:
                pass

        if user_role is not None and not self.is_role_authorized(user_role, approval.requested_for):
            raise PermissionError(
                f"User role '{user_role}' is not authorized to approve requests for '{approval.requested_for}'"
            )

        # Ensure associated task is active if present
        if approval.task_id is not None:
            task = self.db.scalar(
                select(Task).where(
                    Task.id == approval.task_id,
                    Task.tenant_id == tenant_id,
                )
            )
            if task is not None and task.status in ("completed", "failed", "cancelled"):
                raise ValueError(
                    f"Cannot approve request for task in terminal status '{task.status}'"
                )

        approval.status = "approved"
        approval.decision_by_user_id = decision_by_user_id
        approval.decided_at = datetime.now(timezone.utc)
        clean_reason = reason.strip() if reason is not None else None
        approval.decision_reason = clean_reason
        approval.reason = clean_reason

        self.db.flush()

        return approval

    def reject(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        decision_by_user_id: UUID,
        reason: str | None = None,
        user_role: str | None = None,
    ) -> Approval:
        approval = self.db.scalar(
            select(Approval)
            .where(
                Approval.id == approval_id,
                Approval.tenant_id == tenant_id,
            )
            .with_for_update()
        )

        if approval is None:
            try:
                cross_tenant = self.db.scalar(
                    select(Approval).where(Approval.id == approval_id)
                )
                if cross_tenant is not None:
                    raise PermissionError(
                        "Cross-tenant access prohibited: approval belongs to another tenant"
                    )
            except Exception as e:
                if isinstance(e, PermissionError):
                    raise
            raise ValueError(
                "Approval not found"
            )

        if approval.status != "pending":
            raise ValueError(
                "Only pending approvals can be rejected"
            )

        # Enforce role authorization
        if user_role is None:
            try:
                user = self.db.scalar(
                    select(User).where(User.id == decision_by_user_id)
                )
                if user is not None:
                    user_role = user.role
            except Exception:
                pass

        if user_role is not None and not self.is_role_authorized(user_role, approval.requested_for):
            raise PermissionError(
                f"User role '{user_role}' is not authorized to reject requests for '{approval.requested_for}'"
            )

        approval.status = "rejected"
        approval.decision_by_user_id = decision_by_user_id
        approval.decided_at = datetime.now(timezone.utc)
        clean_reason = reason.strip() if reason is not None else None
        approval.decision_reason = clean_reason
        approval.reason = clean_reason

        # Synchronize rejection with associated waiting task if present
        if approval.task_id is not None:
            task = self.db.scalar(
                select(Task).where(
                    Task.id == approval.task_id,
                    Task.tenant_id == tenant_id,
                )
            )
            if task is not None and task.status == "waiting_approval":
                task.status = "failed"
                detail_r = clean_reason or "Approval rejected by authorized user"
                task.error = f"Task failed: Required approval for '{approval.action}' was rejected ({detail_r})"
                if task.plan and isinstance(task.plan, dict) and "steps" in task.plan:
                    for s in task.plan["steps"]:
                        if s.get("status") == "waiting_approval":
                            s["status"] = "failed"
                            s["error"] = task.error
                from sqlalchemy.orm.attributes import flag_modified
                try:
                    flag_modified(task, "plan")
                except Exception:
                    pass

        self.db.flush()

        return approval

    def cancel(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        user_id: UUID | None = None,
        user_role: str | None = None,
    ) -> Approval:
        approval = self.get_approval(
            tenant_id,
            approval_id,
        )

        if approval is None:
            try:
                cross_tenant = self.db.scalar(
                    select(Approval).where(Approval.id == approval_id)
                )
                if cross_tenant is not None:
                    raise PermissionError(
                        "Cross-tenant access prohibited: approval belongs to another tenant"
                    )
            except Exception as e:
                if isinstance(e, PermissionError):
                    raise
            raise ValueError(
                "Approval not found"
            )

        if approval.status != "pending":
            raise ValueError(
                "Only pending approvals can be cancelled"
            )

        if user_role is None and user_id is not None:
            try:
                user = self.db.scalar(
                    select(User).where(User.id == user_id)
                )
                if user is not None:
                    user_role = user.role
            except Exception:
                pass

        if user_role is not None and user_role not in (
            "owner", "tenant_owner", "admin", "tenant_admin", "superadmin"
        ):
            raise PermissionError("Only administrators or owners can cancel approvals")

        approval.status = "cancelled"

        self.db.flush()

        return approval

