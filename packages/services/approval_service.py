from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Approval


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

    def approve(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        decision_by_user_id: UUID,
        reason: str | None = None,
    ) -> Approval:
        approval = self.get_approval(
            tenant_id,
            approval_id,
        )

        if approval is None:
            raise ValueError(
                "Approval not found"
            )

        if approval.status != "pending":
            raise ValueError(
                "Only pending approvals can be approved"
            )

        approval.status = "approved"
        approval.decision_by_user_id = decision_by_user_id
        approval.reason = (
            reason.strip()
            if reason is not None
            else None
        )

        self.db.flush()

        return approval

    def reject(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        decision_by_user_id: UUID,
        reason: str | None = None,
    ) -> Approval:
        approval = self.get_approval(
            tenant_id,
            approval_id,
        )

        if approval is None:
            raise ValueError(
                "Approval not found"
            )

        if approval.status != "pending":
            raise ValueError(
                "Only pending approvals can be rejected"
            )

        approval.status = "rejected"
        approval.decision_by_user_id = decision_by_user_id
        approval.reason = (
            reason.strip()
            if reason is not None
            else None
        )

        self.db.flush()

        return approval

    def cancel(
        self,
        tenant_id: UUID,
        approval_id: UUID,
    ) -> Approval:
        approval = self.get_approval(
            tenant_id,
            approval_id,
        )

        if approval is None:
            raise ValueError(
                "Approval not found"
            )

        if approval.status != "pending":
            raise ValueError(
                "Only pending approvals can be cancelled"
            )

        approval.status = "cancelled"

        self.db.flush()

        return approval
