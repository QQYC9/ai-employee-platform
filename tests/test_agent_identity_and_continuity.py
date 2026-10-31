from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from sqlalchemy import select

from packages.ai_providers.base import AIProvider
from packages.models.domain import (
    Agent,
    Channel,
    Conversation,
    Fact,
    Message,
    Tool,
)
from packages.models.tenant import Tenant
from packages.services.agent_identity_service import (
    AgentIdentityService,
    DigitalEmployeeProfile,
)
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.tools.registry import ToolRegistry


class MockAIProvider(AIProvider):
    def __init__(self, responses: list[str] | None = None, response: str = "تمت المعالجة بنجاح"):
        self.responses = list(responses) if responses is not None else [response]
        self.calls: list[dict] = []

    def generate_text(self, prompt: str, *, system_instruction: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction, "kwargs": kwargs})
        if self.responses:
            return self.responses.pop(0)
        return "تم استلام رسالتك"

    def generate_json(self, *args, **kwargs) -> dict:
        return {}


@pytest.fixture
def identity_test_setup(test_db_session):
    uid = uuid4().hex[:6]
    tenant = Tenant(
        id=uuid4(),
        name=f"شركة الحلول الرقمية {uid}",
        slug=f"ds-{uid}",
        employee_name="ناظم",
    )
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

    f_identity = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "الحلول الرقمية المتطورة"},
        status="confirmed",
        visibility="public",
    )
    f_prod1 = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="product.nazem.overview",
        subject="برنامج ناظم المحاسبي",
        value={"description": "برنامج سحابي متكامل لإدارة الحسابات والمخزون والمبيعات"},
        status="confirmed",
        visibility="public",
    )
    f_prod2 = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="product.nazem.inventory",
        subject="المخزون والمستودعات في برنامج ناظم",
        value={
            "module": "inventory",
            "features": [
                "إدارة عدة مستودعات وفروع",
                "تحويل البضائع بين المستودعات",
                "متابعة أرصدة المخزون بدقة",
            ],
        },
        status="confirmed",
        visibility="public",
    )
    test_db_session.add_all([f_identity, f_prod1, f_prod2])
    test_db_session.commit()

    return tenant, channel


# =========================================================================
# A. الهوية والقدرات المهنية (Identity & Capabilities)
# =========================================================================

def test_1_identity_clarification_honest_ai(test_db_session, identity_test_setup):
    """
    سؤال: «هل أنت بشري أم ذكاء اصطناعي؟»
    يجب أن يوضح الموظف هويته بصدق بوصفه موظفاً رقمياً يعمل بالذكاء الاصطناعي دون ادعاء أنه إنسان.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(tenant.id)

    assert profile.core.is_ai is True
    assert profile.core.name == "ناظم"
    assert "ذكاء اصطناعي" in profile.core.nature_description or "الذكاء الاصطناعي" in profile.core.nature_description

    # Test deterministic synthesis
    reply = identity_svc.synthesize_identity_reply(profile, "هل أنت بشري أم ذكاء اصطناعي؟")
    assert "موظف رقمي" in reply
    assert "الذكاء الاصطناعي" in reply or "ذكاء اصطناعي" in reply
    assert profile.core.company_name in reply
    assert "بشري" not in reply or "موظف رقمي" in reply


def test_2_actual_capabilities_linked_to_tools_and_permissions(test_db_session, identity_test_setup):
    """
    سؤال: «ماذا تستطيع أن تفعل لشركتنا؟»
    يجب أن يذكر قدرات مرتبطة بالأدوات والصلاحيات الفعلية في النظام.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(tenant.id)

    reply = identity_svc.synthesize_identity_reply(profile, "ماذا تستطيع أن تفعل لشركتنا؟")
    assert len(profile.activated.directly_executable) > 0
    # Must describe actual skills (customer support, tasks, reports)
    assert any("العملاء" in s or "الاستفسارات" in s or "المستندات" in s for s in profile.activated.directly_executable)
    assert "مساعدتك" in reply
    assert profile.core.company_name in reply


