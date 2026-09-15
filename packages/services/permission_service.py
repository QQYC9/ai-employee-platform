from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Permission


class PermissionService:
    def __init__(self, db: Session):
        self.db = db

    def list_permissions(
        self,
        tenant_id: UUID,
        agent_id: UUID | None = None,
    ) -> list[Permission]:
        statement = (
            select(Permission)
            .where(
                Permission.tenant_id == tenant_id,
            )
            .order_by(Permission.created_at)
        )

        if agent_id is not None:
            statement = statement.where(
                Permission.agent_id == agent_id
            )

        return list(
            self.db.scalars(statement).all()
        )

    def get_permission(
        self,
        tenant_id: UUID,
        permission_id: UUID,
    ) -> Permission | None:
        return self.db.scalar(
            select(Permission).where(
                Permission.id == permission_id,
                Permission.tenant_id == tenant_id,
            )
        )

    def create_permission(
        self,
        tenant_id: UUID,
        action: str,
        resource: str,
        effect: str = "allow",
        agent_id: UUID | None = None,
        conditions: dict | None = None,
    ) -> Permission:
        action = action.strip()
        resource = resource.strip()
        effect = effect.strip().lower()

        if not action:
            raise ValueError(
                "Permission action cannot be empty"
            )

        if not resource:
            raise ValueError(
                "Permission resource cannot be empty"
            )

        if effect not in {"allow", "deny"}:
            raise ValueError(
                "Permission effect must be allow or deny"
            )

        existing = self.db.scalar(
            select(Permission).where(
                Permission.tenant_id == tenant_id,
                Permission.agent_id == agent_id,
                Permission.action == action,
                Permission.resource == resource,
            )
        )

        if existing is not None:
            raise ValueError(
                "Permission already exists"
            )

        permission = Permission(
            tenant_id=tenant_id,
            agent_id=agent_id,
            action=action,
            resource=resource,
            effect=effect,
            conditions=conditions or {},
        )

        self.db.add(permission)
        self.db.flush()

        return permission

    def update_permission(
        self,
        tenant_id: UUID,
        permission_id: UUID,
        effect: str | None = None,
        conditions: dict | None = None,
    ) -> Permission:
        permission = self.get_permission(
            tenant_id,
            permission_id,
        )

        if permission is None:
            raise ValueError(
                "Permission not found"
            )

        if effect is not None:
            effect = effect.strip().lower()

            if effect not in {"allow", "deny"}:
                raise ValueError(
                    "Permission effect must be allow or deny"
                )

            permission.effect = effect

        if conditions is not None:
            permission.conditions = conditions

        self.db.flush()

        return permission

    def delete_permission(
        self,
        tenant_id: UUID,
        permission_id: UUID,
    ) -> None:
        permission = self.get_permission(
            tenant_id,
            permission_id,
        )

        if permission is None:
            raise ValueError(
                "Permission not found"
            )

        self.db.delete(permission)
        self.db.flush()

    def is_allowed(
        self,
        tenant_id: UUID,
        action: str,
        resource: str,
        agent_id: UUID | None = None,
    ) -> bool:
        action = action.strip()
        resource = resource.strip()

        # Tenant-level permissions always apply.
        # Agent-level permissions apply only to the requested agent.
        if agent_id is None:
            statement = select(Permission).where(
                Permission.tenant_id == tenant_id,
                Permission.agent_id.is_(None),
                Permission.action == action,
                Permission.resource == resource,
            )
        else:
            statement = select(Permission).where(
                Permission.tenant_id == tenant_id,
                Permission.action == action,
                Permission.resource == resource,
                or_(
                    Permission.agent_id.is_(None),
                    Permission.agent_id == agent_id,
                ),
            )

        permissions = list(
            self.db.scalars(statement).all()
        )

        if not permissions:
            return False

        # Explicit deny always wins.
        if any(
            permission.effect == "deny"
            for permission in permissions
        ):
            return False

        return any(
            permission.effect == "allow"
            for permission in permissions
        )
