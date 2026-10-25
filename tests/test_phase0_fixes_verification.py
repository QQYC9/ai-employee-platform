from __future__ import annotations

import json
import uuid
from typing import Any
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProviderError
from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.domain import AuditEvent, BusinessBrain, Channel, Conversation, Customer, Message, User
from packages.models.tenant import Tenant
from packages.services.business_brain_service import BusinessBrainService
from packages.services.channel_service import ChannelService
from packages.services.conversation_service import ConversationService
from packages.services.conversational_agent_engine import ConversationalAgentEngine


class MockAIProvider:
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["أهلاً بك! أنا موظفك الرقمي."]
        self.calls: list[dict[str, Any]] = []
        self._idx = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "system_instruction": system_instruction,
                "temperature": temperature,
            }
        )
        resp = self.responses[self._idx % len(self.responses)]
        self._idx += 1
        return resp

    def generate_json(self, *args, **kwargs):
        return {}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant_a(db: Session):
    t = Tenant(name="Phase 0 Tenant A", slug=f"p0-tenant-a-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tenant_b(db: Session):
    t = Tenant(name="Phase 0 Tenant B", slug=f"p0-tenant-b-{uuid.uuid4().hex[:8]}", status="active")
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def customer_a(db: Session, tenant_a: Tenant):
    c = Customer(
        tenant_id=tenant_a.id,
        name="عميل تجريبي",
        phone="+967770000001",
        customer_type="individual",
        status="active",
        metadata_json={"telegram_id": "tg-77001"},
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def owner_user_a(db: Session, tenant_a: Tenant):
    u = User(
        tenant_id=tenant_a.id,
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        name="المالك المنذر",
        role="owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# 0.1 Fix list_messages: fetch latest N messages and reverse to chronological
# ---------------------------------------------------------------------------
def test_0_1_list_messages_window_fetches_latest_chronological(db: Session, tenant_a: Tenant, customer_a: Customer):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=customer_a.id,
        subject="30-turn test conversation",
    )

    # Insert 30 messages sequentially
    for i in range(1, 31):
        conv_svc.send_message(
            tenant_id=tenant_a.id,
            conversation_id=conv.id,
            sender_type="customer" if i % 2 != 0 else "agent",
            content=f"Message {i}",
        )

    # Query latest 15 messages (history window limit)
    latest_15 = conv_svc.list_messages(tenant_a.id, conv.id, limit=15)
    assert len(latest_15) == 15

    # Verify the last message (Message 30) is present and is at the end of the slice
    assert latest_15[-1].content == "Message 30"
    # Verify the first message of this window is Message 16
    assert latest_15[0].content == "Message 16"
    # Verify strict chronological progression
    for idx, msg in enumerate(latest_15):
        expected_num = 16 + idx
        assert msg.content == f"Message {expected_num}"


# ---------------------------------------------------------------------------
# 0.2 Fix _process_owner_message: anti-hallucination + context
# ---------------------------------------------------------------------------
def test_0_2_owner_message_with_empty_brain_anti_hallucination(db: Session, tenant_a: Tenant, owner_user_a: User):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant_a.id,
        customer_id=None,
        subject="Owner Chat",
    )

    # Ensure empty business brain
    brain_svc = BusinessBrainService(db)
    brain_svc.create_brain_if_not_exists(tenant_a.id)

    msg = conv_svc.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user_a.id,
        content="ايش هو ناظم؟",
        metadata_json={"is_owner": True},
    )

    # Mock provider returning honest response
    mock_provider = MockAIProvider(responses=["برنامج ناظم غير مسجل في قاعدة بيانات المنشأة حتى الآن. يرجى تزويدي بوصفه لاعتماده."])
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_provider)

    res = engine.process_incoming_message(tenant_a.id, msg.id)
    assert res.success is True

    # Inspect LLM call
    assert len(mock_provider.calls) == 1
    call = mock_provider.calls[0]
    sys_inst = call["system_instruction"]
    user_prompt = call["prompt"]

    # Verify anti-hallucination constraint in system instruction
    assert "قواعد الأمان ومنع الهلوسة الإلزامية" in sys_inst
    assert "ناظم" in sys_inst

    # Verify BusinessBrain Context in prompt shows None provided
    assert "### BUSINESS BRAIN CONTEXT (Verified)" in user_prompt
    assert "None provided." in user_prompt
    assert "ايش هو ناظم؟" in user_prompt


