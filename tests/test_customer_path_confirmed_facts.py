"""
Tests for Customer Path Answering from Confirmed Public Facts & Safe Handoffs.

Verifies:
  1. Products question ("ما هي منتجاتكم؟") answers from confirmed facts without handoff.
  2. Cities question ("وين تخدموا؟") answers from confirmed coverage facts without handoff.
  3. "ايش تبيعوا؟" answers from confirmed products facts without handoff.
  4. "عندكم فرع في صنعاء؟" blocked/handed off when no branch fact exists, and allowed when a branch fact exists.
  5. Hallucinated price of ناظم without price fact is blocked and handed off.
  6. Hallucinated free trial without trial fact is blocked and handed off.
  7. Hallucinated VAT/ZATCA tax support without tax fact is blocked and handed off.
  8. Handoff text is "هذا الاستفسار يحتاج تأكيدًا من الفريق، وسنعود إليك." and every handoff is logged in audit_events.
"""

from typing import Any
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.context.builder import ContextBuilder
from packages.context.models import TaskContext
from packages.models.domain import (
    AuditEvent,
    BusinessBrain,
    Channel,
    Conversation,
    Customer,
    Fact,
    Message,
    OutboxEvent,
)
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import (
    ConversationalAgentEngine,
    DEFAULT_HANDOFF_REPLY,
)
from packages.core.database import SessionLocal


class NaturalMockAIProvider:
    """Mock AI Provider that returns natural responses for testing real path."""

    def __init__(self, reply: str = ""):
        self.reply = reply
        self.last_prompt = ""
        self.last_system_instruction = ""
        self.called_count = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.called_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return self.reply

    def generate_json(self, *args, **kwargs) -> dict[str, Any]:
        return {}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()


@pytest.fixture
def test_setup(db: Session):
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="Tech Solutions Tenant",
        slug=f"tech-sol-{tenant_id.hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    brain = BusinessBrain(
        tenant_id=tenant_id,
        identity={"name": "المنذر للتقنية", "legal_name": "المنذر للتقنية"},
        products={
            "سيرو": {"description": "برنامج لإدارة الشبكات والتحكم الكامل"},
            "الموظف الذكي": {"description": "برنامج للموظف الذكي"},
            "ناظم المحاسبي": {"description": "برنامج لإدارة المحاسبة"},
        },
        services={},
        operations={},
        policies={},
    )
    db.add(brain)

    facts = [
        Fact(
            tenant_id=tenant_id,
            subject="اسم الشركة",
            topic="company.identity",
            value="المنذر تكنولوجي",
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="المدن التي نخدمها",
            topic="operations.coverage",
            value=["صنعاء", "الحديدة", "إب", "المحويت", "ريمة", "عمران"],
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="الموظف الذكي",
            topic="product.الموظف_الذكي",
            value={"description": "برنامج للموظف الذكي"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="برنامج سيرو لإدارة الشبكات والتحكم الكامل بها",
            topic="product.سيرو",
            value={"description": "برنامج لإدارة الشبكات والتحكم الكامل"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="برنامج ناظم المحاسبي",
            topic="product.ناظم_المحاسبي",
            value={"description": "برنامج لإدارة المحاسبة"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="مجال العمل",
            topic="company.industry",
            value=["برمجيات", "شبكات", "تقنيات حاسوب"],
            status="confirmed",
            visibility="public",
            source="owner",
        ),
    ]
    for f in facts:
        db.add(f)

    channel_id = uuid4()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Telegram Customer Channel",
        channel_type="telegram",
        status="active",
        config={
            "owner_sender_ids": ["967770000001", "owner_tg"],
            "bot_token": "token_123",
        },
    )
    db.add(channel)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "channel_id": channel_id,
    }


def _replay_inbound_message(db: Session, tenant_id: UUID, channel_id: UUID, sender_id: str, content: str) -> Message:
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=sender_id,
        sender_name="Customer User",
        content=content,
        content_type="text",
        raw_payload={"text": content, "from": {"id": sender_id}},
    )
    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()
    return msg


