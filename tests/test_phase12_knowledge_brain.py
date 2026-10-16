from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.context.builder import ContextBuilder
from packages.context.models import TaskContext
from packages.context.ranking import ContextRanking
from packages.context.retriever import ContextRetriever
from packages.core.database import SessionLocal
from packages.memory.sanitizer import SecretDetectedError
from packages.models.domain import AuditEvent, BusinessBrain, Knowledge, Provenance, Source, SourcePolicy, User
from packages.models.tenant import Tenant
from packages.services.business_brain_service import BusinessBrainService
from packages.services.knowledge_service import KnowledgeService

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db):
    t = Tenant(
        name="Phase 12 Tenant A",
        slug=f"p12-tenant-a-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def tenant_b(db):
    t = Tenant(
        name="Phase 12 Tenant B",
        slug=f"p12-tenant-b-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def api_setup():
    db = SessionLocal()
    t = Tenant(
        name="API Phase 12 Tenant",
        slug=f"api-p12-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()

    # Pre-create BusinessBrain
    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "API Enterprise Inc", "industry": "Cloud SaaS"},
        brand={"tone": "Professional"},
        version=1,
    )
    db.add(brain)

    owner = User(
        tenant_id=t.id,
        name="Phase 12 Owner",
        email=f"p12-owner-{uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    member = User(
        tenant_id=t.id,
        name="Phase 12 Member",
        email=f"p12-member-{uuid4().hex[:8]}@example.com",
        role="tenant_member",
        status="active",
    )
    db.add(member)

    manager = User(
        tenant_id=t.id,
        name="Phase 12 Manager",
        email=f"p12-manager-{uuid4().hex[:8]}@example.com",
        role="manager",
        status="active",
    )
    db.add(manager)
    db.commit()

    tenant_id = t.id
    owner_id = owner.id
    member_id = member.id
    manager_id = manager.id
    db.close()

    yield {
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "member_id": member_id,
        "manager_id": manager_id,
    }

    cleanup_db = SessionLocal()
    target_t = cleanup_db.get(Tenant, tenant_id)
    if target_t:
        cleanup_db.delete(target_t)
        cleanup_db.commit()
    cleanup_db.close()


# ---------------------------------------------------------------------------
# 1. Business Brain Service Tests
# ---------------------------------------------------------------------------

def test_business_brain_creation_and_retrieval(db, tenant):
    """BusinessBrainService initializes and fetches structured business context."""
    service = BusinessBrainService(db)

    brain = service.create_brain_if_not_exists(
        tenant_id=tenant.id,
        initial_data={
            "identity": {"name": "Apex Logistics", "industry": "Supply Chain"},
            "brand": {"voice": "Formal", "tone": "Direct"},
        },
    )

    assert brain.id is not None
    assert brain.tenant_id == tenant.id
    assert brain.identity["name"] == "Apex Logistics"
    assert brain.brand["voice"] == "Formal"
    assert brain.version == 1

    # Second call returns existing record
    brain_again = service.create_brain_if_not_exists(tenant.id)
    assert brain_again.id == brain.id


def test_business_brain_partial_update_merges_nested_sections(db, tenant):
    """Updating a section merges nested keys rather than clobbering sibling fields."""
    service = BusinessBrainService(db)
    service.create_brain_if_not_exists(
        tenant.id,
        initial_data={
            "brand": {"tone": "Helpful", "archetype": "Advisor"},
            "pricing": {"currency": "SAR", "tax_rate": 0.15},
        },
    )

    # Partial update: modify tone, add guidelines, leave archetype unchanged
    updated_brain = service.update_brain(
        tenant.id,
        brand={"tone": "Friendly", "guidelines": ["No jargon", "Be concise"]},
    )

    assert updated_brain.brand["tone"] == "Friendly"
    assert updated_brain.brand["archetype"] == "Advisor"  # Preserved!
    assert "No jargon" in updated_brain.brand["guidelines"]
    assert updated_brain.pricing["currency"] == "SAR"  # Unrelated section preserved
    assert updated_brain.version == 2


def test_business_brain_rejects_credentials_and_secrets(db, tenant):
    """BusinessBrainService blocks any attempt to store credentials or API keys."""
    service = BusinessBrainService(db)
    service.create_brain_if_not_exists(tenant.id)

    # Attempt to store API key in operations
    with pytest.raises(SecretDetectedError):
        service.update_brain(
            tenant.id,
            operations={"api_gateway": "Use key sk-ant-api03-1234567890abcdef1234567890 for sync"},
        )

    # Attempt to store password assignment in policies
    with pytest.raises(SecretDetectedError):
        service.update_brain(
            tenant.id,
            policies={"admin_note": "Server login is password='SuperSecretPassword123'"},
        )


def test_business_brain_tenant_isolation(db, tenant, tenant_b):
    """Tenant A cannot read or mutate Tenant B's Business Brain."""
    service = BusinessBrainService(db)
    service.create_brain_if_not_exists(tenant.id, initial_data={"identity": {"name": "Tenant A Brain"}})
    service.create_brain_if_not_exists(tenant_b.id, initial_data={"identity": {"name": "Tenant B Brain"}})

    # Cross-tenant access guarded method raises PermissionError
    with pytest.raises(PermissionError, match="Cross-tenant access prohibited"):
        service.get_brain_guarded(
            requesting_tenant_id=tenant.id,
            target_tenant_id=tenant_b.id,
        )


def test_business_brain_versioning_and_audit(db, tenant):
    """Updating the Business Brain increments version and records audit event."""
    service = BusinessBrainService(db)
    service.create_brain_if_not_exists(tenant.id)

    updated = service.update_brain(
        tenant.id,
        goals={"q4_target": "Expand into MENA region"},
    )
    assert updated.version >= 2

    events = db.query(AuditEvent).filter(
        AuditEvent.tenant_id == tenant.id,
        AuditEvent.event_type == "business_brain_updated",
    ).all()
    assert len(events) >= 1
    assert "goals" in events[-1].event_metadata["sections_updated"]


# ---------------------------------------------------------------------------
# 2. Knowledge Base Service Tests
# ---------------------------------------------------------------------------

def test_knowledge_create_and_get(db, tenant):
    """Create a structured knowledge record and retrieve it."""
    service = KnowledgeService(db)

    item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Enterprise SLA Policy",
        content="Our guaranteed response time for tier 1 incidents is under 30 minutes.",
        knowledge_type="policy",
        status="active",
        metadata_json={"priority": "high", "department": "support"},
    )

    assert item.id is not None
    assert item.title == "Enterprise SLA Policy"
    assert item.knowledge_type == "policy"
    assert item.status == "active"
    assert item.version == 1

    fetched = service.get_knowledge(tenant.id, item.id)
    assert fetched is not None
    assert fetched.content == item.content


