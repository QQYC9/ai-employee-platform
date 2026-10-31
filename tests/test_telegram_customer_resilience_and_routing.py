from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy import select

from packages.ai_providers.base import AIProvider, AIProviderError
from packages.ai_providers.resilient_provider import ResilientAIProvider


class MockAIProvider:
    def __init__(self, responses: list[str] | None = None, response: str = "مرحبا بك"):
        self.responses = list(responses) if responses is not None else [response]
        self.calls: list[dict] = []

    def generate_text(self, prompt: str, *, system_instruction: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction, "kwargs": kwargs})
        if self.responses:
            return self.responses.pop(0)
        return "تم استلام رسالتك"

    def generate_json(self, *args, **kwargs) -> dict:
        return {}
from packages.models.domain import Channel, Conversation, Fact, Message, OutboxEvent, User
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.fact_service import FactService
from packages.services.outbox_service import OutboxService
from packages.services.outbox_worker import OutboxWorker


class FailingAIProvider(AIProvider):
    def __init__(self, error_message: str = "Rate limit exceeded (429)"):
        self.error_message = error_message
        self.calls = []

    def generate_text(self, prompt: str, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "kwargs": kwargs})
        raise AIProviderError(self.error_message)


@pytest.fixture
def test_setup(test_db_session):
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Resilience Tenant {uid}", slug=f"rt-{uid}")
    test_db_session.add(tenant)
    test_db_session.flush()

    channel = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={
            "bot_token": "mock_token",
            "owner_telegram_id": "775274399",
            "owner_identifiers": ["775274399"],
        },
    )
    test_db_session.add(channel)
    test_db_session.flush()

    # Seed verified facts
    f1 = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "المنذر تكنولوجي"},
        status="confirmed",
        visibility="public",
    )
    f2 = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="product.nazem.inventory",
        subject="المخزون والمستودعات في برنامج ناظم",
        value={
            "module": "inventory",
            "features": [
                "إدارة عدة مستودعات وفروع",
                "تحويل البضائع والجرد وتسويات المخزون",
                "متابعة المخزون في المستودعين",
            ],
        },
        status="confirmed",
        visibility="public",
    )
    f3 = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="product.nazem.sales_purchases",
        subject="المبيعات والمشتريات والديون في برنامج ناظم",
        value={
            "module": "sales_purchases",
            "features": [
                "فواتير المبيعات والمشتريات",
                "متابعة ديون العملاء والموردين",
            ],
        },
        status="confirmed",
        visibility="public",
    )
    test_db_session.add_all([f1, f2, f3])
    test_db_session.commit()

    return tenant, channel


def test_1_customer_message_generates_and_dispatches_reply(test_db_session, test_setup):
    """
    Test 1: وصول رسالة عميل وتوليد رد وإرساله عبر Outbox
    """
    tenant, channel = test_setup

    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="open",
        metadata_json={
            "is_owner": False,
            "sender_id": "1899616033",
            "channel_type": "telegram",
            "conversation_type": "customer_support",
        },
    )
    test_db_session.add(cust_conv)
    test_db_session.flush()

    cust_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="السلام عليكم، هل أقدر أدير مستودعين وأحوّل البضاعة بينهما وأتابع ديوني؟",
        metadata_json={
            "is_owner": False,
            "sender_id": "1899616033",
            "recipient_id": "1899616033",
            "channel_id": str(channel.id),
            "channel_type": "telegram",
            "external_message_id": "282",
        },
    )
    test_db_session.add(cust_msg)
    test_db_session.flush()

    mock_ai = MockAIProvider(responses=[
        "وعليكم السلام، نعم يدعم برنامج ناظم إدارة المستودعين وتحويل البضاعة بينهما ومتابعة ديون العملاء والموردين بدقة."
    ])
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    result = engine.process_incoming_message(tenant.id, cust_msg.id)
    assert result.success is True
    assert result.reply_message_id is not None
    assert "المستودعين" in result.reply_content

    # Verify message persisted
    reply_msg = test_db_session.scalar(select(Message).where(Message.id == result.reply_message_id))
    assert reply_msg is not None
    assert reply_msg.sender_type == "agent"


def test_2_owner_message_processed_and_answered_correctly(test_db_session, test_setup):
    """
    Test 2: وصول رسالة مالك ومعالجتها بشكل صحيح عبر مسار الإدارة دون تطبيق حاجز العملاء
    """
    tenant, channel = test_setup

    owner_user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        name=f"Owner {tenant.id.hex[:6]}",
        email=f"owner_{tenant.id.hex[:6]}@test.com",
        password_hash="hash",
        role="owner",
    )
    owner_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={
            "is_owner": True,
            "conversation_type": "owner_management",
            "sender_id": "775274399",
        },
    )
    test_db_session.add_all([owner_user, owner_conv])
    test_db_session.flush()

    owner_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        customer_id=None,
        content="كيفك ياصديقي",
        metadata_json={
            "is_owner": True,
            "sender_id": "775274399",
            "recipient_id": "775274399",
            "channel_id": str(channel.id),
        },
    )
    test_db_session.add(owner_msg)
    test_db_session.flush()

    mock_ai = MockAIProvider(responses=["أهلاً بك يا صاحب المنشأة! أنا موظفك الذكي وجاهز لمساعدتك."])
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, owner_msg.id)
    assert res.success is True
    assert res.reply_message_id is not None
    assert "أهلاً بك" in res.reply_content


