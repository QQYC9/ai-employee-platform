from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.auth.rate_limiter import rate_limiter
from packages.auth.security import hash_password, verify_password
from packages.context.retriever import ContextRetriever
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import (
    ActionPolicy,
    Agent,
    AgentCapability,
    BusinessBrain,
    Capability,
    Knowledge,
    Memory,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.services.business_brain_service import BusinessBrainService
from packages.services.tenant_provisioning_service import (
    BusinessBrainInput,
    InitialAgentInput,
    TenantProvisioningRequest,
    TenantProvisioningService,
    slugify_text,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter_and_settings():
    """Ensure clean state before and after each test."""
    rate_limiter.reset()
    original_env = settings.environment
    original_allow = settings.allow_dev_auth_header
    original_jwt_key = settings.jwt_secret_key
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    yield
    rate_limiter.reset()
    settings.environment = original_env
    settings.allow_dev_auth_header = original_allow
    settings.jwt_secret_key = original_jwt_key


def create_user_with_role(
    role: str = "platform_admin",
    name: str = "Admin User",
    tenant_id=None,
) -> tuple[User, str]:
    """Helper to create a user and return (user, bearer_token)."""
    db = SessionLocal()
    user = User(
        tenant_id=tenant_id,
        name=name,
        email=f"user-{uuid4().hex[:8]}@example.com",
        role=role,
        status="active",
        password_hash=hash_password("StrongPassword123!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    token = create_access_token(user.id, user.tenant_id, user.role)
    return user, token


def create_global_capability(name: str = "Global Analytics") -> Capability:
    """Helper to create an active global capability (tenant_id=None)."""
    db = SessionLocal()
    cap = Capability(
        tenant_id=None,
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        description="Global system capability",
        config={},
        is_active=True,
    )
    db.add(cap)
    db.commit()
    db.refresh(cap)
    db.close()
    return cap


# =========================================================================
# 1. Successful Tenant Provisioning Tests
# =========================================================================

def test_successful_tenant_provisioning_full_payload():
    client = TestClient(app)
    admin_user, admin_token = create_user_with_role(role="platform_admin")
    global_cap = create_global_capability("Market Research")

    unique_email = f"owner-{uuid4().hex[:8]}@acme.com"
    payload = {
        "name": "Acme Innovations Inc",
        "slug": f"acme-innovations-{uuid4().hex[:6]}",
        "owner_name": "Alice Johnson",
        "owner_email": unique_email,
        "owner_password": "SecurePassword123!",
        "business_brain": {
            "industry": "Artificial Intelligence SaaS",
            "products": ["AI Knowledge Assistant", "Automated Scheduler"],
            "services": ["Enterprise Agent Onboarding", "Custom Integrations"],
            "pricing": {"tier": "enterprise", "currency": "USD", "annual": True},
            "brand": {"voice": "Professional, authoritative, helpful"},
            "target_customers": ["B2B SaaS companies", "Enterprise operations teams"],
            "competitors": ["Legacy CRM bots", "Basic automation scripts"],
            "business_objectives": ["Automate 80% of support queries", "Increase lead conversion"],
            "operating_rules": ["Never promise discounts over 15%", "Escalate refunds to human"],
            "communication_preferences": {"tone": "concise", "language": "en"},
        },
        "agent": {
            "name": "Acme Lead Operations Agent",
            "agent_type": "main",
            "system_config": {"model": "gemini-2.5-flash", "temperature": 0.2},
            "capability_ids": [str(global_cap.id)],
        },
        "default_action_policies": [
            {
                "action": "execute_refund",
                "resource": "billing",
                "requires_approval": True,
                "approval_for": "tenant_owner",
            },
            {
                "action": "send_customer_email",
                "resource": "crm",
                "requires_approval": False,
                "approval_for": "tenant_owner",
            },
        ],
    }

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=payload,
    )

    assert res.status_code == 201, res.text
    data = res.json()

    assert data["status"] == "provisioned"
    assert data["tenant"]["name"] == "Acme Innovations Inc"
    assert data["tenant"]["status"] == "active"
    assert "id" in data["tenant"]

    # Verify Owner
    assert data["owner"]["name"] == "Alice Johnson"
    assert data["owner"]["email"] == unique_email
    assert data["owner"]["role"] == "tenant_owner"
    assert "password_hash" not in data["owner"]

    # Verify Agent
    assert data["agent"]["name"] == "Acme Lead Operations Agent"
    assert data["agent"]["agent_type"] == "main"
    assert data["agent"]["status"] == "active"

    # Verify BusinessBrain
    assert data["business_brain"]["industry"] == "Artificial Intelligence SaaS"
    assert "identity" in data["business_brain"]["sections_initialized"]
    assert "products" in data["business_brain"]["sections_initialized"]

    # Verify Capabilities & Policies
    assert len(data["assigned_capabilities"]) == 1
    assert data["assigned_capabilities"][0]["name"] == "Market Research"
    assert len(data["action_policies"]) == 2

    # Verify Database State
    db = SessionLocal()
    tenant_id = data["tenant"]["id"]
    db_tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    assert db_tenant is not None

    db_owner = db.query(User).filter(User.email == unique_email).first()
    assert db_owner is not None
    assert db_owner.tenant_id == db_tenant.id
    assert verify_password("SecurePassword123!", db_owner.password_hash) is True

    db_brain = db.query(BusinessBrain).filter(BusinessBrain.tenant_id == tenant_id).first()
    assert db_brain is not None
    assert db_brain.identity["industry"] == "Artificial Intelligence SaaS"
    assert db_brain.products["items"] == ["AI Knowledge Assistant", "Automated Scheduler"]

    db_agent = db.query(Agent).filter(Agent.tenant_id == tenant_id).first()
    assert db_agent is not None
    assert db_agent.name == "Acme Lead Operations Agent"

    db.close()


def test_successful_tenant_provisioning_minimal_payload():
    client = TestClient(app)
    admin_user, admin_token = create_user_with_role(role="platform_admin")

    unique_email = f"minimal-{uuid4().hex[:8]}@startup.io"
    payload = {
        "name": "Lean Startup Co",
        "owner_name": "Bob Vance",
        "owner_email": unique_email,
        "owner_password": "MinimumPassword123!",
    }

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=payload,
    )

    assert res.status_code == 201, res.text
    data = res.json()

    assert data["status"] == "provisioned"
    assert data["tenant"]["name"] == "Lean Startup Co"
    # Agent default name applied
    assert "Lean Startup Co" in data["agent"]["name"]
    # Safe default action policies applied
    policy_actions = [p["action"] for p in data["action_policies"]]
    assert "external_payment" in policy_actions
    assert "data_deletion" in policy_actions
    assert "customer_broadcast" in policy_actions


# =========================================================================
# 2. Validation & Duplicate Handling Tests
# =========================================================================

def test_provisioning_empty_tenant_name():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "   ",
            "owner_name": "Test Owner",
            "owner_email": f"test-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res.status_code == 400
    assert "cannot be empty" in res.json()["detail"].lower()


def test_provisioning_invalid_email_format():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Valid Tenant",
            "owner_name": "Test Owner",
            "owner_email": "invalid-email-address-without-at",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res.status_code == 400
    assert "invalid email format" in res.json()["detail"].lower()


def test_provisioning_short_password():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Valid Tenant",
            "owner_name": "Test Owner",
            "owner_email": f"test-{uuid4().hex[:6]}@example.com",
            "owner_password": "short",
        },
    )
    assert res.status_code == 422


