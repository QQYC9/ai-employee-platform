from __future__ import annotations

from datetime import datetime, timezone
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
    Message,
    User,
)
from packages.models.tenant import Tenant
from packages.connectors.base import InboundMessage
from packages.services.approval_service import ApprovalService
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine


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
        name="Tenant Alpha Approvals",
        slug=f"tenant-alpha-app-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner Alpha",
        email=f"owner-{uuid.uuid4().hex[:6]}@alpha.app",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    brain = BusinessBrain(
        tenant_id=t.id,
        identity={"name": "متجر ألفا المعتمد"},
        brand={"tone": "رسمي"},
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
        name="Tenant Beta Approvals",
        slug=f"tenant-beta-app-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner Beta",
        email=f"owner-{uuid.uuid4().hex[:6]}@beta.app",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)
    db.commit()
    return t


@pytest.fixture
def channel_alpha(db: Session, tenant_alpha: Tenant):
    svc = ChannelService(db)
    channel = svc.register_channel(
        tenant_id=tenant_alpha.id,
        name="WhatsApp Alpha",
        channel_type="whatsapp",
        provider="whatsapp",
        config={
            "phone_number_id": "10001",
            "owner_identifiers": ["+966555111222"],
        },
    )
    db.commit()
    return channel


# ===========================================================================
# 1. Generic word 'موافق' alone DOES NOT approve a sensitive operation
# ===========================================================================

def test_1_generic_approval_does_not_approve_sensitive_operation(
    db: Session, tenant_alpha: Tenant, channel_alpha: Channel
):
    """
    Scenario 1:
    A sensitive approval exists (e.g. bulk deletion of customers).
    Owner sends a bare, generic confirmation: "موافق" or "نعم أوافق".
    HARDENING REQUIREMENT:
    System MUST reject the generic approval, demanding the explicit UUID.
    The approval MUST remain in 'pending' status.
    No data must be deleted.
    """
    approval_svc = ApprovalService(db)
    app = approval_svc.create_approval(
        tenant_id=tenant_alpha.id,
        requested_for="tenant_owner",
        action="bulk_destructive_operation",
        description="حذف جميع بيانات العملاء والمحادثات",
    )
    db.commit()

    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.gen1.{uuid.uuid4().hex[:8]}",
        content="موافق",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    engine = ConversationalAgentEngine(db=db)
    res = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg.id)
    db.commit()

    assert res.success is True
    # Reply must warn the owner that sensitive operations cannot be approved with generic words
    assert "إجراءً حساساً" in res.reply_content or "لا يمكن اعتماده بكلمة عامة" in res.reply_content
    assert str(app.id) in res.reply_content

    # CRITICAL CHECK: Approval must still be PENDING!
    db.expire_all()
    db_app = approval_svc.get_approval(tenant_alpha.id, app.id)
    assert db_app.status == "pending"
    assert db_app.decision_by_user_id is None


# ===========================================================================
# 2. Multiple pending approvals: generic 'موافق' does not pick any random approval
# ===========================================================================

def test_2_multiple_pending_approvals_require_explicit_id(
    db: Session, tenant_alpha: Tenant, channel_alpha: Channel
):
    """
    Scenario 2:
    Multiple pending approvals exist in the database (e.g. 2 different actions).
    Owner sends generic "أوافق".
    HARDENING REQUIREMENT:
    System MUST NOT default to pending[0].
    System must ask the owner to specify the exact UUID, listing pending items.
    Both approvals MUST remain 'pending'.
    """
    approval_svc = ApprovalService(db)
    app1 = approval_svc.create_approval(
        tenant_id=tenant_alpha.id,
        requested_for="tenant_owner",
        action="task_approval",
        description="اعتماد خطة تسويقية لموسم العسل",
    )
    app2 = approval_svc.create_approval(
        tenant_id=tenant_alpha.id,
        requested_for="tenant_owner",
        action="data_export",
        description="تصدير تقرير المبيعات السنوي",
    )
    db.commit()

    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.multi.{uuid.uuid4().hex[:8]}",
        content="أوافق على الطلب",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    engine = ConversationalAgentEngine(db=db)
    res = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg.id)
    db.commit()

    assert res.success is True
    assert "توجد عدة طلبات موافقة معلقة" in res.reply_content
    assert str(app1.id) in res.reply_content
    assert str(app2.id) in res.reply_content

    # CRITICAL CHECK: Neither approval was approved!
    db.expire_all()
    db_app1 = approval_svc.get_approval(tenant_alpha.id, app1.id)
    db_app2 = approval_svc.get_approval(tenant_alpha.id, app2.id)
    assert db_app1.status == "pending"
    assert db_app2.status == "pending"


