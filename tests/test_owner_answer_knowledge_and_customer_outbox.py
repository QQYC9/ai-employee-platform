"""
Test Suite: Owner Answer Matching, Classified Knowledge Persistence,
Tailored Customer Outbox Dispatch, and Capability Gap Guard.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4
import pytest
from sqlalchemy import func, select

from packages.core.database import SessionLocal
from packages.models.domain import (
    Channel,
    Conversation,
    Customer,
    Fact,
    Message,
    OutboxEvent,
    OwnerInquiry,
)
from packages.models.tenant import Tenant
from packages.services.channel_service import OutboundDeliveryResult
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.outbox_worker import OutboxWorker
from packages.services.owner_inquiry_service import OwnerInquiryService


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


SAMPLE_NAZEM_FEATURES = """احفظ مميزات ناظم وافهمها ورد عليه 
هذه مميزات ناظم 
ملخص مميزات برنامج ناظم المحاسبي

1. المحاسبة المالية
- دليل حسابات هرمي قابل للتخصيص.
- القيود اليومية المزدوجة والترحيل الآلي.
- ميزان المراجعة وقائمة الأرباح والخسائر.

2. المبيعات والمشتريات
- عروض الأسعار وفواتير المبيعات والمشتريات.
- متابعة الديون والمستحقات والتنبيهات بمواعيد السداد.

3. الصناديق والبنوك
- إدارة عدة صناديق وحسابات بنكية وسندات القبض والصرف.

4. المخزون والمستودعات
- إدارة عدة مستودعات وفروع والتحويل بينها.
- الجرد وتسويات المخزون والباركود.

5. العملات المتعددة
- التعامل مع الريال اليمني والدولار وتحديد أسعار الصرف.

6. الأصول الثابتة
- تسجيل الأصول واحتساب الإهلاك.

7. التقارير والتحليلات
- تقارير مالية وتحليل الأرباح وهامش الربح لكل فاتورة وصنف.

8. المستخدمون والصلاحيات والأمان
- صلاحيات دقيقة حسب المستخدم وسجل تدقيق للعمليات.

9. الأتمتة والذكاء الاصطناعي
- إنشاء القيود تلقائيًا عند تنفيذ المعاملات.

10. التكامل وإدارة الأعمال
- تكامل المحاسبة مع المبيعات والمخزون ونقاط البيع.

11. نقاط البيع
- واجهة بيع سريعة تدعم الباركود والورديات.

12. متطلبات السوق اليمني
- العمل دون إنترنت عند الحاجة والعملة المحلية.

13. أفضل الممارسات المستفادة من البرامج العالمية
- Odoo: تكامل ERP.
- QuickBooks: سهولة الاستخدام.

14. أولويات التطوير المقترحة
الأولوية الأولى: سلامة القيود والترحيل.
الأولوية الثانية: المخزون وتكلفة البضاعة.
"""


def test_safe_owner_answer_matching_with_explicit_inquiry_number(db_session):
    """
    Verifies that an owner message referencing an inquiry number anywhere
    (e.g. 'رد على استفسار X: احفظ...') matches the target inquiry safely.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Match Tenant {uid}", slug=f"mt-{uid}")
    db_session.add(tenant)
    db_session.flush()

    cust_conv = Conversation(id=uuid4(), tenant_id=tenant.id)
    db_session.add(cust_conv)
    db_session.flush()

    svc = OwnerInquiryService(db_session)

    # Create two inquiries to test ambiguity avoidance
    inq_a, _ = svc.handle_customer_inquiry(tenant.id, cust_conv.id, "+967770000005", "سؤال استفسار أول")
    inq_b, _ = svc.handle_customer_inquiry(tenant.id, cust_conv.id, "+967770000006", "سؤال استفسار ثان")
    db_session.flush()

    # Test explicit inquiry number in command
    msg_text = f"رد على استفسار {inq_b.inquiry_number}: {SAMPLE_NAZEM_FEATURES}"
    matched_inq, matched_ans = svc.match_owner_answer(tenant.id, msg_text)

    assert matched_inq is not None
    assert matched_inq.id == inq_b.id
    assert matched_inq.inquiry_number == inq_b.inquiry_number
    assert "المحاسبة المالية" in matched_ans


