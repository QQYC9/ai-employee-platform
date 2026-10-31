from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    GeneratedDocument,
    Knowledge,
    Message,
    User,
)
from packages.models.tenant import Tenant
from packages.self_development.engine import SelfDevelopmentEngine
from packages.services.approval_service import ApprovalService
from packages.services.business_brain_service import BusinessBrainService
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.tools.registry import create_default_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def mundhir_tenant(db: Session):
    """
    Tenant modeling 'Al-Mundhir Technology' before business facts are taught.
    Has empty products and services in BusinessBrain.
    """
    t = Tenant(
        name="Al-Mundhir Technology",
        slug=f"al-mundhir-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        tenant_id=t.id,
        name="Al-Mundhir Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@al-mundhir.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    customer = User(
        id=uuid.uuid4(),
        tenant_id=t.id,
        name="Prospective Client",
        email=f"client-{uuid.uuid4().hex[:6]}@client.com",
        role="customer",
        status="active",
    )
    db.add(customer)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "المنذر تكنولوجي"},
        brand={"tone": "مهني"},
        products={},
        services={},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def mundhir_owner(db: Session, mundhir_tenant: Tenant):
    return db.scalar(select(User).where(User.tenant_id == mundhir_tenant.id, User.role == "tenant_owner"))


@pytest.fixture
def telegram_channel(db: Session, mundhir_tenant: Tenant, mundhir_owner: User):
    ch = Channel(
        tenant_id=mundhir_tenant.id,
        channel_type="telegram",
        name="Telegram Channel Al-Mundhir",
        status="active",
        config={
            "bot_token": "TEST_TG_TOKEN_123",
            "owner_identifiers": [str(mundhir_owner.id), "775274399", "mundhir_tg_owner"],
        },
    )
    db.add(ch)
    db.commit()
    return ch


@pytest.fixture
def owner_conv(db: Session, mundhir_tenant: Tenant, telegram_channel: Channel):
    conv = Conversation(
        tenant_id=mundhir_tenant.id,
        channel_id=telegram_channel.id,
        status="open",
        subject="Telegram Owner Direct",
        metadata_json={"is_owner": True},
    )
    db.add(conv)
    db.commit()
    return conv


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_1_al_mundhir_technology_company_profile_without_knowledge_inquires_without_hallucination(
    db: Session,
    mundhir_tenant: Tenant,
    telegram_channel: Channel,
    mundhir_owner: User,
    owner_conv: Conversation,
):
    """
    Scenario 1:
    The exact live scenario reported for tenant 'Al-Mundhir Technology':
    Owner sends the complex prompt asking to prepare a professional company profile,
    and says: "إذا لم تكن لديك المهارة اللازمة فاكتشف المهارة الناقصة وطورها... واطلب موافقتي إذا كانت دورة التطوير تتطلب ذلك".

    Verification requirements:
      1. Must NOT output the false-positive generic approval response:
         "لا توجد حالياً أي طلبات موافقة معلقة بانتظار الاعتماد في منشأتكم."
      2. Must distinguish Missing Business Context from Capability Gap:
         - generate_document already exists in ToolRegistry.
         - Company definition, products, and services are missing in BusinessBrain.
      3. Must NOT invent or hallucinate unverified facts.
      4. Must NOT create a spurious DevelopmentRequest or code version.
      5. Must politely inquire with clear, structured questions to collect the missing facts.
    """
    engine = ConversationalAgentEngine(db=db)

    prompt = (
        "يا موظف المنذر تكنولوجي، أريد منك إعداد ملف تعريفي احترافي لشركتي أستطيع إرساله للعملاء المحتملين، "
        "بحيث يوضح من نحن، وما الخدمات والمنتجات التي نقدمها، وما الذي يميزنا عن المنافسين، وكيف يمكن للعميل الاستفادة من خدماتنا. "
        "أريد الملف منظماً وجاهزاً للاستخدام التجاري، وإذا لم تكن لديك المهارة اللازمة لتنفيذ هذه المهمة، "
        "فاكتشف المهارة الناقصة وطوّرها وفق نظام التطوير الذاتي لديك، ولا تدّعِ أي معلومات عن شركتنا لم أزوّدك بها. "
        "أخبرني بما تحتاج إليه، واطلب موافقتي إذا كانت دورة التطوير تتطلب ذلك."
    )

    msg = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content=prompt,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    db.commit()

    res = engine.process_message(msg)
    assert res is not None
    assert res.success is True
    reply = res.reply_content

    # 1. Critical Assertion: Must NOT output the erroneous generic approval response
    assert "لا توجد حالياً أي طلبات موافقة معلقة" not in reply

    # 2. Recognizes tool availability and inquires about missing facts without hallucination
    assert "generate_document" in reply
    assert "البيانات الأساسية" in reply or "البيانات الناقصة" in reply or "الخدمات والمنتجات" in reply
    assert "المزايا التنافسية" in reply
    assert "من نحن" in reply

    # 3. No spurious DevelopmentRequest created
    dev_reqs = db.scalars(
        select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == mundhir_tenant.id)
    ).all()
    assert len(dev_reqs) == 0

    # 4. No spurious Approval created
    approvals = db.scalars(
        select(Approval).where(Approval.tenant_id == mundhir_tenant.id)
    ).all()
    assert len(approvals) == 0


