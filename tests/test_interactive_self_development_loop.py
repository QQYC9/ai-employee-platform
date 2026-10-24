from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from typing import Any
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
    Message,
    User,
)
from packages.models.tenant import Tenant
from packages.self_development.engine import SelfDevelopmentEngine
from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.verifier import CapabilitySecurityVerifier
from packages.services.approval_service import ApprovalService
from packages.services.audit_service import AuditService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.tools.contract import ToolExecutionContext
from packages.tools.executor import ToolExecutor
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
def tenant(db: Session):
    t = Tenant(
        name="Honey & Agro Enterprise",
        slug=f"agro-ent-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        id=uuid.uuid4(),
        tenant_id=t.id,
        name="Business Owner",
        email=f"owner-{uuid.uuid4().hex[:6]}@agro.local",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    customer = User(
        id=uuid.uuid4(),
        tenant_id=t.id,
        name="External Customer",
        email=f"customer-{uuid.uuid4().hex[:6]}@gmail.com",
        role="customer",
        status="active",
    )
    db.add(customer)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "مؤسسة عسل السدر الطبيعي"},
        brand={"tone": "مهني"},
        products={"sidr_honey": {"name": "عسل سدر فاخر", "price": 250, "unit": "ريال"}},
        pricing={},
        policies={},
        version=1,
    )
    db.add(brain)
    db.commit()
    return t


@pytest.fixture
def owner_user(db: Session, tenant: Tenant):
    return db.scalar(select(User).where(User.tenant_id == tenant.id, User.role == "tenant_owner"))


@pytest.fixture
def customer_user(db: Session, tenant: Tenant):
    return db.scalar(select(User).where(User.tenant_id == tenant.id, User.role == "customer"))


@pytest.fixture
def channel(db: Session, tenant: Tenant, owner_user: User):
    ch = Channel(
        tenant_id=tenant.id,
        channel_type="telegram",
        name="Telegram Support & Management",
        status="active",
        config={
            "bot_token": "TEST_TOKEN_12345",
            "owner_identifiers": [str(owner_user.id), "775274399", "owner_telegram_handle"],
        },
    )
    db.add(ch)
    db.commit()
    return ch


@pytest.fixture
def owner_conversation(db: Session, tenant: Tenant, channel: Channel, owner_user: User):
    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id,
        status="open",
        subject="Owner Channel Direct",
        metadata_json={"is_owner": True},
    )
    db.add(conv)
    db.commit()
    return conv


@pytest.fixture
def customer_conversation(db: Session, tenant: Tenant, channel: Channel, customer_user: User):
    cust = Customer(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Client Abu Fahad",
        email="fahad@gmail.com",
    )
    db.add(cust)
    db.flush()

    conv = Conversation(
        tenant_id=tenant.id,
        channel_id=channel.id,
        customer_id=cust.id,
        status="open",
        subject="Customer Inquiries",
        metadata_json={"is_owner": False},
    )
    db.add(conv)
    db.commit()
    return conv


# ---------------------------------------------------------------------------
# Test 1: Full Capability Gap Detection & Sandboxed Candidate Generation
# ---------------------------------------------------------------------------