def test_safe_owner_answer_matching_with_reply_to_reference(db_session):
    """
    Verifies that swiping/replying to an owner notification message
    matches the inquiry via external_message_id metadata.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"ReplyTo Tenant {uid}", slug=f"rt-{uid}")
    db_session.add(tenant)
    db_session.flush()

    owner_conv = Conversation(id=uuid4(), tenant_id=tenant.id, customer_id=None, status="open")
    cust_conv = Conversation(id=uuid4(), tenant_id=tenant.id)
    db_session.add_all([owner_conv, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    inq, _ = svc.handle_customer_inquiry(tenant.id, cust_conv.id, "+967771234567", "ما هي شروط التقسيط؟")
    db_session.flush()

    # Notification message sent to owner via Telegram (external_message_id = 9911)
    notif_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=owner_conv.id,
        sender_type="agent",
        content=f"❓ استفسار جديد (#{inq.inquiry_number})",
        metadata_json={
            "inquiry_id": str(inq.id),
            "inquiry_number": inq.inquiry_number,
            "external_message_id": "9911",
            "delivery_status": "delivered",
        },
    )
    db_session.add(notif_msg)
    inq.owner_notification_message_id = str(notif_msg.id)
    db_session.flush()

    # Owner swipes reply to message 9911 with answer text
    matched_inq, matched_ans = svc.match_owner_answer(
        tenant_id=tenant.id,
        content="شروط التقسيط: دفعة أولى 30% وكفيل تجاري",
        reply_to_message_id="9911",
    )

    assert matched_inq is not None
    assert matched_inq.id == inq.id
    assert matched_inq.inquiry_number == inq.inquiry_number
    assert "دفعة أولى 30%" in matched_ans


def test_command_separation_and_no_guessing_with_multiple_open_inquiries(db_session):
    """
    Verifies that when multiple inquiries exist and the owner sends product knowledge with
    'احفظ مميزات ناظم وافهمها ورد عليه' WITHOUT specifying a number:
    1. Product knowledge is saved and classified into FactService.
    2. System does NOT guess a customer or send a random reply.
    3. System prompts owner to specify which inquiry number to reply to.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"NoGuess Tenant {uid}", slug=f"ng-{uid}")
    db_session.add(tenant)
    db_session.flush()

    cust_conv = Conversation(id=uuid4(), tenant_id=tenant.id)
    db_session.add(cust_conv)
    db_session.flush()

    svc = OwnerInquiryService(db_session)

    # Create 3 open inquiries
    inqs = []
    for num in [1, 2, 3]:
        inq_obj, _ = svc.handle_customer_inquiry(
            tenant.id, cust_conv.id, f"+96777000000{num}", f"سؤال رقم فريد {num}"
        )
        inqs.append(inq_obj)
    db_session.flush()

    # match_owner_answer should NOT guess
    matched_inq, _ = svc.match_owner_answer(tenant.id, SAMPLE_NAZEM_FEATURES)
    assert matched_inq is None  # Safe: no guesswork!

    # handle_knowledge_teaching handles the message
    reply_to_owner = svc.handle_knowledge_teaching(tenant.id, SAMPLE_NAZEM_FEATURES)

    assert "تم استيعاب وتوثيق مميزات برنامج ناظم" in reply_to_owner
    assert "نظراً لوجود عدة استفسارات معلقة" in reply_to_owner
    for i in inqs:
        assert f"#{i.inquiry_number}" in reply_to_owner

    # Verify facts were stored and classified in FactService!
    facts = db_session.scalars(
        select(Fact).where(Fact.tenant_id == tenant.id, Fact.status == "confirmed")
    ).all()
    assert len(facts) >= 12

    # Check inventory fact is public and available
    inv_fact = next(f for f in facts if f.topic == "product.nazem.inventory")
    assert inv_fact.visibility == "public"
    assert inv_fact.value.get("feature_status") == "available"

    # Check benchmark fact is private and benchmark_only
    bench_fact = next(f for f in facts if f.topic == "product.nazem.benchmarks")
    assert bench_fact.visibility in ("private", "internal")
    assert bench_fact.value.get("feature_status") == "benchmark_only"

    # Check roadmap fact is private and planned_roadmap
    road_fact = next(f for f in facts if f.topic == "product.nazem.roadmap")
    assert road_fact.visibility in ("private", "internal")
    assert road_fact.value.get("feature_status") == "planned_roadmap"


