"""
Regression test suite for Safe Product Catalog Retrieval and Grounded Escalation.
Verifies Tasks A, B, C, and D:
  1. Customer requesting 3 products with conditional prices displays tenant's registered products without escalation.
  2. Sub-module facts of a single product do not crowd out the other primary products.
  3. Missing prices do not prevent product listing and do not lead to escalation on their own.
  4. Empty catalog triggers safe escalation via OwnerInquiry without hallucinating products.
  5. Unauthorized tool is blocked by DecisionEngine and catalog path does not bypass permissions.
  6. Strict tenant isolation: Tenant A cannot access Tenant B's products.
  7. Internal agent tools/capabilities are not claimed as products sold by the company.
  8. Unsupported non-catalog questions still escalate properly to OwnerInquiry.
  9. Shortfall handling: Requesting 5 products when only 2 exist displays the 2 confirmed products and clarifies count without fabrication.
"""

from typing import Any
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal
from packages.models.domain import (
    AuditEvent,
    BusinessBrain,
    Channel,
    Conversation,
    Customer,
    Fact,
    Message,
    OutboxEvent,
    OwnerInquiry,
    Permission,
    Tool,
)
from packages.models.tenant import Tenant
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.owner_inquiry_service import DEFAULT_HOLDING_SENTENCE, OwnerInquiryService
from packages.tools.business_tools import ProductListTool
from packages.tools.registry import ToolRegistry


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
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        self.called_count += 1
        return self.reply


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()


