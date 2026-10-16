from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.memory.sanitizer import MemorySanitizer
from packages.models.domain import BusinessBrain
from packages.services.audit_service import AuditService


class BusinessBrainService:
    """
    Service for managing a tenant's BusinessBrain.
    Enforces strict tenant isolation, secret scanning, and validated updates.
    """

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

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

    def create_brain_if_not_exists(
        self,
        tenant_id: UUID,
        initial_data: dict[str, Any] | None = None,
    ) -> BusinessBrain:
        """Create a default BusinessBrain for a tenant if it doesn't already exist."""
        existing = self.get_brain(tenant_id)
        if existing is not None:
            return existing

        initial = initial_data or {}
        for section, content in initial.items():
            if not isinstance(content, dict):
                raise ValueError(f"Section '{section}' must be a dictionary")
            MemorySanitizer.scan_dict_for_secrets(content)

        brain = BusinessBrain(
            tenant_id=tenant_id,
            identity=initial.get("identity", {}),
            products=initial.get("products", {}),
            services=initial.get("services", {}),
            pricing=initial.get("pricing", {}),
            brand=initial.get("brand", {}),
            customers=initial.get("customers", {}),
            competitors=initial.get("competitors", {}),
            marketing=initial.get("marketing", {}),
            sales=initial.get("sales", {}),
            operations=initial.get("operations", {}),
            policies=initial.get("policies", {}),
            people=initial.get("people", {}),
            goals=initial.get("goals", {}),
            strategy=initial.get("strategy", {}),
            preferences=initial.get("preferences", {}),
            performance=initial.get("performance", {}),
            lessons=initial.get("lessons", {}),
            version=1,
        )
        self.db.add(brain)
        self.db.flush()
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
        updated_by_user_id: UUID | None = None,
    ) -> BusinessBrain:
        """Update validated sections of a tenant's BusinessBrain with secret scanning."""
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

        updated_sections: list[str] = []

        for field_name, value in fields.items():
            if value is not None:
                if not isinstance(value, dict):
                    raise ValueError(f"Section '{field_name}' must be a dictionary")

                # Security guard: scan dictionary recursively for secrets/credentials
                MemorySanitizer.scan_dict_for_secrets(value)

                current_val = getattr(brain, field_name) or {}
                if isinstance(current_val, dict):
                    updated = self._deep_merge_dict(current_val, value)
                    setattr(brain, field_name, updated)
                else:
                    setattr(brain, field_name, value)
                updated_sections.append(field_name)

        brain.version += 1
        self.db.flush()

        if updated_sections:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                user_id=updated_by_user_id,
                event_type="business_brain_updated",
                action="update_brain",
                description=f"Updated BusinessBrain sections: {', '.join(updated_sections)}",
                event_metadata={
                    "sections_updated": updated_sections,
                    "version": brain.version,
                },
            )

        return brain

    @classmethod
    def _deep_merge_dict(cls, base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries to preserve nested sub-structures during partial updates."""
        result = dict(base)
        for k, v in updates.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = cls._deep_merge_dict(result[k], v)
            else:
                result[k] = v
        return result

    @staticmethod
    def serialize_brain(brain: BusinessBrain) -> dict[str, Any]:
        """Serialize BusinessBrain into a safe dictionary format without exposing secrets."""
        return {
            "id": str(brain.id),
            "tenant_id": str(brain.tenant_id),
            "version": brain.version,
            "identity": brain.identity or {},
            "products": brain.products or {},
            "services": brain.services or {},
            "pricing": brain.pricing or {},
            "brand": brain.brand or {},
            "customers": brain.customers or {},
            "competitors": brain.competitors or {},
            "marketing": brain.marketing or {},
            "sales": brain.sales or {},
            "operations": brain.operations or {},
            "policies": brain.policies or {},
            "people": brain.people or {},
            "goals": brain.goals or {},
            "strategy": brain.strategy or {},
            "preferences": brain.preferences or {},
            "performance": brain.performance or {},
            "lessons": brain.lessons or {},
            "created_at": brain.created_at.isoformat() if brain.created_at else None,
            "updated_at": brain.updated_at.isoformat() if brain.updated_at else None,
        }