def test_customer_6_tailored_reply_and_outbox_dispatch(db_session):
    """
    End-to-end verification for Customer #6:
    1. Inquiry addresses 2 warehouses, inventory, sales/purchases, profits/debts.
    2. Owner answers -> tailored 4-point response synthesized (NO raw owner commands, NO benchmarks, NO roadmap).
    3. OutboxEvent('dispatch_channel_reply') created with exact payload and idempotency key.
    4. Inquiry status set to 'answered' (NOT fake 'delivered').
    5. OutboxWorker processes event -> marks delivered.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Cust6 Tenant {uid}", slug=f"c6-{uid}")
    db_session.add(tenant)
    db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "mock_token", "owner_telegram_id": "+96777999888"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"sender_id": "1899616033"},
    )
    db_session.add_all([channel, cust_conv])
    db_session.flush()

    q_text = "السلام عليكم، أريد معرفة مميزات برنامج ناظم المحاسبي. عندي متجر فيه مستودعين ومبيعات ومشتريات، وأحتاج نظاماً يتابع المخزون والأرباح والديون التي لي وعلى متجري، وهل يناسبني ناظم؟"
    svc = OwnerInquiryService(db_session)
    inq6, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="1899616033",
        question=q_text,
    )
    db_session.flush()

    prompt_res = svc.answer_inquiry(
        tenant_id=tenant.id,
        inquiry=inq6,
        answer=SAMPLE_NAZEM_FEATURES,
    )

    assert "✅ تم إرسال الإجابة للعميل وحفظها" in prompt_res
    db_session.refresh(inq6)
    # Status must be 'answered', NOT 'delivered' before worker dispatch!
    assert inq6.status == "answered"

    # Verify Customer Message was created in customer conversation
    cust_msg = db_session.scalar(
        select(Message).where(
            Message.tenant_id == tenant.id,
            Message.conversation_id == cust_conv.id,
            Message.sender_type == "agent",
        )
    )
    assert cust_msg is not None
    assert cust_msg.metadata_json.get("delivery_status") == "pending_dispatch"
    assert cust_msg.metadata_json.get("inquiry_id") == str(inq6.id)

    # Verify Tailored Customer Content
    content = cust_msg.content
    assert "إدارة المستودعات" in content
    assert "بالمستودعين" in content or "مستودعين" in content
    assert "المبيعات والمشتريات" in content
    assert "الأرباح" in content
    assert "الديون" in content
    # Crucial: verify raw owner command was NOT copied
    assert "احفظ مميزات ناظم وافهمها ورد عليه" not in content
    assert "عشان لو جا استفسار مشابه" not in content
    assert "Odoo" not in content  # benchmark excluded
    assert "الأولوية الأولى" not in content  # roadmap excluded

    # Verify OutboxEvent
    outbox_event = db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant.id,
            OutboxEvent.event_type == "dispatch_channel_reply",
            OutboxEvent.message_id == cust_msg.id,
        )
    )
    assert outbox_event is not None
    assert outbox_event.status == "pending"
    assert outbox_event.payload.get("channel_id") == str(channel.id)
    assert outbox_event.payload.get("recipient") == "1899616033"
    assert outbox_event.payload.get("reply_message_id") == str(cust_msg.id)

    db_session.commit()

    # Verify OutboxWorker delivery updates inquiry to delivered
    mock_chan = MagicMock()
    mock_chan.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="1899616033",
        external_message_id="mock_telegram_cust_9999",
    )
    worker = OutboxWorker(channel_service=mock_chan)
    success = worker.process_event(outbox_event.id)
    assert success is True

    db_session.refresh(outbox_event)
    assert outbox_event.status == "completed"

    db_session.refresh(cust_msg)
    assert cust_msg.metadata_json.get("delivery_status") == "delivered"
    assert cust_msg.metadata_json.get("external_message_id") == "mock_telegram_cust_9999"

    db_session.refresh(inq6)
    assert inq6.status == "delivered"
    assert inq6.delivered_at is not None


def test_capability_gap_guard_does_not_hijack_knowledge_teaching(db_session):
    """
    Verifies that an owner message teaching product knowledge with 'هامش الربح'
    is NOT intercepted by _check_and_handle_capability_gap as a tool generation request.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"CapGuard Tenant {uid}", slug=f"cg-{uid}")
    db_session.add(tenant)
    db_session.flush()

    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=None,
        status="open",
        metadata_json={"is_owner": True},
    )
    owner_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        content=SAMPLE_NAZEM_FEATURES,
    )
    db_session.add_all([conv, owner_msg])
    db_session.flush()

    engine = ConversationalAgentEngine(db=db_session)
    gap_res = engine._check_and_handle_capability_gap(tenant.id, owner_msg, conv)

    # Must return None so it is treated as knowledge / inquiry, NOT a capability gap!
    assert gap_res is None