# ---------------------------------------------------------------------------
# 0.3 Fix _construct_prompt: inject branches, locations, working hours
# ---------------------------------------------------------------------------
def test_0_3_construct_prompt_injects_branches_locations_working_hours(db: Session, tenant_a: Tenant, customer_a: Customer):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(tenant_id=tenant_a.id, customer_id=customer_a.id, subject="Customer Chat")
    msg = conv_svc.send_message(tenant_id=tenant_a.id, conversation_id=conv.id, sender_type="customer", content="أين فروعكم؟")

    brain_svc = BusinessBrainService(db)
    brain_svc.update_brain(
        tenant_id=tenant_a.id,
        identity={"name": "المنذر تكنولوجي"},
        operations={
            "branches": ["صنعاء", "الحديدة", "ذمار"],
            "working_hours": "من 9 صباحاً حتى 9 مساءً",
        },
    )

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    from packages.context.models import TaskContext
    task_ctx = TaskContext(task_id=uuid.uuid4(), agent_id=None, objective="Test branches", title="Test", status="active", priority="normal")
    agent_ctx = engine.context_builder.build(tenant_a.id, task_ctx, customer_id=customer_a.id)

    system_inst, user_prompt = engine._construct_prompt(
        agent_context=agent_ctx,
        conversation=conv,
        history_dialogue=[],
        incoming_message=msg,
    )

    assert "Operations, Branches, Locations & Working Hours" in user_prompt
    assert "صنعاء" in user_prompt
    assert "الحديدة" in user_prompt
    assert "من 9 صباحاً حتى 9 مساءً" in user_prompt


# ---------------------------------------------------------------------------
# 0.4 Fix _extract_business_knowledge: strip filler words
# ---------------------------------------------------------------------------
def test_0_4_extract_business_knowledge_strips_filler_words(db: Session):
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # Case 1: Formal full sentence with filler words
    t1 = "الاسم التجاري الرسمي لمنشأتنا المنذر تكنولوجي"
    res1 = engine._extract_business_knowledge(t1)
    assert res1 is not None
    assert res1["category"] == "identity"
    assert res1["data"]["name"] == "المنذر تكنولوجي"

    # Case 2: Direct company declaration
    t2 = "اسم شركتنا المنذر تكنولوجي"
    res2 = engine._extract_business_knowledge(t2)
    assert res2 is not None
    assert res2["category"] == "identity"
    assert res2["data"]["name"] == "المنذر تكنولوجي"

    # Case 3: Shop with colon
    t3 = "اسم المحل: النور للعسل"
    res3 = engine._extract_business_knowledge(t3)
    assert res3 is not None
    assert res3["category"] == "identity"
    assert res3["data"]["name"] == "النور للعسل"


# ---------------------------------------------------------------------------
# 0.5 Verify products & cities persistence in business_brain
# ---------------------------------------------------------------------------
def test_0_5_products_and_cities_persistence_in_business_brain(db: Session, tenant_a: Tenant, owner_user_a: User):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(tenant_id=tenant_a.id, customer_id=None, subject="Owner Setup")
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # Step A: Teach products
    products_msg = conv_svc.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user_a.id,
        content="نحن شركة المنذر تكنولوجي نقدم برنامج ناظم المحاسبي وبرنامج سيرو لادارة الشبكات والموظف الذكي",
        metadata_json={"is_owner": True},
    )

    res_p = engine.process_incoming_message(tenant_a.id, products_msg.id)
    assert res_p.success is True

    # Verify products persisted in DB record
    brain_p = db.scalar(select(BusinessBrain).where(BusinessBrain.tenant_id == tenant_a.id))
    assert brain_p is not None
    assert "nazim_accounting" in brain_p.products
    assert brain_p.products["nazim_accounting"]["name"] == "برنامج ناظم المحاسبي"
    assert "ciro_networks" in brain_p.products
    assert brain_p.products["ciro_networks"]["name"] == "برنامج سيرو لادارة الشبكات"
    assert "smart_employee" in brain_p.products
    assert brain_p.products["smart_employee"]["name"] == "الموظف الذكي"

    # Step B: Teach cities / branches
    cities_msg = conv_svc.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user_a.id,
        content="فروعنا في المدن التالية: صنعاء، الحديدة، ذمار، إب، المحويت، ريمة",
        metadata_json={"is_owner": True},
    )

    res_c = engine.process_incoming_message(tenant_a.id, cities_msg.id)
    assert res_c.success is True

    # Verify cities persisted in DB record
    db.expire_all()
    brain_c = db.scalar(select(BusinessBrain).where(BusinessBrain.tenant_id == tenant_a.id))
    assert brain_c is not None
    assert brain_c.operations is not None
    stored_cities = brain_c.operations.get("cities") or brain_c.operations.get("branches")
    expected_cities = ["صنعاء", "الحديدة", "ذمار", "إب", "المحويت", "ريمة"]
    for c in expected_cities:
        assert c in stored_cities