def test_3_marketing_capabilities_and_setup_vs_execution(test_db_session, identity_test_setup):
    """
    سؤال عن التسويق:
    يجب أن يشرح قدراته التسويقية ذات الصلة ويميز بين الإعداد والتنفيذ الفعلي الذي يحتاج موافقة.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(tenant.id)

    reply = identity_svc.synthesize_identity_reply(profile, "كيف تساعدنا في التسويق وإعداد الحملات؟")
    assert "الخطط" in reply or "التسويقية" in reply
    # Must distinguish between planning/drafting vs mass campaign execution needing approval
    assert "موافقة" in reply or "الإدارة" in reply or "تنسيق" in reply


def test_4_unconfigured_capability_clarification(test_db_session, identity_test_setup):
    """
    سؤال عن قدرة غير مفعّلة (مكالمات هاتفية):
    يجب أن يوضح أنها غير متاحة أو غير مفعّلة، لا أن يدّعي امتلاكها.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(tenant.id)

    reply = identity_svc.synthesize_identity_reply(profile, "هل تستطيع إجراء مكالمات هاتفية للعملاء؟")
    assert "غير متاحة" in reply or "غير مفعّلة" in reply or "غير مدعوم" in reply
    assert "المكالمات الهاتفية" in reply or "صوتية" in reply