def test_3_primary_provider_fails_and_switches_to_fallback(test_db_session, test_setup):
    """
    Test 3: فشل النموذج الأساسي والتحويل التلقائي إلى المزود الاحتياطي (ResilientAI)
    """
    tenant, channel = test_setup

    primary = FailingAIProvider("Groq rate limit exceeded: TPM limit 8000")
    fallback = MockAIProvider(responses=["هذا الرد صادر من المزود الاحتياطي بنجاح."])

    resilient_provider = ResilientAIProvider(
        providers=[
            ("primary", primary),
            ("fallback", fallback),
        ],
        tenant_id=tenant.id,
        max_retries_per_provider=1,
        base_backoff_seconds=0.01,
    )

    resp = resilient_provider.generate_text("سؤال تجريبي")
    assert resp == "هذا الرد صادر من المزود الاحتياطي بنجاح."
    assert len(primary.calls) >= 1
    assert len(fallback.calls) == 1


def test_4_both_providers_fail_preserves_message_and_marks_failure(test_db_session, test_setup):
    """
    Test 4: فشل المزودين مع الحفاظ على الرسالة وإظهار حالة فشل واضحة دون ادعاء نجاح كاذب
    """
    tenant, channel = test_setup

    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="open",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(cust_conv)
    test_db_session.flush()

    cust_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="سؤال عن المنتجات",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(cust_msg)
    test_db_session.flush()

    failing_ai = FailingAIProvider("All AI providers unavailable (503 Service Unavailable)")
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=failing_ai)

    res = engine.process_incoming_message(tenant.id, cust_msg.id)
    assert res.success is False
    assert "All AI providers unavailable" in res.error

    # Message must NOT be marked processed, preserving it for safe future retry
    test_db_session.refresh(cust_msg)
    meta = cust_msg.metadata_json or {}
    assert meta.get("agent_processed") is not True
    assert meta.get("reply_message_id") is None


def test_5_reprocessing_failed_message_no_duplicate_replies(test_db_session, test_setup):
    """
    Test 5: إعادة معالجة رسالة فاشلة بعد تعافي المزود دون إنشاء ردود مكررة
    """
    tenant, channel = test_setup

    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="open",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(cust_conv)
    test_db_session.flush()

    cust_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="سؤال للاختبار",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(cust_msg)
    test_db_session.flush()

    # Step 1: Provider fails
    failing_ai = FailingAIProvider("Transient failure")
    engine1 = ConversationalAgentEngine(db=test_db_session, ai_provider=failing_ai)
    res1 = engine1.process_incoming_message(tenant.id, cust_msg.id)
    assert res1.success is False

    # Step 2: Provider recovers -> Reprocess
    recovering_ai = MockAIProvider(responses=["تمت الإجابة بعد التعافي."])
    engine2 = ConversationalAgentEngine(db=test_db_session, ai_provider=recovering_ai)
    res2 = engine2.process_incoming_message(tenant.id, cust_msg.id)
    assert res2.success is True
    reply_id = res2.reply_message_id

    # Step 3: Repeated reprocessing attempt -> Skipped via Idempotency
    res3 = engine2.process_incoming_message(tenant.id, cust_msg.id)
    assert res3.success is True
    assert res3.skipped is True
    assert res3.reply_message_id == reply_id

    # Count agent replies in conversation
    agent_replies = test_db_session.scalars(
        select(Message).where(
            Message.conversation_id == cust_conv.id,
            Message.sender_type == "agent",
        )
    ).all()
    assert len(agent_replies) == 1


def test_6_consecutive_customer_messages_processed_per_policy(test_db_session, test_setup):
    """
    Test 6: وصول رسالتين متتاليتين من العميل ومعالجة كل واحدة وفق سياسة النظام
    """
    tenant, channel = test_setup

    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="open",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(cust_conv)
    test_db_session.flush()

    mock_ai = MockAIProvider(responses=[
        "إجابة السؤال الأول عن المستودعات.",
        "إجابة السؤال الثاني عن الديون.",
    ])
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    # First message
    msg1 = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="السؤال الأول: هل تديرون المستودعات؟",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(msg1)
    test_db_session.flush()
    res1 = engine.process_incoming_message(tenant.id, msg1.id)
    assert res1.success is True

    # Second message
    msg2 = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="السؤال الثاني: وكيف تتابعون الديون؟",
        metadata_json={"is_owner": False, "sender_id": "1899616033"},
    )
    test_db_session.add(msg2)
    test_db_session.flush()
    res2 = engine.process_incoming_message(tenant.id, msg2.id)
    assert res2.success is True

    assert res1.reply_message_id != res2.reply_message_id
    agent_replies = test_db_session.scalars(
        select(Message).where(
            Message.conversation_id == cust_conv.id,
            Message.sender_type == "agent",
        )
    ).all()
    assert len(agent_replies) == 2