def test_knowledge_rejects_secrets(db, tenant):
    """Knowledge creation and updates reject embedded secrets, passwords, or keys."""
    service = KnowledgeService(db)

    # Reject API key in content
    with pytest.raises(SecretDetectedError):
        service.create_knowledge(
            tenant_id=tenant.id,
            title="Setup instructions",
            content="Use API key sk-proj-1234567890abcdef1234567890abcdef for authentication",
        )

    # Reject password in metadata
    with pytest.raises(SecretDetectedError):
        service.create_knowledge(
            tenant_id=tenant.id,
            title="Database doc",
            content="Production database notes",
            metadata_json={"db_pass": "password=MyDatabaseSecret123"},
        )


def test_knowledge_update_and_version_increment(db, tenant):
    """Updating a knowledge item increments the version and updates the audit log."""
    service = KnowledgeService(db)

    item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Shipping Policy",
        content="Free delivery on orders over 100 SAR.",
        knowledge_type="sales",
    )
    assert item.version == 1

    updated = service.update_knowledge(
        tenant.id,
        item.id,
        content="Free delivery on orders over 150 SAR.",
        metadata_json={"updated_by": "marketing_team"},
    )

    assert updated.version == 2
    assert "150 SAR" in updated.content
    assert updated.metadata_json["updated_by"] == "marketing_team"