def test_5_business_value_explanation_grounded_in_enterprise(test_db_session, identity_test_setup):
    """
    سؤال عن قيمة الموظف الرقمي:
    يجب أن يقدم شرحاً عملياً ملائماً لنشاط المنشأة ومعلوماتها المؤكدة دون وعود خيالية.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(tenant.id)

    reply = identity_svc.synthesize_identity_reply(profile, "ما الفائدة العملية من الموظف الرقمي لشركتنا؟")
    assert "قيمة" in reply or "دعم" in reply
    assert profile.core.company_name in reply
    assert "على مدار الساعة" in reply or "فوري" in reply


# =========================================================================
# B. تعدد المستأجرين والعزل (Multi-tenancy & Isolation)
# =========================================================================

def test_6_multi_tenant_different_products_and_activities(test_db_session):
    """
    اختلاف المنتجات والأنشطة بين مستأجرين:
    المستأجر 1 ناظم للمحاسبة والمستأجر 2 متجر عسل.
    """
    u1, u2 = uuid4().hex[:6], uuid4().hex[:6]
    t1 = Tenant(id=uuid4(), name=f"ناظم للحلول {u1}", slug=f"nazem-{u1}", employee_name="ناظم")
    t2 = Tenant(id=uuid4(), name=f"مناحل الشفاء {u2}", slug=f"honey-{u2}", employee_name="سالم")
    test_db_session.add_all([t1, t2])
    test_db_session.flush()

    f1 = Fact(
        id=uuid4(), tenant_id=t1.id, topic="product.nazem", subject="برنامج ناظم",
        value={"features": ["إدارة المستودعات", "المحاسبة"]}, status="confirmed", visibility="public",
    )
    f2 = Fact(
        id=uuid4(), tenant_id=t2.id, topic="product.honey", subject="عسل السدر البلدي",
        value={"features": ["طبيعي 100%", "مفحوص مخبرياً"]}, status="confirmed", visibility="public",
    )
    test_db_session.add_all([f1, f2])
    test_db_session.commit()

    identity_svc = AgentIdentityService(test_db_session)
    p1 = identity_svc.get_profile(t1.id)
    p2 = identity_svc.get_profile(t2.id)

    assert p1.core.name == "ناظم"
    assert p2.core.name == "سالم"
    assert "برنامج ناظم" in p1.enterprise.products_and_services
    assert "عسل السدر البلدي" in p2.enterprise.products_and_services
    assert "عسل" not in str(p1.enterprise.products_and_services)
    assert "ناظم" not in str(p2.enterprise.products_and_services)


def test_7_multi_tenant_different_tools_and_permissions(test_db_session):
    """
    اختلاف الأدوات بين موظفين رقميين لمستأجرين مختلفين:
    المستأجر 1 لديه أداة مهام مخصصة والمستأجر 2 ليس لديه.
    """
    u1, u2 = uuid4().hex[:6], uuid4().hex[:6]
    t1 = Tenant(id=uuid4(), name=f"مستأجر أدوات {u1}", slug=f"tools-{u1}")
    t2 = Tenant(id=uuid4(), name=f"مستأجر بسيط {u2}", slug=f"simple-{u2}")
    test_db_session.add_all([t1, t2])
    test_db_session.flush()

    tool1 = Tool(
        id=uuid4(),
        tenant_id=t1.id,
        name="Task Tool",
        slug="task_create",
        tool_type="internal",
        is_active=True,
    )
    test_db_session.add(tool1)
    test_db_session.commit()

    reg = ToolRegistry()
    identity_svc = AgentIdentityService(test_db_session, tool_registry=reg)
    p1 = identity_svc.get_profile(t1.id)
    p2 = identity_svc.get_profile(t2.id)

    assert "task_create" in p1.activated.raw_tools
    assert "task_create" not in p2.activated.raw_tools


def test_8_strict_tenant_isolation_no_leakage(test_db_session):
    """
    التأكد من عدم تسرب الهوية أو الحقائق أو القدرات الخاصة بمستأجر إلى آخر.
    """
    u1, u2 = uuid4().hex[:6], uuid4().hex[:6]
    t1 = Tenant(id=uuid4(), name=f"سري 1 {u1}", slug=f"sec1-{u1}", employee_name="سري_الأول")
    t2 = Tenant(id=uuid4(), name=f"سري 2 {u2}", slug=f"sec2-{u2}", employee_name="سري_الثاني")
    test_db_session.add_all([t1, t2])
    test_db_session.flush()

    identity_svc = AgentIdentityService(test_db_session)
    corpus1 = identity_svc.get_corpus_text(identity_svc.get_profile(t1.id))
    corpus2 = identity_svc.get_corpus_text(identity_svc.get_profile(t2.id))

    assert "سري_الأول" in corpus1
    assert "سري_الأول" not in corpus2
    assert "سري_الثاني" in corpus2
    assert "سري_الثاني" not in corpus1


def test_9_automatic_shared_logic_without_manual_per_tenant_config(test_db_session):
    """
    ضمان أن المنطق المشترك يعمل تلقائياً دون إعداد يدوي منفصل لكل مستأجر جديد.
    """
    uid = uuid4().hex[:6]
    fresh_tenant = Tenant(id=uuid4(), name=f"منشأة جديدة {uid}", slug=f"fresh-{uid}")
    test_db_session.add(fresh_tenant)
    test_db_session.commit()

    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(fresh_tenant.id)

    # Automatically has 4 layers populated
    assert profile.core is not None
    assert profile.general is not None
    assert profile.activated is not None
    assert profile.enterprise is not None
    assert profile.core.is_ai is True
    assert len(profile.general.skills) > 0


# =========================================================================
# C. استمرارية المحادثة والتواصل الطبيعي (Conversation Continuity)
# =========================================================================

def test_10_continuity_new_conversation_allows_greeting(test_db_session, identity_test_setup):
    """
    بدء محادثة جديدة (الرسالة الأولى):
    يسمح بتحية مناسبة وطبيعية.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)
    test_db_session.flush()

    msg1 = Message(
        id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id,
        sender_type="customer", content="ما هي خدماتكم؟",
    )
    test_db_session.add(msg1)
    test_db_session.commit()

    ai_reply = "مرحبًا بك! نحن في الحلول الرقمية نقدم برنامج ناظم المحاسبي."
    mock_ai = MockAIProvider(response=ai_reply)
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, msg1.id)
    assert res.success is True
    assert "مرحبًا بك!" in res.reply_content


