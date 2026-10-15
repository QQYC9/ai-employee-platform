from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import BusinessBrain


class BusinessBrainService:
    """
    Service for managing a tenant's BusinessBrain.
    Enforces strict tenant isolation and validated updates.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_brain(self, tenant_id: UUID) -> BusinessBrain | None:
        """Fetch the BusinessBrain for a specific tenant."""
        statement = select(BusinessBrain).where(
            BusinessBrain.tenant_id == tenant_id,
        )
        return self.db.scalar(statement)

    def get_brain_guarded(self, requesting_tenant_id: UUID, target_tenant_id: UUID) -> BusinessBrain:
        """
        Fetch BusinessBrain with explicit cross-tenant boundary verification.
        Raises PermissionError if requesting_tenant_id does not match target_tenant_id.
        """
        if requesting_tenant_id != target_tenant_id:
            raise PermissionError("Cross-tenant access prohibited: cannot access another tenant's BusinessBrain")

        brain = self.get_brain(target_tenant_id)
        if brain is None:
            raise ValueError("BusinessBrain not found")
        return brain

    def update_brain(
        self,
        tenant_id: UUID,
        identity: dict | None = None,
        products: dict | None = None,
        services: dict | None = None,
        pricing: dict | None = None,
        brand: dict | None = None,
        customers: dict | None = None,
        competitors: dict | None = None,
        marketing: dict | None = None,
        sales: dict | None = None,
        operations: dict | None = None,
        policies: dict | None = None,
        people: dict | None = None,
        goals: dict | None = None,
        strategy: dict | None = None,
        preferences: dict | None = None,
        performance: dict | None = None,
        lessons: dict | None = None,
    ) -> BusinessBrain:
        """Update validated sections of a tenant's BusinessBrain."""
        brain = self.get_brain(tenant_id)
        if brain is None:
            raise ValueError("BusinessBrain not found")

        fields = {
            "identity": identity,
            "products": products,
            "services": services,
            "pricing": pricing,
            "brand": brand,
            "customers": customers,
            "competitors": competitors,
            "marketing": marketing,
            "sales": sales,
            "operations": operations,
            "policies": policies,
            "people": people,
            "goals": goals,
            "strategy": strategy,
            "preferences": preferences,
            "performance": performance,
            "lessons": lessons,
        }

        for field_name, value in fields.items():
            if value is not None:
                current_val = getattr(brain, field_name) or {}
                if isinstance(current_val, dict) and isinstance(value, dict):
                    updated = dict(current_val)
                    updated.update(value)
                    setattr(brain, field_name, updated)
                else:
                    setattr(brain, field_name, value)

        brain.version += 1
        self.db.flush()
        return brain

    @staticmethod
    def serialize_brain(brain: BusinessBrain) -> dict[str, Any]:
        """Serialize BusinessBrain into a safe dictionary format without exposing secrets."""
        return {
            "id": str(brain.id),
            "tenant_id": str(brain.tenant_id),
            "version": brain.version,
            "identity": brain.identity,
            "products": brain.products,
            "services": brain.services,
            "pricing": brain.pricing,
            "brand": brain.brand,
            "customers": brain.customers,
            "competitors": brain.competitors,
            "marketing": brain.marketing,
            "sales": brain.sales,
            "operations": brain.operations,
            "policies": brain.policies,
            "people": brain.people,
            "goals": brain.goals,
            "strategy": brain.strategy,
            "preferences": brain.preferences,
            "created_at": brain.created_at.isoformat() if brain.created_at else None,
            "updated_at": brain.updated_at.isoformat() if brain.updated_at else None,
        }