def test_knowledge_activation_and_deactivation_lifecycle(db, tenant):
    """Knowledge records transition explicitly between active and inactive states."""
    service = KnowledgeService(db)

    item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Winter Promo 2026",
        content="25% off all seasonal outerwear.",
        status="active",
    )
    assert item.status == "active"

    # Deactivate with reason
    deactivated = service.deactivate_knowledge(
        tenant.id,
        item.id,
        reason="Winter season has concluded",
    )
    assert deactivated.status == "inactive"
    assert deactivated.metadata_json["deactivation_reason"] == "Winter season has concluded"
    assert deactivated.version == 2

    # Reactivate
    reactivated = service.activate_knowledge(tenant.id, item.id)
    assert reactivated.status == "active"
    assert reactivated.version == 3


def test_knowledge_pagination_and_filtering(db, tenant):
    """KnowledgeService lists items with pagination, status filtering, and query searching."""
    service = KnowledgeService(db)

    # Create 5 policy items and 3 faq items
    for i in range(5):
        service.create_knowledge(
            tenant_id=tenant.id,
            title=f"Security Policy {i + 1}",
            content=f"Password rotation rule number {i + 1} for employees.",
            knowledge_type="policy",
            status="active" if i < 3 else "inactive",
        )

    for i in range(3):
        service.create_knowledge(
            tenant_id=tenant.id,
            title=f"Billing FAQ {i + 1}",
            content=f"Common questions about invoice payment methods {i + 1}.",
            knowledge_type="faq",
            status="active",
        )

    # 1. Total count
    items, total = service.list_knowledge(tenant.id)
    assert total >= 8

    # 2. Filter by status active
    active_items, active_total = service.list_knowledge(tenant.id, status="active")
    assert all(k.status == "active" for k in active_items)

    # 3. Filter by type faq
    faq_items, faq_total = service.list_knowledge(tenant.id, knowledge_type="faq")
    assert all(k.knowledge_type == "faq" for k in faq_items)
    assert faq_total == 3

    # 4. Pagination
    paged_items, _ = service.list_knowledge(tenant.id, limit=2, offset=0)
    assert len(paged_items) == 2


def test_knowledge_tenant_isolation(db, tenant, tenant_b):
    """Strict tenant isolation: Tenant A cannot read, update, list, or delete Tenant B's knowledge."""
    service = KnowledgeService(db)

    item_a = service.create_knowledge(
        tenant_id=tenant.id,
        title="Tenant A Proprietary Formula",
        content="Confidential manufacturing procedure for Tenant A.",
    )

    item_b = service.create_knowledge(
        tenant_id=tenant_b.id,
        title="Tenant B Strategy",
        content="Confidential market entry plan for Tenant B.",
    )

    # Tenant A cannot fetch Tenant B's item
    assert service.get_knowledge(tenant.id, item_b.id) is None

    # Tenant B cannot fetch Tenant A's item
    assert service.get_knowledge(tenant_b.id, item_a.id) is None

    # Cross-tenant guarded method raises PermissionError
    with pytest.raises(PermissionError):
        service.get_knowledge_guarded(tenant.id, tenant_b.id, item_b.id)

    # Tenant A cannot delete Tenant B's item
    with pytest.raises(ValueError, match="not found"):
        service.delete_knowledge(tenant.id, item_b.id)

    # Listing for Tenant A does not include Tenant B's item
    items_a, _ = service.list_knowledge(tenant.id)
    assert item_b.id not in [k.id for k in items_a]


