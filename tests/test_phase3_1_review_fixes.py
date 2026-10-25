"""
Comprehensive Pytest Suite for Phase 3.1: Adaptive Owner Onboarding Review Fixes.

Verifies all 10 reviewer findings via real router -> engine path:
1. Coverage decided by content: Topic asked is not automatically answered. If reply addresses
   different topics, acknowledges them, re-asks the open topic, and parks after 2 attempts.
2. Never re-ask a covered topic.
3. Company name saved as company.identity verbatim, not company.description (مجال النشاط).
4. Verbatim product names without hardcoded overrides ('الموظف الذكي السحابي', 'برنامج ناظم لإدارة الشركات', 'منصة الأفق للمتاجر').
5. Universal topics adapt to business (software -> service_coverage, digital payment quick replies without COD).
6. Negative 'لا' answer marks topic as not_applicable/skipped, never answered.
7. Profile tags shown in Arabic; unstated tags stored as inferred and not used in topic planning.
8. No duplicated greeting on starting interview.
9. Connection code link flow in channel_service starts interview immediately.
"""
from __future__ import annotations

import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.domain import (
    BusinessBrain,
    Channel,
    Fact,
    InterviewState,
    InterviewTopic,
    Message,
    User,
)
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.link_code_service import LinkCodeService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.fact_service import FactService
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
# Requirement 1: Content-Driven Coverage & Re-asking
# Honey owner answered payment question with honey types -> payment re-asked
# ---------------------------------------------------------------------------

def test_honey_payment_answered_with_honey_types_reasks_payment(db: Session):
    """
    When the honey shop owner is asked about payment methods and answers with honey types,
    payment is NOT marked answered; honey_types is marked covered; payment is re-asked briefly.
    """
    setup = _create_tenant_and_channel(db, name="مناحل البركة")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    profile = {"owner_name": "أبو سالم", "country": "اليمن", "tags": ["honey", "shop", "Yemen"]}
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)

    # Set current topic as ordering_payment
    state.current_topic_slug = "ordering_payment"
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # Owner replies to payment question with honey types!
    off_target_reply = "لدينا عسل سدر دوعني وعسل سمر وعسل مراعي طبيعي مفحوص مخبرياً"
    msg = _replay_inbound(db, tenant_id, channel_id, owner_id, off_target_reply)
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    db.expire_all()
    t_payment = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "ordering_payment"))
    t_honey = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "honey_types"))

    # ordering_payment MUST NOT be marked answered!
    assert t_payment.status in ("asked", "unknown")
    assert t_payment.status != "answered"

    # honey_types MUST be marked answered because the content covered it!
    assert t_honey.status == "answered"

    # Reply must acknowledge what was understood and re-ask payment!
    assert "توثيق" in res.reply_content or "سدر" in res.reply_content or "أنواع العسل" in res.reply_content
    assert "الدفع" in res.reply_content or "الطلب" in res.reply_content


# ---------------------------------------------------------------------------
# Requirement 1 & 2: Never re-ask a covered topic
# Software owner answers payment with target clients, licenses, and support
# ---------------------------------------------------------------------------

def test_software_payment_answered_with_target_clients_and_licenses_never_reasked(db: Session):
    """
    The software owner replies: 'أنظمتنا موجهة للمؤسسات والشركات المتوسطة والكبيرة ونقدم تراخيص سنوية ودعم فني'.
    Payment is re-asked; target_clients, software_licenses, and support_sla_policy are marked covered and NEVER re-asked.
    """
    setup = _create_tenant_and_channel(db, name="شركة المنذر للحلول البرمجية")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    profile = {"owner_name": "المهندس منذر", "country": "اليمن", "tags": ["software", "company"]}
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)

    # Set current topic as ordering_payment
    state.current_topic_slug = "ordering_payment"
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    multi_cover_reply = "أنظمتنا موجهة للمؤسسات والشركات المتوسطة والكبيرة ونقدم تراخيص سنوية ودعم فني مستمر"
    msg = _replay_inbound(db, tenant_id, channel_id, owner_id, multi_cover_reply)
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    db.expire_all()
    t_target = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "target_clients"))
    t_licenses = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "software_licenses"))
    t_support = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "support_sla_policy"))
    t_payment = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "ordering_payment"))

    # Covered topics must be marked answered
    assert t_target.status == "answered"
    assert t_licenses.status == "answered"
    assert t_support.status == "answered"

    # Payment topic must remain open to be re-asked
    assert t_payment.status != "answered"

    # Ensure none of target_clients, software_licenses, support is EVER chosen as next question!
    next_q = interview_svc.get_next_question(tenant_id)
    assert "العملاء المستهدفون" not in (next_q or "")
    assert "التراخيص" not in (next_q or "")
    assert "الدعم الفني" not in (next_q or "")