# ---------------------------------------------------------------------------
# 0.6 Post-generation guardrail in customer path blocks unverified prices
# ---------------------------------------------------------------------------
def test_0_6_post_generation_guardrail_blocks_unverified_prices_and_discounts(db: Session, tenant_a: Tenant, customer_a: Customer):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(tenant_id=tenant_a.id, customer_id=customer_a.id, subject="Customer Inquiry")

    # BusinessBrain with only one verified product
    brain_svc = BusinessBrainService(db)
    brain_svc.update_brain(
        tenant_id=tenant_a.id,
        identity={"name": "متجر العسل"},
        products={"sidr_honey": {"name": "عسل سدر", "price": 150.0, "unit": "ريال"}},
    )

    # 1. Mock provider outputs hallucinated price (80 ريال) and fake discount (30%)
    hallucinated_reply = "سعر العسل لدينا 80 ريال فقط وهناك خصم 30% لطلبك!"
    mock_provider = MockAIProvider(responses=[hallucinated_reply])
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_provider)

    msg1 = conv_svc.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        customer_id=customer_a.id,
        content="كم سعر العسل وهل يوجد خصم؟",
    )

    res1 = engine.process_incoming_message(tenant_a.id, msg1.id)
    assert res1.success is True

    # Verify reply was blocked by guardrail and replaced with safe handoff
    reply_msg1 = db.scalar(select(Message).where(Message.id == res1.reply_message_id))
    assert reply_msg1.content == "سأحوّل استفسارك للموظف المختص وسيرد عليك قريبًا."
    assert reply_msg1.metadata_json.get("guardrail_blocked") is True

    # Verify audit event logged
    audit = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_a.id,
            AuditEvent.event_type == "agent_reply_blocked_by_guardrail",
        )
    )
    assert audit is not None

    # 2. Mock provider outputs verified price (150 ريال) -> Passes guardrail
    valid_reply = "سعر عسل سدر هو 150 ريال شامل الضريبة."
    mock_provider2 = MockAIProvider(responses=[valid_reply])
    engine2 = ConversationalAgentEngine(db=db, ai_provider=mock_provider2)

    msg2 = conv_svc.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="customer",
        customer_id=customer_a.id,
        content="كم السعر الرسمي لعسل السدر؟",
    )

    res2 = engine2.process_incoming_message(tenant_a.id, msg2.id)
    assert res2.success is True
    reply_msg2 = db.scalar(select(Message).where(Message.id == res2.reply_message_id))
    assert reply_msg2.content == valid_reply
    assert reply_msg2.metadata_json.get("guardrail_blocked") is not True


# ---------------------------------------------------------------------------
# 0.7 3 consecutive messages land in same conversation_id
# ---------------------------------------------------------------------------
def test_0_7_consecutive_messages_from_same_customer_share_conversation_id(db: Session, tenant_a: Tenant):
    chan_svc = ChannelService(db)

    # 1. Telegram channel test
    tg_channel = Channel(
        tenant_id=tenant_a.id,
        name="Telegram Support",
        channel_type="telegram",
        status="active",
        config={"bot_token": "fake-tg-token", "webhook_secret": "sec"},
    )
    db.add(tg_channel)
    db.flush()

    tg_conv_ids = []
    for i in range(1, 4):
        inbound = InboundMessage(
            tenant_id=tenant_a.id,
            channel_id=tg_channel.id,
            channel_type="telegram",
            sender_id="tg_user_9999",
            sender_name="Mohamed Telegram",
            content=f"Telegram message {i}",
            external_message_id=f"tg-msg-{uuid.uuid4().hex[:6]}",
        )
        persisted = chan_svc.process_inbound_message(inbound)
        tg_conv_ids.append(persisted.conversation_id)

    assert len(tg_conv_ids) == 3
    assert tg_conv_ids[0] == tg_conv_ids[1] == tg_conv_ids[2]

    # 2. WhatsApp channel test
    wa_channel = Channel(
        tenant_id=tenant_a.id,
        name="WhatsApp Support",
        channel_type="whatsapp",
        status="active",
        config={"phone_number_id": "wa_num_123", "access_token": "token"},
    )
    db.add(wa_channel)
    db.flush()

    wa_conv_ids = []
    for i in range(1, 4):
        inbound = InboundMessage(
            tenant_id=tenant_a.id,
            channel_id=wa_channel.id,
            channel_type="whatsapp",
            sender_id="+96777999888",
            sender_name="Khaled WhatsApp",
            content=f"WhatsApp message {i}",
            external_message_id=f"wa-msg-{uuid.uuid4().hex[:6]}",
        )
        persisted = chan_svc.process_inbound_message(inbound)
        wa_conv_ids.append(persisted.conversation_id)

    assert len(wa_conv_ids) == 3
    assert wa_conv_ids[0] == wa_conv_ids[1] == wa_conv_ids[2]