def test_knowledge_provenance_and_source_attribution(db, tenant, tenant_b):
    """Knowledge can be linked to registered Sources and Provenance records with tenant enforcement."""
    # 1. Create a Source for Tenant A
    source_a = Source(
        tenant_id=tenant.id,
        name="Employee Handbook 2026",
        uri="https://docs.tenant-a.internal/handbook-2026.pdf",
        source_type="document",
        trust_level="verified",
        status="active",
    )
    db.add(source_a)
    db.commit()

    service = KnowledgeService(db)

    # Link knowledge to source_a
    item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Vacation Policy",
        content="Employees are granted 30 paid leave days annually.",
        source_id=source_a.id,
    )

    assert item.provenance_id is not None
    assert item.metadata_json["source_name"] == "Employee Handbook 2026"

    # Verify Provenance record was created
    prov = db.query(Provenance).filter(Provenance.id == item.provenance_id).first()
    assert prov is not None
    assert prov.source_uri == "https://docs.tenant-a.internal/handbook-2026.pdf"

    # Tenant A cannot link to Tenant B's source
    source_b = Source(
        tenant_id=tenant_b.id,
        name="Tenant B Doc",
        uri="https://tenant-b.com/doc",
        source_type="document",
    )
    db.add(source_b)
    db.commit()

    with pytest.raises(ValueError, match="not found for tenant"):
        service.create_knowledge(
            tenant_id=tenant.id,
            title="Invalid Link",
            content="Testing cross-tenant source linking rejection.",
            source_id=source_b.id,
        )


def test_knowledge_conflict_detection_and_resolution(db, tenant):
    """Contradictory knowledge is explicitly flagged rather than silently overwritten, and resolved cleanly."""
    service = KnowledgeService(db)

    # Record A: Return policy 14 days
    item_a = service.create_knowledge(
        tenant_id=tenant.id,
        title="Return Policy 2025",
        content="Customers may return merchandise within 14 calendar days of delivery.",
    )

    # Record B: Return policy 30 days
    item_b = service.create_knowledge(
        tenant_id=tenant.id,
        title="Return Policy 2026",
        content="Customers may return merchandise within 30 calendar days of delivery.",
    )

    # 1. Flag conflict
    flagged_a, flagged_b = service.flag_conflict(
        tenant_id=tenant.id,
        knowledge_id=item_a.id,
        conflicting_knowledge_id=item_b.id,
        reason="Discrepancy in allowable return window (14 vs 30 days)",
    )

    assert flagged_a.metadata_json["conflict_status"] == "flagged"
    assert str(item_b.id) in flagged_a.metadata_json["conflicts_with"]
    assert str(item_a.id) in flagged_b.metadata_json["conflicts_with"]

    # 2. Resolve conflict: 2026 policy wins and supersedes 2025 policy
    winner, loser = service.resolve_conflict(
        tenant_id=tenant.id,
        winner_id=item_b.id,
        loser_id=item_a.id,
        resolution_reason="Executive approval of 2026 updated return policy terms",
    )

    assert winner.metadata_json["supersedes"] == str(item_a.id)
    assert winner.metadata_json["conflict_status"] == "resolved"
    assert loser.status == "archived"  # Deprecated/archived
    assert loser.metadata_json["superseded_by"] == str(item_b.id)


# ---------------------------------------------------------------------------
# 3. Context Retrieval & Ranking Integration Tests
# ---------------------------------------------------------------------------

def test_context_retriever_excludes_inactive_knowledge(db, tenant):
    """ContextRetriever strictly excludes inactive and archived knowledge records."""
    service = KnowledgeService(db)

    active_item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Current Discount Rules",
        content="Active discount rule: 10% off with promo code SAVE10.",
        status="active",
    )
    inactive_item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Expired Promo",
        content="Expired promo rule: 50% off during Black Friday.",
        status="inactive",
    )
    archived_item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Archived Warranty Terms",
        content="Historical warranty terms from 2020.",
        status="archived",
    )

    retriever = ContextRetriever(db)
    retrieved = retriever.get_knowledge(tenant.id)
    retrieved_ids = [k.id for k in retrieved]

    assert active_item.id in retrieved_ids
    assert inactive_item.id not in retrieved_ids
    assert archived_item.id not in retrieved_ids


def test_context_ranking_boosts_relevant_knowledge():
    """ContextRanking scores knowledge matching title and query terms higher than irrelevant records."""
    ranking = ContextRanking()

    k_relevant = Knowledge(
        title="Warranty and Return Guidelines",
        content="Standard returns must be processed within 30 days with receipt.",
        updated_at=datetime.now(timezone.utc),
        metadata_json={},
    )
    k_irrelevant = Knowledge(
        title="Office Kitchen Sanitation Guidelines",
        content="Please clean the microwave after heating lunch.",
        updated_at=datetime.now(timezone.utc),
        metadata_json={},
    )

    score_rel = ranking.score_knowledge(k_relevant, query="warranty return receipt")
    score_irrel = ranking.score_knowledge(k_irrelevant, query="warranty return receipt")

    assert score_rel > score_irrel