def test_future_reuse_for_subsequent_customer_queries(db_session):
    """
    Verifies that after Nazem knowledge is persisted:
    1. A new customer asking about multi-warehouse management retrieves ONLY relevant facts.
    2. Zero leakage of Customer #6's private data or conversation context.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Reuse Tenant {uid}", slug=f"ru-{uid}")
    db_session.add(tenant)
    db_session.flush()

    # 1. Persist Nazem knowledge
    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    # 2. Subsequent customer asks about multi-warehouse
    from packages.services.fact_service import FactService
    fact_svc = FactService(db_session)
    retrieved = fact_svc.get_relevant_facts(
        tenant_id=tenant.id,
        query="هل يدعم ناظم إدارة أكثر من مستودع والجرد؟",
        include_private=False,
    )

    # Should find inventory fact among top results
    topics = [f.topic for f in retrieved]
    assert "product.nazem.inventory" in topics

    # Must NOT include private benchmarks (Odoo/Sage) or roadmap facts
    assert "product.nazem.benchmarks" not in topics
    assert "product.nazem.roadmap" not in topics

    # Content of inventory fact
    inv_f = next(f for f in retrieved if f.topic == "product.nazem.inventory")
    val = inv_f.value
    assert "إدارة عدة مستودعات وفروع" in str(val.get("features", []))
    assert val.get("feature_status") == "available"


def test_customer_7_not_falsely_blocked_by_guardrail(db_session):
    """
    Verifies that a customer reply mentioning 'لا تحتاج إلى برنامج منفصل للمخزون'
    is NOT falsely blocked as an unverified product 'منفصل', and is treated as safe.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Guardrail Tenant {uid}", slug=f"gt-{uid}")
    db_session.add(tenant)
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)
    db_session.commit()

    engine = ConversationalAgentEngine(db=db_session)
    from packages.context.models import TaskContext
    task_ctx = TaskContext(
        task_id=uuid4(),
        agent_id=None,
        objective="Inquiry response",
        title="Inquiry response",
        priority="normal",
        status="active",
    )
    agent_ctx = engine.context_builder.build(tenant_id=tenant.id, task=task_ctx)

    reply_text = (
        "نعم، يدعم برنامج ناظم إدارة المستودعين والمبيعات والديون والأرباح بدقة، "
        "وبالتالي لا تحتاج إلى برنامج منفصل للمخزون فوظائف المخزون مدمجة بالكامل."
    )

    is_safe, reason = engine._evaluate_reply_guardrails(reply_text, agent_ctx)
    assert is_safe is True
    assert reason is None