def test_provisioning_duplicate_owner_email():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    # Create first tenant with an email
    dup_email = f"dup-{uuid4().hex[:8]}@example.com"
    client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "First Tenant",
            "owner_name": "First Owner",
            "owner_email": dup_email,
            "owner_password": "Password123!",
        },
    )

    # Attempt second tenant with same owner email
    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Second Tenant",
            "owner_name": "Second Owner",
            "owner_email": dup_email,
            "owner_password": "Password123!",
        },
    )
    assert res.status_code == 400
    assert "already registered" in res.json()["detail"]


def test_provisioning_duplicate_slug_rejected():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    fixed_slug = f"fixed-slug-{uuid4().hex[:6]}"
    res1 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Company One",
            "slug": fixed_slug,
            "owner_name": "Owner One",
            "owner_email": f"o1-{uuid4().hex[:6]}@example.com",
            "owner_password": "Password123!",
        },
    )
    assert res1.status_code == 201

    res2 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Company Two",
            "slug": fixed_slug,
            "owner_name": "Owner Two",
            "owner_email": f"o2-{uuid4().hex[:6]}@example.com",
            "owner_password": "Password123!",
        },
    )
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


# =========================================================================
# 3. Authorization & Role Checks Tests
# =========================================================================

def test_unauthenticated_provisioning_rejected():
    client = TestClient(app)
    res = client.post(
        "/api/v1/tenants/provision",
        json={
            "name": "Unauthorized Co",
            "owner_name": "Hacker",
            "owner_email": "hacker@example.com",
            "owner_password": "Password123!",
        },
    )
    assert res.status_code == 401
    assert "Authentication required" in res.json()["detail"]