def test_11_continuity_second_turn_direct_answer_no_repeated_greeting(test_db_session, identity_test_setup):
    """
    الرسالة الثانية في المحادثة:
    إجابة مباشرة دون تكرار الترحيب.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)
    test_db_session.flush()

    # Prior turns
    msg1 = Message(
        id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id,
        sender_type="customer", content="ما هي منتجاتكم؟",
    )
    agent_msg1 = Message(
        id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id,
        sender_type="agent", content="مرحبًا بك! نحن في الحلول الرقمية نقدم برنامج ناظم.",
    )
    test_db_session.add_all([msg1, agent_msg1])
    test_db_session.flush()

    # Second incoming customer message
    msg2 = Message(
        id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id,
        sender_type="customer", content="وهل يدعم التحويل بين المستودعات؟",
    )
    test_db_session.add(msg2)
    test_db_session.commit()

    # Model echoes a repeated greeting in turn 2
    mock_ai = MockAIProvider(response="أهلاً بك! نعم، يدعم برنامج ناظم التحويل بين المستودعات بدقة.")
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, msg2.id)
    assert res.success is True
    # Repeated greeting MUST be stripped
    assert not res.reply_content.startswith("أهلاً بك")
    assert "يدعم برنامج ناظم التحويل بين المستودعات بدقة." in res.reply_content


def test_12_continuity_multiple_turns_no_repeated_intro_or_canned_openers(test_db_session, identity_test_setup):
    """
    عدة رسائل متتابعة:
    عدم تكرار المقدمة أو التعريف بالموظف («بالتأكيد، يمكنني مساعدتك»، «أنا ناظم»).
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)

    agent_msg = Message(
        id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id,
        sender_type="agent", content="أنا ناظم الموظف الرقمي، كيف أساعدك؟",
    )
    test_db_session.add(agent_msg)
    test_db_session.flush()

    msg3 = Message(
        id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id,
        sender_type="customer", content="كم تستغرق عملية الجرد؟",
    )
    test_db_session.add(msg3)
    test_db_session.commit()

    # Model generates canned opener
    mock_ai = MockAIProvider(response="بالتأكيد، يمكنني مساعدتك! تتم عملية الجرد آلياً وبشكل فوري.")
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, msg3.id)
    assert res.success is True
    assert not res.reply_content.startswith("بالتأكيد")
    assert not res.reply_content.startswith("يسعدني")
    assert "تتم عملية الجرد آلياً وبشكل فوري." in res.reply_content


def test_13_continuity_followup_question_builds_on_previous_context(test_db_session, identity_test_setup):
    """
    سؤال متابعة:
    الاستفادة من السياق السابق وحقن سجل المحادثة في الـ Prompt.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)

    m1 = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="عندي مستودعين")
    m2 = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="agent", content="ناظم يدعم المستودعات المتعددة")
    m3 = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="وكيف أحول بينهم؟")
    test_db_session.add_all([m1, m2, m3])
    test_db_session.commit()

    mock_ai = MockAIProvider(response="يتم التحويل عبر إنشاء سند تحويل مخزني مباشر بين المستودعين.")
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, m3.id)
    assert res.success is True

    # Verify history was passed to provider
    call = mock_ai.calls[0]
    prompt = call["prompt"]
    assert "عندي مستودعين" in prompt
    assert "ناظم يدعم المستودعات المتعددة" in prompt
    assert "وكيف أحول بينهم؟" in prompt


def test_14_continuity_topic_change_answers_directly_without_regreeting(test_db_session, identity_test_setup):
    """
    تغيير الموضوع:
    الإجابة عن الموضوع الجديد دون إعادة الترحيب.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)

    agent_m = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="agent", content="تم توضيح المستودعات.")
    cust_m = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="ما هي طرق الدفع المتاحة؟")
    test_db_session.add_all([agent_m, cust_m])
    test_db_session.commit()

    mock_ai = MockAIProvider(response="أهلاً بك! طرق الدفع المعتمدة هي التحويل البنكي والدفع الإلكتروني.")
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, cust_m.id)
    assert res.success is True
    assert not res.reply_content.startswith("أهلاً بك")
    assert "طرق الدفع" in res.reply_content


