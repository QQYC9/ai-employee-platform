"""
Comprehensive Pytest Suite for Phase 3: Adaptive Owner Onboarding Interview.

All tests go through the REAL router -> engine path with deterministic mocking
(and Arabic text exactly as written), verifying:
1. Honey-shop vs. software-company produces different topic sets.
2. Yemen follow-up chain and negative branch closure.
3. Multi-topic answer coverage in a single owner message.
4. Skip / 'لا أعلم' / 'لا ينطبق' handling.
5. Pause and resume days later + 'وش باقي؟' progress summary.
6. Unrelated owner question during interview is answered and interview state preserved.
7. Go-live gate: interview_required blocks customer messages until threshold, existing tenants unaffected.
8. Tenant isolation for interview tables.
9. Verbatim product names and no invented descriptions regression inside interview.
10. Live-model smoke test (skipped if no API key).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.domain import (
    AuditEvent,
    BusinessBrain,
    Channel,
    Conversation,
    Customer,
    Fact,
    InterviewState,
    InterviewTopic,
    Message,
    User,
)
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.interview_service import InterviewService


class MockAIProvider:
    """Mock AI Provider for deterministic real-path testing."""

    def __init__(self, reply: str = ""):
        self.reply = reply
        self.last_prompt = ""
        self.last_system_instruction = ""
        self.call_count = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return self.reply

    def generate_json(self, prompt: str, schema: type = None, **kwargs) -> dict:
        self.call_count += 1
        return {}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()


def _create_tenant_and_channel(
    db: Session,
    name: str = "Test Tenant",
    interview_required: bool = False,
    connection_code: str | None = None,
    owner_sender_id: str = "967770000001",
) -> dict:
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=f"tenant-{uuid4().hex[:8]}",
        status="active",
        interview_required=interview_required,
        interview_threshold=80.0,
    )
    db.add(tenant)
    db.flush()

    owner_user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"owner_{uuid4().hex[:6]}@example.com",
        name="Owner User",
        role="tenant_owner",
        status="active",
    )
    db.add(owner_user)

    channel_id = uuid4()
    channel_cfg = {
        "bot_token": "token_123",
        "owner_identifiers": [owner_sender_id],
        "owner_sender_ids": [owner_sender_id],
    }
    if connection_code:
        channel_cfg["connection_code"] = connection_code

    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config=channel_cfg,
    )
    db.add(channel)

    brain = BusinessBrain(
        tenant_id=tenant_id,
        identity={"name": name},
        products={},
        services={},
        pricing={},
        operations={},
        policies={},
    )
    db.add(brain)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "owner_user": owner_user,
        "channel_id": channel_id,
        "owner_sender_id": owner_sender_id,
        "connection_code": connection_code,
    }


def _replay_inbound(
    db: Session,
    tenant_id: UUID,
    channel_id: UUID,
    sender_id: str,
    content: str,
) -> Message:
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=sender_id,
        sender_name="Sender",
        content=content,
        content_type="text",
        raw_payload={"text": content, "from": {"id": sender_id}},
    )
    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()
    return msg


# ---------------------------------------------------------------------------
# Test 1: Honey-shop vs Software-company Produce Different Topic Sets
# ---------------------------------------------------------------------------

def test_different_profiles_produce_different_topic_sets(db: Session):
    """
    A honey shop and a software company must produce completely different
    topic sets with NO code changes per business type.
    """
    interview_svc = InterviewService(db)
    tenant_id = uuid4()

    # Profile 1: Honey Shop in Yemen
    honey_profile = {
        "owner_name": "أبو عبدالله",
        "owner_role": "المالك والمؤسس",
        "entity_type": "متجر فعلي",
        "country": "اليمن",
        "field_of_activity": "تجارة العسل الطبيعي والمناحل",
        "tags": ["honey", "retail", "shop", "Yemen"],
    }
    honey_plan = interview_svc.generate_topic_plan(tenant_id, honey_profile)
    honey_slugs = {t.slug for t in honey_plan.topics}

    # Profile 2: Software Company in Saudi Arabia
    software_profile = {
        "owner_name": "المهندس منذر",
        "owner_role": "المدير التنفيذي",
        "entity_type": "شركة",
        "country": "المملكة العربية السعودية",
        "field_of_activity": "تطوير البرمجيات والأنظمة المحاسبية والشبكات",
        "tags": ["software", "company", "b2b", "development", "Saudi Arabia"],
    }
    software_plan = interview_svc.generate_topic_plan(tenant_id, software_profile)
    software_slugs = {t.slug for t in software_plan.topics}

    # 1. Assert Honey-specific topics exist only for Honey
    assert "honey_types" in honey_slugs
    assert "packaging_sizes" in honey_slugs
    assert "authenticity_guarantee" in honey_slugs
    assert "honey_storage" in honey_slugs

    assert "honey_types" not in software_slugs
    assert "authenticity_guarantee" not in software_slugs

    # 2. Assert Software-specific topics exist only for Software
    assert "target_clients" in software_slugs
    assert "software_licenses" in software_slugs
    assert "support_sla_policy" in software_slugs

    assert "software_licenses" not in honey_slugs
    assert "support_sla_policy" not in honey_slugs

    # 3. Assert Yemen delivery ladder exists for Yemen honey shop
    assert "delivery_zones_yemen" in honey_slugs
    assert "international_shipping" in honey_slugs

    # The topic sets must be distinct
    assert honey_slugs != software_slugs


# ---------------------------------------------------------------------------
# Test 2: Yemen Follow-Up Chain & Negative Answer Branch Closure
# ---------------------------------------------------------------------------

def test_yemen_follow_up_chain_and_negative_branch_closure(db: Session):
    """
    The Yemen follow-up chain appears after the owner says Yemen;
    answering 'لا' to international delivery closes that branch.
    """
    setup = _create_tenant_and_channel(db, name="مناحل البركة للعسل")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    mock_ai = MockAIProvider()
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    # 1. Start interview
    msg0 = _replay_inbound(db, tenant_id, channel_id, owner_id, "ابدأ التعارف")
    res0 = engine.process_incoming_message(tenant_id, msg0.id)
    assert "ما هو اسمك الكريم؟" in res0.reply_content

    # 2. Q1 answer: Owner Name
    msg1 = _replay_inbound(db, tenant_id, channel_id, owner_id, "أنا أحمد البركة")
    res1 = engine.process_incoming_message(tenant_id, msg1.id)
    assert "أحمد البركة" in res1.reply_content
    assert "ما هو دورك" in res1.reply_content

    # 3. Q2 answer: Role
    msg2 = _replay_inbound(db, tenant_id, channel_id, owner_id, "صاحب المنشأة والمؤسس")
    res2 = engine.process_incoming_message(tenant_id, msg2.id)
    assert "طبيعة منشأتكم" in res2.reply_content

    # 4. Q3 answer: Entity Type
    msg3 = _replay_inbound(db, tenant_id, channel_id, owner_id, "متجر فعلي ومحل لبيع العسل")
    res3 = engine.process_incoming_message(tenant_id, msg3.id)
    assert "في أي دولة تعمل منشأتكم" in res3.reply_content

    # 5. Q4 answer: Country (Yemen) and Field (Honey)
    msg4 = _replay_inbound(db, tenant_id, channel_id, owner_id, "اليمن - تجارة العسل الطبيعي والمناحل")
    res4 = engine.process_incoming_message(tenant_id, msg4.id)

    # Stage 1 Complete: verify Yemen follow-up topics are planned
    topics = db.scalars(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)).all()
    topic_slugs = {t.slug for t in topics}
    assert "delivery_zones_yemen" in topic_slugs
    assert "between_governorates_yemen" in topic_slugs
    assert "international_shipping" in topic_slugs
    assert "international_shipping_details" in topic_slugs

    # Set up topic state to ask international_shipping
    intl_shipping = next(t for t in topics if t.slug == "international_shipping")
    intl_shipping.status = "asked"
    state = db.scalar(select(InterviewState).where(InterviewState.tenant_id == tenant_id))
    state.current_topic_slug = "international_shipping"
    db.commit()

    # Answer 'لا' to international delivery
    msg_no = _replay_inbound(db, tenant_id, channel_id, owner_id, "لا، لا نوفر شحن دولي خارج اليمن")
    res_no = engine.process_incoming_message(tenant_id, msg_no.id)
    assert res_no.success is True

    # Verify international_shipping is answered, and dependent international_shipping_details is marked not_applicable!
    db.expire_all()
    t_intl = db.scalar(
        select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "international_shipping")
    )
    t_intl_det = db.scalar(
        select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "international_shipping_details")
    )
    assert t_intl.status in ("not_applicable", "skipped")
    assert t_intl_det.status == "not_applicable", "Answering 'لا' must close the whole dependent branch"


# ---------------------------------------------------------------------------
# Test 3: Multi-Topic Answer Covering in a Single Message
# ---------------------------------------------------------------------------

def test_single_owner_message_covers_multiple_topics_and_advances(db: Session):
    """
    One owner message covering products, prices and cities marks those topics covered,
    and the next question is a different one.
    """
    setup = _create_tenant_and_channel(db, name="منشأة التجربة")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    # Fast forward into interviewing stage with planned topics
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    profile = {
        "owner_name": "سالم",
        "owner_role": "مالك",
        "entity_type": "شركة",
        "country": "اليمن",
        "field_of_activity": "برمجيات",
        "tags": ["software", "company"],
    }
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)
    db.commit()

    # Set current topic as identity
    state.current_topic_slug = "identity"
    db.commit()

    mock_ai = MockAIProvider()
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    # Owner reply covers: Company name + Products + Prices + Cities in ONE message!
    multi_reply = "نحن شركة المنذر تكنولوجي، نقدم برنامج ناظم المحاسبي بسعر 500 ريال وبرنامج سيرو بسعر 800 ريال ونخدم صنعاء وعدن"
    msg = _replay_inbound(db, tenant_id, channel_id, owner_id, multi_reply)
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    db.expire_all()
    t_identity = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "identity"))
    t_products = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "products_services_prices"))
    t_coverage = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug.in_(["delivery_coverage", "service_coverage"])))

    # All 3 topics must be marked answered!
    assert t_identity.status == "answered"
    assert t_products.status == "answered"
    assert t_coverage.status == "answered"

    # Next question asked must be a DIFFERENT topic (not identity, products, or coverage)
    assert "الاسم التجاري" not in res.reply_content
    assert "قائمتها وأسعارها" not in res.reply_content


# ---------------------------------------------------------------------------
# Test 4: Skip / 'لا أعلم' / 'لا ينطبق' Handling
# ---------------------------------------------------------------------------

def test_skip_and_not_applicable_handling(db: Session):
    """
    Understand 'لا أعلم' / 'تخطى' (marks skipped) and 'لا ينطبق' (marks not_applicable).
    """
    setup = _create_tenant_and_channel(db, name="متجر الإتقان")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    profile = {"owner_name": "سامي", "tags": ["shop"]}
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # 1. Topic 'branches_hours' asked -> Owner replies 'لا ينطبق'
    state.current_topic_slug = "branches_hours"
    db.commit()
    msg_na = _replay_inbound(db, tenant_id, channel_id, owner_id, "لا ينطبق علينا، نحن متجر إلكتروني فقط")
    res_na = engine.process_incoming_message(tenant_id, msg_na.id)
    assert res_na.success is True
    assert "لا ينطبق" in res_na.reply_content

    db.expire_all()
    t_branches = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "branches_hours"))
    assert t_branches.status == "not_applicable"

    # 2. Next topic asked -> Owner replies 'تخطى' / 'لا أعلم'
    state.current_topic_slug = "authority_limits"
    db.commit()
    msg_skip = _replay_inbound(db, tenant_id, channel_id, owner_id, "لا أعلم، تخطى هذا السؤال حالياً")
    res_skip = engine.process_incoming_message(tenant_id, msg_skip.id)
    assert res_skip.success is True
    assert "تخطي" in res_skip.reply_content

    db.expire_all()
    t_auth = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "authority_limits"))
    assert t_auth.status == "skipped"


# ---------------------------------------------------------------------------
# Test 5: Pause, Resume Days Later & 'وش باقي؟' Progress Summary
# ---------------------------------------------------------------------------

def test_pause_resume_days_later_and_progress_summary(db: Session):
    """
    Pause, then resume days later continues correctly; progress summary on 'وش باقي؟'.
    """
    setup = _create_tenant_and_channel(db, name="شركة المستقبل")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    profile = {"owner_name": "ماجد", "tags": ["software"]}
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)

    # Mark 3 topics answered
    for slug in ("identity", "products_services_prices", "ordering_payment"):
        t = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == slug))
        if t:
            t.status = "answered"
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # 1. Ask for progress: "وش باقي؟"
    msg_prog = _replay_inbound(db, tenant_id, channel_id, owner_id, "وش باقي؟")
    res_prog = engine.process_incoming_message(tenant_id, msg_prog.id)
    assert res_prog.success is True
    assert "ملخص تقدم التعارف" in res_prog.reply_content
    assert "المواضيع المكتملة" in res_prog.reply_content

    # 2. Simulate passage of 5 days
    past_date = datetime.now(timezone.utc) - timedelta(days=5)
    state.last_interaction_at = past_date
    db.add(state)
    db.commit()

    # 3. Resume interview: "كمّل التعارف"
    msg_resume = _replay_inbound(db, tenant_id, channel_id, owner_id, "كمّل التعارف")
    res_resume = engine.process_incoming_message(tenant_id, msg_resume.id)
    assert res_resume.success is True
    assert "مرحباً بك مجدداً! لنواصل التعارف من حيث توقفنا" in res_resume.reply_content


# ---------------------------------------------------------------------------
# Test 6: Unrelated Owner Question During Interview is Answered
# ---------------------------------------------------------------------------

def test_unrelated_owner_question_answered_and_state_preserved(db: Session):
    """
    An unrelated owner question during the interview is answered,
    and the interview state is kept intact.
    """
    setup = _create_tenant_and_channel(db, name="مؤسسة الريادة")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    state.current_topic_slug = "delivery_coverage"
    profile = {"owner_name": "عمر", "tags": ["retail"]}
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)
    db.commit()

    # Model returns answer to the off-topic question
    mock_ai = MockAIProvider(reply="الوقت الحالي هو الرابعة مساءً.")
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    # Owner asks unrelated off-topic question
    msg_off = _replay_inbound(db, tenant_id, channel_id, owner_id, "كم الساعة الآن لديك؟")
    res_off = engine.process_incoming_message(tenant_id, msg_off.id)
    assert res_off.success is True

    # 1. Verify question was answered
    assert "الوقت الحالي هو الرابعة مساءً" in res_off.reply_content

    # 2. Verify reminder to continue interview is attached
    assert "محادثة التعارف قيد الانتظار" in res_off.reply_content
    assert "كمّل التعارف" in res_off.reply_content

    # 3. Verify interview state is PRESERVED and still active
    db.expire_all()
    refreshed_state = db.scalar(select(InterviewState).where(InterviewState.tenant_id == tenant_id))
    assert refreshed_state.is_active is True
    assert refreshed_state.stage == "interviewing"
    assert refreshed_state.current_topic_slug == "delivery_coverage"


# ---------------------------------------------------------------------------
# Test 7: Go-Live Gate Enforcement and Existing Tenants Unaffected
# ---------------------------------------------------------------------------

def test_go_live_gate_enforcement_and_existing_tenants_unaffected(db: Session):
    """
    Gate: an interview_required tenant with low coverage gets the neutral customer reply;
    after enough critical coverage, replies are normal; an existing tenant is unaffected.
    """
    # 1. Tenant A: interview_required = True (New tenant)
    setup_a = _create_tenant_and_channel(db, name="New Gated Tenant", interview_required=True)
    tenant_a = setup_a["tenant_id"]
    channel_a = setup_a["channel_id"]

    interview_svc = InterviewService(db)
    plan_a = interview_svc.generate_topic_plan(tenant_a, {"tags": ["general"]})
    interview_svc.store_planned_topics(tenant_a, plan_a.topics)
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider(reply="مرحبًا بك! نحن في خدمتك."))

    # Customer message to Tenant A (Coverage is 0% < 80% threshold)
    msg_cust_a = _replay_inbound(db, tenant_a, channel_a, "customer_001", "مرحبًا، هل المتجر مفتوح؟")
    res_cust_a = engine.process_incoming_message(tenant_a, msg_cust_a.id)
    assert res_cust_a.success is True

    # MUST receive neutral Arabic reply
    assert "نجهّز الخدمة حاليًا، سنتواصل معك قريبًا" in res_cust_a.reply_content

    # Verify audit event was logged
    audit = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_a,
            AuditEvent.event_type == "customer_query_blocked_by_interview_gate",
        )
    )
    assert audit is not None

    # Now answer critical topics for Tenant A to surpass 80% threshold
    crit_topics = db.scalars(
        select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_a, InterviewTopic.criticality >= 4)
    ).all()
    for t in crit_topics:
        t.status = "answered"
    db.commit()

    # Customer message to Tenant A after threshold met -> normal reply!
    msg_cust_a2 = _replay_inbound(db, tenant_a, channel_a, "customer_002", "مرحبًا، هل المتجر مفتوح؟")
    res_cust_a2 = engine.process_incoming_message(tenant_a, msg_cust_a2.id)
    assert res_cust_a2.success is True
    assert "نجهّز الخدمة حاليًا" not in res_cust_a2.reply_content
    assert "مرحبًا بك! نحن في خدمتك." in res_cust_a2.reply_content

    # 2. Tenant B: interview_required = False (Existing tenant)
    setup_b = _create_tenant_and_channel(db, name="Existing Tenant", interview_required=False)
    tenant_b = setup_b["tenant_id"]
    channel_b = setup_b["channel_id"]

    # Customer message to Tenant B -> normal reply without any gate block!
    msg_cust_b = _replay_inbound(db, tenant_b, channel_b, "customer_003", "أهلاً وسهلاً")
    res_cust_b = engine.process_incoming_message(tenant_b, msg_cust_b.id)
    assert res_cust_b.success is True
    assert "نجهّز الخدمة حاليًا" not in res_cust_b.reply_content
    assert "مرحبًا بك! نحن في خدمتك." in res_cust_b.reply_content


# ---------------------------------------------------------------------------
# Test 8: Tenant Isolation for Interview Tables
# ---------------------------------------------------------------------------

def test_tenant_isolation_for_interview_tables(db: Session):
    """
    Every new table has tenant_id plus a tenant-isolation test.
    Tenant A's topics and state are strictly invisible to Tenant B.
    """
    setup1 = _create_tenant_and_channel(db, name="Tenant Isolation 1")
    setup2 = _create_tenant_and_channel(db, name="Tenant Isolation 2")
    t1 = setup1["tenant_id"]
    t2 = setup2["tenant_id"]

    svc = InterviewService(db)
    s1 = svc.get_or_create_state(t1)
    s2 = svc.get_or_create_state(t2)
    s1.classification_answers = {"owner_name": "مالك 1"}
    s2.classification_answers = {"owner_name": "مالك 2"}

    plan1 = svc.generate_topic_plan(t1, {"tags": ["honey"]})
    svc.store_planned_topics(t1, plan1.topics)

    plan2 = svc.generate_topic_plan(t2, {"tags": ["software"]})
    svc.store_planned_topics(t2, plan2.topics)
    db.commit()

    # Query topics for T1
    t1_topics = db.scalars(select(InterviewTopic).where(InterviewTopic.tenant_id == t1)).all()
    t1_slugs = {t.slug for t in t1_topics}
    assert "honey_types" in t1_slugs
    assert "software_licenses" not in t1_slugs

    # Query topics for T2
    t2_topics = db.scalars(select(InterviewTopic).where(InterviewTopic.tenant_id == t2)).all()
    t2_slugs = {t.slug for t in t2_topics}
    assert "software_licenses" in t2_slugs
    assert "honey_types" not in t2_slugs

    # Verify no cross-tenant leakage in state
    assert svc.get_or_create_state(t1).classification_answers["owner_name"] == "مالك 1"
    assert svc.get_or_create_state(t2).classification_answers["owner_name"] == "مالك 2"


# ---------------------------------------------------------------------------
# Test 9: Verbatim Product Names and No Invented Descriptions in Interview
# ---------------------------------------------------------------------------

def test_verbatim_product_names_and_no_invented_descriptions_in_interview(db: Session):
    """
    Keep product names verbatim in extraction and never store invented descriptions
    (regression test inside an interview scenario).
    """
    setup = _create_tenant_and_channel(db, name="شركة التقنية المتقدمة")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    state.current_topic_slug = "products_services_prices"
    plan = interview_svc.generate_topic_plan(tenant_id, {"tags": ["software"]})
    interview_svc.store_planned_topics(tenant_id, plan.topics)
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # Owner reply provides exact product name without description
    prod_reply = "منتجنا المعتمد هو الموظف الذكي"
    msg = _replay_inbound(db, tenant_id, channel_id, owner_id, prod_reply)
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    # Check stored facts
    db.expire_all()
    prod_facts = db.scalars(
        select(Fact).where(
            Fact.tenant_id == tenant_id,
            Fact.topic.like("product.%"),
            Fact.status == "confirmed",
        )
    ).all()
    assert len(prod_facts) >= 1

    stored_fact = prod_facts[0]
    # Name must be verbatim 'الموظف الذكي' (not embellished into 'برنامج للموظف الذكي')
    assert stored_fact.subject == "الموظف الذكي"
    val = stored_fact.value
    if isinstance(val, dict):
        desc = val.get("description", "")
        # Zero invented descriptions
        assert desc in ("", "الموظف الذكي")


# ---------------------------------------------------------------------------
# Test 10: Live Model Smoke Test (Skipped when no API key is set)
# ---------------------------------------------------------------------------

def test_live_model_adaptive_interview_smoke(db: Session):
    """
    Live-model smoke test, skipped when no API key is set.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("No live API key set (GEMINI_API_KEY / OPENROUTER_API_KEY); skipping live smoke test.")

    from packages.ai_providers.gemini_provider import GeminiProvider
    provider = GeminiProvider(api_key=api_key)

    interview_svc = InterviewService(db)
    tenant_id = uuid4()
    profile = {
        "owner_name": "سعد",
        "owner_role": "مؤسس",
        "entity_type": "متجر عسل",
        "country": "اليمن",
        "field_of_activity": "عسل سدر يمني طبيعي",
        "tags": ["honey", "retail", "Yemen"],
    }
    plan = interview_svc.generate_topic_plan(tenant_id, profile, ai_provider=provider)
    assert plan.topics and len(plan.topics) >= 5
    slugs = {t.slug for t in plan.topics}
    assert "identity" in slugs