# ===========================================================================
# 3. Explicit UUID approval works correctly
# ===========================================================================

def test_3_explicit_uuid_approval_succeeds(
    db: Session, tenant_alpha: Tenant, channel_alpha: Channel
):
    """
    Scenario 3:
    Multiple pending approvals exist.
    Owner sends explicit confirmation with the exact UUID of App 2:
    "أوافق على الطلب <UUID_APP2>"
    HARDENING REQUIREMENT:
    App 2 MUST transition to 'approved'.
    App 1 MUST remain 'pending'.
    """
    approval_svc = ApprovalService(db)
    app1 = approval_svc.create_approval(
        tenant_id=tenant_alpha.id,
        requested_for="tenant_owner",
        action="task_approval",
        description="مهمة تجهيز الطلبات",
    )
    app2 = approval_svc.create_approval(
        tenant_id=tenant_alpha.id,
        requested_for="tenant_owner",
        action="bulk_destructive_operation",
        description="حذف العملاء غير النشطين",
    )
    db.commit()

    chan_svc = ChannelService(db)
    inbound = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.explicit.{uuid.uuid4().hex[:8]}",
        content=f"أوافق على الطلب {app2.id}",
    )
    msg = chan_svc.process_inbound_message(inbound)
    db.commit()

    engine = ConversationalAgentEngine(db=db)
    res = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg.id)
    db.commit()

    assert res.success is True
    assert "تمت الموافقة بنجاح" in res.reply_content
    assert str(app2.id) in res.reply_content

    db.expire_all()
    db_app1 = approval_svc.get_approval(tenant_alpha.id, app1.id)
    db_app2 = approval_svc.get_approval(tenant_alpha.id, app2.id)
    assert db_app1.status == "pending"
    assert db_app2.status == "approved"
    assert db_app2.decision_by_user_id is not None


# ===========================================================================
# 4. Non-existent UUID or cross-tenant UUID is strictly rejected
# ===========================================================================

def test_4_nonexistent_or_cross_tenant_uuid_rejected(
    db: Session, tenant_alpha: Tenant, tenant_beta: Tenant, channel_alpha: Channel
):
    """
    Scenario 4:
    A: Owner sends a random non-existent UUID.
    B: Owner attempts to approve an approval belonging to Tenant Beta.
    HARDENING REQUIREMENT:
    Both must be rejected with informative error messages.
    No approval in either tenant may be altered.
    """
    approval_svc = ApprovalService(db)
    app_beta = approval_svc.create_approval(
        tenant_id=tenant_beta.id,
        requested_for="tenant_owner",
        action="beta_sensitive_op",
        description="عملية خاصة بمستأجر بيتا",
    )
    db.commit()

    chan_svc = ChannelService(db)
    engine = ConversationalAgentEngine(db=db)

    # 4A: Non-existent UUID
    random_uuid = uuid.uuid4()
    inbound_fake = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.fake.{uuid.uuid4().hex[:8]}",
        content=f"أوافق على الطلب {random_uuid}",
    )
    msg_fake = chan_svc.process_inbound_message(inbound_fake)
    db.commit()

    res_fake = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg_fake.id)
    db.commit()
    assert "لم يتم العثور على أي طلب موافقة" in res_fake.reply_content

    # 4B: Cross-tenant approval attempt
    inbound_cross = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.cross.{uuid.uuid4().hex[:8]}",
        content=f"أوافق على الطلب {app_beta.id}",
    )
    msg_cross = chan_svc.process_inbound_message(inbound_cross)
    db.commit()

    res_cross = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg_cross.id)
    db.commit()
    assert "غير مصرح" in res_cross.reply_content or "لا ينتمي" in res_cross.reply_content

    # Ensure Beta's approval remains pending
    db.expire_all()
    beta_check = approval_svc.get_approval(tenant_beta.id, app_beta.id)
    assert beta_check.status == "pending"


# ===========================================================================
# 5. Re-sending approval does not duplicate execution
# ===========================================================================