def test_15_continuity_return_after_break_contextual_handling(test_db_session, identity_test_setup):
    """
    عودة العميل بعد انقطاع مع تحية:
    استخدام السياق لاحترام تحية العميل دون تعسف.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)

    agent_m = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="agent", content="شكراً لتواصلك معنا سابقاً.")
    test_db_session.add(agent_m)
    test_db_session.flush()

    cust_greeting = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="السلام عليكم ورحمة الله")
    test_db_session.add(cust_greeting)
    test_db_session.commit()

    mock_ai = MockAIProvider(response="وعليكم السلام ورحمة الله وبركاته! كيف يمكنني خدمتك اليوم؟")
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, cust_greeting.id)
    assert res.success is True
    # Greeting is NOT stripped because customer explicitly greeted!
    assert "وعليكم السلام" in res.reply_content


def test_16_continuity_missing_history_no_hallucination(test_db_session, identity_test_setup):
    """
    غياب سجل المحادثة:
    عدم اختلاق معلومات عن محادثة سابقة.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)
    test_db_session.flush()

    single_msg = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="ما هو سعر البرنامج؟")
    test_db_session.add(single_msg)
    test_db_session.commit()

    engine = ConversationalAgentEngine(db=test_db_session)
    continuity = engine._analyze_dialogue_continuity([single_msg], single_msg, "ناظم")

    assert continuity["is_new_conversation"] is True
    assert continuity["has_prior_greeting"] is False
    assert continuity["has_prior_intro"] is False
    assert continuity["turn_count"] == 0


def test_17_continuity_varied_phrasing_no_fixed_template(test_db_session, identity_test_setup):
    """
    اختلاف صياغة الأسئلة:
    عدم تكرار قالب ثابت في جميع الإجابات.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)
    profile = identity_svc.get_profile(tenant.id)

    reply_identity = identity_svc.synthesize_identity_reply(profile, "هل أنت ذكاء اصطناعي؟")
    reply_marketing = identity_svc.synthesize_identity_reply(profile, "كيف تساعدنا في التسويق؟")
    reply_value = identity_svc.synthesize_identity_reply(profile, "ما القيمة من الموظف الرقمي؟")

    # All three must have different structures and opening phrases
    assert reply_identity != reply_marketing
    assert reply_marketing != reply_value
    assert "موظف رقمي أعمل بتقنيات الذكاء" in reply_identity
    assert "الخطط والأفكار التسويقية" in reply_marketing
    assert "قيمة مهنية متعددة" in reply_value


def test_18_continuity_repeated_customer_question_adapted_response(test_db_session, identity_test_setup):
    """
    سؤال متكرر من العميل:
    تقديم إجابة ملائمة للسياق دون تجاهل السؤال أو إنشاء حلقة تكرار.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)

    m1 = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="كم السعر؟")
    m2 = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="agent", content="السعر يعتمد على الباقة المطلوبة.")
    m3 = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="كم السعر؟")
    test_db_session.add_all([m1, m2, m3])
    test_db_session.commit()

    engine = ConversationalAgentEngine(db=test_db_session)
    continuity = engine._analyze_dialogue_continuity([m1, m2, m3], m3, "ناظم")

    assert continuity["is_repeated_query"] is True
    assert continuity["is_new_conversation"] is False


# =========================================================================
# B. التحقق من فصل مصادر الحقائق والأدوات والصلاحيات والاستمرارية الزمنية
# =========================================================================

def test_19_fact_source_separation_agent_tools_do_not_validate_product_claims(test_db_session, identity_test_setup):
    """
    فصل مصادر الحقائق:
    أدوات الموظف الرقمي الداخلية (مثل task_create) لا تُعتبر دليلاً على ميزات المنتجات (مثل برنامج ناظم).
    إذا ادعى الرد أن برنامج ناظم يدير المهام أو المشاريع دون وجود حقيقة منتج تؤكد ذلك، يجب حظر الرد.
    """
    tenant, channel = identity_test_setup
    conv = Conversation(id=uuid4(), tenant_id=tenant.id, channel_id=channel.id, status="open")
    test_db_session.add(conv)
    m = Message(id=uuid4(), tenant_id=tenant.id, conversation_id=conv.id, sender_type="customer", content="هل برنامج ناظم يدير المهام والمشاريع؟")
    test_db_session.add(m)
    test_db_session.commit()

    # Product embellishment claiming task management in Nazem without confirmed product fact
    hallucinated_product_reply = "نعم، برنامج ناظم المحاسبي يوفر إدارة المهام وزيادة الإنتاجية لتوزيع الأعمال بين الموظفين."
    mock_ai = MockAIProvider(response=hallucinated_product_reply)
    engine = ConversationalAgentEngine(db=test_db_session, ai_provider=mock_ai)

    res = engine.process_incoming_message(tenant.id, m.id)
    assert res.success is True
    # The reply must NOT accept the hallucinated product claim; guardrail blocks it
    reply_msg = test_db_session.scalar(select(Message).where(Message.id == res.reply_message_id))
    assert reply_msg.metadata_json.get("guardrail_blocked") is True
    assert "Unsupported capability/benefit embellishment" in reply_msg.metadata_json.get("guardrail_reason", "")