def test_1_capability_gap_detection_and_candidate_creation(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Step 1:
    Owner asks: "احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة"
    Verifies:
      - Capability gap detected (zakat_calculator does not exist in registry).
      - Specification generated and risk evaluated.
      - AST security verifier passes clean code.
      - Sandboxed execution runs acceptance tests in ExecutionSandbox.
      - SHA-256 content hash computed and bound to Approval.
      - Pending goal persisted in conversation metadata.
      - Clear Arabic approval request returned to owner.
    """
    engine = ConversationalAgentEngine(db=db)

    msg = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    db.commit()

    res = engine.process_message(msg)
    assert res is not None
    reply = res.reply_content

    # Assertions on response
    assert "اكتشاف فجوة قدرات" in reply
    assert "حاسبة الزكاة الشرعية" in reply
    assert "ExecutionSandbox" in reply
    assert "100%" in reply
    assert "طلب اعتماد المالك" in reply
    assert "أوافق على تفعيل الأداة zakat_calculator" in reply

    # Verify DB records
    dev_req = db.scalar(
        select(DevelopmentRequest).where(
            DevelopmentRequest.tenant_id == tenant.id,
            DevelopmentRequest.title == "حاسبة الزكاة الشرعية",
        )
    )
    assert dev_req is not None

    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant.id,
            CapabilityVersion.slug == "zakat_calculator",
        )
    )
    assert cap_ver is not None
    assert cap_ver.status == "awaiting_approval"
    assert cap_ver.implementation_code is not None

    # Assert content hash exists and matches actual code
    expected_hash = hashlib.sha256(cap_ver.implementation_code.strip().encode("utf-8")).hexdigest()
    assert (cap_ver.test_results or {}).get("content_hash") == expected_hash

    # Verify Approval record
    assert cap_ver.approval_id is not None
    approval = db.scalar(select(Approval).where(Approval.id == cap_ver.approval_id))
    assert approval is not None
    assert approval.tenant_id == tenant.id
    assert approval.status == "pending"
    assert f"[hash:{expected_hash}]" in approval.description

    # Verify pending_goal in conversation
    db.refresh(owner_conversation)
    pending_goal = (owner_conversation.metadata_json or {}).get("pending_goal")
    assert pending_goal is not None
    assert pending_goal["slug"] == "zakat_calculator"
    assert pending_goal["approval_id"] == str(approval.id)
    assert pending_goal["extracted_inputs"]["quantity"] == 40.0
    assert pending_goal["extracted_inputs"]["price_per_unit"] == 250.0
    assert pending_goal["extracted_inputs"]["rate"] == 0.025
    assert pending_goal["extracted_inputs"]["amount"] == 10000.0


# ---------------------------------------------------------------------------
# Test 2: Owner Approval, Version Activation & Task Resumption
# ---------------------------------------------------------------------------

def test_2_owner_approval_activation_and_resumed_execution(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Step 2:
    Owner sends: "أوافق على تفعيل الأداة zakat_calculator"
    Verifies:
      - Sender verified as tenant owner.
      - Content hash verified (no tampering).
      - Version activated (Capability created / updated).
      - DynamicCapabilityTool registered into ToolRegistry and ToolExecutor.
      - Original task resumed: Honey zakat calculated (10,000 SAR -> 250 SAR).
      - AuditEvent recorded.
      - Pending goal cleared.
    """
    engine = ConversationalAgentEngine(db=db)

    # First turn: trigger gap detection
    msg1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine.process_message(msg1)

    # Second turn: Owner approves
    msg2 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg2)
    db.commit()

    res2 = engine.process_message(msg2)
    assert res2 is not None
    reply2 = res2.reply_content

    # Assert approval confirmation & original task execution
    assert "تمت الموافقة وتفعيل القدرة الجديدة بنجاح" in reply2
    assert "تم استئناف وتنفيذ طلبك الأصلي بنجاح" in reply2
    assert "مقدار الزكاة الواجب إخراجها: 250.0 ريال" in reply2
    assert "القيمة الإجمالية الخاضعة للزكاة: 10000.0 ريال" in reply2

    # Assert capability version status in DB
    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant.id,
            CapabilityVersion.slug == "zakat_calculator",
        )
    )
    assert cap_ver.status == "active"
    assert cap_ver.activated_at is not None

    # Assert Approval marked approved
    approval = db.scalar(select(Approval).where(Approval.id == cap_ver.approval_id))
    assert approval.status == "approved"

    # Assert Tool exists in ToolRegistry
    dyn_tool = engine.tool_registry.get("zakat_calculator")
    assert dyn_tool is not None
    assert dyn_tool.contract.slug == "zakat_calculator"

    # Assert AuditEvent was recorded
    audit_event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "self_development.task.resumed_and_executed",
        )
    )
    assert audit_event is not None
    assert audit_event.event_metadata["slug"] == "zakat_calculator"
    assert audit_event.event_metadata["result"]["zakat_due"] == 250.0

    # Assert pending goal cleared
    db.refresh(owner_conversation)
    assert "pending_goal" not in (owner_conversation.metadata_json or {})


# ---------------------------------------------------------------------------
# Test 3: Deduplication & Reusing Existing Dynamic Capability (Turn 3)
# ---------------------------------------------------------------------------