def test_context_builder_assembles_knowledge_with_provenance_and_untrusted_flag():
    """ContextBuilder injects knowledge records tagged with provenance and marked as untrusted context data."""
    fake_prov_id = uuid4()
    fake_k = Knowledge(
        id=uuid4(),
        tenant_id=uuid4(),
        provenance_id=fake_prov_id,
        title="Authorized Payment Gateways",
        content="Supported payment gateways are Mada, Visa, and Apple Pay.",
        knowledge_type="financial",
        metadata_json={"source_name": "Finance Portal"},
        version=2,
    )

    class DummyRetriever:
        def get_business_brain(self, tenant_id):
            return None

        def get_memories(self, tenant_id, agent_id=None, customer_id=None, limit=20, query=None):
            return []

        def get_knowledge(self, tenant_id, query=None, limit=20):
            return [fake_k]

    task = TaskContext(
        task_id=uuid4(),
        agent_id=None,
        objective="Process customer checkout",
        title="Checkout",
        priority="high",
        status="pending",
    )

    builder = ContextBuilder(DummyRetriever())
    context = builder.build(tenant_id=fake_k.tenant_id, task=task)

    assert len(context.knowledge) == 1
    k_dict = context.knowledge[0]
    assert k_dict["title"] == "Authorized Payment Gateways"
    assert k_dict["provenance_id"] == str(fake_prov_id)
    assert k_dict["is_untrusted_data"] is True
    assert context.metadata["is_untrusted_data"] is True


# ---------------------------------------------------------------------------
# 4. REST API Integration Tests
# ---------------------------------------------------------------------------

def test_api_business_brain_me_endpoint(api_setup):
    """GET and PATCH /api/v1/me/brain: reading and partial updates with role enforcement."""
    tenant_id = api_setup["tenant_id"]
    owner_id = api_setup["owner_id"]
    member_id = api_setup["member_id"]

    owner_token = create_access_token(user_id=owner_id, tenant_id=tenant_id, role="tenant_owner")
    member_token = create_access_token(user_id=member_id, tenant_id=tenant_id, role="tenant_member")

    headers_owner = {"Authorization": f"Bearer {owner_token}"}
    headers_member = {"Authorization": f"Bearer {member_token}"}

    # 1. Member can read brain
    resp_get = client.get("/api/v1/me/brain", headers=headers_member)
    assert resp_get.status_code == 200
    assert resp_get.json()["identity"]["name"] == "API Enterprise Inc"

    # 2. Member cannot update brain (403)
    resp_patch_forbidden = client.patch(
        "/api/v1/me/brain",
        headers=headers_member,
        json={"pricing": {"discount_limit": 0.20}},
    )
    assert resp_patch_forbidden.status_code == 403

    # 3. Owner updates brain (200)
    resp_patch_ok = client.patch(
        "/api/v1/me/brain",
        headers=headers_owner,
        json={"pricing": {"discount_limit": 0.20, "currency": "USD"}},
    )
    assert resp_patch_ok.status_code == 200
    assert resp_patch_ok.json()["pricing"]["discount_limit"] == 0.20

    # 4. Attempting to inject secrets returns 400 Bad Request
    resp_patch_secret = client.patch(
        "/api/v1/me/brain",
        headers=headers_owner,
        json={"operations": {"ssh_secret": "password='ProductionMasterSecret123'"}},
    )
    assert resp_patch_secret.status_code == 400


