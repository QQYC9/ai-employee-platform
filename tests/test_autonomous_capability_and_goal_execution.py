from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.domain import (
    Approval,
    AuditEvent,
    BusinessBrain,
    Capability,
    CapabilityVersion,
    Channel,
    Conversation,
    Customer,
    DevelopmentRequest,
    DevelopmentRun,
    Knowledge,
    Message,
    OutboxEvent,
    Task,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService
from packages.services.business_brain_service import BusinessBrainService
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.knowledge_service import KnowledgeService
from packages.self_development.engine import SelfDevelopmentEngine
from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.specification import CapabilitySpecification
from packages.self_development.verifier import CapabilitySecurityVerifier
from packages.tools.registry import create_default_registry


# ---------------------------------------------------------------------------
# Test Fixtures & Utilities
# ---------------------------------------------------------------------------
class MockChatAIProvider:
    """Deterministic Mock AI provider for controlled conversational tests."""
    def __init__(self, reply_text: str = "مرحباً بك! هذه إجابة اختبارية دقيقة دون تخمين."):
        self.reply_text = reply_text
        self.call_count = 0
        self.last_prompt = ""
        self.last_system_instruction = ""

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
        return self.reply_text


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_tenant(db: Session):
    t = Tenant(
        id=uuid.uuid4(),
        name="Al-Nokhba Enterprise",
        slug=f"al-nokhba-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        tenant_id=t.id,
        name="Abu Fahad (Owner)",
        email=f"owner-{uuid.uuid4().hex[:6]}@alnokhba.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "مؤسسة النخبة التجارية", "industry": "retail"},
        products={},
        pricing={},
        policies={},
        operations={},
        version=1,
    )
    db.add(brain)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def telegram_channel(db: Session, test_tenant: Tenant):
    ch = Channel(
        tenant_id=test_tenant.id,
        name="Telegram Official",
        channel_type="telegram",
        status="active",
        config={
            "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            "owner_chat_id": "987654321",
            "owner_identifiers": ["987654321", "@abufahad_owner"],
        },
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


def make_inbound_message(
    channel: Channel,
    tenant: Tenant,
    content: str,
    *,
    is_owner: bool = True,
    sender_id: str = "987654321",
    sender_name: str = "Abu Fahad",
    customer_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> InboundMessage:
    return InboundMessage(
        channel_type=channel.channel_type,
        channel_id=channel.id,
        tenant_id=tenant.id,
        sender_id=sender_id,
        sender_name=sender_name,
        external_message_id=f"msg.{uuid.uuid4().hex[:8]}",
        content=content,
        timestamp=datetime.now(timezone.utc),
        raw_payload={"test": True},
    )


# ===========================================================================
# 14 MANDATORY ARCHITECTURAL INTEGRATION ACCEPTANCE TESTS
# ===========================================================================

def test_scenario_1_intent_routing_conversation_summary_vs_business_summary(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 1 — توجيه النية الصحيح:
    المالك يطلب تلخيص محادثة عميل طلب موظفًا بشريًا.
    المتوقع:
    - لا تستدعى أداة business_summary
    - يسترجع النظام المحادثة المطابقة بدقة
    - يلخص الرسائل الفعلية وحالة التصعيد لموظف بشري
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry)

    # 1. Seed a customer and an escalated conversation
    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        name="أحمد بن صالح",
        phone="+966500112233",
    )
    db.add(customer)
    db.flush()

    cust_conv = Conversation(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        channel_id=telegram_channel.id,
        customer_id=customer.id,
        status="open",
        metadata_json={
            "is_owner": False,
            "needs_human": True,
            "escalation_reason": "العميل يطلب استرجاعاً فورياً لمبلغ الطلب",
        },
    )
    db.add(cust_conv)
    db.flush()

    msg1 = Message(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        conversation_id=cust_conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="السلام عليكم، المنتج وصل تالف وأريد استرجاع المبلغ والتحدث مع موظف بشري فوراً",
    )
    msg2 = Message(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        conversation_id=cust_conv.id,
        sender_type="agent",
        content="وعليكم السلام يا أستاذ أحمد. تم تصعيد طلبك لخدمة العملاء وسيتواصل معك موظف بشري في أقرب وقت.",
    )
    db.add_all([msg1, msg2])
    db.commit()

    # 2. Owner asks specifically to summarize Ahmed's escalated conversation
    owner_inbound = make_inbound_message(
        telegram_channel,
        test_tenant,
        "لخص لي محادثة العميل أحمد بن صالح اللي طلب موظف بشري",
        is_owner=True,
    )
    owner_msg = channel_svc.process_inbound_message(owner_inbound)
    db.commit()

    result = engine.process_message(owner_msg)
    assert result.success is True
    reply = result.reply_content or ""

    # Must contain conversation summary details, not general business operations
    assert "أحمد بن صالح" in reply or "أحمد" in reply
    assert "استرجاع" in reply or "تالف" in reply or "موظف بشري" in reply
    assert "المهام" not in reply  # Proves business_summary was NOT mistakenly triggered


def test_scenario_2_business_summary_accurate_data(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 2 — ملخص النشاط:
    المالك يطلب ملخص نشاط المنشأة اليوم.
    المتوقع:
    - تُستدعى أداة ملخص النشاط
    - تظهر الإحصائيات المحسوبة من البيانات الفعلية، لا قيم ثابتة أو أصفار افتراضية
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry)

    # Seed 3 tasks with real statuses
    task1 = Task(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        title="تجهيز الشحنات",
        objective="تجهيز شحنات الطلبات",
        status="completed",
    )
    task2 = Task(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        title="متابعة طلبات الموردين",
        objective="متابعة وصول بضائع الموردين",
        status="in_progress",
    )
    task3 = Task(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        title="تدقيق الفواتير الضريبية",
        objective="تدقيق ومراجعة الفواتير",
        status="pending",
    )
    db.add_all([task1, task2, task3])
    db.commit()

    owner_inbound = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أعطني ملخص نشاط المنشأة والعمليات اليوم",
        is_owner=True,
    )
    owner_msg = channel_svc.process_inbound_message(owner_inbound)
    db.commit()

    result = engine.process_message(owner_msg)
    assert result.success is True
    reply = result.reply_content or ""

    # Real calculated statistics
    assert "إجمالي المهام: 3" in reply
    assert "المكتملة: 1" in reply
    assert "قيد التنفيذ: 1" in reply
    assert "المعلقة: 1" in reply


def test_scenario_3_reuse_existing_capability_customer_search(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 3 — تنفيذ قدرة موجودة:
    المالك يطلب البحث عن عميل.
    المتوقع:
    - يعيد استخدام أداة البحث الموجودة customer_search
    - لا يبدأ تطوير قدرة جديدة بلا داعٍ
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry, self_development_engine=self_dev)

    # Seed customer
    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        name="سلطان القحطاني",
        phone="+966555123456",
    )
    db.add(customer)
    db.commit()

    owner_inbound = make_inbound_message(
        telegram_channel,
        test_tenant,
        "ابحث عن العميل سلطان القحطاني",
        is_owner=True,
    )
    owner_msg = channel_svc.process_inbound_message(owner_inbound)
    db.commit()

    result = engine.process_message(owner_msg)
    assert result.success is True
    reply = result.reply_content or ""

    # Found using customer_search
    assert "سلطان القحطاني" in reply

    # Ensure NO spurious development request was created
    dev_reqs = db.scalars(
        select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == test_tenant.id)
    ).all()
    assert len(dev_reqs) == 0