def test_regular_tenant_user_cannot_provision_tenant():
    client = TestClient(app)
    _, member_token = create_user_with_role(role="tenant_user")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {member_token}"},
        json={
            "name": "Rogue Tenant",
            "owner_name": "Rogue Owner",
            "owner_email": f"rogue-{uuid4().hex[:6]}@example.com",
            "owner_password": "Password123!",
        },
    )
    assert res.status_code == 403
    assert "lacks platform administration privileges" in res.json()["detail"]


def test_tenant_owner_cannot_provision_new_tenants():
    client = TestClient(app)
    _, owner_token = create_user_with_role(role="tenant_owner")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "name": "Another Tenant",
            "owner_name": "Owner",
            "owner_email": f"owner-{uuid4().hex[:6]}@example.com",
            "owner_password": "Password123!",
        },
    )
    assert res.status_code == 403
    assert "lacks platform administration privileges" in res.json()["detail"]


# =========================================================================
# 4. Multi-Tenant Isolation & Anti-Tampering Tests
# =========================================================================

def test_provisioning_blocks_assigning_another_tenant_private_capability():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    # Create Tenant B and a private capability belonging strictly to Tenant B
    db = SessionLocal()
    tenant_b = Tenant(name="Tenant B", slug=f"tenant-b-{uuid4().hex[:6]}", status="active")
    db.add(tenant_b)
    db.flush()

    private_cap = Capability(
        tenant_id=tenant_b.id,
        name="Tenant B Proprietary Tool",
        slug=f"prop-tool-{uuid4().hex[:6]}",
        description="Private capability",
        is_active=True,
    )
    db.add(private_cap)
    db.commit()
    private_cap_id = private_cap.id
    db.close()

    # Now attempt to provision Tenant C and illegitimately assign Tenant B's private capability
    new_tenant_email = f"tenant-c-{uuid4().hex[:6]}@example.com"
    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Tenant C",
            "owner_name": "Tenant C Owner",
            "owner_email": new_tenant_email,
            "owner_password": "Password123!",
            "agent": {
                "name": "Tenant C Agent",
                "capability_ids": [str(private_cap_id)],
            },
        },
    )

    # Must be 403 Forbidden with clear cross-tenant prohibition
    assert res.status_code == 403
    assert "Cross-tenant capability assignment prohibited" in res.json()["detail"]

    # Verify atomic rollback: Tenant C must NOT exist in DB
    db = SessionLocal()
    c_user = db.query(User).filter(User.email == new_tenant_email).first()
    assert c_user is None
    c_tenant = db.query(Tenant).filter(Tenant.name == "Tenant C").first()
    assert c_tenant is None
    db.close()