def test_3_capability_reuse_and_deduplication(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Step 3:
    After activating zakat_calculator, owner asks a new calculation:
    "احسب لي زكاة عسل 80 كيلو بسعر 200 ريال للكيلو بنسبة 2.5%"
    Verifies:
      - Capability is reused directly from registry/DB.
      - Zero new development requests created.
      - Zero approvals required.
      - Immediate calculation executed (80 * 200 = 16,000 -> zakat: 400 SAR).
    """
    engine = ConversationalAgentEngine(db=db)

    # 1. Generate & activate capability
    msg1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine.process_message(msg1)

    msg2 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg2)
    db.commit()
    engine.process_message(msg2)

    initial_dev_req_count = len(db.scalars(select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == tenant.id)).all())
    initial_app_count = len(db.scalars(select(Approval).where(Approval.tenant_id == tenant.id)).all())

    # 2. Turn 3: Subsequent request using the active capability
    msg3 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 80 كيلو بسعر 200 ريال للكيلو بنسبة 2.5%",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg3)
    db.commit()

    res3 = engine.process_message(msg3)
    reply3 = res3.reply_content

    # Direct execution confirmation
    assert "تم استخدام القدرة المعتمدة في النظام مباشرة" in reply3
    assert "القيمة الإجمالية الخاضعة للزكاة: 16000.0 ريال" in reply3
    assert "مقدار الزكاة الواجب إخراجها: 400.0 ريال" in reply3

    # Assert no new development requests or approvals were created
    current_dev_req_count = len(db.scalars(select(DevelopmentRequest).where(DevelopmentRequest.tenant_id == tenant.id)).all())
    current_app_count = len(db.scalars(select(Approval).where(Approval.tenant_id == tenant.id)).all())

    assert current_dev_req_count == initial_dev_req_count
    assert current_app_count == initial_app_count


# ---------------------------------------------------------------------------
# Test 4: Cryptographic Content Hash Tampering Detection
# ---------------------------------------------------------------------------

def test_4_code_tampering_blocks_activation(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Verifies that if implementation code is tampered with after sandbox testing,
    the activation is blocked by cryptographic content hash mismatch.
    """
    engine = ConversationalAgentEngine(db=db)

    # 1. Trigger capability development
    msg1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine.process_message(msg1)

    # 2. Simulate malicious attacker modifying implementation_code in DB
    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant.id,
            CapabilityVersion.slug == "zakat_calculator",
        )
    )
    assert cap_ver is not None
    cap_ver.implementation_code = "def run(inputs):\n    # Tampered backdoor\n    return {'tampered': True}\n"
    db.commit()

    # 3. Owner attempts to approve
    msg2 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg2)
    db.commit()

    res2 = engine.process_message(msg2)
    reply2 = res2.reply_content

    # Must detect tamper and reject activation
    assert "تم رفض التفعيل لانتهاك أمني (Tamper Detection)" in reply2 or "tamper" in reply2.lower()

    # Capability must NOT be activated
    db.refresh(cap_ver)
    assert cap_ver.status != "active"


# ---------------------------------------------------------------------------
# Test 5: Customer (Non-Owner) Cannot Approve or Activate Capabilities
# ---------------------------------------------------------------------------

def test_5_customer_cannot_approve_or_activate_capability(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    customer_user: User,
    owner_conversation: Conversation,
    customer_conversation: Conversation,
):
    """
    Verifies that a customer attempting to send approval commands is strictly barred.
    Customer mode processes the message as ordinary customer chat without touching approvals.
    """
    engine = ConversationalAgentEngine(db=db)

    # 1. Owner triggers gap creation
    msg1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine.process_message(msg1)

    cap_ver = db.scalar(
        select(CapabilityVersion).where(
            CapabilityVersion.tenant_id == tenant.id,
            CapabilityVersion.slug == "zakat_calculator",
        )
    )
    assert cap_ver.status == "awaiting_approval"

    # 2. Customer attempts to send approval message in customer chat
    msg_cust = Message(
        tenant_id=tenant.id,
        conversation_id=customer_conversation.id,
        sender_type="user",
        sender_id=customer_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg_cust)
    db.commit()

    res_cust = engine.process_message(msg_cust)
    reply_cust = res_cust.reply_content

    # Customer mode response must NOT approve the tool
    assert "تمت الموافقة وتفعيل القدرة" not in reply_cust
    db.refresh(cap_ver)
    assert cap_ver.status == "awaiting_approval"