def test_api_knowledge_lifecycle(api_setup):
    """Full HTTP REST API lifecycle for Knowledge: POST, GET, PATCH, activate, deactivate, search, DELETE with RBAC."""
    tenant_id = api_setup["tenant_id"]
    owner_id = api_setup["owner_id"]
    manager_id = api_setup["manager_id"]
    member_id = api_setup["member_id"]

    owner_token = create_access_token(user_id=owner_id, tenant_id=tenant_id, role="tenant_owner")
    manager_token = create_access_token(user_id=manager_id, tenant_id=tenant_id, role="manager")
    member_token = create_access_token(user_id=member_id, tenant_id=tenant_id, role="tenant_member")

    headers_owner = {"Authorization": f"Bearer {owner_token}"}
    headers_manager = {"Authorization": f"Bearer {manager_token}"}
    headers_member = {"Authorization": f"Bearer {member_token}"}

    # 1. Member creates knowledge forbidden (403)
    resp_create_forbid = client.post(
        "/api/v1/knowledge",
        headers=headers_member,
        json={
            "title": "Unauthorized Policy",
            "content": "Member cannot create policies.",
        },
    )
    assert resp_create_forbid.status_code == 403

    # 2. Manager creates knowledge record (201)
    resp_create = client.post(
        "/api/v1/knowledge",
        headers=headers_manager,
        json={
            "title": "Customer Refund SLA",
            "content": "Refund requests must be processed within 5 business days.",
            "knowledge_type": "policy",
            "status": "active",
            "metadata_json": {"tier": "standard"},
        },
    )
    assert resp_create.status_code == 201
    k_data = resp_create.json()
    k_id = k_data["id"]
    assert k_data["title"] == "Customer Refund SLA"

    # 3. Member can read knowledge record (200)
    resp_get = client.get(f"/api/v1/knowledge/{k_id}", headers=headers_member)
    assert resp_get.status_code == 200
    assert "5 business days" in resp_get.json()["content"]

    # 4. Member can search knowledge (200)
    resp_search = client.get("/api/v1/knowledge/search?query=Refund", headers=headers_member)
    assert resp_search.status_code == 200
    assert len(resp_search.json()["items"]) >= 1

    # 5. Member patch forbidden (403)
    resp_patch_forbid = client.patch(
        f"/api/v1/knowledge/{k_id}",
        headers=headers_member,
        json={"content": "Unauthorized update."},
    )
    assert resp_patch_forbid.status_code == 403

    # 6. Manager patch allowed (200)
    resp_patch = client.patch(
        f"/api/v1/knowledge/{k_id}",
        headers=headers_manager,
        json={"content": "Refund requests must be processed within 3 business days."},
    )
    assert resp_patch.status_code == 200
    assert "3 business days" in resp_patch.json()["content"]

    # 7. Member deactivate forbidden (403)
    resp_deact_forbid = client.post(
        f"/api/v1/knowledge/{k_id}/deactivate",
        headers=headers_member,
        json={"reason": "Test"},
    )
    assert resp_deact_forbid.status_code == 403

    # 8. Manager deactivates knowledge (200)
    resp_deact = client.post(
        f"/api/v1/knowledge/{k_id}/deactivate",
        headers=headers_manager,
        json={"reason": "Updated refund policy coming next month"},
    )
    assert resp_deact.status_code == 200
    assert resp_deact.json()["status"] == "inactive"

    # 9. Manager activates knowledge (200)
    resp_act = client.post(f"/api/v1/knowledge/{k_id}/activate", headers=headers_manager)
    assert resp_act.status_code == 200
    assert resp_act.json()["status"] == "active"

    # 10. Member and Manager delete forbidden (403)
    resp_del_member = client.delete(f"/api/v1/knowledge/{k_id}", headers=headers_member)
    assert resp_del_member.status_code == 403
    resp_del_manager = client.delete(f"/api/v1/knowledge/{k_id}", headers=headers_manager)
    assert resp_del_manager.status_code == 403

    # 11. Owner delete allowed (200)
    resp_del_ok = client.delete(f"/api/v1/knowledge/{k_id}", headers=headers_owner)
    assert resp_del_ok.status_code == 200

    # 12. Get after delete returns 404
    resp_get_404 = client.get(f"/api/v1/knowledge/{k_id}", headers=headers_owner)
    assert resp_get_404.status_code == 404


