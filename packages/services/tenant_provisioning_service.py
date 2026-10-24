from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.auth.security import hash_password
from packages.models.domain import (
    ActionPolicy,
    Agent,
    AgentCapability,
    BusinessBrain,
    Capability,
    User,
)
from packages.models.tenant import Tenant

ARABIC_CHAR_MAP: dict[str, str] = {
    "أ": "a", "إ": "i", "آ": "aa", "ا": "a", "ء": "", "ؤ": "u", "ئ": "e",
    "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh",
    "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh",
    "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "ة": "h", "و": "w", "ي": "y", "ى": "a",
    "پ": "p", "چ": "ch", "ژ": "zh", "گ": "g", "ڤ": "v",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
}


def slugify_text(text: str) -> str:
    """
    Convert text (supporting Arabic and Latin) into a clean, URL-safe slug.
    Transliterates Arabic characters into Latin equivalents and normalizes separators.
    """
    if not text:
        return ""
    chars: list[str] = []
    for ch in text.lower():
        if ch in ARABIC_CHAR_MAP:
            chars.append(ARABIC_CHAR_MAP[ch])
        else:
            chars.append(ch)
    joined = "".join(chars)
    cleaned = re.sub(r"[^a-z0-9]+", "-", joined)
    return re.sub(r"-+", "-", cleaned).strip("-")



class BusinessBrainInput(BaseModel):
    industry: str | None = None
    products: list[Any] | dict | None = None
    services: list[Any] | dict | None = None
    pricing: dict | None = None
    brand: dict | None = None
    target_customers: list[Any] | dict | None = None
    competitors: list[Any] | dict | None = None
    business_objectives: list[str] | dict | None = None
    operating_rules: list[str] | dict | None = None
    communication_preferences: dict | None = None


class InitialAgentInput(BaseModel):
    name: str | None = None
    agent_type: str = "main"
    system_config: dict = Field(default_factory=dict)
    capability_ids: list[UUID] = Field(default_factory=list)


class ActionPolicyInput(BaseModel):
    action: str = Field(min_length=1)
    resource: str | None = None
    requires_approval: bool = True
    approval_for: str = "tenant_owner"
    conditions: dict = Field(default_factory=dict)


class TenantProvisioningRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=100)
    owner_name: str = Field(min_length=1, max_length=255)
    owner_email: str = Field(min_length=3, max_length=320)
    owner_password: str = Field(min_length=8)
    business_brain: BusinessBrainInput | None = None
    agent: InitialAgentInput | None = None
    default_action_policies: list[ActionPolicyInput] | None = None


class TenantProvisioningResponse(BaseModel):
    status: str
    tenant: dict[str, Any]
    owner: dict[str, Any]
    agent: dict[str, Any]
    business_brain: dict[str, Any]
    assigned_capabilities: list[dict[str, Any]]
    action_policies: list[dict[str, Any]]