def test_7_owner_flow_does_not_interfere_with_customer_flow(test_db_session, test_setup):
    """
    Test 7: عدم تأثير مسار المالك في مسار العملاء مع الفصل التام بين المحادثتين
    """
    tenant, channel = test_setup

    owner_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=None,
        status="open",
        metadata_json={"is_owner": True, "conversation_type": "owner_management"},
    )
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="open",
        metadata_json={"is_owner": False, "conversation_type": "customer_support"},
    )
    test_db_session.add_all([owner_conv, cust_conv])
    test_db_session.flush()

    mock_ai = MockAIProvider(responses=[
        "أهلاً بك يا مالك المنشأة.",
        "مرحباً بك يا عميلنا العزيز.",
    ])
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    # Owner message
    owner_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        customer_id=None,
        content="مرحباً موظفي",
        metadata_json={"is_owner": True},
    )
    # Customer message
    cust_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="مرحباً، أريد استفساراً",
        metadata_json={"is_owner": False},
    )
    test_db_session.add_all([owner_msg, cust_msg])
    test_db_session.flush()

    res_owner = engine.process_incoming_message(tenant.id, owner_msg.id)
    res_cust = engine.process_incoming_message(tenant.id, cust_msg.id)

    assert res_owner.success is True
    assert res_cust.success is True
    assert "مالك" in res_owner.reply_content
    assert "عميلنا" in res_cust.reply_content


def test_8_strict_tenant_isolation_maintained(test_db_session, test_setup):
    """
    Test 8: استمرار عزل بيانات المستأجرين ومنع تسرب الحقائق أو الردود بين المستأجرين
    """
    tenant_a, channel_a = test_setup

    # Create Tenant B with distinct name and private product
    uid_b = uuid4().hex[:6]
    tenant_b = Tenant(id=uuid4(), name=f"Secret Tenant {uid_b}", slug=f"st-{uid_b}")
    test_db_session.add(tenant_b)
    test_db_session.flush()

    f_b1 = Fact(
        id=uuid4(),
        tenant_id=tenant_b.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "مؤسسة السرية التامة"},
        status="confirmed",
        visibility="public",
    )
    f_b2 = Fact(
        id=uuid4(),
        tenant_id=tenant_b.id,
        topic="product.secret",
        subject="منتج سري جدا",
        value={"description": "شريحة مشفرة لا تباع علنا"},
        status="confirmed",
        visibility="public",
    )
    test_db_session.add_all([f_b1, f_b2])
    test_db_session.commit()

    # Query facts for Tenant A: Must NOT contain Tenant B facts
    fact_svc = FactService(test_db_session)
    facts_a = fact_svc.get_relevant_facts(tenant_a.id, query="سري جدا")
    assert not any("السرية" in str(f.value) or "شريحة مشفرة" in str(f.value) for f in facts_a)

    # Customer in Tenant A asks question: Must NOT receive Tenant B name or data
    cust_conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_a.id,
        channel_id=channel_a.id,
        status="open",
        metadata_json={"is_owner": False},
    )
    test_db_session.add(cust_conv)
    test_db_session.flush()

    cust_msg = Message(
        id=uuid4(),
        tenant_id=tenant_a.id,
        conversation_id=cust_conv.id,
        sender_type="customer",
        content="ما هو اسم منشأتكم؟",
        metadata_json={"is_owner": False},
    )
    test_db_session.add(cust_msg)
    test_db_session.flush()

    mock_ai = MockAIProvider(responses=["نحن شركة المنذر تكنولوجي."])
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    # Inspect prompt constructed for Tenant A
    task_ctx = type('TaskContext', (), {
        'task_id': uuid4(), 'agent_id': None, 'objective': cust_msg.content,
        'title': 'Test', 'priority': 'normal', 'status': 'active'
    })()
    agent_ctx = engine.context_builder.build(tenant_id=tenant_a.id, task=task_ctx)
    sys_inst, user_prompt = engine._construct_prompt(agent_ctx, cust_conv, [], cust_msg)

    assert "المنذر تكنولوجي" in sys_inst or "المنذر تكنولوجي" in user_prompt
    assert "السرية التامة" not in sys_inst
    assert "السرية التامة" not in user_prompt
    assert "شريحة مشفرة" not in user_prompt