def test_scenario_4_capability_gap_detection_and_dev_request(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 4 — اكتشاف قدرة ناقصة:
    المالك يطلب عملية تتطلب قدرة برمجية غير متوفرة.
    المتوقع:
    - يميز النظام بين نقص القدرة وغياب أداة موجودة
    - ينشئ طلب تطوير رسمي DevelopmentRequest
    - يعد المواصفات ويتحقق في صندوق الرمل
    - يطلب موافقة المالك الصريحة
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry, self_development_engine=self_dev)

    owner_inbound = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أريد حساب ضريبة القيمة المضافة للفواتير، هل يمكنك تطوير أداة حساب الضريبة vat_calculator؟",
        is_owner=True,
    )
    owner_msg = channel_svc.process_inbound_message(owner_inbound)
    db.commit()

    result = engine.process_message(owner_msg)
    assert result.success is True
    reply = result.reply_content or ""

    # Verified gap discovery message
    assert "اكتشاف فجوة قدرات" in reply or "vat_calculator" in reply
    assert "أوافق على تفعيل القدرة vat_calculator" in reply

    # DevelopmentRequest created in database
    dev_req = db.scalar(
        select(DevelopmentRequest).where(
            DevelopmentRequest.tenant_id == test_tenant.id,
            DevelopmentRequest.requirements["slug"].as_string() == "vat_calculator",
        )
    )
    assert dev_req is not None
    assert dev_req.status in ("requested", "under_development", "pending_review", "specified")

    # Pending goal stored in conversation metadata for resumption
    conv = db.scalar(select(Conversation).where(Conversation.id == owner_msg.conversation_id))
    assert conv is not None
    pending_goal = (conv.metadata_json or {}).get("pending_goal")
    assert pending_goal is not None
    assert pending_goal["slug"] == "vat_calculator"