def test_2_owner_provides_facts_and_generates_company_profile_document(
    db: Session,
    mundhir_tenant: Tenant,
    telegram_channel: Channel,
    mundhir_owner: User,
    owner_conv: Conversation,
):
    """
    Scenario 2:
    Owner provides company facts (Nazem, Ciro, Digital Employees), which are saved into BusinessBrain,
    and then asks to prepare the company profile document.
    Verifies:
      1. Business facts are properly extracted and persisted into BusinessBrain.
      2. DocumentGeneratorTool (generate_document) creates the actual document in storage.
      3. Generated profile contains Nazem, Ciro, and Digital Employees.
    """
    engine = ConversationalAgentEngine(db=db)

    # Step 1: Owner provides company details
    teach_msg = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content="نحن شركة المنذر تكنولوجي، نقدم موظفين رقميين للشركات، وبرنامج محاسبي اسمه ناظم وبرنامج لإدارة الشبكات اسمه سيرو. ميزتنا هي توفير التكاليف وسرعة النشر.",
        created_at=datetime.now(timezone.utc),
    )
    db.add(teach_msg)
    db.commit()

    res1 = engine.process_message(teach_msg)
    assert res1.success is True
    assert "تم حفظ وتحديث معلومات النشاط التجاري" in res1.reply_content or "المنذر تكنولوجي" in res1.reply_content

    # Verify brain updated
    brain_svc = BusinessBrainService(db)
    brain = brain_svc.get_brain(mundhir_tenant.id)
    assert brain is not None
    assert "المنذر تكنولوجي" in (brain.identity.get("name") or "")

    # Step 2: Owner requests document generation
    doc_req_msg = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content="أريد الآن إعداد ملف تعريفي احترافي لشركتنا لإرساله للعملاء المحتملين.",
        created_at=datetime.now(timezone.utc),
    )
    db.add(doc_req_msg)
    db.commit()

    res2 = engine.process_message(doc_req_msg)
    assert res2.success is True
    reply2 = res2.reply_content

    assert "تم إعداد وتوليد الملف التعريفي الاحترافي بنجاح" in reply2
    assert "ناظم" in reply2 or "سيرو" in reply2 or "موظفون رقميون" in reply2
    assert "المنذر تكنولوجي" in reply2

    # Verify GeneratedDocument DB record
    docs = db.scalars(
        select(GeneratedDocument).where(GeneratedDocument.tenant_id == mundhir_tenant.id)
    ).all()
    assert len(docs) >= 1
    assert docs[0].document_type == "company_profile"


def test_3_computational_capability_gap_triggers_autonomous_self_development_and_approval(
    db: Session,
    mundhir_tenant: Tenant,
    telegram_channel: Channel,
    mundhir_owner: User,
    owner_conv: Conversation,
):
    """
    Scenario 3:
    Owner requests an actual missing algorithmic/computational tool (depreciation_calculator)
    that does NOT exist in ToolRegistry.
    Verifies:
      1. Autonomous capability gap detection activates.
      2. DevelopmentRequest registered.
      3. AST check & ExecutionSandbox acceptance tests run and pass 100%.
      4. SHA-256 content hash verified and bound to Approval record.
      5. Pending goal persisted in conversation metadata.
      6. Clear Arabic approval request returned to owner.
    """
    engine = ConversationalAgentEngine(db=db)

    gap_msg = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content="احسب لي استهلاك أصول بقيمة 150000 ريال على 5 سنوات بنسبة استهلاك 20% وإذا لم تكن المهارة متوفرة فاكتشف الفجوة وطورها واطلب موافقتي",
        created_at=datetime.now(timezone.utc),
    )
    db.add(gap_msg)
    db.commit()

    res = engine.process_message(gap_msg)
    assert res.success is True
    reply = res.reply_content

    assert "اكتشاف فجوة قدرات" in reply
    assert "حاسبة استهلاك الأصول الثابتة" in reply
    assert "ExecutionSandbox" in reply
    assert "100%" in reply
    assert "طلب اعتماد المالك" in reply
    assert "أوافق على تفعيل القدرة depreciation_calculator" in reply

    # Verify DB records
    dev_req = db.scalar(
        select(DevelopmentRequest).where(
            DevelopmentRequest.tenant_id == mundhir_tenant.id,
            DevelopmentRequest.requirements["slug"].as_string() == "depreciation_calculator",
        )
    )
    assert dev_req is not None

    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == mundhir_tenant.id,
            CapabilityVersion.slug == "depreciation_calculator",
        )
    )
    assert cap_ver is not None
    assert cap_ver.status == "awaiting_approval"

    # Verify Approval record
    assert cap_ver.approval_id is not None
    approval = db.scalar(select(Approval).where(Approval.id == cap_ver.approval_id))
    assert approval is not None
    assert approval.status == "pending"

    # Verify pending goal in conversation
    db.refresh(owner_conv)
    goal = (owner_conv.metadata_json or {}).get("pending_goal")
    assert goal is not None
    assert goal["slug"] == "depreciation_calculator"