def test_customer_products_question_answers_naturally(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999001"

    # Natural model reply describing confirmed products
    natural_reply = (
        "مرحبًا بك! نحن في المنذر للتقنية نقدم المنتجات التالية:\n"
        "1. الموظف الذكي: برنامج يُسهل تنظيم أعمال الموظفين.\n"
        "2. برنامج سيرو لإدارة الشبكات والتحكم الكامل بها: حل شامل لإدارة الشبكات.\n"
        "3. برنامج ناظم المحاسبي: برنامج متكامل لإدارة المحاسبة وإصدار الفواتير.\n"
        "هل ترغب في معرفة تفاصيل إضافية؟"
    )
    mock_ai = NaturalMockAIProvider(reply=natural_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    # Replay through REAL path: inbound -> outbox -> engine
    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "ما هي منتجاتكم؟")
    assert inbound_msg.sender_type == "customer"
    assert inbound_msg.metadata_json.get("is_owner") is False

    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == natural_reply

    # Verify not blocked by guardrail
    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is not True


def test_customer_cities_question_answers_naturally(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999002"

    natural_reply = (
        "أهلاً بك! نحن نخدم العملاء في المدن والمحافظات التالية:\n"
        "- صنعاء\n"
        "- الحديدة\n"
        "- إب\n"
        "- المحويت\n"
        "- ريمة\n"
        "- عمران\n"
        "يسعدنا تواصلك وخدمتك في أي من هذه المناطق."
    )
    mock_ai = NaturalMockAIProvider(reply=natural_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "وين تخدموا؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == natural_reply

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is not True


def test_customer_ayna_tabiou_question_answers_naturally(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999003"

    natural_reply = (
        "أهلاً بك! نبيع برامج وحلول رقمية تشمل:\n"
        "- برنامج سيرو لإدارة الشبكات والتحكم الكامل بها\n"
        "- برنامج ناظم المحاسبي لإدارة العمليات المالية\n"
        "- الموظف الذكي\n"
        "أخبرنا بالنظام الذي يناسب نشاطك لنزودك بالتفاصيل."
    )
    mock_ai = NaturalMockAIProvider(reply=natural_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "ايش تبيعوا؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == natural_reply

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is not True


def test_customer_branch_sanaa_blocked_and_handed_off_when_no_fact(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999004"

    # Model hallucinates a branch in Sana'a when only coverage exists (no branch fact)
    hallucinated_branch_reply = "نعم، لدينا فرع في صنعاء بشارع الستين."
    mock_ai = NaturalMockAIProvider(reply=hallucinated_branch_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "عندكم فرع في صنعاء؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    # Must be replaced with the exact required handoff text
    assert res.reply_content == DEFAULT_HANDOFF_REPLY
    assert res.reply_content == "هذا الاستفسار يحتاج تأكيدًا من الفريق، وسنعود إليك."

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "Unverified location claim" in reply_msg.metadata_json.get("guardrail_reason", "")

    # Verify handoff event logged in queryable audit_events table
    audit_svc = AuditService(db)
    handoff_events = audit_svc.list_events(tenant_id=tenant_id, event_type="customer_inquiry_handoff")
    assert len(handoff_events) >= 1
    latest_handoff = handoff_events[0]
    assert latest_handoff.event_metadata.get("question") == "عندكم فرع في صنعاء؟"
    assert latest_handoff.event_metadata.get("handoff_reply") == DEFAULT_HANDOFF_REPLY


def test_customer_branch_sanaa_allowed_when_fact_exists(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999005"

    # Add confirmed branch fact
    branch_fact = Fact(
        tenant_id=tenant_id,
        subject="فرع صنعاء",
        topic="operations.branches",
        value={"address": "شارع حدة", "city": "صنعاء"},
        status="confirmed",
        visibility="public",
        source="owner",
    )
    db.add(branch_fact)
    db.commit()

    verified_branch_reply = "نعم، لدينا فرع في صنعاء بشارع حدة، ويسعدنا استقبالك."
    mock_ai = NaturalMockAIProvider(reply=verified_branch_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "عندكم فرع في صنعاء؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == verified_branch_reply

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is not True


def test_customer_price_blocked_and_handed_off_when_no_price_fact(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999006"

    # Hallucinated price claim when no price fact exists
    hallucinated_price_reply = "سعر برنامج ناظم المحاسبي هو 500 ريال فقط."
    mock_ai = NaturalMockAIProvider(reply=hallucinated_price_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "كم سعر ناظم؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "Unverified price" in reply_msg.metadata_json.get("guardrail_reason", "")


def test_customer_free_trial_blocked_and_handed_off(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999007"

    # Hallucinated trial claim when no trial fact exists
    hallucinated_trial_reply = "نعم، نوفر نسخة تجريبية مجانية لمدة 14 يومًا لجميع البرامج."
    mock_ai = NaturalMockAIProvider(reply=hallucinated_trial_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "عندكم نسخة تجريبية؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "free trial" in reply_msg.metadata_json.get("guardrail_reason", "")


def test_customer_vat_zatca_blocked_and_handed_off(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999008"

    # Hallucinated tax claim when no tax fact exists
    hallucinated_tax_reply = "نعم، برنامج ناظم يدعم الربط مع الضرائب والفوترة الإلكترونية لهيئة الزكاة زاتكا."
    mock_ai = NaturalMockAIProvider(reply=hallucinated_tax_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "وهل ناظم يدعم الضرائب في السعودية؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "tax/ZATCA/VAT" in reply_msg.metadata_json.get("guardrail_reason", "")


def test_handoff_logging_is_queryable_by_owner(db: Session, test_setup: dict):
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999009"

    mock_ai = NaturalMockAIProvider(reply="سعر ناظم هو 999 ريال.")
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "كم السعر؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY

    audit_svc = AuditService(db)
    # Query handoff logs for this tenant
    events = audit_svc.list_events(tenant_id=tenant_id, event_type="customer_inquiry_handoff")
    assert len(events) >= 1
    for ev in events:
        assert ev.tenant_id == tenant_id
        assert ev.event_metadata is not None
        assert "conversation_id" in ev.event_metadata
        assert "question" in ev.event_metadata
        assert ev.event_metadata["question"] == "كم السعر؟"
        assert "handoff_reply" in ev.event_metadata
        assert ev.event_metadata["handoff_reply"] == DEFAULT_HANDOFF_REPLY


def test_customer_forwarding_promise_blocked_and_replaced_with_approved_handoff(db: Session, test_setup: dict):
    """
    Phase 2.11 Addendum:
    Customer reply must never say or imply that request was forwarded or will be answered
    by a team ("سأنقل طلبك", "سيرد عليك", "سنعود إليك بأسرع وقت").
    Live reply: "سأنقل طلبك إلى فريق المبيعات المختص..." -> replaced by approved handoff text.
    """
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999010"

    # Exact pattern observed in live Groq / gpt-oss-120b execution
    live_forwarding_reply = (
        "سأنقل طلبك إلى فريق المبيعات المختص وسيتواصلون معك قريباً للإجابة على كافة تفاصيل الأسعار."
    )
    mock_ai = NaturalMockAIProvider(reply=live_forwarding_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "كم سعر ناظم؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY
    assert res.reply_content == "هذا الاستفسار يحتاج تأكيدًا من الفريق، وسنعود إليك."

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "Unapproved forwarding or promise phrase" in reply_msg.metadata_json.get("guardrail_reason", "")

    # Audit event logged
    audit_svc = AuditService(db)
    events = audit_svc.list_events(tenant_id=tenant_id, event_type="customer_inquiry_handoff")
    assert any(e.event_metadata.get("original_blocked_reply") == live_forwarding_reply for e in events)


def test_customer_unrecorded_topic_offers_blocked(db: Session, test_setup: dict):
    """
    Phase 2.11 Addendum:
    The reply must not suggest unrecorded topics ("مميزات البرنامج", "المتطلبات التقنية", "طريقة الاستخدام", "طرق الترخيص").
    """
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999011"

    # Model offers unrecorded topics at the end of reply
    unrecorded_topics_reply = (
        "نحن نقدم الموظف الذكي وبرنامج سيرو وناظم المحاسبي. "
        "هل ترغب في معرفة تفاصيل إضافية حول الخصائص التقنية وطرق الترخيص وطريقة الاستخدام؟"
    )
    mock_ai = NaturalMockAIProvider(reply=unrecorded_topics_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "ما هي منتجاتكم؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "Unrecorded topic offer" in reply_msg.metadata_json.get("guardrail_reason", "")


def test_customer_stray_english_words_blocked(db: Session, test_setup: dict):
    """
    Phase 2.11 Addendum:
    Reply must be entirely Arabic; stray Latin words (like 'Customer Replay' or 'Support')
    that are not verified product/brand names in facts are deterministically blocked.
    """
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999012"

    stray_english_reply = "مرحبًا عزيزي Customer Replay، يسعدنا تواصلك معنا لخدمتك."
    mock_ai = NaturalMockAIProvider(reply=stray_english_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "مرحبا")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == DEFAULT_HANDOFF_REPLY

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "Stray English/Latin word" in reply_msg.metadata_json.get("guardrail_reason", "")


def test_customer_verified_latin_product_name_allowed(db: Session, test_setup: dict):
    """
    Phase 2.11 Addendum:
    Verified Latin product/brand names in the verified facts (e.g. 'Ciro Networks')
    are permitted in Arabic customer replies without being blocked.
    """
    tenant_id = test_setup["tenant_id"]
    channel_id = test_setup["channel_id"]
    non_owner_id = "967779999013"

    # Add verified fact containing Latin product name
    latin_fact = Fact(
        tenant_id=tenant_id,
        subject="Ciro Networks",
        topic="product.ciro_networks",
        value={"name": "Ciro Networks", "description": "حل إدارة الشبكات المتقدم"},
        status="confirmed",
        visibility="public",
        source="owner",
    )
    db.add(latin_fact)
    db.commit()

    verified_latin_reply = "أهلاً بك! نقدم نظام Ciro Networks المتخصص في إدارة الشبكات السلكية واللاسلكية."
    mock_ai = NaturalMockAIProvider(reply=verified_latin_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound_message(db, tenant_id, channel_id, non_owner_id, "عندكم Ciro Networks؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)
    assert res.success is True
    assert res.reply_content == verified_latin_reply

    reply_msg = db.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is not True

