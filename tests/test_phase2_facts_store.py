from __future__ import annotations

import json
import os
import uuid
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal, Base, engine
from packages.models.domain import BusinessBrain, Fact, Knowledge, Message, Conversation, Channel, User
from packages.models.tenant import Tenant
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.conversation_service import ConversationService
from packages.services.fact_service import ExtractedFactItem, FactExtractionResponse, FactService


@pytest.fixture(scope="session", autouse=True)
def setup_facts_table():
    """Ensure the facts table is created strictly in the isolated test database."""
    from packages.core.safety_guard import verify_test_database_isolation
    import packages.core.database as core_db
    actual_db = verify_test_database_isolation(core_db.engine)
    assert actual_db == "ai_employee_test", f"Safety violation: attempted table creation on {actual_db}"
    Fact.__table__.create(bind=core_db.engine, checkfirst=True)
    yield


class MockAIProvider:
    def __init__(self, reply: str = "مرحبا بك", json_reply: dict[str, Any] | None = None):
        self.reply = reply
        self.json_reply = json_reply or {}
        self.called_count = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.called_count += 1
        return self.reply

    def generate_json(self, *args, **kwargs) -> dict[str, Any]:
        self.called_count += 1
        return self.json_reply


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant(db: Session) -> Tenant:
    t = Tenant(
        name="Al-Munther Tech Enterprise",
        slug=f"facts-test-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def tenant_b(db: Session) -> Tenant:
    t = Tenant(
        name="Competitor Enterprise B",
        slug=f"comp-b-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def channel(db: Session, tenant: Tenant) -> Channel:
    ch = Channel(
        tenant_id=tenant.id,
        name="Owner WhatsApp Channel",
        channel_type="whatsapp",
        status="active",
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


# ---------------------------------------------------------------------------
# Test 1: Complex Arabic Dialect Fact Extraction
# ---------------------------------------------------------------------------
def test_extraction_of_complex_arabic_owner_message(
    db: Session, tenant: Tenant, channel: Channel
):
    """
    Requirement 8: Extraction of:
    "اسم الشركة المنذر تكنولوجي، نبيع الموظف الذكي وبرنامج ناظم المحاسبي وبرنامج سيرو لإدارة الشبكات، نخدم صنعاء والحديدة وذمار وإب والمحويت وريمة"
    into correct separate facts.
    """
    owner_sentence = (
        "اسم الشركة المنذر تكنولوجي، نبيع الموظف الذكي وبرنامج ناظم المحاسبي وبرنامج سيرو لإدارة الشبكات، "
        "نخدم صنعاء والحديدة وذمار وإب والمحويت وريمة"
    )

    fact_svc = FactService(db)

    # Test extraction via deterministic engine (supporting Yemeni business dialect)
    extraction = fact_svc.extract_facts(tenant.id, owner_sentence, provider=None)
    assert extraction is not None
    assert len(extraction.facts) >= 5

    topics = [f.topic for f in extraction.facts]
    subjects = [f.subject for f in extraction.facts]

    # Verify company name
    assert "company.identity" in topics
    assert any("المنذر تكنولوجي" in str(f.value) for f in extraction.facts if f.topic == "company.identity")

    # Verify products
    assert any("الموظف الذكي" in s for s in subjects)
    assert any("ناظم" in s for s in subjects)
    assert any("سيرو" in s for s in subjects)

    # Verify coverage cities
    coverage_fact = next(f for f in extraction.facts if f.topic == "operations.delivery_zones")
    cities = coverage_fact.value.get("cities", [])
    expected_cities = ["صنعاء", "الحديدة", "ذمار", "إب", "المحويت", "ريمة"]
    for c in expected_cities:
        assert c in cities

    # Save to database and verify persistence
    save_res = fact_svc.save_extracted_facts(tenant.id, extraction.facts, auto_confirm_direct=True)
    assert len(save_res["confirmed"]) == len(extraction.facts)
    assert len(save_res["conflicts"]) == 0

    # Query DB directly
    db_facts = db.scalars(select(Fact).where(Fact.tenant_id == tenant.id, Fact.status == "confirmed")).all()
    assert len(db_facts) >= 5


# ---------------------------------------------------------------------------
# Test 2: Confirmation & Correction Flow
# ---------------------------------------------------------------------------
def test_confirmation_and_correction_flow(db: Session, tenant: Tenant):
    """
    Requirement 3: Store as pending_confirmation until the owner confirms;
    then mark confirmed/owner_confirmed. Corrections replace the pending fact.
    """
    fact_svc = FactService(db)

    # 1. Inferred/Ambiguous fact stored as pending_confirmation
    item = ExtractedFactItem(
        topic="product.test_item",
        subject="منتج تجريبي غير مؤكد",
        value={"price": 250},
        visibility="public",
        is_direct_unambiguous=False,
    )

    save_res = fact_svc.save_extracted_facts(tenant.id, [item], auto_confirm_direct=False)
    assert len(save_res["pending"]) == 1
    pending_fact = save_res["pending"][0]
    assert pending_fact.status == "pending_confirmation"
    assert pending_fact.source == "inferred"

    # 2. Confirm the pending fact
    confirmed = fact_svc.confirm_fact(tenant.id, pending_fact.id)
    assert confirmed.status == "confirmed"
    assert confirmed.source == "owner_confirmed"
    assert confirmed.confidence == 1.0

    # 3. Owner corrects the fact (corrections replace the pending fact)
    corrected = fact_svc.correct_fact(
        tenant.id, confirmed.id, corrected_value={"price": 200, "note": "سعر مخفض"}
    )
    assert corrected.status == "confirmed"
    assert corrected.value["price"] == 200

    # Verify old version is superseded (never overwritten silently)
    old_version = db.scalar(select(Fact).where(Fact.id == confirmed.id))
    assert old_version.status == "superseded"
    assert old_version.superseded_by == corrected.id


# ---------------------------------------------------------------------------
# Test 3: Conflict Flow
# ---------------------------------------------------------------------------
def test_conflict_flow(db: Session, tenant: Tenant):
    """
    Requirement 4: If a new fact contradicts an existing confirmed fact on the same topic/subject,
    mark status=conflict and ask the owner which is correct; keep both until answered.
    """
    fact_svc = FactService(db)

    # 1. Existing confirmed fact
    fact1 = ExtractedFactItem(
        topic="pricing.nazim",
        subject="سعر اشتراك ناظم",
        value={"price": 500, "currency": "SAR"},
        visibility="public",
        is_direct_unambiguous=True,
    )
    res1 = fact_svc.save_extracted_facts(tenant.id, [fact1], auto_confirm_direct=True)
    assert len(res1["confirmed"]) == 1
    existing_fact = res1["confirmed"][0]

    # 2. Owner later states a conflicting fact with different price
    fact2_conflict = ExtractedFactItem(
        topic="pricing.nazim",
        subject="سعر اشتراك ناظم",
        value={"price": 350, "currency": "SAR"},
        visibility="public",
        is_direct_unambiguous=True,
    )
    res2 = fact_svc.save_extracted_facts(tenant.id, [fact2_conflict], auto_confirm_direct=True)

    # Assert conflict detected and both kept
    assert len(res2["conflicts"]) == 1
    conflict_pair = res2["conflicts"][0]
    assert conflict_pair["existing_fact"].id == existing_fact.id
    conflicting_fact = conflict_pair["conflicting_fact"]
    assert conflicting_fact.status == "conflict"
    assert existing_fact.status == "confirmed"

    # Both exist in the DB
    all_facts = db.scalars(
        select(Fact).where(Fact.tenant_id == tenant.id, Fact.topic == "pricing.nazim")
    ).all()
    assert len(all_facts) == 2

    # 3. Owner resolves conflict by picking the new fact
    chosen = fact_svc.resolve_conflict(
        tenant.id, kept_fact_id=conflicting_fact.id, rejected_fact_id=existing_fact.id
    )
    assert chosen.id == conflicting_fact.id
    assert chosen.status == "confirmed"
    assert chosen.source == "owner_confirmed"

    # Rejected fact is superseded
    db.refresh(existing_fact)
    assert existing_fact.status == "superseded"
    assert existing_fact.superseded_by == chosen.id


# ---------------------------------------------------------------------------
# Test 4: Private Fact Never Reaches Customer Prompt
# ---------------------------------------------------------------------------
def test_private_fact_never_reaches_customer_prompt(db: Session, tenant: Tenant, channel: Channel):
    """
    Requirement 6 & 8: Private facts (internal margins, strategic goals) must never be returned
    to customers, but must be accessible in the owner path.
    """
    fact_svc = FactService(db)

    # 1. Add public fact and private fact
    pub_fact = ExtractedFactItem(
        topic="product.nazim.overview",
        subject="برنامج ناظم المحاسبي",
        value={"summary": "برنامج محاسبي لإدارة الفواتير"},
        visibility="public",
    )
    priv_fact = ExtractedFactItem(
        topic="company.financials.margins",
        subject="هامش الربح الداخلي",
        value={"profit_margin": "45%", "cost_basis": "100$"},
        visibility="private",
    )
    fact_svc.save_extracted_facts(tenant.id, [pub_fact, priv_fact], auto_confirm_direct=True)

    # 2. Customer query: include_private=False
    customer_facts = fact_svc.get_relevant_facts(
        tenant.id, query="هامش الربح وناظم", include_private=False
    )
    for f in customer_facts:
        assert f.visibility == "public"
        assert "هامش الربح" not in f.subject
        assert "profit_margin" not in json.dumps(f.value)

    # 3. Owner query: include_private=True
    owner_facts = fact_svc.get_relevant_facts(
        tenant.id, query="هامش الربح", include_private=True
    )
    assert any(f.visibility == "private" for f in owner_facts)
    assert any("هامش الربح" in f.subject for f in owner_facts)


# ---------------------------------------------------------------------------
# Test 5: Expired Fact Detection
# ---------------------------------------------------------------------------
def test_expired_fact_detection(db: Session, tenant: Tenant):
    """
    Requirement 5: Facts about prices/hours get expires_at; add function listing stale facts.
    """
    fact_svc = FactService(db)
    now = datetime.now(timezone.utc)

    # Active fact
    active = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="pricing.active",
        subject="عرض ساري",
        value={"discount": "10%"},
        visibility="public",
        status="confirmed",
        expires_at=now + timedelta(days=10),
    )
    # Expired fact (expired 2 hours ago)
    expired = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="pricing.expired",
        subject="عرض منتهي",
        value={"discount": "50%"},
        visibility="public",
        status="confirmed",
        expires_at=now - timedelta(hours=2),
    )
    db.add_all([active, expired])
    db.commit()

    # List stale facts
    stale_list = fact_svc.list_stale_facts(tenant.id)
    assert len(stale_list) == 1
    assert stale_list[0].id == expired.id
    assert stale_list[0].status == "stale"

    # get_relevant_facts should exclude expired/stale facts from customer context
    active_facts = fact_svc.get_relevant_facts(tenant.id, include_private=False)
    active_ids = [f.id for f in active_facts]
    assert active.id in active_ids
    assert expired.id not in active_ids


# ---------------------------------------------------------------------------
# Test 6: Strict Multi-Tenant Isolation
# ---------------------------------------------------------------------------
def test_tenant_isolation_in_facts_store(db: Session, tenant: Tenant, tenant_b: Tenant):
    """
    Mandatory Rule: Tenant A can never read, modify, or supersede Tenant B's facts.
    """
    fact_svc = FactService(db)

    fact_a = ExtractedFactItem(
        topic="product.secret_a",
        subject="منتج المستأجر أ",
        value={"proprietary": "Tech A Secret"},
        visibility="public",
    )
    fact_svc.save_extracted_facts(tenant.id, [fact_a], auto_confirm_direct=True)

    fact_b = ExtractedFactItem(
        topic="product.secret_b",
        subject="منتج المستأجر ب",
        value={"proprietary": "Tech B Secret"},
        visibility="public",
    )
    fact_svc.save_extracted_facts(tenant_b.id, [fact_b], auto_confirm_direct=True)

    # Tenant B queries facts
    tenant_b_facts = fact_svc.get_relevant_facts(tenant_b.id, include_private=True)
    b_contents = [json.dumps(f.value) for f in tenant_b_facts]
    assert not any("Tech A Secret" in c for c in b_contents)

    # Tenant B cannot confirm or correct Tenant A's fact
    fact_a_record = db.scalar(select(Fact).where(Fact.tenant_id == tenant.id))
    with pytest.raises(ValueError, match="not found for tenant"):
        fact_svc.confirm_fact(tenant_b.id, fact_a_record.id)


# ---------------------------------------------------------------------------
# Test 7: Migration Correctness on Copy of Real Data
# ---------------------------------------------------------------------------
def test_migration_correctness_on_copy_of_real_data(db: Session, tenant: Tenant):
    """
    Requirement 7 & 8: Migration of BusinessBrain and Knowledge into Facts Store
    with zero data loss, preserving all fields, and leaving original rows intact.
    """
    fact_svc = FactService(db)

    # 1. Create realistic source BusinessBrain and Knowledge
    brain = BusinessBrain(
        tenant_id=tenant.id,
        version=1,
        identity={"name": "المنذر تكنولوجي", "description": "حلول الأنظمة المحاسبية والشبكات"},
        products={
            "الموظف الذكي": {"name": "الموظف الذكي", "price": 1000},
            "برنامج ناظم المحاسبي": {"name": "برنامج ناظم المحاسبي", "price": 500},
        },
        services={"الدعم الفني والربط": {"name": "الدعم الفني والربط"}},
        pricing={"subscription": "سنوي"},
        operations={
            "branches": ["صنعاء", "عدن"],
            "working_hours": "من 9 صباحاً حتى 5 مساءً",
        },
        policies={"trial": "14 يوم تجربة مجانية"},
        goals={"q4_target": "توسيع الانتشار في 5 محافظات"},
    )
    db.add(brain)

    k_row = Knowledge(
        tenant_id=tenant.id,
        title="دليل التثبيت",
        content="خطوات تثبيت برنامج ناظم على السيرفر المحلي",
        knowledge_type="technical",
        status="active",
        metadata_json={"visibility": "public"},
    )
    db.add(k_row)
    db.commit()

    # 2. Execute migration for this tenant
    res = fact_svc.migrate_business_brains_and_knowledge_to_facts(tenant_id=tenant.id)
    assert res["migrated_facts_count"] >= 8

    # 3. Verify facts in database
    facts = db.scalars(select(Fact).where(Fact.tenant_id == tenant.id)).all()
    topics = [f.topic for f in facts]
    subjects = [f.subject for f in facts]

    assert "company.identity" in topics
    assert "اسم المنشأة" in subjects
    assert any("الموظف الذكي" in s for s in subjects)
    assert any("ناظم" in s for s in subjects)
    assert "pricing.general" in topics
    assert "operations.branches" in topics
    assert "operations.working_hours" in topics
    assert "company.goals" in topics

    # Verify goals is private
    goals_fact = next(f for f in facts if f.topic == "company.goals")
    assert goals_fact.visibility == "private"

    # Verify knowledge migrated
    assert any("دليل التثبيت" in s for s in subjects)

    # 4. Verify ZERO DATA LOSS on source tables (BusinessBrain and Knowledge remain 100% intact)
    orig_brain = db.scalar(select(BusinessBrain).where(BusinessBrain.tenant_id == tenant.id))
    assert orig_brain is not None
    assert orig_brain.identity["name"] == "المنذر تكنولوجي"

    orig_k = db.scalar(select(Knowledge).where(Knowledge.tenant_id == tenant.id))
    assert orig_k is not None
    assert orig_k.title == "دليل التثبيت"

    # 5. Requirement 3: All migrated facts have source="migrated" and status="pending_confirmation"
    for f in facts:
        assert f.source == "migrated"
        assert f.status == "pending_confirmation"

    # Customer retrieval must not return unconfirmed migrated facts
    customer_facts = fact_svc.get_relevant_facts(tenant_id=tenant.id, include_private=False)
    assert len(customer_facts) == 0


# ---------------------------------------------------------------------------
# Test 8: Owner Corrects Auto-Confirmed Fact Preserves History (Item 6)
# ---------------------------------------------------------------------------
def test_owner_corrects_auto_confirmed_fact_preserves_history(db: Session, tenant: Tenant):
    """
    Item 6: When the owner states a fact directly, it is auto-confirmed with a read-back.
    When the owner later corrects that fact, the old fact is superseded (superseded_by set,
    status='superseded') and the new corrected fact becomes confirmed, fully preserving history.
    """
    fact_svc = FactService(db)

    # 1. Owner directly declares branches: auto-confirmed with read-back
    item = ExtractedFactItem(
        topic="operations.branches",
        subject="فروع المنشأة",
        value={"branches": ["صنعاء", "الحديدة"]},
        visibility="public",
        is_direct_unambiguous=True,
    )
    save_res = fact_svc.save_extracted_facts(tenant.id, [item], auto_confirm_direct=True)
    assert len(save_res["confirmed"]) == 1
    original_fact = save_res["confirmed"][0]
    assert original_fact.status == "confirmed"
    assert original_fact.source == "owner_stated"
    assert original_fact.superseded_by is None
    original_fact_id = original_fact.id

    # 2. Owner sends a correction: updates branches
    corrected_val = {"branches": ["صنعاء", "عدن", "تعز"]}
    corrected_fact = fact_svc.correct_fact(
        tenant_id=tenant.id,
        fact_id=original_fact_id,
        corrected_value=corrected_val,
    )

    # 3. Verify the new fact is confirmed and active
    assert corrected_fact.id != original_fact_id
    assert corrected_fact.status == "confirmed"
    assert corrected_fact.source == "owner_confirmed"
    assert corrected_fact.value == corrected_val
    assert corrected_fact.superseded_by is None

    # 4. Verify history preservation: original fact still exists in DB as superseded
    db.expire_all()
    orig_in_db = db.scalar(select(Fact).where(Fact.id == original_fact_id))
    assert orig_in_db is not None
    assert orig_in_db.status == "superseded"
    assert orig_in_db.superseded_by == corrected_fact.id
    assert orig_in_db.value == {"branches": ["صنعاء", "الحديدة"]}

    # 5. Customer retrieval returns ONLY the active corrected fact, not the superseded one
    active_facts = fact_svc.get_relevant_facts(tenant.id, query="فروع", include_private=False)
    assert len(active_facts) == 1
    assert active_facts[0].id == corrected_fact.id
    assert active_facts[0].value == corrected_val


def test_owner_runtime_learning_queries_and_conflict_resolution(
    db: Session, tenant: Tenant, channel: Channel
):
    """
    Verifies the end-to-end runtime owner flow through the real entry point:
    1. Business declaration: company name, description, products, coverage cities.
    2. Products catalog query: answered strictly from Facts Store.
    3. Conflicting company name declaration: creates conflict, does not overwrite silently.
    4. Additive delivery coverage declaration: merges governorate, keeps others, supersedes old.
    5. Delivery coverage query: returns all 7 cities.
    6. Product price query: states price not recorded, no invented features or irrelevant categories.
    """
    owner_user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"owner_{uuid4().hex[:8]}@example.com",
        role="owner",
        name="Owner Tester",
        status="active",
    )
    db.add(owner_user)
    db.commit()

    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Owner Management Chat",
        channel_id=channel.id,
    )

    mock_provider = MockAIProvider(reply="رد اختباري")
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_provider)

    # Turn 1: Business declaration
    msg1 = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content=(
            "اسم شركتنا المنذر تكنولوجي، شركة برمجيات وشبكات وتقنيات حاسوب. "
            "نبيع ثلاثة منتجات: الموظف الذكي، وبرنامج ناظم المحاسبي، وبرنامج سيرو لإدارة الشبكات والتحكم الكامل بها. "
            "نخدم صنعاء والحديدة وذمار وإب والمحويت وريمة."
        ),
        metadata_json={"is_owner": True},
    )
    res1 = engine.process_incoming_message(tenant.id, msg1.id)
    assert res1.success is True
    assert "تم استيعاب وتوثيق البيانات في قاعدة الحقائق بنجاح" in res1.reply_content
    assert "المنذر تكنولوجي" in res1.reply_content
    assert "الموظف الذكي" in res1.reply_content
    assert "ناظم" in res1.reply_content
    assert "سيرو" in res1.reply_content

    db.expire_all()
    initial_facts = db.scalars(
        select(Fact).where(Fact.tenant_id == tenant.id, Fact.status == "confirmed")
    ).all()
    assert len(initial_facts) >= 5

    # Turn 2: Product query ("ما هي منتجاتنا؟")
    msg2 = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="ما هي منتجاتنا؟",
        metadata_json={"is_owner": True},
    )
    res2 = engine.process_incoming_message(tenant.id, msg2.id)
    assert res2.success is True
    assert "قائمة المنتجات المعتمدة" in res2.reply_content
    assert "الموظف الذكي" in res2.reply_content
    assert "ناظم" in res2.reply_content
    assert "سيرو" in res2.reply_content

    # Turn 3: Conflicting company name declaration
    msg3 = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="اسم شركتنا المنذر للتقنية",
        metadata_json={"is_owner": True},
    )
    res3 = engine.process_incoming_message(tenant.id, msg3.id)
    assert res3.success is True
    assert "تعارض" in res3.reply_content
    assert "المنذر تكنولوجي" in res3.reply_content
    assert "المنذر للتقنية" in res3.reply_content

    db.expire_all()
    conflicts = db.scalars(
        select(Fact).where(Fact.tenant_id == tenant.id, Fact.status == "conflict")
    ).all()
    assert len(conflicts) == 1
    assert "المنذر للتقنية" in str(conflicts[0].value)

    # Turn 4: Additive coverage declaration ("لا، نخدم أيضًا محافظة عمران")
    msg4 = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="لا، نخدم أيضًا محافظة عمران",
        metadata_json={"is_owner": True},
    )
    res4 = engine.process_incoming_message(tenant.id, msg4.id)
    assert res4.success is True
    assert "عمران" in res4.reply_content

    db.expire_all()
    active_cov = db.scalar(
        select(Fact).where(
            Fact.tenant_id == tenant.id,
            Fact.topic.in_(["operations.delivery_zones", "operations.coverage"]),
            Fact.status == "confirmed",
            Fact.superseded_by.is_(None),
        )
    )
    assert active_cov is not None
    cities_in_val = active_cov.value if isinstance(active_cov.value, list) else active_cov.value.get("cities", [])
    assert "عمران" in cities_in_val
    assert "صنعاء" in cities_in_val
    assert len(cities_in_val) == 7

    # Turn 5: Coverage query ("ما هي المدن التي نخدمها؟")
    msg5 = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="ما هي المدن التي نخدمها؟",
        metadata_json={"is_owner": True},
    )
    res5 = engine.process_incoming_message(tenant.id, msg5.id)
    assert res5.success is True
    for c in ["صنعاء", "الحديدة", "ذمار", "إب", "المحويت", "ريمة", "عمران"]:
        assert c in res5.reply_content

    # Turn 6: Specific product price query ("كم سعر ناظم؟")
    msg6 = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="كم سعر ناظم؟",
        metadata_json={"is_owner": True},
    )
    res6 = engine.process_incoming_message(tenant.id, msg6.id)
    assert res6.success is True
    assert "السعر الخاص بـ" in res6.reply_content
    assert "غير مسجل حالياً" in res6.reply_content
    # Must not hallucinate or ask about heat regulators or lighting
    assert "حرارة" not in res6.reply_content
    assert "إنارة" not in res6.reply_content


@pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GROQ_API_KEY")),
    reason="Live AI Provider API key not available in environment",
)
def test_live_model_facts_extraction_smoke(db: Session, tenant: Tenant):
    """
    Optional live-model smoke test exercising real AIProvider structured JSON extraction.
    Skipped automatically if no live API key is configured.
    """
    from packages.ai_providers.factory import AIProviderFactory
    from packages.services.fact_service import FactService

    provider = AIProviderFactory.create_resilient_provider(tenant_id=tenant.id, db=db)
    assert provider is not None

    fact_svc = FactService(db)
    res = fact_svc.extract_facts(
        tenant_id=tenant.id,
        message_text="اسم شركتنا المنذر تكنولوجي، نبيع برنامج ناظم المحاسبي وبرنامج سيرو للشبكات.",
        provider=provider,
    )
    assert res is not None
    assert len(res.facts) >= 2