def test_20_tool_permission_and_readiness_distinction(test_db_session, identity_test_setup):
    """
    التحقق الفعلي من الأدوات والصلاحيات:
    - الأداة المسجلة التي تفتقر لصلاحيات المستأجر تُستبعد من directly_executable.
    - أداة http_request في غياب التكاملات الخارجية تُصنف ضمن requires_setup_or_approval.
    - أداة product_add_or_update تُصنف ضمن العمليات الحساسة التي تتطلب موافقة الإدارة.
    """
    from packages.models.domain import Permission
    tenant, channel = identity_test_setup

    # Register tools via mock registry
    mock_registry = MagicMock(spec=ToolRegistry)
    
    c_tasks = MagicMock()
    c_tasks.slug = "task_create"
    c_tasks.required_permissions = [("create", "task")]

    c_restricted = MagicMock()
    c_restricted.slug = "customer_create_or_update"
    c_restricted.required_permissions = [("update", "customer")]

    c_http = MagicMock()
    c_http.slug = "http_request"
    c_http.required_permissions = []

    c_product = MagicMock()
    c_product.slug = "product_add_or_update"
    c_product.required_permissions = []

    mock_registry.list_contracts.return_value = [c_tasks, c_restricted, c_http, c_product]

    # Grant only task permission to tenant, but DENY customer update
    perm = Permission(
        id=uuid4(),
        tenant_id=tenant.id,
        action="create",
        resource="task",
        effect="allow",
    )
    test_db_session.add(perm)
    test_db_session.commit()

    identity_svc = AgentIdentityService(test_db_session, tool_registry=mock_registry)
    profile = identity_svc.get_profile(tenant.id, refresh=True)

    # 1. Allowed tool is directly executable
    assert any("مهام" in s for s in profile.activated.directly_executable)

    # 2. Restricted tool without permission is NOT directly executable
    assert not any("تسجيل عميل جديد" in s for s in profile.activated.directly_executable)

    # 3. http_request without active HTTP integration is in requires_setup_or_approval
    assert any("التواصل مع خدمات خارجية" in s and "تكامل API" in s for s in profile.activated.requires_setup_or_approval)

    # 4. Sensitive tool product_add_or_update requires owner approval
    assert any("إضافة أو تعديل منتج" in s and "موافقة الإدارة" in s for s in profile.activated.requires_setup_or_approval)