def test_unauthorized_roles_mutation_endpoints(api_setup):
    """Test unauthorized roles (member/viewer) across all mutation endpoints."""
    tenant_id = api_setup["tenant_id"]
    member_id = api_setup["member_id"]
    member_token = create_access_token(user_id=member_id, tenant_id=tenant_id, role="tenant_member")
    headers = {"Authorization": f"Bearer {member_token}"}
    fake_id = uuid4()

    # Create mutation
    assert client.post("/api/v1/knowledge", headers=headers, json={"title": "T", "content": "C"}).status_code == 403

    # Update mutation
    assert client.patch(f"/api/v1/knowledge/{fake_id}", headers=headers, json={"title": "T"}).status_code == 403

    # Activate mutation
    assert client.post(f"/api/v1/knowledge/{fake_id}/activate", headers=headers).status_code == 403

    # Deactivate mutation
    assert client.post(f"/api/v1/knowledge/{fake_id}/deactivate", headers=headers).status_code == 403

    # Flag conflict mutation
    assert client.post(
        f"/api/v1/knowledge/{fake_id}/flag-conflict",
        headers=headers,
        json={"conflicting_knowledge_id": str(uuid4()), "reason": "Contradiction"},
    ).status_code == 403

    # Resolve conflict mutation
    assert client.post(
        f"/api/v1/knowledge/{fake_id}/resolve-conflict",
        headers=headers,
        json={"loser_knowledge_id": str(uuid4()), "resolution_reason": "Resolution"},
    ).status_code == 403

    # Delete mutation
    assert client.delete(f"/api/v1/knowledge/{fake_id}", headers=headers).status_code == 403


def test_source_policy_enforcement(db, tenant):
    """Verify SourcePolicy and source active status enforcement during creation and activation."""
    service = KnowledgeService(db)

    # 1. Inactive source
    inactive_src = Source(
        tenant_id=tenant.id,
        name="Legacy Knowledge Base",
        uri="https://legacy.internal/docs",
        source_type="confluence",
        status="inactive",
    )
    db.add(inactive_src)
    db.commit()

    with pytest.raises(ValueError, match="inactive source"):
        service.create_knowledge(
            tenant_id=tenant.id,
            title="Confluence Policy",
            content="Internal confluence documentation.",
            source_id=inactive_src.id,
        )

    # 2. SourcePolicy forbids learning
    restricted_src = Source(
        tenant_id=tenant.id,
        name="Restricted Customer Portal",
        uri="https://portal.internal/restricted",
        source_type="portal_restricted",
        status="active",
    )
    db.add(restricted_src)
    policy_no_learn = SourcePolicy(
        tenant_id=tenant.id,
        source_type="portal_restricted",
        trust_level="external",
        allow_learning=False,
        require_approval=True,
    )
    db.add(policy_no_learn)
    db.commit()

    with pytest.raises(ValueError, match="forbids learning"):
        service.create_knowledge(
            tenant_id=tenant.id,
            title="Restricted Doc",
            content="Should not be learned.",
            source_id=restricted_src.id,
        )

    # 3. SourcePolicy requires approval before activation
    approval_src = Source(
        tenant_id=tenant.id,
        name="Vendor Agreement Feed",
        uri="https://feed.vendor.com/agreements",
        source_type="vendor_feed",
        status="active",
    )
    db.add(approval_src)
    policy_approval = SourcePolicy(
        tenant_id=tenant.id,
        source_type="vendor_feed",
        trust_level="vendor",
        allow_learning=True,
        require_approval=True,
    )
    db.add(policy_approval)
    db.commit()

    # Active creation raises error
    with pytest.raises(ValueError, match="requires approval before activation"):
        service.create_knowledge(
            tenant_id=tenant.id,
            title="Vendor SLA Contract",
            content="Terms and conditions from vendor feed.",
            source_id=approval_src.id,
            status="active",
        )

    # Draft creation succeeds
    draft_item = service.create_knowledge(
        tenant_id=tenant.id,
        title="Vendor SLA Contract Draft",
        content="Terms and conditions from vendor feed in draft.",
        source_id=approval_src.id,
        status="draft",
    )
    assert draft_item.status == "draft"

    # Direct activation without approval raises error
    with pytest.raises(ValueError, match="requires approval before activation"):
        service.activate_knowledge(tenant.id, draft_item.id)