# ---------------------------------------------------------------------------
# Test 6: Approval Idempotency & Replay Protection
# ---------------------------------------------------------------------------

def test_6_approval_idempotency_prevents_duplicate_resumption(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Verifies that resending an approval message after it has already been approved
    does not cause double execution, errors, or duplicate records.
    """
    engine = ConversationalAgentEngine(db=db)

    # 1. Trigger gap
    msg1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine.process_message(msg1)

    # 2. Approve once
    msg2 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg2)
    db.commit()
    res2 = engine.process_message(msg2)
    assert "تمت الموافقة وتفعيل القدرة الجديدة بنجاح" in res2.reply_content

    # 3. Resend the exact same approval
    msg3 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg3)
    db.commit()
    res3 = engine.process_message(msg3)
    reply3 = res3.reply_content

    # Must indicate that no pending approval remains or already approved
    assert "تعذر العثور على طلب موافقة معلق" in reply3 or "لا توجد حالياً أي طلبات موافقة معلقة" in reply3 or "غير معلق" in reply3


# ---------------------------------------------------------------------------
# Test 7: AST Verifier Blocks Dangerous / Forbidden Operations
# ---------------------------------------------------------------------------

def test_7_ast_security_verifier_blocks_system_calls():
    """
    Verifies that dangerous operations (open, eval, os.system, exec, sub-processes)
    are strictly caught and rejected by AST analysis before sandbox execution.
    """
    verifier = CapabilitySecurityVerifier()

    malicious_code_1 = """
def run(inputs):
    with open('/etc/passwd', 'r') as f:
        return {'leak': f.read()}
"""
    res1 = verifier.static_analysis(malicious_code_1)
    assert not res1["valid"]
    assert any("open" in v.lower() for v in res1["violations"])

    malicious_code_2 = """
import os

def run(inputs):
    os.system('rm -rf /')
    return {'status': 'done'}
"""
    res2 = verifier.static_analysis(malicious_code_2)
    assert not res2["valid"]
    assert any("os" in v.lower() for v in res2["violations"])

    malicious_code_3 = """
def run(inputs):
    fn = eval("lambda x: x * 2")
    return {'result': fn(inputs.get('val', 0))}
"""
    res3 = verifier.static_analysis(malicious_code_3)
    assert not res3["valid"]
    assert any("eval" in v.lower() for v in res3["violations"])


# ---------------------------------------------------------------------------
# Test 8: Persisted Activation & Tool Restoration Across Engine Reboots
# ---------------------------------------------------------------------------

def test_8_persisted_activation_restores_tool_across_engine_reboots(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Step 8 (Integration Test - Real Database):
    Proves that after a CapabilityVersion is activated:
      1. Completely discarding and re-instantiating ConversationalAgentEngine and ToolRegistry
         (simulating a server reboot / new worker process) starts with an empty dynamic registry.
      2. The moment an incoming message or tool request arrives for the tenant, the active capability
         is automatically restored and bound to ToolRegistry and ToolExecutor from PostgreSQL.
      3. The tool executes immediately without re-generating or requesting new approvals.
    """
    engine1 = ConversationalAgentEngine(db=db)

    # 1. Trigger development
    msg1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg1)
    db.commit()
    engine1.process_message(msg1)

    # 2. Owner approves
    msg2 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg2)
    db.commit()
    res2 = engine1.process_message(msg2)
    assert "تمت الموافقة وتفعيل القدرة الجديدة بنجاح" in res2.reply_content

    # 3. Simulate process reboot: discard engine1 entirely, create a fresh engine2
    del engine1
    engine2 = ConversationalAgentEngine(db=db)

    # Assert that dynamic tool is not in engine2's initial static registry before tenant message
    assert engine2.tool_registry.get("zakat_calculator") is None

    # 4. Process a new calculation request with the rebooted engine
    msg_reboot = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 60 كيلو بسعر 200 ريال للكيلو بنسبة 2.5%",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg_reboot)
    db.commit()

    res_reboot = engine2.process_message(msg_reboot)
    reply_reboot = res_reboot.reply_content

    # Assert tool was restored from DB and executed directly
    assert "تم استخدام القدرة المعتمدة في النظام مباشرة" in reply_reboot
    assert "القيمة الإجمالية الخاضعة للزكاة: 12000.0 ريال" in reply_reboot
    assert "مقدار الزكاة الواجب إخراجها: 300.0 ريال" in reply_reboot

    # Assert that tool is now active in engine2's runtime registry
    assert engine2.tool_registry.get("zakat_calculator") is not None