class TenantProvisioningService:
    """
    Orchestrates atomic provisioning of a new SaaS tenant, its initial owner,
    configured BusinessBrain, initial Digital Employee, assigned capabilities,
    and safe default action policies.
    """

    def __init__(self, db: Session):
        self.db = db

    def provision_tenant(
        self,
        request: TenantProvisioningRequest,
    ) -> dict[str, Any]:
        """
        Atomically provision a tenant and all related initial artifacts.
        Rolls back completely if any validation or DB operation fails.
        """
        # 1. Validation & Sanitization
        clean_name = request.name.strip()
        if not clean_name:
            raise ValueError("Tenant name cannot be empty")

        clean_owner_name = request.owner_name.strip()
        if not clean_owner_name:
            raise ValueError("Owner name cannot be empty")

        clean_email = request.owner_email.strip().lower()
        if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
            raise ValueError(f"Invalid email format: '{clean_email}'")

        if len(request.owner_password) < 8:
            raise ValueError("Owner password must be at least 8 characters")

        # Uniqueness check for email
        existing_user = self.db.scalar(
            select(User).where(func.lower(User.email) == clean_email)
        )
        if existing_user is not None:
            raise ValueError(f"Email '{clean_email}' is already registered")

        # Slug generation & uniqueness check
        if request.slug and request.slug.strip():
            slug = slugify_text(request.slug)
            if not slug:
                raise ValueError("Invalid tenant slug")
            if len(slug) > 100:
                slug = slug[:100].rstrip("-")
            existing_tenant = self.db.scalar(
                select(Tenant).where(Tenant.slug == slug)
            )
            if existing_tenant is not None:
                raise ValueError(f"Tenant slug '{slug}' already exists")
        else:
            base_slug = slugify_text(clean_name)
            if not base_slug:
                base_slug = "tenant"
            base_prefix = base_slug[:80].rstrip("-")
            if not base_prefix:
                base_prefix = "tenant"

            for _ in range(5):
                candidate_slug = f"{base_prefix}-{uuid4().hex[:8]}"
                existing_tenant = self.db.scalar(
                    select(Tenant).where(Tenant.slug == candidate_slug)
                )
                if existing_tenant is None:
                    slug = candidate_slug
                    break
            else:
                slug = f"tenant-{uuid4().hex}"[:100]

        # Capabilities validation: ensure only global or tenant-approved capabilities are assigned
        agent_input = request.agent or InitialAgentInput()
        capabilities_to_attach: list[Capability] = []
        if agent_input.capability_ids:
            for cap_id in agent_input.capability_ids:
                cap = self.db.scalar(
                    select(Capability).where(
                        Capability.id == cap_id,
                        Capability.is_active.is_(True),
                    )
                )
                if cap is None:
                    raise ValueError(f"Capability '{cap_id}' not found or inactive")

                # Cross-tenant capability security rule:
                # Can only assign global capabilities (tenant_id is None).
                # Cannot assign private capabilities belonging to other tenants.
                if cap.tenant_id is not None:
                    raise PermissionError(
                        f"Cross-tenant capability assignment prohibited: capability '{cap.name}' ({cap.id}) belongs to another tenant"
                    )
                capabilities_to_attach.append(cap)

        # 2. Atomic Database Execution with Savepoint
        sp = self.db.begin_nested()
        try:
            # Step A: Create Tenant
            tenant = Tenant(
                name=clean_name,
                slug=slug,
                status="active",
            )
            self.db.add(tenant)
            self.db.flush()

            # Step B: Create Tenant Owner User (hashed password, role='tenant_owner')
            owner_pwd_hash = hash_password(request.owner_password)
            owner = User(
                tenant_id=tenant.id,
                name=clean_owner_name,
                email=clean_email,
                role="tenant_owner",
                status="active",
                password_hash=owner_pwd_hash,
            )
            self.db.add(owner)
            self.db.flush()

            # Step C: Initialize BusinessBrain
            bb = request.business_brain or BusinessBrainInput()
            identity_data: dict[str, Any] = {"name": tenant.name}
            if bb.industry:
                identity_data["industry"] = bb.industry.strip()

            products_data = (
                {"items": bb.products}
                if isinstance(bb.products, list)
                else (bb.products or {})
            )
            services_data = (
                {"items": bb.services}
                if isinstance(bb.services, list)
                else (bb.services or {})
            )
            customers_data = (
                {"target_segments": bb.target_customers}
                if isinstance(bb.target_customers, list)
                else (bb.target_customers or {})
            )
            competitors_data = (
                {"items": bb.competitors}
                if isinstance(bb.competitors, list)
                else (bb.competitors or {})
            )
            goals_data = (
                {"objectives": bb.business_objectives}
                if isinstance(bb.business_objectives, list)
                else (bb.business_objectives or {})
            )
            policies_data = (
                {"operating_rules": bb.operating_rules}
                if isinstance(bb.operating_rules, list)
                else (bb.operating_rules or {})
            )

            business_brain = BusinessBrain(
                tenant_id=tenant.id,
                identity=identity_data,
                products=products_data,
                services=services_data,
                pricing=bb.pricing or {},
                brand=bb.brand or {},
                customers=customers_data,
                competitors=competitors_data,
                goals=goals_data,
                policies=policies_data,
                preferences=bb.communication_preferences or {},
                version=1,
            )
            self.db.add(business_brain)
            self.db.flush()

            # Step D: Create Initial Digital Employee (Agent)
            agent_name = (
                agent_input.name.strip()
                if agent_input.name and agent_input.name.strip()
                else f"{clean_name} Digital Employee"
            )
            agent_type = (
                agent_input.agent_type.strip()
                if agent_input.agent_type and agent_input.agent_type.strip()
                else "main"
            )

            agent = Agent(
                tenant_id=tenant.id,
                name=agent_name,
                agent_type=agent_type,
                status="active",
                system_config=agent_input.system_config or {},
            )
            self.db.add(agent)
            self.db.flush()

            # Step E: Attach Validated Capabilities
            assigned_caps = []
            for cap in capabilities_to_attach:
                agent_cap = AgentCapability(
                    tenant_id=tenant.id,
                    agent_id=agent.id,
                    capability_id=cap.id,
                    config={},
                )
                self.db.add(agent_cap)
                assigned_caps.append({
                    "id": str(cap.id),
                    "name": cap.name,
                    "slug": cap.slug,
                })
            if assigned_caps:
                self.db.flush()

            # Step F: Configure Safe Default Action Policies
            created_policies = []
            if request.default_action_policies is not None:
                policy_defs = [
                    p.model_dump() if hasattr(p, "model_dump") else p.dict()
                    for p in request.default_action_policies
                ]
            else:
                policy_defs = [
                    {
                        "action": "external_payment",
                        "resource": "finance",
                        "requires_approval": True,
                        "approval_for": "tenant_owner",
                    },
                    {
                        "action": "data_deletion",
                        "resource": "database",
                        "requires_approval": True,
                        "approval_for": "tenant_owner",
                    },
                    {
                        "action": "customer_broadcast",
                        "resource": "messaging",
                        "requires_approval": True,
                        "approval_for": "tenant_owner",
                    },
                ]

            for p_def in policy_defs:
                act = p_def["action"].strip()
                if not act:
                    continue
                pol = ActionPolicy(
                    tenant_id=tenant.id,
                    action=act,
                    resource=p_def.get("resource"),
                    requires_approval=p_def.get("requires_approval", True),
                    approval_for=p_def.get("approval_for", "tenant_owner"),
                    conditions=p_def.get("conditions", {}),
                    is_active=True,
                )
                self.db.add(pol)
                created_policies.append({
                    "action": pol.action,
                    "resource": pol.resource,
                    "requires_approval": pol.requires_approval,
                    "approval_for": pol.approval_for,
                })
            self.db.flush()

            # Commit savepoint and top-level transaction
            sp.commit()
            self.db.commit()

            self.db.refresh(tenant)
            self.db.refresh(owner)
            self.db.refresh(agent)
            self.db.refresh(business_brain)

            return {
                "status": "provisioned",
                "tenant": {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "status": tenant.status,
                    "created_at": (
                        tenant.created_at.isoformat()
                        if tenant.created_at
                        else None
                    ),
                },
                "owner": {
                    "id": str(owner.id),
                    "name": owner.name,
                    "email": owner.email,
                    "role": owner.role,
                    "status": owner.status,
                },
                "agent": {
                    "id": str(agent.id),
                    "name": agent.name,
                    "agent_type": agent.agent_type,
                    "status": agent.status,
                },
                "business_brain": {
                    "id": str(business_brain.id),
                    "version": business_brain.version,
                    "industry": business_brain.identity.get("industry")
                    if isinstance(business_brain.identity, dict)
                    else None,
                    "sections_initialized": [
                        k
                        for k in [
                            "identity",
                            "products",
                            "services",
                            "pricing",
                            "brand",
                            "customers",
                            "competitors",
                            "goals",
                            "policies",
                            "preferences",
                        ]
                        if getattr(business_brain, k, None)
                    ],
                },
                "assigned_capabilities": assigned_caps,
                "action_policies": created_policies,
            }

        except Exception:
            sp.rollback()
            self.db.rollback()
            raise