def test_5_re_approval_does_not_duplicate_execution(
    db: Session, tenant_alpha: Tenant, channel_alpha: Channel
):
    """
    Scenario 5:
    Approval has already been approved.
    Owner sends another message approving the same UUID.
    HARDENING REQUIREMENT:
    System detects approval is already processed/approved.
    Informs owner without error or re-executing actions.
    """
    approval_svc = ApprovalService(db)
    app = approval_svc.create_approval(
        tenant_id=tenant_alpha.id,
        requested_for="tenant_owner",
        action="sensitive_export",
        description="تصدير كشف حساب",
    )
    db.commit()

    chan_svc = ChannelService(db)
    engine = ConversationalAgentEngine(db=db)

    # First approval
    inbound1 = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.app1.{uuid.uuid4().hex[:8]}",
        content=f"أوافق على الطلب {app.id}",
    )
    msg1 = chan_svc.process_inbound_message(inbound1)
    db.commit()
    res1 = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg1.id)
    db.commit()
    assert "تمت الموافقة بنجاح" in res1.reply_content

    # Second approval in a new message
    inbound2 = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.app2.{uuid.uuid4().hex[:8]}",
        content=f"تأكيد أوافق على الطلب {app.id}",
    )
    msg2 = chan_svc.process_inbound_message(inbound2)
    db.commit()
    res2 = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg2.id)
    db.commit()

    assert "غير معلق حالياً" in res2.reply_content or "معتمد" in res2.reply_content or "لم يتم تكرار العملية" in res2.reply_content


# ===========================================================================
# 6. No destructive effect prior to explicit approval
# ===========================================================================

def test_6_no_destructive_effect_prior_to_explicit_approval(
    db: Session, tenant_alpha: Tenant, channel_alpha: Channel
):
    """
    Scenario 6:
    A customer exists in the database.
    Owner sends: "حذف جميع العملاء وتصفير النظام".
    1. System creates an approval.
    2. Customer MUST NOT be deleted.
    Owner says: "موافق" (generic).
    3. Generic approval is rejected; customer MUST NOT be deleted.
    Owner says: "أوافق على الطلب <UUID>".
    4. Only now does the approval transition to 'approved'.
    """
    # Seed customer
    cust = Customer(
        tenant_id=tenant_alpha.id,
        name="عميل مميز",
        phone="+966509998877",
        status="active",
    )
    db.add(cust)
    db.commit()

    chan_svc = ChannelService(db)
    engine = ConversationalAgentEngine(db=db)

    # Step 1: Owner initiates destructive request
    inbound1 = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.del1.{uuid.uuid4().hex[:8]}",
        content="حذف جميع العملاء وتصفير قاعدة البيانات",
    )
    msg1 = chan_svc.process_inbound_message(inbound1)
    db.commit()
    res1 = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg1.id)
    db.commit()

    assert "طلب موافقة رسمي" in res1.reply_content
    approval_svc = ApprovalService(db)
    pending_apps = approval_svc.list_approvals(tenant_alpha.id, status="pending")
    assert len(pending_apps) == 1
    destruct_app = pending_apps[0]

    # Verify customer still intact!
    db.expire_all()
    check_cust = db.scalar(select(Customer).where(Customer.id == cust.id))
    assert check_cust is not None
    assert check_cust.status == "active"

    # Step 2: Owner sends generic 'موافق'
    inbound2 = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.del2.{uuid.uuid4().hex[:8]}",
        content="موافق",
    )
    msg2 = chan_svc.process_inbound_message(inbound2)
    db.commit()
    res2 = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg2.id)
    db.commit()

    assert "إجراءً حساساً" in res2.reply_content
    # Approval must still be pending!
    db.expire_all()
    assert approval_svc.get_approval(tenant_alpha.id, destruct_app.id).status == "pending"
    # Customer still intact!
    check_cust = db.scalar(select(Customer).where(Customer.id == cust.id))
    assert check_cust is not None

    # Step 3: Owner provides explicit UUID
    inbound3 = InboundMessage(
        channel_type="whatsapp",
        channel_id=channel_alpha.id,
        tenant_id=tenant_alpha.id,
        sender_id="+966555111222",
        external_message_id=f"wamid.del3.{uuid.uuid4().hex[:8]}",
        content=f"أوافق على الطلب {destruct_app.id}",
    )
    msg3 = chan_svc.process_inbound_message(inbound3)
    db.commit()
    res3 = engine.process_incoming_message(tenant_id=tenant_alpha.id, message_id=msg3.id)
    db.commit()

    assert "تمت الموافقة بنجاح" in res3.reply_content
    db.expire_all()
    assert approval_svc.get_approval(tenant_alpha.id, destruct_app.id).status == "approved"