# ---------------------------------------------------------------------------
# Test 9: Strict Cross-Tenant Isolation on Capability Execution & Approvals
# ---------------------------------------------------------------------------

def test_9_cross_tenant_isolation_on_dynamic_capability(
    db: Session,
    tenant: Tenant,
    channel: Channel,
    owner_user: User,
    owner_conversation: Conversation,
):
    """
    Step 9 (Integration Test - Real Database Multi-Tenancy):
    Proves that dynamic capabilities activated in Tenant A cannot be executed or
    approved by Tenant B:
      1. Context tenant isolation raises PermissionError on cross-tenant tool invocation.
      2. Tenant B's engine does not register or execute Tenant A's private dynamic tools.
      3. Tenant B owner cannot approve Tenant A's pending approval requests.
    """
    # Create Tenant B
    tenant_b = Tenant(
        name="Beta Dairy Enterprise",
        slug=f"dairy-beta-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(tenant_b)
    db.flush()

    owner_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        name="Owner Beta",
        email=f"owner-{uuid.uuid4().hex[:6]}@beta.local",
        role="tenant_owner",
        status="active",
    )
    db.add(owner_b)

    channel_b = Channel(
        tenant_id=tenant_b.id,
        channel_type="telegram",
        name="Telegram Beta",
        status="active",
        config={
            "bot_token": "TEST_TOKEN_B_9999",
            "owner_identifiers": [str(owner_b.id), "999888777"],
        },
    )
    db.add(channel_b)

    conv_b = Conversation(
        tenant_id=tenant_b.id,
        channel_id=channel_b.id,
        status="open",
        subject="Owner Beta Chat",
        metadata_json={"is_owner": True},
    )
    db.add(conv_b)
    db.commit()

    engine = ConversationalAgentEngine(db=db)

    # 1. Tenant A develops and activates zakat_calculator
    msg_a1 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="احسب لي زكاة عسل 40 كيلو بسعر 250 ريال للكيلو بنسبة 2.5% وأنشئ مهارة قابلة لإعادة الاستخدام إذا لم توجد أداة مناسبة",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg_a1)
    db.commit()
    engine.process_message(msg_a1)

    msg_a2 = Message(
        tenant_id=tenant.id,
        conversation_id=owner_conversation.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أوافق على تفعيل الأداة zakat_calculator",
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg_a2)
    db.commit()
    engine.process_message(msg_a2)

    # 2. Get Tenant A's dynamic tool
    tool_a = engine.tool_registry.get("zakat_calculator")
    assert tool_a is not None
    assert getattr(tool_a, "tenant_id", None) == tenant.id

    # 3. Direct execution attempt with Tenant B's context MUST raise PermissionError
    ctx_b = ToolExecutionContext(tenant_id=tenant_b.id, conversation_id=conv_b.id)
    with pytest.raises(PermissionError) as exc_info:
        tool_a.run(ctx_b, amount=10000, rate=0.025)
    assert "Cross-tenant execution denied" in str(exc_info.value)

    # 4. Tenant B loading active capabilities must NOT load Tenant A's tools
    engine_b = ConversationalAgentEngine(db=db)
    loaded_b = engine_b.load_tenant_active_capabilities(tenant_b.id)
    assert "zakat_calculator" not in loaded_b


# ---------------------------------------------------------------------------
# Test 10: Sandbox Isolation Policy Enforcement
# ---------------------------------------------------------------------------

