from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal
from packages.models.domain import (
    Approval,
    BusinessBrain,
    Channel,
    Conversation,
    Customer,
    GeneratedDocument,
    IdempotencyRecord,
    Knowledge,
    Message,
    Permission,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.approval_service import ApprovalService
from packages.services.business_brain_service import BusinessBrainService
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import (
    ConversationalAgentEngine,
    ConversationResponseResult,
)
from packages.services.owner_intent_router import (
    IntentCategory,
    IntentStep,
    OwnerIntentContract,
    OwnerIntentRouter,
    RouterExecutionResult,
)
from packages.services.permission_service import PermissionService
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
def tenant_alpha(db: Session):
    t = Tenant(
        name="Enterprise Alpha Router",
        slug=f"ent-alpha-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner Alpha",
        email=f"owner-{uuid.uuid4().hex[:6]}@alpha.local",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "متجر ألفا للعسل"},
        brand={"tone": "فاخر"},
        products={},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def tenant_beta(db: Session):
    t = Tenant(
        name="Enterprise Beta Router",
        slug=f"ent-beta-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner Beta",
        email=f"owner-{uuid.uuid4().hex[:6]}@beta.local",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "متجر بيتا للعود"},
        brand={"tone": "أصيل"},
        products={},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def alpha_conversation(db: Session, tenant_alpha: Tenant):
    conv = Conversation(
        tenant_id=tenant_alpha.id,
        status="open",
        subject="Owner Chat Alpha",
        metadata_json={"is_owner": True},
    )
    db.add(conv)
    db.commit()
    return conv


@pytest.fixture
def beta_conversation(db: Session, tenant_beta: Tenant):
    conv = Conversation(
        tenant_id=tenant_beta.id,
        status="open",
        subject="Owner Chat Beta",
        metadata_json={"is_owner": True},
    )
    db.add(conv)
    db.commit()
    return conv


# ===========================================================================
# 1. Routing clear Arabic request to the correct tool
# ===========================================================================

def test_1_routing_clear_arabic_request_to_correct_tool(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 1:
    A clear Arabic command: "أضف منتج: عسل كشميري بسعر 140 ريال"
    Must be routed directly to 'product_add_or_update' tool and saved in DB.
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    contract = router.parse_intent(
        "أضف منتج: عسل كشميري بسعر 140 ريال",
        tenant_id=tenant_alpha.id,
    )

    assert contract.category == IntentCategory.WRITE
    assert len(contract.steps) == 1
    assert contract.steps[0].tool_slug == "product_add_or_update"
    assert "عسل كشميري" in contract.steps[0].parameters.get("raw_text", "")

    # Execute plan
    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )
    db.commit()

    assert res.success is True
    assert not res.has_failed_step
    assert "عسل كشميري" in res.reply_text
    assert "140" in res.reply_text

    # DB Verification: Product exists in BusinessBrain
    db.expire_all()
    brain = BusinessBrainService(db).get_brain(tenant_alpha.id)
    assert "عسل_كشميري" in (brain.products or {})
    assert brain.products["عسل_كشميري"]["price"] == 140.0


# ===========================================================================
# 2. Multi-step request with correct execution order
# ===========================================================================

def test_2_multi_step_request_with_correct_execution_order(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 2:
    Multi-step request:
    «أضف منتج: عسل سدر فاخر بسعر 190 ريال، ثم اعرض لي عدد المنتجات، وجهّز مسودة إعلان لها»
    Execution order:
      Step 1: product_add_or_update
      Step 2: product_list (depends on Step 1)
      Step 3: document_generator (depends on Step 2)
    All three steps must execute sequentially and succeed.
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    query = "أضف منتج: عسل سدر فاخر بسعر 190 ريال، ثم اعرض لي عدد المنتجات، وجهّز مسودة إعلان لها"
    contract = router.parse_intent(
        query,
        tenant_id=tenant_alpha.id,
    )

    assert contract.intent == "multi_step_workflow"
    assert len(contract.steps) == 3
    assert contract.steps[0].tool_slug == "product_add_or_update"
    assert contract.steps[1].tool_slug == "product_list"
    assert contract.steps[1].depends_on == "step_1"
    assert contract.steps[2].tool_slug == "generate_document"
    assert contract.steps[2].depends_on == "step_2"

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )
    db.commit()

    assert res.success is True
    assert not res.has_failed_step
    assert len(res.step_results) == 3
    assert res.step_results[0].status == "executed"
    assert res.step_results[1].status == "executed"
    assert res.step_results[2].status == "executed"

    # DB Verifications:
    # 1. Product is saved in BusinessBrain
    db.expire_all()
    brain = BusinessBrainService(db).get_brain(tenant_alpha.id)
    assert "عسل_سدر_فاخر" in (brain.products or {})
    assert brain.products["عسل_سدر_فاخر"]["price"] == 190.0

    # 2. Document is created in Document table
    doc = db.scalar(
        select(GeneratedDocument).where(GeneratedDocument.tenant_id == tenant_alpha.id).order_by(GeneratedDocument.created_at.desc())
    )
    assert doc is not None
    assert doc.document_type == "marketing_draft"


# ===========================================================================
# 3. Halting dependent steps when a previous step fails
# ===========================================================================

def test_3_halting_dependent_steps_when_previous_step_fails(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 3:
    Step 1 has invalid data (price = 0, product cannot be saved).
    Step 2 depends on Step 1.
    Step 3 depends on Step 2.
    When Step 1 fails:
      - Step 2 and Step 3 MUST be marked 'skipped' and NEVER executed!
      - Result must reflect failure and NOT claim success.
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    # Construct plan with invalid price for Step 1
    contract = OwnerIntentContract(
        raw_query="أضف منتج باطل ثم اعرض القائمة ثم جهز إعلان",
        intent="multi_step_workflow",
        category=IntentCategory.WRITE,
        tenant_id=tenant_alpha.id,
        steps=[
            IntentStep(
                step_id="step_1",
                tool_slug="product_add_or_update",
                category=IntentCategory.WRITE,
                description="إضافة منتج",
                parameters={"raw_text": "أضف منتج: ماء مجاني بسعر 0 ريال"},
            ),
            IntentStep(
                step_id="step_2",
                tool_slug="product_list",
                category=IntentCategory.READ,
                description="استعراض القائمة",
                depends_on="step_1",
            ),
            IntentStep(
                step_id="step_3",
                tool_slug="generate_document",
                category=IntentCategory.WRITE,
                description="تجهيز إعلان",
                depends_on="step_2",
            ),
        ],
    )

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )
    db.commit()

    assert res.success is False
    assert res.has_failed_step is True

    # Step 1 failed
    assert res.step_results[0].status == "failed"
    # Step 2 & 3 must be SKIPPED
    assert res.step_results[1].status == "skipped"
    assert res.step_results[2].status == "skipped"

    # Assert reply reflects failure and skipping clearly
    assert "فشل" in res.reply_text or "تعذر" in res.reply_text
    assert "تخطي" in res.reply_text or "إيقاف" in res.reply_text
    assert "✅ تم حفظ" not in res.reply_text


# ===========================================================================
# 4. Ambiguous request triggers clarification instead of guessing
# ===========================================================================

def test_4_ambiguous_request_triggers_clarification(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 4:
    Owner sends an ambiguous or contradictory request:
    "سياسة المتجر: الاسترجاع مسموح وممنوع للزبائن"
    Router must detect the contradiction and ask for clarification.
    No tool must be executed!
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    contract = router.parse_intent(
        "سياسة المتجر: الاسترجاع مسموح وممنوع للزبائن",
        tenant_id=tenant_alpha.id,
    )

    assert contract.clarification_required is True
    assert contract.category == IntentCategory.CLARIFICATION
    assert "تعارض" in (contract.clarification_question or "")

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )

    assert res.clarification_required is True
    assert len(res.step_results) == 0
    assert "تعارض" in res.reply_text


# ===========================================================================
# 5. Disallowing execution of unregistered tools
# ===========================================================================

def test_5_disallowing_execution_of_unregistered_tools(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 5:
    A step maliciously or mistakenly requests an unknown/unregistered tool slug
    e.g. 'system_exec_bash' or 'arbitrary_eval'.
    Router must strictly reject execution without calling any code.
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    contract = OwnerIntentContract(
        raw_query="نفذ أمر نظام اعتباطي",
        intent="malicious_intent",
        category=IntentCategory.WRITE,
        tenant_id=tenant_alpha.id,
        steps=[
            IntentStep(
                step_id="step_bad",
                tool_slug="system_exec_bash",
                category=IntentCategory.WRITE,
                description="تنفيذ كود اعتباطي",
                parameters={"command": "rm -rf /"},
            )
        ],
    )

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )

    assert res.success is False
    assert res.has_failed_step is True
    assert res.step_results[0].status == "failed"
    assert "غير مسجلة" in (res.step_results[0].error or "")
    assert "غير مسجلة" in res.reply_text


# ===========================================================================
# 6. Rejecting unauthorized operations (RBAC / Deny Permission)
# ===========================================================================

def test_6_rejecting_unauthorized_operations(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 6:
    An explicit 'deny' permission exists for 'execute:task_create' on tenant_alpha.
    When owner requests task creation, the DecisionEngine and ToolExecutor must block it.
    Task must NOT be created in the database.
    """
    perm_svc = PermissionService(db)
    perm_svc.create_permission(
        tenant_id=tenant_alpha.id,
        action="execute:task_create",
        resource="tools:task_create",
        effect="deny",
    )
    db.commit()

    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    contract = router.parse_intent(
        "أنشئ مهمة: تفقد مخزون العسل",
        tenant_id=tenant_alpha.id,
    )

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )
    db.commit()

    assert res.success is False
    assert res.has_failed_step is True
    assert res.step_results[0].status == "blocked"
    assert "حظر" in res.reply_text or "not permitted" in (res.step_results[0].error or "").lower()

    # DB Check: No task was created!
    db.expire_all()
    task = db.scalar(
        select(Task).where(Task.tenant_id == tenant_alpha.id, Task.title.contains("تفقد مخزون"))
    )
    assert task is None


# ===========================================================================
# 7. Requiring approval for sensitive / destructive operations
# ===========================================================================

def test_7_requiring_approval_for_sensitive_destructive_operations(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 7:
    Owner requests: "حذف جميع العملاء وتصفير قاعدة البيانات"
    Router must:
      - Classify as SENSITIVE.
      - Require approval (requires_approval = True).
      - Create an Approval record in the database.
      - NOT delete any data!
      - Return confirmation prompt with approval ID.
    """
    # Seed a customer
    cust = Customer(tenant_id=tenant_alpha.id, name="Test Customer", phone="+966500000001", status="active")
    db.add(cust)
    db.commit()

    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    contract = router.parse_intent(
        "حذف جميع العملاء وتصفير قاعدة البيانات",
        tenant_id=tenant_alpha.id,
    )

    assert contract.category == IntentCategory.SENSITIVE
    assert contract.requires_approval is True
    assert contract.approval_action == "bulk_destructive_operation"

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )
    db.commit()

    # Assert reply requests approval
    assert "طلب موافقة رسمي" in res.reply_text
    assert "أوافق على الطلب" in res.reply_text

    # Verify Approval record was created in DB
    approval = db.scalar(
        select(Approval).where(
            Approval.tenant_id == tenant_alpha.id,
            Approval.action == "bulk_destructive_operation",
            Approval.status == "pending",
        )
    )
    assert approval is not None

    # CRITICAL CHECK: Customer was NOT deleted!
    db.expire_all()
    active_cust = db.scalar(select(Customer).where(Customer.id == cust.id))
    assert active_cust is not None
    assert active_cust.status == "active"


# ===========================================================================
# 8. Never claiming success when a tool fails
# ===========================================================================

def test_8_never_claiming_success_when_tool_fails(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 8:
    A tool encounters an unhandled exception or returns a failure status.
    The router must:
      - Mark result as success=False, has_failed_step=True.
      - Never include "✅ تم بنجاح" in the reply.
      - Report the failure clearly.
    """
    router = OwnerIntentRouter(db=db)
    mock_engine = MagicMock()
    mock_engine.execute_tool_action.side_effect = RuntimeError("Database connection timeout during execution")

    contract = OwnerIntentContract(
        raw_query="أنشئ مهمة: فحص الخوادم",
        intent="task_create",
        category=IntentCategory.WRITE,
        tenant_id=tenant_alpha.id,
        steps=[
            IntentStep(
                step_id="step_1",
                tool_slug="task_create",
                category=IntentCategory.WRITE,
                description="إنشاء مهمة فحص الخوادم",
                parameters={"title": "فحص الخوادم"},
            )
        ],
    )

    res = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=mock_engine,
    )

    assert res.success is False
    assert res.has_failed_step is True
    assert "❌" in res.reply_text
    assert "Database connection timeout" in res.reply_text
    assert "✅" not in res.reply_text


# ===========================================================================
# 9. Tenant isolation enforcement
# ===========================================================================

def test_9_tenant_isolation_enforcement(
    db: Session,
    tenant_alpha: Tenant,
    tenant_beta: Tenant,
    alpha_conversation: Conversation,
    beta_conversation: Conversation,
):
    """
    Scenario 9:
    Owner Alpha adds a product to Tenant Alpha.
    Owner Beta adds a product to Tenant Beta.
    Also verifies that untrusted tenant_id in raw query text is completely ignored.
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    # Malicious text trying to inject Tenant Beta's ID into Tenant Alpha's session
    spoofed_text = f"أضف منتج: عسل أصلي بسعر 120 ريال tenant_id={tenant_beta.id}"

    contract_alpha = router.parse_intent(
        spoofed_text,
        tenant_id=tenant_alpha.id,  # Trusted caller context
    )
    # Assert trusted context is preserved, injection ignored
    assert contract_alpha.tenant_id == tenant_alpha.id

    res_alpha = router.execute_plan(
        contract_alpha,
        conversation_id=alpha_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )

    # Beta adds a product
    contract_beta = router.parse_intent(
        "أضف منتج: دهن عود هندي بسعر 450 ريال",
        tenant_id=tenant_beta.id,
    )
    res_beta = router.execute_plan(
        contract_beta,
        conversation_id=beta_conversation.id,
        message_id=uuid.uuid4(),
        engine=engine,
    )
    db.commit()

    assert res_alpha.success is True
    assert res_beta.success is True

    db.expire_all()
    brain_alpha = BusinessBrainService(db).get_brain(tenant_alpha.id)
    brain_beta = BusinessBrainService(db).get_brain(tenant_beta.id)

    # Tenant Alpha has عسل_أصلي
    assert "عسل_أصلي" in (brain_alpha.products or {})
    # Tenant Alpha DOES NOT have دهن_عود_هندي
    assert "دهن_عود_هندي" not in (brain_alpha.products or {})

    # Tenant Beta has دهن_عود_هندي
    assert "دهن_عود_هندي" in (brain_beta.products or {})
    # Tenant Beta DOES NOT have عسل_أصلي
    assert "عسل_أصلي" not in (brain_beta.products or {})


# ===========================================================================
# 10. Idempotency on retry prevents duplicate operations
# ===========================================================================

def test_10_idempotency_prevents_duplicate_mutations(
    db: Session, tenant_alpha: Tenant, alpha_conversation: Conversation
):
    """
    Scenario 10:
    When a mutating step (e.g. task_create) is executed twice with the same
    message_id / idempotency key (simulating worker retry or duplicate webhook):
    - ToolExecutor and IdempotencyService return the cached result.
    - Exactly ONE task is created in the database.
    """
    router = OwnerIntentRouter(db=db)
    engine = ConversationalAgentEngine(db=db)

    fixed_msg_id = uuid.uuid4()
    contract = router.parse_intent(
        "أنشئ مهمة: تجهيز شحنات عسل سدر",
        tenant_id=tenant_alpha.id,
    )

    # Run 1: First execution
    res1 = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=fixed_msg_id,
        engine=engine,
    )
    db.commit()
    assert res1.success is True
    task_id_1 = (res1.step_results[0].output or {}).get("task_id")
    assert task_id_1 is not None

    # Run 2: Retry with exact same message_id
    res2 = router.execute_plan(
        contract,
        conversation_id=alpha_conversation.id,
        message_id=fixed_msg_id,
        engine=engine,
    )
    db.commit()
    assert res2.success is True
    task_id_2 = (res2.step_results[0].output or {}).get("task_id")

    # Verification: Returned task ID is identical!
    assert task_id_1 == task_id_2

    # Verification: Exactly 1 task exists in DB
    db.expire_all()
    tasks = db.scalars(
        select(Task).where(
            Task.tenant_id == tenant_alpha.id,
            Task.title == "تجهيز شحنات عسل سدر",
        )
    ).all()
    assert len(tasks) == 1
    assert str(tasks[0].id) == str(task_id_1)