def test_owner_referencing_documented_features_resolves_inquiry(db_session):
    """
    Verifies that when owner responds 'هذا الموضوع ذكرته لك انا في المميزات',
    the inquiry is resolved from stored knowledge and dispatched to the customer.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"OwnerRef Tenant {uid}", slug=f"ort-{uid}")
    db_session.add(tenant)
    db_session.flush()

    # Channel & conversations
    chan = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Test Telegram",
        channel_type="telegram",
        provider="telegram",
        status="active",
        config={"bot_token": "TEST_TOKEN"},
    )
    cust = Customer(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Test Customer 99",
        phone="+967770000099",
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=cust.id,
        channel_id=chan.id,
        status="open",
        metadata_json={"sender_id": "cust-tg-99"},
    )
    owner_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        customer_id=None,
        channel_id=chan.id,
        status="open",
        metadata_json={"is_owner": True, "sender_id": "owner-tg-88"},
    )
    db_session.add(cust)
    db_session.flush()
    db_session.add_all([chan, cust_conv, owner_conv])
    db_session.flush()

    # Persist Nazem knowledge
    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    # Customer asks question -> inquiry #7 created
    inq, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-99",
        question="هل أقدر أدير مستودعين وهل أحتاج برنامج منفصل للمخزون؟",
    )
    db_session.commit()

    assert inq.status == "asked"

    # Owner message referencing features in owner conversation
    owner_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="هذا الموضوع ذكرته لك انا في المميزات",
        metadata_json={"is_owner": True, "sender_id": "owner-tg-88"},
    )
    db_session.add(owner_msg)
    db_session.commit()

    engine = ConversationalAgentEngine(db=db_session)
    res = engine._process_owner_message(
        tenant_id=tenant.id,
        message=owner_msg,
        conversation=owner_conv,
    )

    db_session.commit()

    # Owner received confirmation
    assert res.success is True
    assert "تم استرجاع مميزات برنامج ناظم المعتمدة وإرسال الرد المفصل للعميل" in res.reply_content

    # Inquiry updated to answered
    db_session.expire_all()
    inq_refreshed = db_session.scalar(select(OwnerInquiry).where(OwnerInquiry.id == inq.id))
    assert inq_refreshed.status == "answered"

    # Outbox event created for customer
    ev = db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant.id,
            OutboxEvent.event_type == "dispatch_channel_reply",
            OutboxEvent.idempotency_key.like(f"outbox:inquiry_reply:{inq.id}:%"),
        )
    )
    assert ev is not None
    assert ev.payload["recipient"] == "cust-tg-99"
    assert "إدارة المستودعات" in ev.payload["content"]
    assert "لا تحتاج إطلاقاً إلى شراء أو استخدام برنامج منفصل للمخزون" in ev.payload["content"]

    # Mock OutboxWorker delivery
    mock_chan = MagicMock()
    mock_chan.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="telegram",
        recipient_id="cust-tg-99",
        external_message_id="ext-reply-777",
    )
    worker = OutboxWorker(channel_service=mock_chan)
    processed = worker.process_event(ev.id)
    assert processed is True

    # Inquiry finalized as delivered
    db_session.expire_all()
    inq_final = db_session.scalar(select(OwnerInquiry).where(OwnerInquiry.id == inq.id))
    assert inq_final.status == "delivered"
    assert inq_final.delivered_at is not None


def test_tailored_reply_focuses_on_debts_and_profits_and_warehouses_without_unrelated_modules(db_session):
    """
    Test 1: Verifies that when customer asks about 2 warehouses, debt tracking, profits,
    and separate inventory software:
    1. Response directly addresses the 2 warehouses, direct stock transfers, debt tracking,
       profit reports & margins, and negates the need for separate software.
    2. Response does NOT dump unrelated modules (POS, fixed assets, Yemeni currency, offline mode).
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Focus Tenant {uid}", slug=f"foc-{uid}")
    db_session.add(tenant)
    db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "mock_token", "owner_telegram_id": "+96777999888"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"sender_id": "cust-tg-focus"},
    )
    db_session.add_all([channel, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    q = "عندي متجر فيه مستودعين وأريد أعرف هل أقدر أحول البضاعة بينهما، وأتابع ديون العملاء والموردين وأعرف أرباحي؟ وهل أحتاج برنامج منفصل للمخزون؟"
    inq, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-focus",
        question=q,
    )
    db_session.flush()

    reply = svc._synthesize_tailored_customer_reply(inq, "مميزات برنامج ناظم")

    # Positive assertions: Requested needs are highlighted
    assert "إدارة المستودعات" in reply
    assert "المستودعين" in reply
    assert "التحويل المباشر للبضائع" in reply or "تحويل" in reply
    assert "ديون العملاء والموردين" in reply
    assert "كشوفات الحساب" in reply
    assert "أعمار الديون" in reply
    assert "الأرباح والتقارير المالية" in reply
    assert "قائمة الأرباح والخسائر" in reply
    assert "هامش الربح" in reply
    assert "لا تحتاج إطلاقاً إلى شراء أو استخدام برنامج منفصل للمخزون" in reply

    # Negative assertions: Unrequested modules must NOT be dumped
    assert "نقاط البيع" not in reply
    assert "(POS)" not in reply
    assert "الأصول الثابتة" not in reply
    assert "الريال اليمني" not in reply
    assert "بدون إنترنت" not in reply
    assert "Odoo" not in reply
    assert "QuickBooks" not in reply


def test_tailored_reply_warehouse_only_does_not_expand_to_debts_or_accounting(db_session):
    """
    Test 2: Verifies that when customer asks ONLY about warehouses and inventory:
    1. Response focuses exclusively on warehouses and inventory.
    2. Response does NOT expand to debts, supplier payables, or accounting ledgers.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"WhOnly Tenant {uid}", slug=f"who-{uid}")
    db_session.add(tenant)
    db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "mock_token", "owner_telegram_id": "+96777999888"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"sender_id": "cust-tg-wh"},
    )
    db_session.add_all([channel, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    q = "هل يدعم البرنامج إدارة عدة مستودعات وفروع ونقل البضائع والجرد؟"
    inq, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-wh",
        question=q,
    )
    db_session.flush()

    reply = svc._synthesize_tailored_customer_reply(inq, "مميزات برنامج ناظم")

    # Positive assertions: Warehouses & Inventory
    assert "إدارة المستودعات" in reply
    assert "تحويل البضائع" in reply or "تحويل" in reply
    assert "الجرد" in reply

    # Negative assertions: Debts, Profits, POS, Accounting must NOT be present
    assert "متابعة ديون العملاء والموردين" not in reply
    assert "أعمار الديون" not in reply
    assert "الأرباح والتقارير المالية" not in reply
    assert "قائمة الأرباح والخسائر" not in reply
    assert "نقاط البيع" not in reply
    assert "دليل حسابات" not in reply


def test_inquiry_answering_idempotency_prevents_duplicate_dispatch(db_session):
    """
    Test 3: Verifies strict idempotency:
    Re-invoking answer_inquiry or resolve_inquiry_from_stored_knowledge on an inquiry
    that was already answered or delivered produces ZERO new Messages and ZERO new OutboxEvents.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Idemp Tenant {uid}", slug=f"idm-{uid}")
    db_session.add(tenant)
    db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "mock_token", "owner_telegram_id": "+96777999888"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"sender_id": "cust-tg-idemp"},
    )
    db_session.add_all([channel, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    # Initial customer question
    cust_inbound = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="هل عندكم إدارة مستودعات؟",
        metadata_json={"sender_id": "cust-tg-idemp"},
    )
    db_session.add(cust_inbound)
    db_session.flush()

    inq, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-idemp",
        question="هل عندكم إدارة مستودعات؟",
    )
    db_session.flush()

    # 1. First resolution
    first_ack = svc.resolve_inquiry_from_stored_knowledge(
        tenant_id=tenant.id,
        inquiry=inq,
        owner_instruction="المميزات موجودة",
    )
    db_session.flush()
    assert inq.status == "answered"
    assert "تم استرجاع مميزات برنامج ناظم" in first_ack

    # Count messages & outbox events after first resolution
    msg_count_1 = db_session.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == cust_conv.id,
            Message.sender_type == "agent",
            Message.metadata_json["is_inquiry_reply"].as_boolean() == True,
        )
    )
    ev_count_1 = db_session.scalar(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.conversation_id == cust_conv.id,
            OutboxEvent.event_type == "dispatch_channel_reply",
        )
    )
    assert msg_count_1 == 1
    assert ev_count_1 == 1

    # 2. Second resolution attempt (duplicate call to resolve_inquiry_from_stored_knowledge)
    second_ack = svc.resolve_inquiry_from_stored_knowledge(
        tenant_id=tenant.id,
        inquiry=inq,
        owner_instruction="المميزات موجودة مكررة",
    )
    db_session.flush()
    assert "تم الرد عليه مسبقاً" in second_ack

    # 3. Third resolution attempt via answer_inquiry
    third_ack = svc.answer_inquiry(
        tenant_id=tenant.id,
        inquiry=inq,
        answer="إجابة أخرى لنفس الاستفسار",
    )
    db_session.flush()
    assert "تم الرد عليه مسبقاً" in third_ack

    # 4. Direct dispatch attempt
    dispatched_direct = svc._dispatch_tailored_reply_to_waiting_customers(inq, "رد زائد")
    assert dispatched_direct == 0

    # Ensure strictly NO duplicate messages or OutboxEvents were generated
    msg_count_final = db_session.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == cust_conv.id,
            Message.sender_type == "agent",
            Message.metadata_json["is_inquiry_reply"].as_boolean() == True,
        )
    )
    ev_count_final = db_session.scalar(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.conversation_id == cust_conv.id,
            OutboxEvent.event_type == "dispatch_channel_reply",
        )
    )
    assert msg_count_final == 1
    assert ev_count_final == 1