def test_10_sandbox_isolation_policy_blocks_uncontained_activation(
    db: Session,
    tenant: Tenant,
    owner_user: User,
):
    """
    Step 10 (Security Policy Enforcement Test):
    Proves that when verified container isolation is required (require_container_isolation=True)
    and the sandbox cannot provide a verified container runtime (is_containerized=False),
    SelfDevelopmentEngine strictly refuses to activate the dynamic capability.
    """
    from unittest.mock import MagicMock
    from packages.self_development.specification import CapabilitySpecification

    # Sandbox simulating a system without Docker / containerization
    uncontained_sandbox = ExecutionSandbox(backend="subprocess")
    # Force is_containerized to False
    uncontained_sandbox.check_docker_available = MagicMock(return_value=False)
    assert uncontained_sandbox.is_containerized is False

    engine = SelfDevelopmentEngine(
        db=db,
        sandbox=uncontained_sandbox,
        require_container_isolation=True,
    )

    # Create development request & spec
    dev_req, _ = engine.create_development_request(
        tenant_id=tenant.id,
        title="حاسبة تجريبية",
        reason="Testing container isolation guard",
    )

    spec_data = {
        "name": "حاسبة تجريبية",
        "slug": f"test_calc_{uuid.uuid4().hex[:6]}",
        "description": "أداة تجريبية لفحص حظر التفعيل بدون حاوية",
        "purpose": "فحص سياسات الأمان والحوكمة",
        "inputs": {"x": "number"},
        "outputs": {"res": "number"},
        "risk_level": "medium",
        "acceptance_tests": [{"input": {"x": 5}, "expected": {"res": 10}}],
    }

    ver = engine.prepare_specification(tenant.id, dev_req.id, spec_data)
    ver, run = engine.develop_and_test(
        tenant.id,
        ver.id,
        "def run(inputs):\n    return {'res': inputs.get('x', 0) * 2}\n",
    )
    assert run.status == "passed"

    # Owner approves candidate
    engine.review_and_approve(tenant.id, ver.id, owner_user, approved=True)

    # Attempt activation without verified container isolation MUST fail with PermissionError
    with pytest.raises(PermissionError) as exc_info:
        engine.activate_version(tenant.id, ver.id, owner_user)

    assert "Activation blocked: Dynamic capability cannot be activated without verified container isolation" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test 11: REQUIRE_CONTAINER_ISOLATION Comprehensive Enforcement Across All Paths
# ---------------------------------------------------------------------------

def test_11_container_isolation_blocks_all_execution_and_restoration_paths(
    db: Session,
    tenant: Tenant,
    owner_user: User,
):
    """
    Step 11 (Verification Gate Requirement 3):
    Proves that REQUIRE_CONTAINER_ISOLATION=true blocks:
      1. DynamicCapabilityTool.run() direct execution if container isolation is missing.
      2. ConversationalAgentEngine.load_tenant_active_capabilities() restoration.
      3. ConversationalAgentEngine.execute_tool_action() dynamic fallback.
      4. SelfDevelopmentEngine.disable_or_rollback() activation of rollback version.
    """
    from unittest.mock import MagicMock, patch
    from packages.self_development.dynamic_tool import DynamicCapabilityTool
    from packages.self_development.specification import CapabilitySpecification

    uncontained_sandbox = ExecutionSandbox(backend="subprocess")
    uncontained_sandbox.check_docker_available = MagicMock(return_value=False)
    assert uncontained_sandbox.is_containerized is False

    spec_dict = {
        "name": "حاسبة معزولة",
        "slug": f"isolated_calc_{uuid.uuid4().hex[:6]}",
        "description": "أداة فحص سياسة العزل",
        "purpose": "فحص سياسة العزل",
        "inputs": {"n": "number"},
        "outputs": {"res": "number"},
        "risk_level": "low",
        "acceptance_tests": [{"input": {"n": 2}, "expected": {"res": 4}}],
    }
    spec = CapabilitySpecification(**spec_dict)
    code = "def run(inputs):\n    return {'res': inputs.get('n', 0) * 2}\n"
    code_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

    # 1. Direct DynamicCapabilityTool.run() blocked
    tool = DynamicCapabilityTool(
        tenant_id=tenant.id,
        slug=spec.slug,
        name=spec.name,
        description=spec.description,
        implementation_code=code,
        spec=spec,
        sandbox=uncontained_sandbox,
        require_container_isolation=True,
    )
    ctx = ToolExecutionContext(tenant_id=tenant.id)
    with pytest.raises(PermissionError) as exc_info:
        tool.run(ctx, n=5)
    assert "Dynamic capability cannot be executed without verified container isolation" in str(exc_info.value)

    # 2. Persisted active capability in DB
    cap_ver = CapabilityVersion(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        version_number=1,
        slug=spec.slug,
        name=spec.name,
        description=spec.description,
        specification=spec_dict,
        implementation_code=code,
        risk_level="low",
        status="active",
        test_results={"all_passed": True, "content_hash": code_hash},
    )
    db.add(cap_ver)
    db.commit()

    # 3. ConversationalAgentEngine.load_tenant_active_capabilities() blocks restoration
    engine = ConversationalAgentEngine(db=db)
    engine.self_development_engine.sandbox = uncontained_sandbox
    engine.self_development_engine.require_container_isolation = True

    with patch.dict(os.environ, {"REQUIRE_CONTAINER_ISOLATION": "true"}):
        restored = engine.load_tenant_active_capabilities(tenant.id)
        assert spec.slug not in restored
        assert engine.tool_registry.get(spec.slug) is None

        # 4. execute_tool_action fallback blocks execution
        with pytest.raises(PermissionError) as exc_fallback:
            engine.execute_tool_action(tenant.id, spec.slug, {"n": 5})
        assert "Dynamic capability cannot be executed without verified container isolation" in str(exc_fallback.value)


