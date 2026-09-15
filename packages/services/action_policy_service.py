from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import ActionPolicy


class ActionPolicyService:
    VALID_APPROVAL_FOR = {
        "tenant_owner",
        "platform_admin",
    }

    def __init__(self, db: Session):
        self.db = db

    def list_policies(
        self,
        tenant_id: UUID,
        action: str | None = None,
        resource: str | None = None,
        active_only: bool = True,
    ) -> list[ActionPolicy]:
        statement = (
            select(ActionPolicy)
            .where(
                (ActionPolicy.tenant_id == tenant_id)
                | (ActionPolicy.tenant_id.is_(None))
            )
            .order_by(ActionPolicy.created_at.desc())
        )

        if action is not None:
            action = action.strip()
            statement = statement.where(ActionPolicy.action == action)

        if resource is not None:
            resource = resource.strip()
            statement = statement.where(
                (ActionPolicy.resource == resource)
                | (ActionPolicy.resource.is_(None))
            )

        if active_only:
            statement = statement.where(ActionPolicy.is_active.is_(True))

        return list(self.db.scalars(statement).all())

    def get_policy(
        self,
        tenant_id: UUID,
        policy_id: UUID,
    ) -> ActionPolicy | None:
        return self.db.scalar(
            select(ActionPolicy).where(
                ActionPolicy.id == policy_id,
                (ActionPolicy.tenant_id == tenant_id)
                | (ActionPolicy.tenant_id.is_(None)),
            )
        )

    def create_policy(
        self,
        tenant_id: UUID | None,
        action: str,
        resource: str | None = None,
        requires_approval: bool = False,
        approval_for: str | None = None,
        conditions: dict | None = None,
        is_active: bool = True,
    ) -> ActionPolicy:
        action = action.strip()

        if not action:
            raise ValueError("Action policy action cannot be empty")

        if resource is not None:
            resource = resource.strip() or None

        if approval_for is not None:
            approval_for = approval_for.strip() or None

            if approval_for not in self.VALID_APPROVAL_FOR:
                raise ValueError("Invalid approval_for")

        if requires_approval and approval_for is None:
            raise ValueError(
                "approval_for is required when approval is required"
            )

        policy = ActionPolicy(
            tenant_id=tenant_id,
            action=action,
            resource=resource,
            requires_approval=requires_approval,
            approval_for=approval_for,
            conditions=conditions or {},
            is_active=is_active,
        )

        self.db.add(policy)
        self.db.flush()

        return policy

    def update_policy(
        self,
        tenant_id: UUID,
        policy_id: UUID,
        action: str | None = None,
        resource: str | None = None,
        requires_approval: bool | None = None,
        approval_for: str | None = None,
        conditions: dict | None = None,
        is_active: bool | None = None,
    ) -> ActionPolicy:
        policy = self.get_policy(tenant_id, policy_id)

        if policy is None:
            raise ValueError("Action policy not found")

        if policy.tenant_id is None:
            raise ValueError("Global action policies cannot be modified by tenant users")

        if action is not None:
            action = action.strip()

            if not action:
                raise ValueError("Action policy action cannot be empty")

            policy.action = action

        if resource is not None:
            policy.resource = resource.strip() or None

        if requires_approval is not None:
            policy.requires_approval = requires_approval

        if approval_for is not None:
            approval_for = approval_for.strip() or None

            if approval_for not in self.VALID_APPROVAL_FOR:
                raise ValueError("Invalid approval_for")

            policy.approval_for = approval_for

        if conditions is not None:
            policy.conditions = conditions

        if is_active is not None:
            policy.is_active = is_active

        if policy.requires_approval and policy.approval_for is None:
            raise ValueError(
                "approval_for is required when approval is required"
            )

        self.db.flush()

        return policy

    def delete_policy(
        self,
        tenant_id: UUID,
        policy_id: UUID,
    ) -> None:
        policy = self.get_policy(tenant_id, policy_id)

        if policy is None:
            raise ValueError("Action policy not found")

        if policy.tenant_id is None:
            raise ValueError("Global action policies cannot be deleted by tenant users")

        self.db.delete(policy)
        self.db.flush()

    def resolve_policy(
        self,
        tenant_id: UUID,
        action: str,
        resource: str | None = None,
    ) -> ActionPolicy | None:
        action = action.strip()

        if not action:
            raise ValueError("Action cannot be empty")

        statement = select(ActionPolicy).where(
            ActionPolicy.action == action,
            ActionPolicy.is_active.is_(True),
            (
                (ActionPolicy.tenant_id == tenant_id)
                | (ActionPolicy.tenant_id.is_(None))
            ),
        )

        if resource is not None:
            resource = resource.strip()

            statement = statement.where(
                (ActionPolicy.resource == resource)
                | (ActionPolicy.resource.is_(None))
            )

        policies = list(
            self.db.scalars(
                statement.order_by(ActionPolicy.created_at.desc())
            ).all()
        )

        if not policies:
            return None

        tenant_specific = [
            policy for policy in policies
            if policy.tenant_id == tenant_id
        ]

        if tenant_specific:
            exact_resource = [
                policy for policy in tenant_specific
                if policy.resource == resource
            ]

            if exact_resource:
                return exact_resource[0]

            tenant_generic = [
                policy for policy in tenant_specific
                if policy.resource is None
            ]

            if tenant_generic:
                return tenant_generic[0]

        global_exact = [
            policy for policy in policies
            if policy.tenant_id is None
            and policy.resource == resource
        ]

        if global_exact:
            return global_exact[0]

        global_generic = [
            policy for policy in policies
            if policy.tenant_id is None
            and policy.resource is None
        ]

        if global_generic:
            return global_generic[0]

        return None