def test_scenario_5_capability_development_and_ast_verification(
    db: Session, test_tenant: Tenant
):
    """
    الاختبار 5 — تطوير قدرة وتفعيلها:
    المتوقع:
    - توليد المواصفات والكود واجتياز فحص الأمان AST وصندوق الرمل
    - لا تفعل القدرة قبل موافقة المالك
    """
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)

    dev_req, _ = self_dev.create_development_request(
        tenant_id=test_tenant.id,
        title="VAT Calculator Tool",
        reason="Calculate 15% VAT for commercial invoices",
        requirements={"slug": "vat_calc_v5"},
    )

    spec_dict = {
        "name": "VAT Calculator v5",
        "slug": "vat_calc_v5",
        "description": "Calculates VAT at 15%",
        "purpose": "Invoice tax computation",
        "inputs": {"subtotal": "number"},
        "outputs": {"tax": "number", "total": "number"},
        "risk_level": "medium",
        "acceptance_tests": [
            {
                "input": {"subtotal": 200},
                "expected": {"tax": 30.0, "total": 230.0},
            }
        ],
    }

    version = self_dev.prepare_specification(
        tenant_id=test_tenant.id,
        request_id=dev_req.id,
        spec_data=spec_dict,
    )

    clean_code = (
        "def run(inputs):\n"
        "    subtotal = float(inputs.get('subtotal', 0))\n"
        "    tax = round(subtotal * 0.15, 2)\n"
        "    return {'tax': tax, 'total': round(subtotal + tax, 2)}\n"
    )

    version, run = self_dev.develop_and_test(
        tenant_id=test_tenant.id,
        version_id=version.id,
        implementation_code=clean_code,
    )

    assert run.status == "passed"
    assert version.status in ("testing", "awaiting_approval")  # Not yet active! Requires approval gate
    assert version.status != "active"
    assert version.approval_id is not None


def test_scenario_6_goal_resumption_after_approval(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 6 — استئناف الهدف:
    بعد موافقة المالك، يستأنف النظام الهدف الأصلي تلقائياً ويثبت نجاحه دون مطالبة المالك بإعادة الشرح.
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry, self_development_engine=self_dev)

    # 1. Trigger development to populate pending goal
    inbound_dev = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أريد حساب ضريبة القيمة المضافة للفواتير، هل يمكنك تطوير أداة حساب الضريبة vat_calculator؟",
        is_owner=True,
    )
    msg1 = channel_svc.process_inbound_message(inbound_dev)
    db.commit()
    engine.process_message(msg1)

    # 2. Owner sends approval command
    inbound_approval = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أوافق على تفعيل القدرة vat_calculator",
        is_owner=True,
        conversation_id=msg1.conversation_id,
    )
    msg2 = channel_svc.process_inbound_message(inbound_approval)
    db.commit()

    result = engine.process_message(msg2)
    assert result.success is True
    reply = result.reply_content or ""

    # Confirms activation AND automatically executes the resumed goal
    assert "تفعيل القدرة" in reply
    assert "استئناف" in reply
    assert "15.0" in reply or "115.0" in reply


