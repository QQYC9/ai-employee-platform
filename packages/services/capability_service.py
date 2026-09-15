from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Capability


class CapabilityService:
    def __init__(self, db: Session):
        self.db = db

    def list_capabilities(
        self,
        tenant_id: UUID,
    ) -> list[Capability]:
        statement = (
            select(Capability)
            .where(
                Capability.is_active.is_(True),
                or_(
                    Capability.tenant_id.is_(None),
                    Capability.tenant_id == tenant_id,
                ),
            )
            .order_by(
                Capability.name,
            )
        )

        return list(self.db.scalars(statement).all())

    def get_capability(
        self,
        tenant_id: UUID,
        capability_id: UUID,
    ) -> Capability | None:
        statement = (
            select(Capability)
            .where(
                Capability.id == capability_id,
                Capability.is_active.is_(True),
                or_(
                    Capability.tenant_id.is_(None),
                    Capability.tenant_id == tenant_id,
                ),
            )
        )

        return self.db.scalar(statement)

    def create_capability(
        self,
        tenant_id: UUID,
        name: str,
        slug: str,
        description: str | None = None,
        config: dict | None = None,
    ) -> Capability:
        name = name.strip()
        slug = slug.strip().lower()

        if not name:
            raise ValueError(
                "Capability name cannot be empty"
            )

        if not slug:
            raise ValueError(
                "Capability slug cannot be empty"
            )

        existing = self.db.scalar(
            select(Capability).where(
                Capability.tenant_id == tenant_id,
                Capability.slug == slug,
            )
        )

        if existing is not None:
            raise ValueError(
                "A capability with this slug already exists"
            )

        capability = Capability(
            tenant_id=tenant_id,
            name=name,
            slug=slug,
            description=description,
            config=config or {},
            is_active=True,
        )

        self.db.add(capability)
        self.db.flush()

        return capability

    def update_capability(
        self,
        tenant_id: UUID,
        capability_id: UUID,
        name: str | None = None,
        description: str | None = None,
        config: dict | None = None,
        is_active: bool | None = None,
    ) -> Capability:
        capability = self.db.scalar(
            select(Capability).where(
                Capability.id == capability_id,
                Capability.tenant_id == tenant_id,
            )
        )

        if capability is None:
            raise ValueError(
                "Capability not found"
            )

        if name is not None:
            name = name.strip()

            if not name:
                raise ValueError(
                    "Capability name cannot be empty"
                )

            capability.name = name

        if description is not None:
            capability.description = description

        if config is not None:
            capability.config = config

        if is_active is not None:
            capability.is_active = is_active

        self.db.flush()

        return capability
