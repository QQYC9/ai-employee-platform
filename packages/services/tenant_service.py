from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.tenant import Tenant


class TenantService:
    """
    Business logic for tenant operations.

    Tenant access is always scoped to the authenticated tenant
    unless the operation is explicitly a platform-level operation.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_current_tenant(self, tenant_id: UUID) -> Tenant | None:
        """Return the active tenant by ID."""
        return self.db.scalar(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.status == "active",
            )
        )

    def update_current_tenant(
        self,
        tenant_id: UUID,
        name: str | None = None,
    ) -> Tenant:
        """
        Update the current tenant.

        Only fields explicitly supplied are changed.
        """
        tenant = self.get_current_tenant(tenant_id)

        if tenant is None:
            raise ValueError("Tenant not found")

        if name is not None:
            name = name.strip()

            if not name:
                raise ValueError("Tenant name cannot be empty")

            tenant.name = name

        self.db.flush()

        return tenant