def test_scenario_7_capability_reuse_without_redevelopment(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 7 — إعادة الاستخدام:
    يستخدم الموظف القدرة التي اكتسبها في طلب لاحق دون إعادة تطويرها.
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry, self_development_engine=self_dev)

    # 1. Activate capability
    inbound_dev = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أريد حساب ضريبة القيمة المضافة للفواتير، هل يمكنك تطوير أداة حساب الضريبة vat_calculator؟",
        is_owner=True,
    )
    msg1 = channel_svc.process_inbound_message(inbound_dev)
    db.commit()
    engine.process_message(msg1)

    inbound_approval = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أوافق على تفعيل القدرة vat_calculator",
        is_owner=True,
        conversation_id=msg1.conversation_id,
    )
    msg2 = channel_svc.process_inbound_message(inbound_approval)
    db.commit()
    engine.process_message(msg2)

    # Count requests after activation
    dev_count_before = len(
        db.scalars(select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == test_tenant.id)).all()
    )

    # 2. Subsequent request requesting vat_calculator
    inbound_reuse = make_inbound_message(
        telegram_channel,
        test_tenant,
        "احسب الضريبة للفاتورة بمبلغ 1000 ريال باستخدام أداة vat_calculator",
        is_owner=True,
    )
    msg3 = channel_svc.process_inbound_message(inbound_reuse)
    db.commit()

    result = engine.process_message(msg3)
    assert result.success is True
    reply = result.reply_content or ""

    # Reused directly
    assert "تم استخدام القدرة المعتمدة في النظام مباشرة" in reply
    assert "النتيجة" in reply

    # Zero new development requests created
    dev_count_after = len(
        db.scalars(select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == test_tenant.id)).all()
    )
    assert dev_count_after == dev_count_before


def test_scenario_8_business_identity_onboarding_no_hallucination(
    db: Session, telegram_channel: Channel
):
    """
    الاختبار 8 — تأسيس معلومات النشاط ومنع الاختلاق:
    عند بدء تهيئة نشاط جديد بلا معلومات مؤكدة، يسأل الموظف المالك عن البيانات الضرورية
    ولا يخترع اسماً مثل 'البركة التجاري' أو دولة أو منتجات عسل.
    """
    # Create brand-new unconfigured tenant
    new_tenant = Tenant(
        id=uuid.uuid4(),
        name="Unconfigured Shop",
        slug=f"unconfigured-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(new_tenant)
    db.flush()

    new_channel = Channel(
        tenant_id=new_tenant.id,
        name="Telegram Fresh",
        channel_type="telegram",
        status="active",
        config={
            "bot_token": "123456:FRESH-TOKEN-ABC",
            "owner_chat_id": "777888999",
            "owner_identifiers": ["777888999"],
        },
    )
    db.add(new_channel)

    # Completely blank BusinessBrain
    empty_brain = BusinessBrain(
        tenant_id=new_tenant.id,
        identity={},
        products={},
        services={},
        pricing={},
        policies={},
        operations={},
        version=1,
    )
    db.add(empty_brain)
    db.commit()

    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry)

    owner_inbound = make_inbound_message(
        new_channel,
        new_tenant,
        "أخبرني اسم متجركم وإيش الخدمات اللي تقدمونها؟",
        is_owner=True,
        sender_id="777888999",
    )
    msg = channel_svc.process_inbound_message(owner_inbound)
    db.commit()

    result = engine.process_message(msg)
    assert result.success is True
    reply = result.reply_content or ""

    # Must NOT hallucinate "البركة" or honey products!
    assert "البركة" not in reply
    assert "عسل" not in reply
    # Must initiate guided interactive onboarding
    assert "ملف المنشأة" in reply
    assert "الاسم التجاري" in reply or "الخدمات" in reply


def test_scenario_9_save_and_retrieve_verified_business_knowledge(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 9 — حفظ المعلومات المؤكدة:
    بعد أن يقدم المالك معلومات النشاط، يحفظها النظام في Tenant الصحيح ويتحقق من إمكانية استرجاعها.
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry)

    owner_inbound = make_inbound_message(
        telegram_channel,
        test_tenant,
        "اسم المتجر: متجر سحابة البرمجيات الذكية",
        is_owner=True,
    )
    msg = channel_svc.process_inbound_message(owner_inbound)
    db.commit()

    result = engine.process_message(msg)
    assert result.success is True
    reply = result.reply_content or ""

    assert "تم حفظ وتحديث معلومات النشاط التجاري بنجاح" in reply

    # Verify persisted in BusinessBrain
    brain_svc = BusinessBrainService(db)
    brain = brain_svc.get_brain(test_tenant.id)
    assert brain is not None
    assert brain.identity.get("name") == "متجر سحابة البرمجيات الذكية"

    # Verify persisted in KnowledgeBase as verified
    knowledge_records = db.scalars(
        select(Knowledge).where(
            Knowledge.tenant_id == test_tenant.id,
            Knowledge.knowledge_type == "identity",
        )
    ).all()
    assert len(knowledge_records) >= 1
    assert any("متجر سحابة البرمجيات الذكية" in k.content for k in knowledge_records)