def test_tenant_cannot_read_another_tenant_business_brain():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    # Provision Tenant 1
    t1_email = f"t1-{uuid4().hex[:6]}@example.com"
    res1 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Alpha Corp",
            "owner_name": "Alpha Owner",
            "owner_email": t1_email,
            "owner_password": "Password123!",
            "business_brain": {"industry": "Aerospace"},
        },
    )
    t1_id = res1.json()["tenant"]["id"]
    t1_owner_id = res1.json()["owner"]["id"]

    # Provision Tenant 2
    t2_email = f"t2-{uuid4().hex[:6]}@example.com"
    res2 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Beta Corp",
            "owner_name": "Beta Owner",
            "owner_email": t2_email,
            "owner_password": "Password123!",
            "business_brain": {"industry": "Biotechnology"},
        },
    )
    t2_id = res2.json()["tenant"]["id"]
    t2_owner_id = res2.json()["owner"]["id"]

    # Authenticate as Tenant 1 Owner
    t1_token = create_access_token(t1_owner_id, t1_id, "tenant_owner")

    # Read my own brain via API
    res_brain = client.get(
        "/api/v1/tenants/me/brain",
        headers={"Authorization": f"Bearer {t1_token}"},
    )
    assert res_brain.status_code == 200
    assert res_brain.json()["tenant_id"] == t1_id
    assert res_brain.json()["identity"]["industry"] == "Aerospace"

    # Verify service-level cross-tenant guard raises PermissionError
    db = SessionLocal()
    brain_service = BusinessBrainService(db)
    with pytest.raises(PermissionError) as exc_info:
        brain_service.get_brain_guarded(
            requesting_tenant_id=t1_id,
            target_tenant_id=t2_id,
        )
    assert "Cross-tenant access prohibited" in str(exc_info.value)
    db.close()


def test_tenant_cannot_read_another_tenant_agent():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res1 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Company Alpha",
            "owner_name": "Owner A",
            "owner_email": f"a-{uuid4().hex[:6]}@example.com",
            "owner_password": "Password123!",
        },
    )
    t1_id = res1.json()["tenant"]["id"]
    t1_owner_id = res1.json()["owner"]["id"]
    agent1_id = res1.json()["agent"]["id"]

    res2 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Company Beta",
            "owner_name": "Owner B",
            "owner_email": f"b-{uuid4().hex[:6]}@example.com",
            "owner_password": "Password123!",
        },
    )
    t2_id = res2.json()["tenant"]["id"]
    t2_owner_id = res2.json()["owner"]["id"]

    # Tenant 2 Owner attempts to access Tenant 1's Agent by ID
    t2_token = create_access_token(t2_owner_id, t2_id, "tenant_owner")
    res = client.get(
        f"/api/v1/agents/{agent1_id}",
        headers={"Authorization": f"Bearer {t2_token}"},
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Agent not found"


def test_tenant_cannot_read_another_tenant_memory_or_knowledge():
    db = SessionLocal()
    tenant_a = Tenant(name="Tenant M1", slug=f"t-m1-{uuid4().hex[:6]}", status="active")
    tenant_b = Tenant(name="Tenant M2", slug=f"t-m2-{uuid4().hex[:6]}", status="active")
    db.add_all([tenant_a, tenant_b])
    db.flush()

    # Create Memory & Knowledge for Tenant A
    mem_a = Memory(
        tenant_id=tenant_a.id,
        content="Confidential financial forecast for Tenant A",
        memory_type="business_rule",
        status="active",
    )
    know_a = Knowledge(
        tenant_id=tenant_a.id,
        title="Internal Architecture Document",
        content="Secret formulas and architecture",
        status="active",
    )
    db.add_all([mem_a, know_a])
    db.commit()

    # Query using ContextRetriever for Tenant B
    retriever = ContextRetriever(db)
    mems_b = retriever.get_memories(tenant_id=tenant_b.id)
    assert len(mems_b) == 0, "Tenant B must not retrieve Tenant A's memories!"

    knows_b = retriever.get_knowledge(tenant_id=tenant_b.id, query="Architecture")
    assert len(knows_b) == 0, "Tenant B must not retrieve Tenant A's knowledge!"
    db.close()


# =========================================================================
# 5. BusinessBrain Update & Role Checks Tests
# =========================================================================

def test_business_brain_update_by_tenant_owner():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Dynamic Retail",
            "owner_name": "Retail Owner",
            "owner_email": f"ret-{uuid4().hex[:6]}@retail.com",
            "owner_password": "Password123!",
            "business_brain": {"industry": "Retail"},
        },
    )
    tenant_id = res.json()["tenant"]["id"]
    owner_id = res.json()["owner"]["id"]

    owner_token = create_access_token(owner_id, tenant_id, "tenant_owner")

    # Update BusinessBrain
    patch_res = client.patch(
        "/api/v1/tenants/me/brain",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "products": {"catalog": ["Shoe A", "Jacket B"]},
            "policies": {"returns": "30 days with receipt"},
        },
    )
    assert patch_res.status_code == 200
    updated_brain = patch_res.json()
    assert updated_brain["version"] == 2
    assert updated_brain["products"]["catalog"] == ["Shoe A", "Jacket B"]
    assert updated_brain["policies"]["returns"] == "30 days with receipt"


