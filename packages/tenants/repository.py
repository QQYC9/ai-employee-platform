from __future__ import annotations

from typing import Generic, TypeVar, Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.tenants.context import get_current_tenant_id


ModelT = TypeVar("ModelT")


class TenantRepository(Generic[ModelT]):
    """
    Base repository for tenant-scoped models.

    Every operation automatically uses the active tenant context.
    """

    def __init__(self, db: Session, model: Type[ModelT]):
        self.db = db
        self.model = model

    def get(self, object_id):
        """Get an object only if it belongs to the active tenant."""
        tenant_id = get_current_tenant_id()

        statement = (
            select(self.model)
            .where(
                self.model.id == object_id,
                self.model.tenant_id == tenant_id,
            )
        )

        return self.db.scalar(statement)

    def list(self):
        """Return only objects belonging to the active tenant."""
        tenant_id = get_current_tenant_id()

        statement = (
            select(self.model)
            .where(self.model.tenant_id == tenant_id)
        )

        return list(self.db.scalars(statement).all())

    def add(self, obj: ModelT) -> ModelT:
        """
        Add an object while enforcing the active tenant.

        The model must expose tenant_id.
        """
        tenant_id = get_current_tenant_id()

        if getattr(obj, "tenant_id", None) is not None:
            if obj.tenant_id != tenant_id:
                raise PermissionError("Tenant access denied")

        obj.tenant_id = tenant_id

        self.db.add(obj)
        self.db.flush()

        return obj
