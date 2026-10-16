from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
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

        approval = Approval(
            tenant_id=tenant_id,
            task_id=task_id,
            requested_by_agent_id=requested_by_agent_id,
            requested_for=requested_for,
            action=action,
            description=description,
            status="pending",
        )

        self.db.add(approval)
        self.db.flush()

        return approval

    @staticmethod
    def is_role_authorized(role: str | None, requested_for: str) -> bool:
        norm_role = (role or "").strip().lower()
        norm_req = (requested_for or "").strip().lower()

        if norm_role in ("owner", "tenant_owner", "superadmin", "platform_admin"):
            return True
        if norm_req in ("tenant_admin", "admin"):
            return norm_role in ("admin", "tenant_admin")
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
    ) -> Approval:
        approval = self.get_approval(
            tenant_id,
            approval_id,
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

        approval.status = "approved"
        approval.decision_by_user_id = decision_by_user_id
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