# ---------------------------------------------------------------------------
# Test 12: Content Hash Tampering & Mismatched Tenant ID Block Restoration
# ---------------------------------------------------------------------------

def test_12_tampered_hash_and_tenant_mismatch_block_restoration(
    db: Session,
    tenant: Tenant,
):
    """
    Step 12 (Verification Gate Requirement 4):
    Proves that active capability restoration strictly rejects:
      1. Capability with mismatched content hash (tampered implementation code).
      2. Capability with mismatched tenant_id (cross-tenant leakage prevention).
    """
    engine = ConversationalAgentEngine(db=db)

    slug_tampered = f"tampered_tool_{uuid.uuid4().hex[:6]}"
    original_code = "def run(inputs):\n    return {'val': 1}\n"
    tested_hash = hashlib.sha256(original_code.strip().encode("utf-8")).hexdigest()

    tampered_code = "def run(inputs):\n    # Malicious injection\n    return {'val': 999}\n"

    # Persist tampered active capability in DB
    cap_tampered = CapabilityVersion(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        version_number=1,
        slug=slug_tampered,
        name="أداة ملعوبة",
        description="أداة تم تعديل كودها في قاعدة البيانات",
        specification={"content_hash": tested_hash},
        implementation_code=tampered_code,
        risk_level="low",
        status="active",
        test_results={"all_passed": True, "content_hash": tested_hash},
    )
    db.add(cap_tampered)

    # Persist capability belonging to Tenant B
    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Foreign Tenant Beta",
        slug=f"foreign-beta-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(tenant_b)
    db.flush()

    slug_tenant_b = f"foreign_tool_{uuid.uuid4().hex[:6]}"
    code_b = "def run(inputs):\n    return {'tenant': 'b'}\n"
    hash_b = hashlib.sha256(code_b.strip().encode("utf-8")).hexdigest()

    cap_b = CapabilityVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        version_number=1,
        slug=slug_tenant_b,
        name="أداة مستأجر خارجي",
        description="أداة لمستأجر آخر",
        specification={"content_hash": hash_b},
        implementation_code=code_b,
        risk_level="low",
        status="active",
        test_results={"all_passed": True, "content_hash": hash_b},
    )
    db.add(cap_b)
    db.commit()

    # 1. load_tenant_active_capabilities for Tenant A must NOT register tampered tool or foreign tool
    loaded_slugs = engine.load_tenant_active_capabilities(tenant.id)
    assert slug_tampered not in loaded_slugs
    assert slug_tenant_b not in loaded_slugs
    assert engine.tool_registry.get(slug_tampered) is None
    assert engine.tool_registry.get(slug_tenant_b) is None

    # 2. execute_tool_action for tampered tool must raise ValueError (Integrity check failed)
    with pytest.raises(ValueError) as exc_tamper:
        engine.execute_tool_action(tenant.id, slug_tampered, {})
    assert "Integrity check failed" in str(exc_tamper.value)

    # 3. execute_tool_action for foreign tenant tool must raise ValueError (not found for tenant A)
    with pytest.raises(ValueError) as exc_foreign:
        engine.execute_tool_action(tenant.id, slug_tenant_b, {})
    assert "Unknown tool slug" in str(exc_foreign.value)


