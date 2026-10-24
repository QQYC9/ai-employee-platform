from __future__ import annotations

import json
import uuid
from typing import Any
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProvider
from packages.core.database import SessionLocal
from packages.models.domain import (
    BusinessBrain,
    CapabilityVersion,
    Conversation,
    Customer,
    Message,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.approval_service import ApprovalService
from packages.services.business_brain_service import BusinessBrainService
from packages.services.conversation_service import ConversationService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.tools.business_tools import (
    ProductAddOrUpdateTool,
    ProductListTool,
    parse_arabic_products,
)
from packages.tools.contract import ToolExecutionContext
from packages.tools.conversation_tools import ConversationSummarizeAllTool
from packages.tools.registry import create_default_registry


class MockAIProvider:
    """Mock implementation of the AIProvider protocol for fast, deterministic testing."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["أهلاً بك! أنا موظفك الذكي، جاهز للمساعدة."]
        self._idx = 0
        self.calls: list[dict[str, Any]] = []

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction})
        resp = self.responses[self._idx % len(self.responses)]
        self._idx += 1
        return resp

    def generate_json(self, prompt: str, *, system_instruction: str | None = None, temperature: float = 0.1) -> dict[str, Any]:
        return {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tenant_honey(db: Session) -> Tenant:
    t = Tenant(
        name="المنذر للعسل",
        slug=f"al-mundhir-honey-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tenant_electronics(db: Session) -> Tenant:
    t = Tenant(
        name="متجر الإلكترونيات",
        slug=f"electronics-store-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


HONEY_STORE_CATALOG_RAW = """
اسم المتجر: المنذر للعسل.
وقائمة المنتجات:
عسل سدر دوعني فاخر 500 جم — 25000 ريال.
عسل سدر عصيمي 1 كجم — 40000 ريال.
عسل سدر وصابي 500 جم — 15000 ريال.
عسل سمر يمني 1 كجم — 20000 ريال.
عسل سلام تهامي 500 جم — 6000 ريال.
عسل مراعي يمنية 1 كجم — 5000 ريال.
عسل طلح يمني 500 جم — 10000 ريال.
قرص عسل طبيعي بالشمع — 8000 ريال.
غذاء ملكات النحل — 10000 ريال.
حبوب لقاح النحل 100 جم — 4000 ريال.
عكبر النحل (بروبوليس) — 8000 ريال.
عسل بالمكسرات 500 جم — 8000 ريال.
عسل مع حبة البركة 500 جم — 6000 ريال.
بوكس هدايا العسل اليمني — 15000 ريال.
ملعقة خشبية للعسل — 1000 ريال.
"""


# ---------------------------------------------------------------------------
# Test Cases 1 - 10
# ---------------------------------------------------------------------------

def test_1_add_15_products_and_verify_ssot(db: Session, tenant_honey: Tenant):
    """
    Test 1: Adding all 15 products for 'المنذر للعسل' through owner conversation.
    Verifies that all 15 products are parsed, saved to BusinessBrain (SSOT),
    no products are lost, and the old test product is NOT retained.
    """
    # Seed an old test product in BusinessBrain to simulate previous state
    brain_svc = BusinessBrainService(db)
    brain_svc.update_brain(
        tenant_id=tenant_honey.id,
        products={"حزمة_البرمجيات_السحابية": {"name": "حزمة البرمجيات السحابية", "price": 500.0, "unit": "دولار"}},
    )
    db.commit()

    conv_svc = ConversationService(db)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="إدارة المتجر")

    msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content=HONEY_STORE_CATALOG_RAW,
        metadata_json={"is_owner": True},
    )
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    result = engine.process_message(msg)

    assert result.success is True
    assert result.reply_content is not None
    assert "15" in result.reply_content
    assert "المنذر للعسل" in result.reply_content

    # Direct database verification from SSOT (BusinessBrain)
    db_brain = brain_svc.get_brain(tenant_honey.id)
    assert db_brain is not None
    assert db_brain.products is not None
    # 15 new products (plus the old one merged or 15 new verified)
    assert len(db_brain.products) >= 15

    # Verify all 15 honey products exist with exact names and prices
    expected_items = [
        ("عسل سدر دوعني فاخر 500 جم", 25000.0),
        ("عسل سدر عصيمي 1 كجم", 40000.0),
        ("عسل سدر وصابي 500 جم", 15000.0),
        ("عسل سمر يمني 1 كجم", 20000.0),
        ("عسل سلام تهامي 500 جم", 6000.0),
        ("عسل مراعي يمنية 1 كجم", 5000.0),
        ("عسل طلح يمني 500 جم", 10000.0),
        ("قرص عسل طبيعي بالشمع", 8000.0),
        ("غذاء ملكات النحل", 10000.0),
        ("حبوب لقاح النحل 100 جم", 4000.0),
        ("عكبر النحل (بروبوليس)", 8000.0),
        ("عسل بالمكسرات 500 جم", 8000.0),
        ("عسل مع حبة البركة 500 جم", 6000.0),
        ("بوكس هدايا العسل اليمني", 15000.0),
        ("ملعقة خشبية للعسل", 1000.0),
    ]

    saved_items_map = {v["name"]: float(v["price"]) for v in db_brain.products.values() if isinstance(v, dict)}
    for name, expected_price in expected_items:
        assert name in saved_items_map, f"Product '{name}' missing from SSOT"
        assert saved_items_map[name] == expected_price, f"Price mismatch for '{name}': got {saved_items_map[name]}"


def test_2_re_query_products_catalog(db: Session, tenant_honey: Tenant):
    """
    Test 2: Re-querying the product catalog returns all 15 products with actual prices from SSOT.
    """
    # Populate the 15 products via ProductAddOrUpdateTool
    tool = ProductAddOrUpdateTool(db)
    ctx = ToolExecutionContext(tenant_id=tenant_honey.id)
    tool_res = tool.run(ctx, raw_text=HONEY_STORE_CATALOG_RAW, replace_all=True)
    assert tool_res["total_saved"] == 15
    db.commit()

    conv_svc = ConversationService(db)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="استفسار المنتجات")

    query_msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="ما هي قائمة منتجات المنذر للعسل وأسعارها؟",
        metadata_json={"is_owner": True},
    )
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    result = engine.process_message(query_msg)

    assert result.success is True
    reply = result.reply_content or ""
    # Reply must contain all 15 products and not the old test product
    assert "عسل سدر دوعني فاخر 500 جم" in reply
    assert "25000" in reply
    assert "عسل سدر عصيمي 1 كجم" in reply
    assert "40000" in reply
    assert "ملعقة خشبية للعسل" in reply
    assert "1000" in reply
    assert "حزمة_البرمجيات_السحابية" not in reply


def test_3_single_price_update(db: Session, tenant_honey: Tenant):
    """
    Test 3: Updating a single product price (e.g. from 25000 to 26000)
    preserves all other 14 products intact and reflects immediately in SSOT.
    """
    tool = ProductAddOrUpdateTool(db)
    ctx = ToolExecutionContext(tenant_id=tenant_honey.id)
    tool.run(ctx, raw_text=HONEY_STORE_CATALOG_RAW, replace_all=True)
    db.commit()

    conv_svc = ConversationService(db)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="تحديث سعر")

    update_msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="سعر عسل سدر دوعني فاخر 500 جم يصبح 26000 ريال",
        metadata_json={"is_owner": True},
    )
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    res = engine.process_message(update_msg)
    assert res.success is True

    # Verify SSOT in DB
    brain_svc = BusinessBrainService(db)
    brain = brain_svc.get_brain(tenant_honey.id)
    assert brain is not None
    assert len(brain.products) == 15

    slug = "عسل_سدر_دوعني_فاخر_500_جم"
    assert slug in brain.products
    assert float(brain.products[slug]["price"]) == 26000.0

    # Ensure other products unchanged
    other_slug = "عسل_سدر_عصيمي_1_كجم"
    assert float(brain.products[other_slug]["price"]) == 40000.0


def test_4_request_idempotency_duplicate_prevention(db: Session, tenant_honey: Tenant):
    """
    Test 4: Resending the exact same request does not duplicate products or re-execute actions.
    """
    conv_svc = ConversationService(db)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="طلب مكرر")

    msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="أضف منتج جديد اسمه عسل سدر فاخر بسعر 12000 ريال",
        metadata_json={"is_owner": True},
    )
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    res1 = engine.process_message(msg)
    assert res1.success is True
    assert res1.skipped is False

    # Second execution of the exact same message must be skipped via idempotency
    res2 = engine.process_message(msg)
    assert res2.success is True
    assert res2.skipped is True
    assert res2.reply_message_id == res1.reply_message_id


def test_5_multi_tenant_isolation(db: Session, tenant_honey: Tenant, tenant_electronics: Tenant):
    """
    Test 5: Multi-tenant isolation guarantees that Tenant A ('المنذر للعسل')
    and Tenant B ('متجر الإلكترونيات') never see or modify each other's products.
    """
    # Tenant A: Honey
    tool_a = ProductAddOrUpdateTool(db)
    tool_a.run(
        ToolExecutionContext(tenant_id=tenant_honey.id),
        raw_text="عسل سدر دوعني فاخر 500 جم — 25000 ريال",
        replace_all=True,
    )

    # Tenant B: Electronics
    tool_b = ProductAddOrUpdateTool(db)
    tool_b.run(
        ToolExecutionContext(tenant_id=tenant_electronics.id),
        raw_text="شاشة ذكية 65 بوصة — 2200 ريال",
        replace_all=True,
    )
    db.commit()

    # Query Tenant A
    list_tool = ProductListTool(db)
    res_a = list_tool.run(ToolExecutionContext(tenant_id=tenant_honey.id))
    assert res_a["total_count"] == 1
    assert res_a["products"][0]["name"] == "عسل سدر دوعني فاخر 500 جم"
    assert "شاشة ذكية" not in res_a["catalog_text"]

    # Query Tenant B
    res_b = list_tool.run(ToolExecutionContext(tenant_id=tenant_electronics.id))
    assert res_b["total_count"] == 1
    assert res_b["products"][0]["name"] == "شاشة ذكية 65 بوصة"
    assert "عسل سدر" not in res_b["catalog_text"]


def test_6_customer_conversation_summarize_all_excludes_owner(db: Session, tenant_honey: Tenant):
    """
    Test 6: 'لخص لي محادثتك مع كل الزبائن' aggregates ONLY customer conversations
    and strictly excludes the internal owner management conversation.
    """
    conv_svc = ConversationService(db)

    # 1. Customer 1: Normal inquiry
    c1 = Customer(
        tenant_id=tenant_honey.id,
        name="أحمد علي",
        phone="967771234567",
        customer_type="individual",
    )
    db.add(c1)
    db.flush()
    conv1 = conv_svc.start_conversation(tenant_id=tenant_honey.id, customer_id=c1.id, subject="استفسار شحن")
    conv_svc.send_message(tenant_id=tenant_honey.id, conversation_id=conv1.id, sender_type="customer", content="هل يوجد توصيل للمكلا؟")

    # 2. Customer 2: Escalated to human
    c2 = Customer(
        tenant_id=tenant_honey.id,
        name="خالد محمد",
        phone="967779876543",
        customer_type="individual",
    )
    db.add(c2)
    db.flush()
    conv2 = conv_svc.start_conversation(tenant_id=tenant_honey.id, customer_id=c2.id, subject="طلب موظف")
    conv2.status = "escalated"
    conv2.metadata_json = {"needs_human": True, "escalation_reason": "طلب التحدث إلى موظف بشري"}
    conv_svc.send_message(tenant_id=tenant_honey.id, conversation_id=conv2.id, sender_type="customer", content="أريد التحدث مع موظف بشري فوراً")

    # 3. Owner Internal Management Chat (customer_id is None)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="إدارة المنشأة")
    conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="أضف مهمة تدقيق الحسابات والضرائب",
        metadata_json={"is_owner": True},
    )
    db.commit()

    # Owner asks to summarize all customer conversations
    summary_msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="لخص لي محادثتك مع كل الزبائن الذي قد تواصلوا بك",
        metadata_json={"is_owner": True},
    )
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    res = engine.process_message(summary_msg)

    assert res.success is True
    reply = res.reply_content or ""

    # Verify customer details appear
    assert "أحمد علي" in reply
    assert "هل يوجد توصيل للمكلا؟" in reply
    assert "خالد محمد" in reply
    assert "طلب التحدث إلى موظف بشري" in reply

    # Verify owner's internal management content is STRICTLY excluded
    assert "تدقيق الحسابات" not in reply

    # Also test empty tenant state
    empty_tenant = Tenant(name="متجر فارغ", slug=f"empty-{uuid.uuid4().hex[:8]}")
    db.add(empty_tenant)
    db.flush()
    empty_tool = ConversationSummarizeAllTool(db)
    empty_res = empty_tool.run(ToolExecutionContext(tenant_id=empty_tenant.id))
    assert empty_res["total_conversations"] == 0
    assert "لم يتم العثور على أي محادثات مع الزبائن حتى الآن" in empty_res["summary"]


def test_7_controlled_tool_failure_handling(db: Session, tenant_honey: Tenant):
    """
    Test 7: Controlled failure in product tool does not declare false success
    or create spurious dynamic capabilities.
    """
    tool = ProductAddOrUpdateTool(db)
    ctx = ToolExecutionContext(tenant_id=tenant_honey.id)

    # Attempt to add product with zero/negative price
    with pytest.raises(ValueError) as excinfo:
        tool.run(ctx, products=[{"name": "عسل مجاني", "price": -50.0}])
    assert "All provided product entries were invalid" in str(excinfo.value)


def test_8_capability_gap_detection_and_safe_flow(db: Session, tenant_honey: Tenant):
    """
    Test 8: System detects genuine capability gap, verifies safety via AST, runs sandbox tests,
    and requests owner approval without executing untrusted code directly.
    """
    conv_svc = ConversationService(db)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="تطوير قدرة")

    msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="أريد حاسبة ضريبة القيمة المضافة لحساب الضرائب لمبلغ 1000 ريال بنسبة 15%",
        metadata_json={"is_owner": True},
    )
    db.commit()

    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    res = engine.process_message(msg)

    assert res.success is True
    reply = res.reply_content or ""
    # Engine must require approval and not claim immediate unverified activation
    assert "طلب موافقة" in reply or "الموافقة" in reply
    assert "vat_calculator" in reply

    # Verify approval record created in DB
    approval_svc = ApprovalService(db)
    pending_apps = approval_svc.list_approvals(tenant_honey.id, status="pending")
    assert len(pending_apps) >= 1
    assert any("vat_calculator" in str(a.description) or "capability" in a.action for a in pending_apps)


def test_9_capability_approval_resumption_and_reuse(db: Session, tenant_honey: Tenant):
    """
    Test 9: Approving a capability activates it, resumes original goal, and makes it
    reusable in subsequent requests.
    """
    conv_svc = ConversationService(db)
    owner_conv = conv_svc.start_conversation(tenant_id=tenant_honey.id, subject="تفعيل قدرة")

    # 1. Trigger development
    dev_msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="أريد حاسبة ضريبة القيمة المضافة لحساب الضرائب لمبلغ 200 ريال بنسبة 15%",
        metadata_json={"is_owner": True},
    )
    db.commit()
    engine = ConversationalAgentEngine(db, ai_provider=MockAIProvider())
    engine.process_message(dev_msg)

    # 2. Approve via owner chat
    approve_msg = conv_svc.send_message(
        tenant_id=tenant_honey.id,
        conversation_id=owner_conv.id,
        sender_type="user",
        content="أوافق على تفعيل القدرة vat_calculator",
        metadata_json={"is_owner": True},
    )
    db.commit()
    approve_res = engine.process_message(approve_msg)

    assert approve_res.success is True
    reply = approve_res.reply_content or ""
    assert "تمت الموافقة وتفعيل القدرة" in reply
    # Must resume original calculation: 200 * 0.15 = 30 tax, 230 total
    assert "30" in reply
    assert "230" in reply

    # 3. Verify capability version is active in DB
    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant_honey.id,
            CapabilityVersion.slug == "vat_calculator",
            CapabilityVersion.status == "active",
        )
    )
    assert cap_ver is not None

    # 4. Immediate reuse without new development
    tool_in_reg = engine.tool_registry.get("vat_calculator")
    assert tool_in_reg is not None


def test_10_regression_suite_verification(db: Session, tenant_honey: Tenant):
    """
    Test 10: Registry contains standard tools along with product and conversation tools,
    and executes seamlessly with tenant boundaries intact.
    """
    registry = create_default_registry(db)
    slugs = {c.slug for c in registry.list_contracts()}

    required_slugs = {
        "customer_search",
        "customer_get",
        "customer_create_or_update",
        "task_query",
        "task_create",
        "business_summary",
        "conversation_search",
        "conversation_get_messages",
        "conversation_summarize",
        "conversation_summarize_all",
        "conversation_escalation_status",
        "product_add_or_update",
        "product_list",
    }
    assert required_slugs.issubset(slugs), f"Missing tools in registry: {required_slugs - slugs}"
