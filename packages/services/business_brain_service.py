from __future__ import annotations

from typing import Any
from uuid import UUID
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.memory.sanitizer import MemorySanitizer
from packages.models.domain import BusinessBrain
from packages.models.tenant import Tenant
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

    def get_or_create_brain(self, tenant_id: UUID) -> BusinessBrain:
        """Alias for create_brain_if_not_exists."""
        return self.create_brain_if_not_exists(tenant_id)

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
        replace_sections: list[str] | set[str] | None = None,
    ) -> BusinessBrain:
        """Update validated sections of a tenant's BusinessBrain with secret scanning."""
        from sqlalchemy.orm.attributes import flag_modified

        brain = self.create_brain_if_not_exists(tenant_id)

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
        replace_set = set(replace_sections or [])

        for field_name, value in fields.items():
            if value is not None:
                if not isinstance(value, dict):
                    raise ValueError(f"Section '{field_name}' must be a dictionary")

                # Security guard: scan dictionary recursively for secrets/credentials
                MemorySanitizer.scan_dict_for_secrets(value)

                current_val = getattr(brain, field_name) or {}
                if field_name in replace_set:
                    # Full section replacement requested
                    setattr(brain, field_name, dict(value))
                elif isinstance(current_val, dict):
                    updated = self._deep_merge_dict(current_val, value)
                    setattr(brain, field_name, updated)
                else:
                    setattr(brain, field_name, value)

                flag_modified(brain, field_name)
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

    def get_profile(self, tenant_id: UUID) -> dict[str, Any]:
        """Fetch unified business profile for a tenant."""
        statement = select(Tenant).where(
            Tenant.id == tenant_id,
            Tenant.status == "active",
        )
        tenant = self.db.scalar(statement)
        if tenant is None:
            raise ValueError(f"Active tenant '{tenant_id}' not found")

        brain = self.create_brain_if_not_exists(tenant_id)
        identity = brain.identity or {}
        commercial_name = identity.get("commercial_name") or tenant.name

        return {
            "tenant_id": str(tenant_id),
            "commercial_name": commercial_name,
            "legal_name": identity.get("legal_name"),
            "business_type": identity.get("business_type"),
            "description": identity.get("description"),
            "contact": identity.get("contact", {}),
            "address": identity.get("address", {}),
            "operating_hours": identity.get("operating_hours", {}),
            "products": brain.products or {},
            "services": brain.services or {},
            "pricing": brain.pricing or {},
            "policies": brain.policies or {},
            "operations": brain.operations or {},
            "version": brain.version,
            "updated_at": brain.updated_at.isoformat() if brain.updated_at else None,
        }

    def update_profile(
        self,
        tenant_id: UUID,
        profile_data: dict[str, Any],
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """
        Update unified business profile for a tenant with strict validation,
        secret scanning, and audit logging. Synchronizes commercial_name with Tenant.name.
        """
        from sqlalchemy.orm.attributes import flag_modified

        statement = select(Tenant).where(
            Tenant.id == tenant_id,
            Tenant.status == "active",
        )
        tenant = self.db.scalar(statement)
        if tenant is None:
            raise ValueError(f"Active tenant '{tenant_id}' not found")

        # 1. Secret scanning across the entire input payload
        MemorySanitizer.scan_dict_for_secrets(profile_data)

        brain = self.create_brain_if_not_exists(tenant_id)
        updated_sections: list[str] = []

        # 2. Commercial name synchronization with Tenant model
        commercial_name = profile_data.get("commercial_name")
        if commercial_name is not None:
            commercial_name = commercial_name.strip()
            if not commercial_name:
                raise ValueError("Commercial name cannot be empty")
            tenant.name = commercial_name

        # 3. Identity attributes
        identity_fields = [
            "legal_name",
            "business_type",
            "description",
            "contact",
            "address",
            "operating_hours",
        ]
        current_identity = dict(brain.identity or {})
        has_identity_updates = False

        if commercial_name is not None:
            current_identity["commercial_name"] = commercial_name
            has_identity_updates = True

        for field in identity_fields:
            if field in profile_data and profile_data[field] is not None:
                val = profile_data[field]
                if isinstance(val, dict) and isinstance(current_identity.get(field), dict):
                    current_identity[field] = self._deep_merge_dict(current_identity[field], val)
                else:
                    current_identity[field] = val
                has_identity_updates = True

        if has_identity_updates:
            brain.identity = current_identity
            flag_modified(brain, "identity")
            updated_sections.append("identity")

        # 4. Direct domain sections
        direct_sections = ["products", "services", "pricing", "policies", "operations"]
        for section in direct_sections:
            if section in profile_data and profile_data[section] is not None:
                val = profile_data[section]
                if isinstance(val, list):
                    normalized_dict = {}
                    for idx, item in enumerate(val):
                        if isinstance(item, dict):
                            name = item.get("name") or f"item_{idx+1}"
                            slug = (
                                item.get("slug")
                                or re.sub(r"[^\w]+", "_", str(name)).strip("_").lower()
                                or f"{section}_{idx+1}"
                            )
                            normalized_dict[slug] = item
                        else:
                            normalized_dict[str(idx)] = item
                    val = normalized_dict

                if not isinstance(val, dict):
                    raise ValueError(f"Section '{section}' must be a dictionary or list")

                current_val = getattr(brain, section) or {}
                if isinstance(current_val, dict):
                    updated = self._deep_merge_dict(current_val, val)
                    setattr(brain, section, updated)
                else:
                    setattr(brain, section, val)

                flag_modified(brain, section)
                updated_sections.append(section)

        brain.version += 1
        self.db.flush()

        if updated_sections:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type="business_profile_updated",
                action="update_profile",
                description=f"Updated business profile sections: {', '.join(updated_sections)}",
                event_metadata={
                    "sections_updated": updated_sections,
                    "version": brain.version,
                },
            )

        return self.get_profile(tenant_id)

    def get_catalog(self, tenant_id: UUID) -> dict[str, Any]:
        """Fetch catalog components (products, services, pricing) for a tenant."""
        brain = self.create_brain_if_not_exists(tenant_id)
        return {
            "tenant_id": str(tenant_id),
            "products": brain.products or {},
            "services": brain.services or {},
            "pricing": brain.pricing or {},
            "version": brain.version,
        }

    def update_catalog(
        self,
        tenant_id: UUID,
        products: Any = None,
        services: Any = None,
        pricing: Any = None,
        replace_all: bool = False,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Update catalog components with secret scanning and versioning."""
        from sqlalchemy.orm.attributes import flag_modified

        payload = {}
        if products is not None:
            payload["products"] = products
        if services is not None:
            payload["services"] = services
        if pricing is not None:
            payload["pricing"] = pricing

        MemorySanitizer.scan_dict_for_secrets(payload)

        brain = self.create_brain_if_not_exists(tenant_id)
        updated_sections = []

        for key, raw_val in payload.items():
            val = raw_val
            if isinstance(val, list):
                normalized = {}
                for idx, item in enumerate(val):
                    if isinstance(item, dict):
                        name = item.get("name") or f"item_{idx+1}"
                        slug = (
                            item.get("slug")
                            or re.sub(r"[^\w]+", "_", str(name)).strip("_").lower()
                            or f"{key}_{idx+1}"
                        )
                        normalized[slug] = item
                    else:
                        normalized[str(idx)] = item
                val = normalized

            if not isinstance(val, dict):
                raise ValueError(f"Field '{key}' must be a dictionary or list")

            if replace_all:
                setattr(brain, key, dict(val))
            else:
                current_val = getattr(brain, key) or {}
                if isinstance(current_val, dict):
                    setattr(brain, key, self._deep_merge_dict(current_val, val))
                else:
                    setattr(brain, key, val)

            flag_modified(brain, key)
            updated_sections.append(key)

        brain.version += 1
        self.db.flush()

        if updated_sections:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type="business_catalog_updated",
                action="update_catalog",
                description=f"Updated catalog sections: {', '.join(updated_sections)}",
                event_metadata={
                    "sections": updated_sections,
                    "replace_all": replace_all,
                    "version": brain.version,
                },
            )

        return self.get_catalog(tenant_id)

    def get_policies(self, tenant_id: UUID) -> dict[str, Any]:
        """Fetch business policies (delivery, returns, exchange, payment, etc.)."""
        brain = self.create_brain_if_not_exists(tenant_id)
        return {
            "tenant_id": str(tenant_id),
            "policies": brain.policies or {},
            "version": brain.version,
        }

    def update_policies(
        self,
        tenant_id: UUID,
        policies: dict[str, Any],
        replace_all: bool = False,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Update business policies with secret scanning and versioning."""
        from sqlalchemy.orm.attributes import flag_modified

        if not isinstance(policies, dict):
            raise ValueError("Policies must be a dictionary")

        MemorySanitizer.scan_dict_for_secrets(policies)

        brain = self.create_brain_if_not_exists(tenant_id)
        if replace_all:
            brain.policies = dict(policies)
        else:
            current_policies = brain.policies or {}
            if isinstance(current_policies, dict):
                brain.policies = self._deep_merge_dict(current_policies, policies)
            else:
                brain.policies = dict(policies)

        flag_modified(brain, "policies")
        brain.version += 1
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="business_policies_updated",
            action="update_policies",
            description="Updated business policies",
            event_metadata={
                "replace_all": replace_all,
                "version": brain.version,
            },
        )

        return self.get_policies(tenant_id)