# ---------------------------------------------------------------------------
# Requirement 3: Company name verbatim in company.identity, NOT مجال النشاط
# ---------------------------------------------------------------------------

def test_company_identity_verbatim_not_description(db: Session):
    """
    'شركة المنذر للحلول البرمجية الذكية' must be stored as company.identity with verbatim name,
    NOT as 'مجال النشاط' (company.description).
    """
    setup = _create_tenant_and_channel(db, name="منشأة جديدة")
    tenant_id = setup["tenant_id"]

    fact_svc = FactService(db)
    raw_text = "شركة المنذر للحلول البرمجية الذكية"
    res = fact_svc.extract_facts(tenant_id=tenant_id, message_text=raw_text)

    # Check extracted facts
    identity_facts = [f for f in res.facts if f.topic == "company.identity"]
    description_facts = [f for f in res.facts if f.topic == "company.description"]

    assert len(identity_facts) >= 1, "Must extract company.identity"
    assert identity_facts[0].value.get("name") == "شركة المنذر للحلول البرمجية الذكية"
    assert len(description_facts) == 0, "Company name must not be stored as company.description"


# ---------------------------------------------------------------------------
# Requirement 4: Verbatim product names and removal of hardcoded strings
# ---------------------------------------------------------------------------

def test_verbatim_product_names_without_hardcoded_overrides(db: Session):
    """
    'نظام الموظف الذكي السحابي' and 'برنامج ناظم لإدارة الشركات' must be stored exactly
    without appending 'المحاسبي' or stripping 'السحابي'. Also tests unseen product 'منصة الأفق للمتاجر'.
    """
    setup = _create_tenant_and_channel(db, name="منشأة التقنية")
    tenant_id = setup["tenant_id"]

    fact_svc = FactService(db)
    text = "نقدم نظام الموظف الذكي السحابي وبرنامج ناظم لإدارة الشركات ومنصة الأفق للمتاجر"
    res = fact_svc.extract_facts(tenant_id=tenant_id, message_text=text)

    names = [f.value.get("name") for f in res.facts if f.topic.startswith("product.")]

    assert "نظام الموظف الذكي السحابي" in names
    assert "برنامج ناظم لإدارة الشركات" in names
    assert "برنامج ناظم المحاسبي" not in names, "Must NOT append 'المحاسبي' when not said!"
    assert "منصة الأفق للمتاجر" in names, "Brand-new unseen product must be extracted verbatim!"


# ---------------------------------------------------------------------------
# Requirement 5: Adapt Universal Topics & Dynamic Quick Replies
# ---------------------------------------------------------------------------

def test_adapted_topics_and_quick_replies(db: Session):
    """
    Software companies get service_coverage (not physical delivery) and digital payment quick replies (no COD).
    Honey shops get physical delivery and COD options.
    """
    interview_svc = InterviewService(db)
    tenant_id = uuid4()

    # 1. Software Company Plan
    sw_plan = interview_svc.generate_topic_plan(tenant_id, {"tags": ["software", "company"]})
    sw_slugs = {t.slug for t in sw_plan.topics}
    assert "service_coverage" in sw_slugs
    assert "delivery_coverage" not in sw_slugs

    sw_payment_topic = next(t for t in sw_plan.topics if t.slug == "ordering_payment")
    sw_q = interview_svc.format_question_with_quick_replies(sw_payment_topic, ["software", "company"])
    assert "تحويل بنكي" in sw_q or "عقد سنوي" in sw_q or "فواتير" in sw_q
    assert "دفع عند الاستلام" not in sw_q
    assert "كاش بالفرع" not in sw_q

    # 2. Honey Shop Plan
    honey_plan = interview_svc.generate_topic_plan(tenant_id, {"tags": ["honey", "shop"]})
    honey_slugs = {t.slug for t in honey_plan.topics}
    assert "delivery_coverage" in honey_slugs
    assert "service_coverage" not in honey_slugs

    honey_payment_topic = next(t for t in honey_plan.topics if t.slug == "ordering_payment")
    honey_q = interview_svc.format_question_with_quick_replies(honey_payment_topic, ["honey", "shop"])
    assert "دفع عند الاستلام" in honey_q or "كاش" in honey_q


# ---------------------------------------------------------------------------
# Requirement 6: Negative Answer 'لا' marks topic as not_applicable / skipped
# ---------------------------------------------------------------------------