def test_business_brain_update_blocked_for_regular_user():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Secured Org",
            "owner_name": "Org Owner",
            "owner_email": f"sec-{uuid4().hex[:6]}@sec.com",
            "owner_password": "Password123!",
        },
    )
    tenant_id = res.json()["tenant"]["id"]

    # Create a regular tenant user inside this tenant
    db = SessionLocal()
    reg_user = User(
        tenant_id=tenant_id,
        name="Regular Employee",
        email=f"emp-{uuid4().hex[:6]}@sec.com",
        role="tenant_user",
        status="active",
        password_hash=hash_password("Password123!"),
    )
    db.add(reg_user)
    db.commit()
    db.refresh(reg_user)
    db.close()

    emp_token = create_access_token(reg_user.id, tenant_id, "tenant_user")

    # Attempt to modify BusinessBrain
    patch_res = client.patch(
        "/api/v1/tenants/me/brain",
        headers={"Authorization": f"Bearer {emp_token}"},
        json={"pricing": {"tier": "free"}},
    )
    assert patch_res.status_code == 403
    assert "Only tenant owners or administrators" in patch_res.json()["detail"]


# =========================================================================
# 6. Initial Agent Tool Execution & Capability Assignment
# =========================================================================

def test_initial_agent_capability_assignment_and_tool_isolation():
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    global_cap = create_global_capability("Public Reporting")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Verified Operations",
            "owner_name": "Ops Owner",
            "owner_email": f"ops-{uuid4().hex[:6]}@ops.com",
            "owner_password": "Password123!",
            "agent": {
                "name": "Ops Bot",
                "capability_ids": [str(global_cap.id)],
            },
        },
    )
    assert res.status_code == 201
    tenant_id = res.json()["tenant"]["id"]
    agent_id = res.json()["agent"]["id"]

    # Verify agent capabilities in DB
    db = SessionLocal()
    agent_caps = db.query(AgentCapability).filter(
        AgentCapability.tenant_id == tenant_id,
        AgentCapability.agent_id == agent_id,
    ).all()
    assert len(agent_caps) == 1
    assert str(agent_caps[0].capability_id) == str(global_cap.id)
    db.close()


# =========================================================================
# 6. Arabic Company Name & Slug Generation Tests
# =========================================================================

def test_slugify_text_unit_cases():
    """Verify slugify_text handles English, Arabic, mixed, numbers, and symbols."""
    # English
    assert slugify_text("Acme Innovations") == "acme-innovations"
    assert slugify_text("Global Tech-2026") == "global-tech-2026"

    # Arabic
    arabic_slug = slugify_text("شركة الأفق الذكي")
    assert arabic_slug == "shrkh-alafq-aldhky"
    assert not arabic_slug.startswith("-")

    # Mixed
    assert slugify_text("شركة AI Solutions 2026") == "shrkh-ai-solutions-2026"

    # Pure symbols / empty
    assert slugify_text("   ") == ""
    assert slugify_text("!@#$%^&*()") == ""
    assert slugify_text("---") == ""