def test_scenario_10_anti_hallucination_unconfirmed_facts(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 10 — منع اختلاق الحقائق:
    إذا سُئل الموظف عن معلومة لم يقدمها المالك ولا يوجد لها مصدر موثوق،
    يوضح أنها غير معروفة بدل اختراع إجابة.
    """
    # Customer asks about an unconfigured installment option
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)

    # Provider will see system prompt with strict anti-hallucination instructions
    mock_provider = MockChatAIProvider(
        reply_text="عذراً، لم يتم تزويدنا بتفاصيل أو شروط التقسيط عبر تابي حتى الآن. يمكنك التواصل مع موظف المبيعات لمساعدتك."
    )
    engine = ConversationalAgentEngine(db=db, tool_registry=registry, ai_provider=mock_provider)

    customer = Customer(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        name="فيصل الشمري",
        phone="+966500998877",
    )
    db.add(customer)
    db.commit()

    cust_conv = Conversation(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        channel_id=telegram_channel.id,
        customer_id=customer.id,
        status="open",
        metadata_json={"is_owner": False},
    )
    db.add(cust_conv)
    db.commit()

    cust_msg = Message(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        conversation_id=cust_conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="هل تتوفر لديكم خدمة التقسيط عبر تابي وبكم الفائدة؟",
    )
    db.add(cust_msg)
    db.commit()

    result = engine.process_message(cust_msg)
    assert result.success is True

    # Verify anti-hallucination instruction was injected into LLM prompt
    assert "CRITICAL ANTI-HALLUCINATION RULE" in mock_provider.last_system_instruction
    assert "Never invent facts not supported by the Business Brain" in mock_provider.last_system_instruction


def test_scenario_11_cross_tenant_isolation(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 11 — عزل المستأجرين:
    لا يستطيع موظف نشاط الوصول إلى محادثات أو منتجات أو قدرات أو ذاكرة نشاط آخر.
    """
    # Create Tenant B
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Tenant B Org",
        slug=f"tenant-b-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(tenant_b)
    db.flush()

    channel_b = Channel(
        tenant_id=tenant_b.id,
        name="Telegram B",
        channel_type="telegram",
        status="active",
        config={"owner_chat_id": "111222333", "owner_identifiers": ["111222333"]},
    )
    db.add(channel_b)

    # Seed confidential customer in Tenant A
    secret_customer_a = Customer(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        name="الأميرة سارة السرية",
        phone="+966511111111",
    )
    db.add(secret_customer_a)
    db.commit()

    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry)

    # Tenant B tries to search for Tenant A's customer
    inbound_b = make_inbound_message(
        channel_b,
        tenant_b,
        "ابحث عن العميل الأميرة سارة السرية",
        is_owner=True,
        sender_id="111222333",
    )
    msg_b = channel_svc.process_inbound_message(inbound_b)
    db.commit()

    result_b = engine.process_message(msg_b)
    assert result_b.success is True
    reply_b = result_b.reply_content or ""

    # Tenant B must NOT find Tenant A's customer
    assert "لم يتم العثور على" in reply_b
    assert "+966511111111" not in reply_b