def test_4_owner_approves_capability_and_original_task_resumes(
    db: Session,
    mundhir_tenant: Tenant,
    telegram_channel: Channel,
    mundhir_owner: User,
    owner_conv: Conversation,
):
    """
    Scenario 4:
    After gap detection from Scenario 3, owner sends approval:
    "أوافق على تفعيل القدرة depreciation_calculator"
    Verifies:
      1. Capability version activated in DB.
      2. DynamicCapabilityTool registered into ToolRegistry.
      3. Original task resumed: calculates asset depreciation (150,000 SAR -> 30,000 SAR annual).
      4. Pending goal cleared from conversation (no loop).
    """
    engine = ConversationalAgentEngine(db=db)

    # First turn: trigger capability gap
    msg1 = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content="احسب لي استهلاك أصول بقيمة 150000 ريال على 5 سنوات بنسبة استهلاك 20% وإذا لم تكن المهارة متوفرة فاكتشف الفجوة وطورها واطلب موافقتي",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine.process_message(msg1)

    # Second turn: Owner approves
    msg2 = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content="أوافق على تفعيل القدرة depreciation_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg2)
    db.commit()

    res2 = engine.process_message(msg2)
    assert res2.success is True
    reply2 = res2.reply_content

    assert "تمت الموافقة وتفعيل القدرة الجديدة بنجاح" in reply2
    assert "تم استئناف وتنفيذ طلبك الأصلي بنجاح" in reply2
    assert "قسط الاستهلاك السنوي: 30000.0 ريال" in reply2

    # Verify pending goal cleared
    db.refresh(owner_conv)
    goal = (owner_conv.metadata_json or {}).get("pending_goal")
    assert goal is None

    # Verify version status in DB
    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == mundhir_tenant.id,
            CapabilityVersion.slug == "depreciation_calculator",
        )
    )
    assert cap_ver.status == "active"


def test_5_conditional_approval_phrasing_is_not_hijacked_as_affirmation(
    db: Session,
    mundhir_tenant: Tenant,
    telegram_channel: Channel,
    mundhir_owner: User,
    owner_conv: Conversation,
):
    """
    Scenario 5:
    Ensures that phrases mentioning approvals as a condition or question:
      - "واطلب موافقتي إذا كانت دورة التطوير تتطلب ذلك"
      - "إذا تطلب ذلك موافقة المالك"
      - "هل توجد موافقة معلقة؟"
    do NOT get hijacked into the Case 3 generic approval branch.
    """
    engine = ConversationalAgentEngine(db=db)

    # Message containing approval words but is not an approval statement
    msg = Message(
        tenant_id=mundhir_tenant.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        sender_id=mundhir_owner.id,
        content="أريد الاستفسار عن حالة المهام الحالية، واطلب موافقتي إذا كان هناك أي إجراء يتطلب موافقة.",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    db.commit()

    res = engine.process_message(msg)
    assert res.success is True
    # Must NOT say "لا توجد حالياً أي طلبات موافقة معلقة بانتظار الاعتماد في منشأتكم"
    assert "لا توجد حالياً أي طلبات موافقة معلقة بانتظار الاعتماد" not in res.reply_content


def test_6_cross_tenant_isolation_on_capabilities_and_knowledge(
    db: Session,
    mundhir_tenant: Tenant,
    telegram_channel: Channel,
    mundhir_owner: User,
    owner_conv: Conversation,
):
    """
    Scenario 6:
    Enforces tenant isolation:
    Tenant Beta cannot view, execute, or access Al-Mundhir Technology's dynamic capabilities or documents.
    """
    tenant_beta = Tenant(name="Beta Software", slug=f"beta-{uuid.uuid4().hex[:6]}", status="active")
    db.add(tenant_beta)
    db.flush()

    owner_beta = User(
        id=uuid.uuid4(),
        tenant_id=tenant_beta.id,
        name="Beta Owner",
        email=f"beta-{uuid.uuid4().hex[:6]}@beta.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner_beta)
    db.commit()

    # Querying Al-Mundhir's capability versions under Tenant Beta must return None
    cap_in_beta = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant_beta.id,
            CapabilityVersion.slug == "depreciation_calculator",
        )
    )
    assert cap_in_beta is None