def test_21_greeting_stripping_advanced_patterns(test_db_session):
    """
    اختبار تجريد التحيات المكررة المتقدم:
    - معالجة النقطتين الرأسيتين (:).
    - معالجة واو العطف (وأهلاً وسهلاً).
    - معالجة 'شكراً لسؤالك'.
    - الحفاظ على جمل الترحيب السياقية التأسيسية ('أهلاً بك في ناظم').
    - منع الردود الفارغة أو المبتورة.
    """
    engine = ConversationalAgentEngine(db=test_db_session)

    # 1. Trailing colon
    res1 = engine._strip_repeated_greeting_opener("أهلاً بك: تفاصيل النظام كالتالي...")
    assert res1 == "تفاصيل النظام كالتالي..."

    # 2. Conjunction waw
    res2 = engine._strip_repeated_greeting_opener("وأهلاً وسهلاً بك! يمكنك الاطلاع على...")
    assert res2 == "يمكنك الاطلاع على..."

    # 3. 'شكراً لسؤالك'
    res3 = engine._strip_repeated_greeting_opener("شكراً لسؤالك! نحن نوفر حلاً محاسبياً...")
    assert res3 == "نحن نوفر حلاً محاسبياً..."

    # 4. 'شكراً على سؤالك المهم'
    res4 = engine._strip_repeated_greeting_opener("شكراً على سؤالك المهم: تجد الأسعار في...")
    assert res4 == "تجد الأسعار في..."

    # 5. Preserves meaningful contextual introductions
    res5 = engine._strip_repeated_greeting_opener("أهلاً بك في ناظم! يسعدنا تقديم الدعم...")
    assert res5.startswith("أهلاً بك في ناظم!")

    # 6. Prevents empty or too short response
    res6 = engine._strip_repeated_greeting_opener("مرحباً بك!")
    assert res6 == "مرحباً بك!"

    # 7. Regression: Must NOT mangle words starting with 'أهل' (e.g. 'أهلي', 'أهلية')
    res7 = engine._strip_repeated_greeting_opener("أهلي يملكون متجراً فهل يناسبهم النظام؟")
    assert res7 == "أهلي يملكون متجراً فهل يناسبهم النظام؟"

    res8 = engine._strip_repeated_greeting_opener("أهلية المنشأة تتطلب سجلاً تجارياً.")
    assert res8 == "أهلية المنشأة تتطلب سجلاً تجارياً."

    # 8. Regression: Cleanly strips valid greetings with various punctuation
    res9 = engine._strip_repeated_greeting_opener("أهلاً بك! يدعم النظام التحويل بين المستودعات.")
    assert res9 == "يدعم النظام التحويل بين المستودعات."

    res10 = engine._strip_repeated_greeting_opener("أهلاً بك: تفاصيل النظام كالتالي.")
    assert res10 == "تفاصيل النظام كالتالي."

    res11 = engine._strip_repeated_greeting_opener("شكراً لسؤالك. نحن نوفر هذه الخدمة.")
    assert res11 == "نحن نوفر هذه الخدمة."


def test_22_temporal_continuity_break_detection_and_merged_greetings(test_db_session, identity_test_setup):
    """
    الاستمرارية الزمنية:
    - رصد انقطاع أكثر من 12 ساعة بين الرسائل.
    - رصد التحيات المدمجة مع أسئلة (مثل: 'مرحبا، كم السعر؟').
    """
    from datetime import datetime, timezone, timedelta
    tenant, channel = identity_test_setup

    engine = ConversationalAgentEngine(db=test_db_session)
    t0 = datetime.now(timezone.utc) - timedelta(hours=14)
    t1 = datetime.now(timezone.utc)

    m_prior = Message(id=uuid4(), tenant_id=tenant.id, sender_type="agent", content="تم تزويدك بالبيانات.", created_at=t0)
    m_returning = Message(id=uuid4(), tenant_id=tenant.id, sender_type="customer", content="أهلاً، كم سعر الاشتراك؟", created_at=t1)

    continuity = engine._analyze_dialogue_continuity([m_prior, m_returning], m_returning, "ناظم")

    # Gap is 14 hours (> 12h) -> is_returning_after_break must be True
    assert continuity["is_returning_after_break"] is True

    # Greeting is merged with query -> customer_is_greeting must be True
    assert continuity["customer_is_greeting"] is True

    # Same day short gap (< 12h)
    t_short = t0 + timedelta(hours=2)
    m_short_gap = Message(id=uuid4(), tenant_id=tenant.id, sender_type="customer", content="كم سعر الاشتراك؟", created_at=t_short)
    continuity_short = engine._analyze_dialogue_continuity([m_prior, m_short_gap], m_short_gap, "ناظم")
    assert continuity_short["is_returning_after_break"] is False
    assert continuity_short["customer_is_greeting"] is False


def test_23_profile_memoization_cache_reduces_queries(test_db_session, identity_test_setup):
    """
    تقليل الاستعلامات وحفظ الذاكرة المؤقتة (Memoization):
    - استدعاء get_profile المتكرر على نفس الكائن يُرجع النسخة المخزنة دون تكرار الاستعلامات.
    - استدعاء clear_cache يفرغ الذاكرة المؤقتة.
    """
    tenant, channel = identity_test_setup
    identity_svc = AgentIdentityService(test_db_session)

    p1 = identity_svc.get_profile(tenant.id)
    p2 = identity_svc.get_profile(tenant.id)
    assert p1 is p2

    identity_svc.clear_cache()
    p3 = identity_svc.get_profile(tenant.id)
    assert p3 is not p1
    assert p3.core.name == p1.core.name