@pytest.fixture
def catalog_test_setup(db: Session):
    """Sets up a tenant with 3 primary products and detailed sub-module facts for one product."""
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="المنذر تكنولوجي",
        slug=f"almonzer-tech-{tenant_id.hex[:8]}",
        status="active",
        employee_name="نبيه",
    )
    db.add(tenant)
    db.flush()

    brain = BusinessBrain(
        tenant_id=tenant_id,
        identity={"name": "المنذر تكنولوجي", "legal_name": "المنذر تكنولوجي"},
        products={
            "الموظف الذكي": {"name": "الموظف الذكي", "description": "موظف رقمي ذكي للرد على العملاء"},
            "سيرو": {"name": "برنامج سيرو", "description": "برنامج لإدارة الشبكات والتحكم الكامل"},
            "برنامج ناظم المحاسبي": {"name": "برنامج ناظم المحاسبي", "description": "نظام محاسبي وإداري متكامل"},
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
        # Primary product 1
        Fact(
            tenant_id=tenant_id,
            subject="برنامج ناظم المحاسبي",
            topic="product.nazem.overview",
            value={
                "name": "برنامج ناظم المحاسبي",
                "description": "نظام محاسبي وإداري متكامل يدعم إدارة المستودعات المتعددة، المبيعات والمشتريات، متابعة المخزون والأرباح والديون، ونقاط البيع ومتطلبات السوق اليمني.",
            },
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        # Primary product 2
        Fact(
            tenant_id=tenant_id,
            subject="الموظف الذكي",
            topic="product.الموظف الذكي",
            value={
                "name": "الموظف الذكي",
                "description": "موظف رقمي يرد على رسائل واتساب وفيسبوك وماسنجر والاتصالات، ويتابع العملاء ويساعد في إتمام الصفقات.",
            },
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        # Primary product 3
        Fact(
            tenant_id=tenant_id,
            subject="برنامج سيرو لإدارة الشبكات والتحكم الكامل بها",
            topic="product.سيرو",
            value={
                "name": "برنامج سيرو لإدارة الشبكات والتحكم الكامل بها",
                "description": "برنامج لإدارة الشبكات والتحكم الكامل",
            },
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        # Detailed sub-module facts for Nazem (to simulate crowding)
        Fact(
            tenant_id=tenant_id,
            subject="المحاسبة المالية في برنامج ناظم",
            topic="product.nazem.accounting",
            value={"notes": "ميزة مؤكدة", "title": "المحاسبة المالية"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="المبيعات والمشتريات والديون في برنامج ناظم",
            topic="product.nazem.sales_purchases",
            value={"notes": "ميزة مؤكدة", "title": "المبيعات والمشتريات"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="المخزون والمستودعات في برنامج ناظم",
            topic="product.nazem.inventory",
            value={"notes": "ميزة مؤكدة", "title": "المخزون والمستودعات"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="التقارير والتحليلات والأرباح في برنامج ناظم",
            topic="product.nazem.reports",
            value={"notes": "ميزة مؤكدة", "title": "التقارير والتحليلات"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="العملات المتعددة في برنامج ناظم",
            topic="product.nazem.multi_currency",
            value={"notes": "ميزة مؤكدة", "title": "العملات المتعددة"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_id,
            subject="متطلبات السوق اليمني في برنامج ناظم",
            topic="product.nazem.yemeni_market",
            value={"notes": "ميزة مؤكدة", "title": "متطلبات السوق اليمني"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
    ]
    db.add_all(facts)

    # Register ProductListTool in DB
    tool_rec = Tool(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Product List Tool",
        slug="product_list",
        description="Retrieves the official verified catalog of products from the tenant BusinessBrain (SSOT).",
        tool_type="real_tool",
        is_active=True,
    )
    db.add(tool_rec)

    # Customer and channel
    channel = Channel(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={},
    )
    db.add(channel)

    customer = Customer(
        id=uuid4(),
        tenant_id=tenant_id,
        name="عميل مهتم",
        phone="+967770000000",
        status="active",
    )
    db.add(customer)
    db.flush()

    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        channel_id=channel.id,
        customer_id=customer.id,
        status="active",
        subject="استفسار كتالوج",
    )
    db.add(conv)
    db.commit()

    return tenant, conv, customer


def test_1_catalog_request_three_products_with_conditional_price(db: Session, catalog_test_setup):
    """
    Test 1: Exact replication of customer prompt from the live issue:
    Customer asks for 3 registered products, with description, and price IF recorded.
    Verifies that all 3 registered products are returned, exact descriptions are included,
    unrecorded prices are marked as 'غير مسجل حالياً في النظام', and NO unnecessary escalation occurs.
    """
    tenant, conv, customer = catalog_test_setup

    query = (
        "ذكرت أنك تستطيع استعراض المنتجات والخدمات المعتمدة. أريدك أن تعرض لي ثلاثة منتجات أو خدمات "
        "مسجلة فعلياً في النظام، مع اسم كل منتج ووصفه وسعره إن كان السعر مسجلاً. لا تخمّن أي معلومة، "
        "وإذا لم تستطع الوصول إلى البيانات الفعلية فأخبرني بذلك بوضوح."
    )

    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content=query,
        metadata_json={"sender_id": "cust_123"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    assert result.reply_content is not None
    reply = result.reply_content

    # 1. Must NOT escalate or output the holding sentence
    assert DEFAULT_HOLDING_SENTENCE not in reply
    assert "سأتحقق من المسؤول" not in reply

    # 2. Must contain all 3 registered products
    assert "برنامج ناظم المحاسبي" in reply
    assert "الموظف الذكي" in reply
    assert "برنامج سيرو لإدارة الشبكات والتحكم الكامل بها" in reply

    # 3. Must contain exact stored descriptions
    assert "نظام محاسبي وإداري متكامل" in reply
    assert "موظف رقمي يرد على رسائل واتساب" in reply
    assert "برنامج لإدارة الشبكات والتحكم الكامل" in reply

    # 4. Must clearly clarify that price is unrecorded rather than escalating
    assert "غير مسجل حالياً في النظام" in reply

    # 5. Must NOT create any OwnerInquiry
    inq = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "customer_inquiry_created",
        )
    )
    assert inq is None


def test_2_single_product_features_do_not_crowd_out_catalog(db: Session, catalog_test_setup):
    """
    Test 2: Verifies that granular sub-modules of one product do NOT crowd out
    other primary products when a customer requests to view available products.
    """
    tenant, conv, customer = catalog_test_setup

    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="ما هي المنتجات والخدمات المتوفرة لديكم؟",
        metadata_json={"sender_id": "cust_123"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # All 3 primary products must be present
    assert "برنامج ناظم المحاسبي" in reply
    assert "الموظف الذكي" in reply
    assert "برنامج سيرو لإدارة الشبكات والتحكم الكامل بها" in reply


def test_3_missing_prices_does_not_prevent_listing_or_cause_escalation(db: Session, catalog_test_setup):
    """
    Test 3: Missing prices does NOT prevent displaying products and does not lead to escalation on its own.
    """
    tenant, conv, customer = catalog_test_setup

    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="اعرض لي المنتجات مع الأسعار المعتمدة",
        metadata_json={"sender_id": "cust_123"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # Products displayed without escalation
    assert DEFAULT_HOLDING_SENTENCE not in reply
    assert "الموظف الذكي" in reply
    assert "غير مسجل حالياً في النظام" in reply


def test_4_empty_catalog_triggers_safe_escalation_without_hallucination(db: Session):
    """
    Test 4: When a tenant has NO products registered, catalog requests safely escalate
    via OwnerInquiry without fabricating products.
    """
    empty_tenant = Tenant(
        id=uuid4(),
        name="متجر فارغ",
        slug=f"empty-store-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(empty_tenant)
    db.flush()

    conv = Conversation(
        id=uuid4(),
        tenant_id=empty_tenant.id,
        status="active",
        subject="طلب منتجات في متجر فارغ",
    )
    db.add(conv)

    msg = Message(
        id=uuid4(),
        tenant_id=empty_tenant.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="اعرض لي قائمة المنتجات المتوفرة لديكم",
        metadata_json={"sender_id": "cust_empty"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # Escalated to owner holding sentence
    assert DEFAULT_HOLDING_SENTENCE in reply

    # Owner inquiry created
    inquiries = list(db.scalars(select(OwnerInquiry).where(OwnerInquiry.tenant_id == empty_tenant.id)).all())
    assert len(inquiries) == 1
    assert inquiries[0].customer_conversation_id == conv.id
    assert inquiries[0].question == "اعرض لي قائمة المنتجات المتوفرة لديكم"


def test_5_unauthorized_tool_is_blocked_and_does_not_bypass_permissions(db: Session, catalog_test_setup):
    """
    Test 5: When tenant permissions explicitly deny or restrict product_list,
    the tool is blocked by DecisionEngine and catalog route does NOT bypass permissions.
    """
    tenant, conv, customer = catalog_test_setup

    # Explicitly deny execute:product_list on tools:product_list
    deny_perm = Permission(
        id=uuid4(),
        tenant_id=tenant.id,
        action="execute:product_list",
        resource="tools:product_list",
        effect="deny",
    )
    db.add(deny_perm)
    db.commit()

    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="اعرض لي قائمة المنتجات المعتمدة",
        metadata_json={"sender_id": "cust_123"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # Must be blocked safely without leaking catalog data
    assert "غير متاح حالياً وفق الصلاحيات" in reply
    assert "برنامج ناظم" not in reply


def test_6_strict_tenant_isolation_no_cross_tenant_catalog_leak(db: Session, catalog_test_setup):
    """
    Test 6: Tenant A cannot see Tenant B's products.
    """
    tenant_a, conv_a, cust_a = catalog_test_setup

    # Tenant B: Honey store
    tenant_b = Tenant(
        id=uuid4(),
        name="متجر العسل اليمني",
        slug=f"yemen-honey-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant_b)
    db.flush()

    fact_honey = Fact(
        tenant_id=tenant_b.id,
        subject="عسل سدر دوعني ملكي فاخر",
        topic="product.honey_sidr",
        value={"name": "عسل سدر دوعني ملكي فاخر", "price": 25000, "unit": "ريال"},
        status="confirmed",
        visibility="public",
        source="owner",
    )
    db.add(fact_honey)

    conv_b = Conversation(
        id=uuid4(),
        tenant_id=tenant_b.id,
        status="active",
        subject="استفسار عسل",
    )
    db.add(conv_b)

    msg_b = Message(
        id=uuid4(),
        tenant_id=tenant_b.id,
        conversation_id=conv_b.id,
        sender_type="customer",
        content="ما هي المنتجات المتوفرة عندكم؟",
        metadata_json={"sender_id": "cust_honey"},
    )
    db.add(msg_b)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result_b = engine.process_message(msg_b)

    assert result_b.success is True
    reply_b = result_b.reply_content or ""

    # Tenant B gets honey product
    assert "عسل سدر دوعني" in reply_b
    # Tenant B MUST NOT see Tenant A's software products
    assert "ناظم المحاسبي" not in reply_b
    assert "الموظف الذكي" not in reply_b
    assert "سيرو" not in reply_b


def test_7_internal_agent_tools_never_claimed_as_products(db: Session, catalog_test_setup):
    """
    Test 7: Internal agent capabilities/tools (customer_search, document_generator)
    are NEVER included in the products and services list.
    """
    tenant, conv, customer = catalog_test_setup

    # Add internal tool
    internal_tool = Tool(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Customer Search Tool",
        slug="customer_search",
        description="Search customer records internally",
        tool_type="real_tool",
        is_active=True,
    )
    db.add(internal_tool)
    db.commit()

    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="اعرض لي ثلاثة منتجات أو خدمات مسجلة في النظام",
        metadata_json={"sender_id": "cust_123"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # Internal tools must NEVER appear as products sold
    assert "Customer Search" not in reply
    assert "البحث في سجلات العملاء" not in reply


def test_8_unsupported_non_catalog_questions_still_escalate_properly(db: Session, catalog_test_setup):
    """
    Test 8: Unsupported questions that are NOT catalog requests still safely escalate
    to OwnerInquiry, persisting the question and notifying the owner.
    """
    tenant, conv, customer = catalog_test_setup

    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        customer_id=customer.id,
        sender_type="customer",
        content="هل عندكم خدمة حجز تذاكر طيران وفنادق دولية عبر منصتكم؟",
        metadata_json={"sender_id": "cust_123"},
    )
    db.add(msg)
    db.commit()

    # Provider outputs handoff because flight booking is not supported
    provider = NaturalMockAIProvider(reply="هذا الاستفسار يحتاج تأكيدًا من الفريق، وسنعود إليك.")
    engine = ConversationalAgentEngine(db, ai_provider=provider)
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # Escalated to holding sentence
    assert DEFAULT_HOLDING_SENTENCE in reply

    # Persisted OwnerInquiry exists
    inqs = list(db.scalars(select(OwnerInquiry).where(OwnerInquiry.tenant_id == tenant.id)).all())
    assert len(inqs) >= 1
    latest_inq = inqs[-1]
    assert "حجز تذاكر طيران" in latest_inq.question


def test_9_shortfall_count_clarification_no_fabrication(db: Session):
    """
    Test 9: When a customer asks for 5 products but only 2 exist, the engine displays
    the 2 confirmed products, notes that only 2 are registered, and does NOT fabricate extra products.
    """
    tenant_short = Tenant(
        id=uuid4(),
        name="متجر صغير",
        slug=f"small-shop-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant_short)
    db.flush()

    facts = [
        Fact(
            tenant_id=tenant_short.id,
            subject="منتج ألف",
            topic="product.item_a",
            value={"name": "منتج ألف", "description": "وصف منتج ألف"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
        Fact(
            tenant_id=tenant_short.id,
            subject="منتج باء",
            topic="product.item_b",
            value={"name": "منتج باء", "description": "وصف منتج باء"},
            status="confirmed",
            visibility="public",
            source="owner",
        ),
    ]
    db.add_all(facts)

    conv = Conversation(
        id=uuid4(),
        tenant_id=tenant_short.id,
        status="active",
        subject="طلب 5 منتجات",
    )
    db.add(conv)

    msg = Message(
        id=uuid4(),
        tenant_id=tenant_short.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="اعرض لي خمسة منتجات مسجلة في النظام مع الوصف",
        metadata_json={"sender_id": "cust_short"},
    )
    db.add(msg)
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=NaturalMockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    reply = result.reply_content or ""

    # Both confirmed products present
    assert "منتج ألف" in reply
    assert "منتج باء" in reply
    # Clarification of shortfall count present
    assert "2 فقط" in reply
    # Must NOT escalate unnecessarily
    assert DEFAULT_HOLDING_SENTENCE not in reply


# ---------------------------------------------------------------------------
# Test 10: Unit-level — _detect_catalog_request handles natural/colloquial Arabic
# ---------------------------------------------------------------------------


def test_10_detect_catalog_natural_arabic_phrasing():
    """
    Test 10: _detect_catalog_request must correctly detect natural and colloquial
    Arabic catalog requests that do NOT use formal imperative forms.

    Regression guard for the bug where messages like
    «ممكن تعرفني على أهم ثلاثة منتجات؟» returned None and triggered escalation
    instead of hitting the catalog path.
    """
    should_match = [
        # The exact failing message from the real customer conversation
        "السلام عليكم، ممكن تعرفني على أهم ثلاثة منتجات أو برامج تقدمونها؟ أريد نبذة بسيطة عن كل واحد، وكم أسعارها إذا ممكن.",
        # Colloquial Gulf: إيش + verb
        "إيش البرامج اللي تقدمونها؟",
        # ممكن + first-person request
        "ممكن أعرف أهم منتجاتكم وأسعارها؟",
        # عرفني imperative with count
        "عرفني على ثلاثة من منتجاتكم.",
        # إيش + عندكم + domain
        "إيش عندكم من برامج محاسبية أو تقنية؟",
        # نبذة + conditional optional phrase
        "أريد نبذة عن برامجكم لو ممكن",
        # ما + البرامج + relative clause
        "ما البرامج التي تقدمونها؟",
        # Short natural imperative
        "عرفني على برامجكم",
        # Superlative form without explicit verb
        "أهم ثلاثة منتجاتكم",
    ]
    should_not_match = [
        # عرفني + unrelated noun — must NOT fire
        "عرفني على الطريقة الصحيحة لاستخدام البرنامج",
        "عرفني على فريق المبيعات لديكم",
        "عرفني على شروط الضمان",
        # Unrelated questions
        "متى يفتح المكتب؟",
        "كيف أحدّث البرنامج؟",
        "أريد التحدث مع المسؤول",
    ]

    for phrase in should_match:
        result = ConversationalAgentEngine._detect_catalog_request(phrase)
        assert result is not None and result["is_catalog"] is True, (
            f"Expected catalog match for: {phrase!r}\nGot: {result!r}"
        )

    for phrase in should_not_match:
        result = ConversationalAgentEngine._detect_catalog_request(phrase)
        assert result is None, (
            f"Expected NO catalog match for: {phrase!r}\nGot: {result!r}"
        )


def test_10b_detect_catalog_price_optional_flag():
    """
    Test 10b: price_optional=True must be set when the customer uses a conditional
    price phrase like «إذا ممكن» or «لو ممكن» so the engine never escalates
    solely because prices are missing.
    """
    msg_with_optional_price = (
        "السلام عليكم، ممكن تعرفني على أهم ثلاثة منتجات أو برامج تقدمونها؟"
        " أريد نبذة بسيطة عن كل واحد، وكم أسعارها إذا ممكن."
    )
    result = ConversationalAgentEngine._detect_catalog_request(msg_with_optional_price)
    assert result is not None
    assert result["price_optional"] is True, (
        f"price_optional must be True for conditional price phrase. Got: {result}"
    )
    # Strict price requirement should NOT be set when the price is phrased optionally
    # (wants_price may be True, but price_optional=True means absence doesn't block listing)
    assert result["wants_description"] is True, (
        f"wants_description must be True when 'نبذة' is present. Got: {result}"
    )


def test_10c_detect_catalog_count_extraction_from_natural_form():
    """
    Test 10c: Count extraction works correctly from natural Arabic phrasing,
    ensuring the engine requests the correct number of products from the catalog tool.
    """
    cases = [
        ("عرفني على ثلاثة من منتجاتكم.", 3),
        ("أهم ثلاثة منتجاتكم", 3),
        ("أريدك تعرضني على منتجين اثنين", 2),
        ("أريد معرفة أهم 5 خدمات لديكم", 5),
        # No count — should be None
        ("إيش البرامج اللي تقدمونها؟", None),
    ]
    for phrase, expected_count in cases:
        result = ConversationalAgentEngine._detect_catalog_request(phrase)
        assert result is not None, f"Should detect catalog for: {phrase!r}"
        assert result["requested_count"] == expected_count, (
            f"For {phrase!r}: expected count={expected_count}, got {result['requested_count']}"
        )