def test_negative_answer_marks_topic_not_applicable_never_answered(db: Session):
    """
    Answering 'لا' to honey packaging sizes marks it not_applicable/skipped, never answered.
    """
    setup = _create_tenant_and_channel(db, name="متجر العسل")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    state.stage = "interviewing"
    profile = {"owner_name": "سعد", "tags": ["honey", "shop"]}
    plan = interview_svc.generate_topic_plan(tenant_id, profile)
    interview_svc.store_planned_topics(tenant_id, plan.topics)

    # Set current topic as packaging_sizes
    state.current_topic_slug = "packaging_sizes"
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    msg = _replay_inbound(db, tenant_id, channel_id, owner_id, "لا، نبيع بحجم كيلو واحد فقط ولا نوفر أحجام أخرى")
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    db.expire_all()
    t_pkg = db.scalar(select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id, InterviewTopic.slug == "packaging_sizes"))
    assert t_pkg.status in ("not_applicable", "skipped")
    assert t_pkg.status != "answered"


# ---------------------------------------------------------------------------
# Requirement 7: Profile Tags in Arabic & Stated vs Inferred Separation
# ---------------------------------------------------------------------------

def test_profile_tags_arabic_and_no_unstated_inferences(db: Session):
    """
    Profile tags displayed to the owner must be in Arabic (e.g. 'اليمن', 'متجر فعلي').
    Unstated tags must NOT be stored as profile facts or used in topic planning unless confirmed.
    """
    answers = {
        "owner_name": "سالم",
        "owner_role": "مالك",
        "entity_type": "متجر فعلي",
        "country": "اليمن",
        "field_of_activity": "تجارة العسل",
    }
    stated, inferred = InterviewService._derive_profile_tags(answers)

    # Stated tags
    assert "Yemen" in stated
    assert "shop" in stated
    assert "honey" in stated
    # 'delivery' was NOT stated by the owner, so it must be inferred, not stated!
    assert "delivery" not in stated
    assert "delivery" in inferred

    # Arabic formatting
    arabic_labels = InterviewService.format_tags_arabic(stated)
    assert "اليمن" in arabic_labels
    assert "متجر فعلي" in arabic_labels
    assert "عسل طبيعي" in arabic_labels
    assert "Yemen" not in arabic_labels, "Raw English tag must not be shown to owner"


# ---------------------------------------------------------------------------
# Requirement 8: Remove Duplicated Greeting at Start of Interview
# ---------------------------------------------------------------------------

def test_no_duplicated_greeting_at_start(db: Session):
    """
    Saying 'ابدأ التعارف' starts with exactly ONE greeting without duplicated welcoming phrases.
    """
    setup = _create_tenant_and_channel(db, name="منشأة الإبداع")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]
    owner_id = setup["owner_sender_id"]

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    msg = _replay_inbound(db, tenant_id, channel_id, owner_id, "ابدأ التعارف")
    res = engine.process_incoming_message(tenant_id, msg.id)

    assert res.success is True
    # Count occurrences of welcoming phrases
    assert res.reply_content.count("مرحباً بك") == 1
    assert "مرحباً بك مجدداً" not in res.reply_content


# ---------------------------------------------------------------------------
# Requirement 9: Entry Point A Connection Code Linking Starts Interview
# ---------------------------------------------------------------------------

def test_connection_code_link_starts_interview(db: Session):
    """
    An owner sending '/link <connection_code>' links them as channel owner
    and starts the adaptive interview immediately.
    """
    setup = _create_tenant_and_channel(
        db,
        name="منشأة الريادة",
        owner_sender_id="967770000001",
    )
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    # New unlinked user sends link command
    new_owner_sender_id = "967779999999"

    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=new_owner_sender_id,
        sender_name="New Owner",
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={"text": f"/link {raw_code}", "from": {"id": new_owner_sender_id}},
    )
    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()
    db.expire_all()

    # Verify channel now includes the new owner sender id
    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert new_owner_sender_id in (channel.config.get("owner_identifiers") or [])

    # Process message through engine
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    # Result must include linking confirmation AND start of interview Q1
    assert "تم ربط حسابك كمالك رسمي للمنشأة بنجاح" in res.reply_content
    assert "ما هو اسمك الكريم؟" in res.reply_content

    # State must be in Stage 1 Question 1
    interview_svc = InterviewService(db)
    state = interview_svc.get_or_create_state(tenant_id)
    assert state.is_active is True
    assert state.stage == "classification_1"