def test_provisioning_arabic_company_name_auto_slug():
    """Verify Arabic company name auto-generates a valid, non-empty, clean slug."""
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "شركة الأفق للتقنية المتقدمة",
            "owner_name": "سعد الشمري",
            "owner_email": f"saad-{uuid4().hex[:6]}@alofoq.sa",
            "owner_password": "ValidPassword123!",
        },
    )

    assert res.status_code == 201, res.text
    data = res.json()
    assert data["status"] == "provisioned"
    assert data["tenant"]["name"] == "شركة الأفق للتقنية المتقدمة"

    generated_slug = data["tenant"]["slug"]
    assert generated_slug
    assert not generated_slug.startswith("-")
    assert "shrkh-alafq" in generated_slug
    # Ensure slug contains only URL-safe lowercase alphanumeric and hyphens
    import re
    assert re.match(r"^[a-z0-9-]+$", generated_slug) is not None


def test_provisioning_english_company_name_auto_slug():
    """Verify English company name auto-generates clean slug with company prefix."""
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    res = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Nexus Enterprise Systems",
            "owner_name": "Edward Norton",
            "owner_email": f"edward-{uuid4().hex[:6]}@nexus.com",
            "owner_password": "ValidPassword123!",
        },
    )

    assert res.status_code == 201, res.text
    data = res.json()
    generated_slug = data["tenant"]["slug"]
    assert generated_slug.startswith("nexus-enterprise-systems-")


def test_provisioning_empty_and_whitespace_slug_fallback():
    """Verify whitespace-only slug or non-transliteratable name generates safe UUID fallback."""
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    # 1. Whitespace slug should fall back to auto-generating from name
    res1 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Fallback Company",
            "slug": "   ",
            "owner_name": "Fallback Owner",
            "owner_email": f"fb-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res1.status_code == 201
    assert res1.json()["tenant"]["slug"].startswith("fallback-company-")

    # 2. Non-alphanumeric name (e.g. symbols only) should safely fall back to 'tenant-<uuid>'
    res2 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "⭐⭐⭐⭐⭐⭐",
            "owner_name": "Stars Owner",
            "owner_email": f"stars-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res2.status_code == 201
    slug2 = res2.json()["tenant"]["slug"]
    assert slug2.startswith("tenant-")
    assert not slug2.startswith("-")


def test_provisioning_invalid_slug_input_rejected():
    """Verify explicitly provided invalid slug (special characters or hyphens only) is rejected."""
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    # Only symbols
    res1 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Symbol Corp",
            "slug": "!@#$%^&*",
            "owner_name": "Owner",
            "owner_email": f"sym-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res1.status_code == 400
    assert "Invalid tenant slug" in res1.json()["detail"]

    # Only hyphens
    res2 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Hyphen Corp",
            "slug": "---",
            "owner_name": "Owner",
            "owner_email": f"hyp-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res2.status_code == 400
    assert "Invalid tenant slug" in res2.json()["detail"]


def test_provisioning_arabic_explicit_slug_and_duplicate_collision():
    """Verify explicit Arabic slug transliterates safely and rejects duplicates."""
    client = TestClient(app)
    _, admin_token = create_user_with_role(role="platform_admin")

    arabic_slug_input = f"شركة-الريادة-{uuid4().hex[:6]}"

    # First tenant creation with Arabic slug
    res1 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "شركة الريادة الأولى",
            "slug": arabic_slug_input,
            "owner_name": "مالك الريادة",
            "owner_email": f"riyada1-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res1.status_code == 201
    assert "shrkh-alryadh" in res1.json()["tenant"]["slug"]

    # Second tenant creation attempting same slug must be rejected
    res2 = client.post(
        "/api/v1/tenants/provision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "شركة الريادة الثانية",
            "slug": arabic_slug_input,
            "owner_name": "مالك آخر",
            "owner_email": f"riyada2-{uuid4().hex[:6]}@example.com",
            "owner_password": "ValidPassword123!",
        },
    )
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]

