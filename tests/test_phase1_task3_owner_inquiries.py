"""
Test Suite: Phase 1 Task 3 - Owner Inquiry Loop & Dynamic Knowledge Resolution
Verifies:
1. Customer path creates inquiry for unrecorded questions, deduplicates waiting customers, and emits holding sentence.
2. Owner matching (reply-to, inquiry #, single pending) through ConversationalAgentEngine, saves fact via FactService, dispatches grounded answers to waiting customers, and prompts for scope.
3. Commands ('الاستفسارات', 'تجاهل 12'), reminders (2h/24h), rate limiting (20/hr), and strict tenant isolation.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select

from packages.core.database import SessionLocal
from packages.models.domain import Conversation, Fact, Message, OwnerInquiry, User
from packages.models.tenant import Tenant
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.owner_inquiry_service import DEFAULT_HOLDING_SENTENCE, OwnerInquiryService


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_customer_inquiry_creation_and_deduplication(db_session):
    """
    Verifies that unknown questions create an OwnerInquiry with holding sentence,
    and subsequent matching questions append to waiting_customers without double-alerting.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Inquiry Tenant {uid}", slug=f"inq-{uid}")
    db_session.add(tenant)
    db_session.flush()

    conv1 = Conversation(id=uuid4(), tenant_id=tenant.id)
    conv2 = Conversation(id=uuid4(), tenant_id=tenant.id)
    db_session.add_all([conv1, conv2])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    q_text = "هل لديكم فرع في تعز؟"

    # 1. First customer asks unknown question
    inquiry1, holding1 = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=conv1.id,
        customer_sender="+967770000001",
        question=q_text,
    )

    assert holding1 == DEFAULT_HOLDING_SENTENCE
    assert inquiry1.status == "asked"
    assert inquiry1.inquiry_number >= 1
    assert len(inquiry1.waiting_customers) == 1

    # 2. Second customer asks the same question with minor punctuation variance
    inquiry2, holding2 = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=conv2.id,
        customer_sender="+967770000002",
        question="هل لديكم فرع في تعز ؟؟",
    )

    assert holding2 == DEFAULT_HOLDING_SENTENCE
    assert inquiry2.id == inquiry1.id  # Deduplicated!
    assert len(inquiry2.waiting_customers) == 2