def test_customer_knowledge_privacy_isolation(db, tenant):
    """Customer-specific knowledge must never leak into general context or other customers."""
    service = KnowledgeService(db)
    cust_a_id = uuid4()
    cust_b_id = uuid4()

    # General knowledge (no customer_id)
    general_k = service.create_knowledge(
        tenant_id=tenant.id,
        title="Enterprise General Support SLA",
        content="Support tickets are answered within 4 hours.",
        status="active",
        metadata_json={"visibility": "general"},
    )

    # Customer A knowledge (with customer_id in metadata)
    cust_a_k = service.create_knowledge(
        tenant_id=tenant.id,
        title="Customer A VIP Custom SLA",
        content="Customer A tickets are answered within 15 minutes.",
        status="active",
        metadata_json={"customer_id": str(cust_a_id), "custom_contract": True},
    )
    db.commit()

    retriever = ContextRetriever(db)

    # 1. Query with customer_id=None -> ONLY general knowledge returned
    general_results = retriever.get_knowledge(tenant.id, customer_id=None)
    returned_ids = {k.id for k in general_results}
    assert general_k.id in returned_ids
    assert cust_a_k.id not in returned_ids, "Customer A private knowledge must NOT leak into general context!"

    # 2. Query with customer_id=cust_a_id -> includes Customer A knowledge
    cust_a_results = retriever.get_knowledge(tenant.id, customer_id=cust_a_id)
    cust_a_ids = {k.id for k in cust_a_results}
    assert general_k.id in cust_a_ids
    assert cust_a_k.id in cust_a_ids

    # 3. Query with customer_id=cust_b_id -> Customer A knowledge excluded
    cust_b_results = retriever.get_knowledge(tenant.id, customer_id=cust_b_id)
    cust_b_ids = {k.id for k in cust_b_results}
    assert general_k.id in cust_b_ids
    assert cust_a_k.id not in cust_b_ids, "Customer A knowledge must NOT leak to Customer B!"

    # 4. ContextBuilder respects customer privacy
    builder = ContextBuilder(retriever)
    task_ctx = TaskContext(
        task_id=uuid4(),
        agent_id=None,
        objective="Check support SLA response times",
        title="Check SLA",
        priority="normal",
        status="pending",
    )

    # Build with customer_id=None
    ctx_general = builder.build(tenant_id=tenant.id, task=task_ctx, customer_id=None)
    k_general_ids = {k["id"] for k in ctx_general.knowledge}
    assert str(cust_a_k.id) not in k_general_ids

    # Build with customer_id=cust_a_id
    ctx_cust_a = builder.build(tenant_id=tenant.id, task=task_ctx, customer_id=cust_a_id)
    k_cust_a_ids = {k["id"] for k in ctx_cust_a.knowledge}
    assert str(cust_a_k.id) in k_cust_a_ids


def test_secret_scanning_in_conflict_notes(db, tenant):
    """Secret detection must be enforced on conflict flagging and resolution reasons."""
    service = KnowledgeService(db)
    k1 = service.create_knowledge(tenant.id, title="Fact 1", content="Server port is 8080.")
    k2 = service.create_knowledge(tenant.id, title="Fact 2", content="Server port is 8443.")
    db.commit()

    # Secret in conflict flag reason
    with pytest.raises(SecretDetectedError):
        service.flag_conflict(
            tenant.id,
            k1.id,
            k2.id,
            reason="Conflicting port with password='ProductionPassword123'",
        )

    # Secret in conflict resolution reason
    with pytest.raises(SecretDetectedError):
        service.resolve_conflict(
            tenant.id,
            k1.id,
            k2.id,
            resolution_reason="Resolved using API key sk-ant-api03-1234567890abcdef1234567890",
        )


def test_business_brain_creation_rejects_non_dict_section(db, tenant):
    """BusinessBrainService must reject corrupted non-dictionary sections during creation."""
    service = BusinessBrainService(db)
    with pytest.raises(ValueError, match="must be a dictionary"):
        service.create_brain_if_not_exists(
            tenant_id=uuid4(),
            initial_data={"identity": "not_a_dictionary_corrupted_value"},
        )