def test_new_customer_message_after_resolution_allows_new_reply(db_session):
    """
    Test 4: Verifies that after an inquiry is resolved and delivered to the customer,
    a subsequent NEW message from the customer opens a new conversation turn and
    can be processed and replied to naturally without being suppressed by previous idempotency constraints.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Turn Tenant {uid}", slug=f"trn-{uid}")
    db_session.add(tenant)
    db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "mock_token", "owner_telegram_id": "+96777999888"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"sender_id": "cust-tg-turn"},
    )
    db_session.add_all([channel, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    # 1. Customer asks first question
    msg1 = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="هل تديرون المستودعات؟",
        metadata_json={"sender_id": "cust-tg-turn"},
    )
    db_session.add(msg1)
    db_session.flush()

    inq1, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-turn",
        question="هل تديرون المستودعات؟",
    )
    db_session.flush()

    # Resolve inquiry 1
    svc.resolve_inquiry_from_stored_knowledge(
        tenant_id=tenant.id,
        inquiry=inq1,
        owner_instruction="من المميزات",
    )
    db_session.flush()

    # Verify first reply was sent
    first_reply = db_session.scalar(
        select(Message).where(
            Message.conversation_id == cust_conv.id,
            Message.metadata_json["inquiry_id"].as_string() == str(inq1.id),
        )
    )
    assert first_reply is not None

    # Verify duplicate dispatch is currently suppressed (since customer hasn't sent a new message)
    re_dispatch = svc._dispatch_tailored_reply_to_waiting_customers(inq1, "رد مكرر")
    assert re_dispatch == 0

    db_session.commit()

    # 2. Customer sends a NEW message after receiving the first reply
    import time
    time.sleep(0.05)  # Ensure strictly greater timestamp

    msg2 = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="ممتاز، وما هي خيارات نقاط البيع والكاشير المتاحة لديكم؟",
        metadata_json={"sender_id": "cust-tg-turn"},
    )
    db_session.add(msg2)
    db_session.commit()

    # 3. New question can create a new inquiry or receive a new reply
    inq2, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-turn",
        question="وما هي خيارات نقاط البيع والكاشير المتاحة لديكم؟",
    )
    db_session.flush()

    # Resolve inquiry 2
    dispatched_2 = svc._dispatch_tailored_reply_to_waiting_customers(
        inq2,
        "نوفر نقاط بيع متطورة تدعم أجهزة الكاشير والباركود والورديات.",
    )
    db_session.flush()

    # Ensure the new reply was dispatched successfully!
    assert dispatched_2 == 1

    second_reply = db_session.scalar(
        select(Message).where(
            Message.conversation_id == cust_conv.id,
            Message.metadata_json["inquiry_id"].as_string() == str(inq2.id),
        )
    )
    assert second_reply is not None
    assert "نقاط بيع متطورة" in second_reply.content


def test_smart_tailored_reply_explains_practical_business_benefits_and_excludes_unrequested_modules(db_session):
    """
    Test 5: Verifies that when a customer asks about specific business needs (e.g. debts and profits),
    the synthesized response:
    1. Focuses strictly on those points without dumping unrequested modules (no warehouses, no POS, no benchmarks).
    2. Explicitly articulates practical business benefits (الفوائد العملية: تسريع التحصيل، حماية السيولة، تسعير مدروس).
    3. Concludes with a relevant, consultative follow-up question.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Benefit Tenant {uid}", slug=f"ben-{uid}")
    db_session.add(tenant)
    db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "mock_token", "owner_telegram_id": "+96777999888"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"sender_id": "cust-tg-benefit"},
    )
    db_session.add_all([channel, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    svc._persist_classified_product_knowledge(tenant.id, SAMPLE_NAZEM_FEATURES)

    q = "أريد أعرف كيف يساعدني ناظم في متابعة ديون العملاء والموردين وتنبيهات السداد، وهل يعطيني تقارير دقيقة عن أرباحي؟"
    inq, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="cust-tg-benefit",
        question=q,
    )
    db_session.flush()

    reply = svc._synthesize_tailored_customer_reply(inq, "مميزات برنامج ناظم")

    # 1. Directly answers requested points
    assert "متابعة ديون العملاء والموردين" in reply
    assert "الأرباح والتقارير المالية" in reply

    # 2. Articulates practical business benefits (الفوائد العملية)
    assert "الفائدة العملية" in reply
    assert "تسريع عمليات التحصيل" in reply or "حماية السيولة" in reply
    assert "صافي أرباحك الحقيقية" in reply or "قرارات تسعير مدروسة" in reply

    # 3. Excludes unrequested modules (strictly zero dumping)
    assert "إدارة المستودعات" not in reply
    assert "المستودعين" not in reply
    assert "تحويل البضائع" not in reply
    assert "نقاط البيع" not in reply
    assert "الأصول الثابتة" not in reply
    assert "Odoo" not in reply
    assert "الريال اليمني" not in reply

    # 4. Contextual closing follow-up question
    assert "هل تود استعراض تفاصيل إضافية حول تقارير الديون والأرباح" in reply