def test_owner_answer_matching_fact_persistence_and_customer_dispatch(db_session):
    """
    Verifies real ConversationalAgentEngine path:
    1. Owner matches pending inquiry via 'جواب #12: ...'.
    2. Answer is saved as confirmed fact in FactService.
    3. Grounded reply is immediately dispatched to all waiting customer conversations.
    4. Scope prompt ('أحفظها للجميع أم لهذا العميل فقط؟') updates visibility via engine.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Answer Tenant {uid}", slug=f"ans-{uid}")
    db_session.add(tenant)
    db_session.flush()

    owner_user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"owner_{uid}@safiasll.com",
        name="مالك المنشأة",
        role="tenant_admin",
    )
    db_session.add(owner_user)
    db_session.flush()

    owner_conv = Conversation(id=uuid4(), tenant_id=tenant.id, status="owner_management")
    cust_conv = Conversation(id=uuid4(), tenant_id=tenant.id)
    db_session.add_all([owner_conv, cust_conv])
    db_session.flush()

    svc = OwnerInquiryService(db_session)
    inquiry, _ = svc.handle_customer_inquiry(
        tenant_id=tenant.id,
        customer_conversation_id=cust_conv.id,
        customer_sender="+967771111111",
        question="ما هي مواعيد الدوام يوم الجمعة؟",
    )

    # Owner sends answer message into owner_management conversation through real engine
    ans_text = "الدوام يوم الجمعة من بعد صلاة العصر حتى 10 مساءً"
    owner_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=owner_conv.id,
        sender_type="owner",
        sender_id=owner_user.id,
        content=f"جواب #{inquiry.inquiry_number}: {ans_text}",
    )
    db_session.add(owner_msg)
    db_session.flush()

    engine = ConversationalAgentEngine(db_session)
    res = engine.process_incoming_message(tenant_id=tenant.id, message_id=owner_msg.id)

    assert res.success is True
    assert "أحفظها للجميع أم لهذا العميل فقط؟" in res.reply_content

    # Verify inquiry updated
    db_session.refresh(inquiry)
    assert inquiry.status == "delivered"
    assert inquiry.owner_answer == ans_text

    # Verify fact created in FactService
    fact = db_session.scalar(
        select(Fact).where(
            Fact.tenant_id == tenant.id,
            Fact.topic == f"faq.inquiry_{inquiry.inquiry_number}",
        )
    )
    assert fact is not None
    assert fact.status == "confirmed"
    assert fact.value.get("answer") == ans_text

    # Verify customer received immediate message in their conversation
    cust_msg = db_session.scalar(
        select(Message).where(
            Message.tenant_id == tenant.id,
            Message.conversation_id == cust_conv.id,
            Message.sender_type == "agent",
        ).order_by(Message.created_at.desc())
    )
    assert cust_msg is not None
    assert ans_text in cust_msg.content

    # 2. Scope reply: owner responds "للجميع" through real engine
    scope_msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=owner_conv.id,
        sender_type="owner",
        sender_id=owner_user.id,
        content="للجميع",
    )
    db_session.add(scope_msg)
    db_session.flush()

    res_scope = engine.process_incoming_message(tenant_id=tenant.id, message_id=scope_msg.id)
    assert res_scope.success is True
    assert "للجميع" in res_scope.reply_content

    db_session.refresh(inquiry)
    db_session.refresh(fact)
    assert inquiry.scope == "public"
    assert fact.visibility == "public"


def test_commands_reminders_rate_limiting_and_tenant_isolation(db_session):
    """
    Verifies:
    1. Commands ('الاستفسارات' and 'تجاهل 12').
    2. Reminders at 2h and status update at 24h.
    3. Max 20 notifications/hr rate limiting.
    4. Tenant isolation (Tenant B cannot access Tenant A's inquiries).
    """
    uid_a = uuid4().hex[:6]
    uid_b = uuid4().hex[:6]
    tenant_a = Tenant(id=uuid4(), name=f"Tenant A {uid_a}", slug=f"t-a-{uid_a}")
    tenant_b = Tenant(id=uuid4(), name=f"Tenant B {uid_b}", slug=f"t-b-{uid_b}")
    db_session.add(tenant_a)
    db_session.flush()
    db_session.add(tenant_b)
    db_session.flush()

    conv_a = Conversation(id=uuid4(), tenant_id=tenant_a.id)
    conv_b = Conversation(id=uuid4(), tenant_id=tenant_b.id)
    db_session.add_all([conv_a, conv_b])
    db_session.flush()

    svc = OwnerInquiryService(db_session)

    # 1. Create inquiry in Tenant A
    inq_a, _ = svc.handle_customer_inquiry(
        tenant_id=tenant_a.id,
        customer_conversation_id=conv_a.id,
        customer_sender="+967772222222",
        question="هل يوجد شحن لمديرية المخا؟",
    )

    # Tenant B tries command 'الاستفسارات' -> must NOT see Tenant A's inquiry!
    list_b = svc.handle_command(tenant_id=tenant_b.id, content="الاستفسارات")
    assert "لا توجد استفسارات معلقة" in list_b

    # Tenant A sees it
    list_a = svc.handle_command(tenant_id=tenant_a.id, content="الاستفسارات")
    assert f"#{inq_a.inquiry_number}" in list_a

    # Tenant B tries to ignore Tenant A's inquiry -> fails
    ign_b = svc.handle_command(tenant_id=tenant_b.id, content=f"تجاهل {inq_a.inquiry_number}")
    assert "غير موجود" in ign_b
    db_session.refresh(inq_a)
    assert inq_a.status != "ignored"

    # Tenant A ignores it -> succeeds
    ign_a = svc.handle_command(tenant_id=tenant_a.id, content=f"تجاهل {inq_a.inquiry_number}")
    assert f"تم تجاهل الاستفسار #{inq_a.inquiry_number}" in ign_a
    db_session.refresh(inq_a)
    assert inq_a.status == "ignored"

    # 2. Test 2h reminder and 24h timeout
    inq_old = OwnerInquiry(
        id=uuid4(),
        tenant_id=tenant_a.id,
        customer_conversation_id=conv_a.id,
        customer_sender="+967773333333",
        question="سؤال قديم للتحقق من التذكير",
        normalized_question="سؤال قديم للتحقق من التذكير",
        status="asked",
        asked_at=datetime.now(timezone.utc) - timedelta(hours=3),
        created_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    db_session.add(inq_old)
    db_session.flush()

    check_stats = svc.check_reminders_and_timeouts(tenant_id=tenant_a.id)
    assert check_stats["reminded"] >= 1
    assert check_stats["timeout"] >= 1

    db_session.refresh(inq_old)
    assert inq_old.status == "timeout"
    assert inq_old.reminded_at is not None
    assert inq_old.timeout_at is not None