def test_scenario_12_honest_failure_on_unsafe_capability(db: Session, test_tenant: Tenant):
    """
    الاختبار 12 — الفشل الصادق:
    عندما يفشل تطوير القدرة أو يرفض أمنياً (AST violation)،
    لا يدعي الموظف نجاحها ويقدم وصفاً واضحاً ومحايداً لما حدث.
    """
    verifier = CapabilitySecurityVerifier()
    malicious_code = (
        "import os\n"
        "def run(inputs):\n"
        "    os.system('cat /etc/passwd')\n"
        "    return {'status': 'hacked'}\n"
    )
    verification = verifier.verify_ast(malicious_code)
    assert verification["valid"] is False
    assert any("os" in v or "system" in v for v in verification["violations"])

    # Engine sandbox reject verification
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)
    dev_req, _ = self_dev.create_development_request(
        tenant_id=test_tenant.id,
        title="Unsafe Capability",
        reason="Security test",
        requirements={"slug": "unsafe_cap"},
    )
    version = self_dev.prepare_specification(
        tenant_id=test_tenant.id,
        request_id=dev_req.id,
        spec_data={
            "name": "Unsafe Cap",
            "slug": "unsafe_cap",
            "description": "Unsafe AST test",
            "purpose": "Security AST verification test",
            "inputs": {},
            "outputs": {},
            "risk_level": "high",
        },
    )

    version, run = self_dev.develop_and_test(
        tenant_id=test_tenant.id,
        version_id=version.id,
        implementation_code=malicious_code,
    )

    assert run.status == "failed"
    assert "failed static security analysis" in (run.error_message or "")
    assert version.status != "active"


def test_scenario_13_inbound_idempotency_prevents_duplicate_processing(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 13 — منع التكرار:
    لا يؤدي تكرار تحديث Telegram أو إعادة محاولة Outbox إلى إنشاء المنتج أو تنفيذ العملية مرتين.
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry)

    inbound = make_inbound_message(
        telegram_channel,
        test_tenant,
        "سجل مهمة تحضير المعرض الدولي",
        is_owner=True,
    )
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    # First execution
    res1 = engine.process_message(msg)
    assert res1.success is True
    assert res1.skipped is False

    # Immediate second duplicate attempt
    res2 = engine.process_message(msg)
    assert res2.skipped is True
    assert "already processed" in (res2.skip_reason or "")


def test_scenario_14_goal_persistence_across_lifecycle(
    db: Session, test_tenant: Tenant, telegram_channel: Channel
):
    """
    الاختبار 14 — عدم فقد الهدف:
    لا يفقد النظام الطلب الأصلي بعد الموافقة أو التطوير أو إعادة محاولة المهمة.
    """
    channel_svc = ChannelService(db)
    registry = create_default_registry(db)
    self_dev = SelfDevelopmentEngine(db=db, tool_registry=registry)
    engine = ConversationalAgentEngine(db=db, tool_registry=registry, self_development_engine=self_dev)

    # 1. Ask for new capability
    inbound_dev = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أريد حساب ضريبة القيمة المضافة للفواتير، هل يمكنك تطوير أداة حساب الضريبة vat_calculator؟",
        is_owner=True,
    )
    msg1 = channel_svc.process_inbound_message(inbound_dev)
    db.commit()
    engine.process_message(msg1)

    conv = db.scalar(select(Conversation).where(Conversation.id == msg1.conversation_id))
    assert conv is not None
    pending_goal = (conv.metadata_json or {}).get("pending_goal")
    assert pending_goal is not None
    assert pending_goal["slug"] == "vat_calculator"

    # 2. Interleave with an informational or greeting query
    inbound_greeting = make_inbound_message(
        telegram_channel,
        test_tenant,
        "السلام عليكم يا مساعدي",
        is_owner=True,
        conversation_id=conv.id,
    )
    msg_greet = channel_svc.process_inbound_message(inbound_greeting)
    db.commit()
    engine.process_message(msg_greet)

    # Goal MUST still be persisted in conversation metadata
    db.refresh(conv)
    persisted_goal = (conv.metadata_json or {}).get("pending_goal")
    assert persisted_goal is not None
    assert persisted_goal["slug"] == "vat_calculator"

    # 3. Now send approval -> Goal resumes!
    inbound_approval = make_inbound_message(
        telegram_channel,
        test_tenant,
        "أوافق على تفعيل القدرة vat_calculator",
        is_owner=True,
        conversation_id=conv.id,
    )
    msg_appr = channel_svc.process_inbound_message(inbound_approval)
    db.commit()
    res_appr = engine.process_message(msg_appr)

    assert res_appr.success is True
    assert "استئناف" in (res_appr.reply_content or "")
    assert "طلبك الأصلي" in (res_appr.reply_content or "")