# ---------------------------------------------------------------------------
# 0.8 Confirmation shows actual persisted value read back from database
# ---------------------------------------------------------------------------
def test_0_8_saved_confirmation_shows_actual_persisted_db_record(db: Session, tenant_a: Tenant, owner_user_a: User):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(tenant_id=tenant_a.id, customer_id=None, subject="Owner Chat")
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    msg = conv_svc.send_message(
        tenant_id=tenant_a.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user_a.id,
        content="الاسم التجاري الرسمي لمنشأتنا المنذر تكنولوجي",
        metadata_json={"is_owner": True},
    )

    res = engine.process_incoming_message(tenant_a.id, msg.id)
    assert res.success is True
    reply = db.scalar(select(Message).where(Message.id == res.reply_message_id))

    # Must contain the clean value actually persisted in the DB
    assert "المنذر تكنولوجي" in reply.content
    assert "الرسمي لمنشأتنا" not in reply.content
    assert "تم حفظ وتأكيد البيانات في قاعدة بيانات المنشأة (BusinessBrain)" in reply.content


# ---------------------------------------------------------------------------
# 0.9 Customer prompt explicitly forbids unsupported capabilities
# ---------------------------------------------------------------------------
def test_0_9_customer_prompt_explicitly_forbids_unsupported_capabilities(db: Session, tenant_a: Tenant, customer_a: Customer):
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(tenant_id=tenant_a.id, customer_id=customer_a.id, subject="Customer Chat")
    msg = conv_svc.send_message(tenant_id=tenant_a.id, conversation_id=conv.id, sender_type="customer", content="مرحبا")

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    from packages.context.models import TaskContext
    task_ctx = TaskContext(task_id=uuid.uuid4(), agent_id=None, objective="General interaction", title="Test", status="active", priority="normal")
    agent_ctx = engine.context_builder.build(tenant_a.id, task_ctx, customer_id=customer_a.id)

    system_inst, _ = engine._construct_prompt(agent_ctx, conv, [], msg)
    assert "STRICT CAPABILITY LIMITS" in system_inst
    assert "phone calls" in system_inst
    assert "booking appointments" in system_inst
    assert "sending external links" in system_inst
    assert "free trials" in system_inst
    assert "designing/generating images" in system_inst


# ---------------------------------------------------------------------------
# Multi-tenant isolation verification
# ---------------------------------------------------------------------------
def test_tenant_isolation_in_phase0(db: Session, tenant_a: Tenant, tenant_b: Tenant):
    # Setup Tenant A with products and cities
    brain_svc = BusinessBrainService(db)
    brain_svc.update_brain(
        tenant_id=tenant_a.id,
        identity={"name": "شركة أ"},
        products={"p1": {"name": "منتج أ", "price": 100.0}},
        operations={"cities": ["صنعاء"]},
    )

    # Tenant B has empty brain
    brain_b = brain_svc.create_brain_if_not_exists(tenant_b.id)
    assert brain_b.products == {}
    assert brain_b.operations == {}

    # Prompt generated for Tenant B must never leak Tenant A's products or cities
    conv_svc = ConversationService(db)
    conv_b = conv_svc.start_conversation(tenant_id=tenant_b.id, customer_id=None, subject="Tenant B chat")
    msg_b = conv_svc.send_message(tenant_id=tenant_b.id, conversation_id=conv_b.id, sender_type="customer", content="ما هي منتجاتكم؟")

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    from packages.context.models import TaskContext
    task_b = TaskContext(task_id=uuid.uuid4(), agent_id=None, objective="Tenant B chat", title="Test", status="active", priority="normal")
    ctx_b = engine.context_builder.build(tenant_b.id, task_b)

    _, prompt_b = engine._construct_prompt(ctx_b, conv_b, [], msg_b)
    assert "منتج أ" not in prompt_b
    assert "صنعاء" not in prompt_b
    assert "None provided." in prompt_b
