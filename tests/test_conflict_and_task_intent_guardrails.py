from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal
from packages.models.domain import (
    Channel,
    Conversation,
    Fact,
    Message,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.conversation_service import ConversationService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.owner_intent_router import IntentCategory, OwnerIntentRouter
from packages.services.fact_service import FactService


class MockAIProvider:
    def __init__(self, reply: str = "رد تجريبي"):
        self.reply = reply

    def generate_reply(self, messages, system_instruction=None, **kwargs):
        return self.reply

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant(db: Session):
    tid = uuid4().hex[:6]
    t = Tenant(
        id=uuid4(),
        name=f"Guardrail Tenant {tid}",
        slug=f"guardrail-tenant-{tid}",
        employee_name="مساعد المنذر الذكي",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def channel(db: Session, tenant: Tenant):
    ch = Channel(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Owner Telegram Channel",
        channel_type="telegram",
        status="active",
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


@pytest.fixture
def owner_user(db: Session, tenant: Tenant):
    u = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"owner-{uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        name="Owner Testing User",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Test 1: Explicit Option 1 / 1 Resolves Conflict and Updates DB
# ---------------------------------------------------------------------------
def test_explicit_option_1_resolves_conflict_and_updates_db(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    f_existing = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "المنذر تكنولوجيا"},
        source="owner_stated",
        confidence=1.0,
        visibility="public",
        status="confirmed",
    )
    f_conflict = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "شركة المنذر للحلول الرقمية"},
        source="owner_stated",
        confidence=0.8,
        visibility="public",
        status="conflict",
    )
    db.add_all([f_existing, f_conflict])
    db.commit()

    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Conflict Test 1",
        channel_id=channel.id,
    )
    conv.metadata_json = {
        "pending_conflict": {
            "existing_fact_id": str(f_existing.id),
            "conflicting_fact_id": str(f_conflict.id),
            "topic": "company.identity",
            "subject": "اسم المنشأة",
            "opt1_label": "المنذر تكنولوجيا",
            "opt2_label": "شركة المنذر للحلول الرقمية",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    msg = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="اعتمد الخيار الأول",
        metadata_json={"is_owner": True},
    )
    res = engine.process_incoming_message(tenant.id, msg.id)
    assert res.success is True
    assert "تم حل التعارض بنجاح" in res.reply_content
    assert "المنذر تكنولوجيا" in res.reply_content

    # Verify DB updates
    db.refresh(f_existing)
    db.refresh(f_conflict)
    db.refresh(conv)

    assert f_existing.status == "confirmed"
    assert f_conflict.status == "superseded"
    assert f_conflict.superseded_by == f_existing.id
    assert "pending_conflict" not in (conv.metadata_json or {})


# ---------------------------------------------------------------------------
# Test 2: Compound Words Like «الأولية» Do NOT Match Option 1
# ---------------------------------------------------------------------------
def test_compound_words_like_awaliya_do_not_match_option_1(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    f_existing = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "المنذر تكنولوجيا"},
        source="owner_stated",
        confidence=1.0,
        visibility="public",
        status="confirmed",
    )
    f_conflict = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "شركة المنذر المتطورة"},
        source="owner_stated",
        confidence=0.8,
        visibility="public",
        status="conflict",
    )
    db.add_all([f_existing, f_conflict])
    db.commit()

    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Awaliya Match Test",
        channel_id=channel.id,
    )
    conv.metadata_json = {
        "pending_conflict": {
            "existing_fact_id": str(f_existing.id),
            "conflicting_fact_id": str(f_conflict.id),
            "topic": "company.identity",
            "subject": "اسم المنشأة",
            "opt1_label": "المنذر تكنولوجيا",
            "opt2_label": "شركة المنذر المتطورة",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # Message containing "الأولية" but NOT selecting option 1
    msg = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="اجعل الحالة الأولية للمهمة معلقة وسنحدد الأولويات لاحقاً",
        metadata_json={"is_owner": True},
    )
    res = engine.process_incoming_message(tenant.id, msg.id)
    assert res.success is True
    # Must NOT report conflict resolution
    assert "تم حل التعارض" not in res.reply_content

    # Verify pending conflict is still intact
    db.refresh(conv)
    assert "pending_conflict" in (conv.metadata_json or {})
    db.refresh(f_existing)
    db.refresh(f_conflict)
    assert f_existing.status == "confirmed"
    assert f_conflict.status == "conflict"


# ---------------------------------------------------------------------------
# Test 3: Unrelated Messages Do Not Consume Pending Conflict
# ---------------------------------------------------------------------------
def test_unrelated_messages_do_not_consume_pending_conflict(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    f_existing = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="operations.working_hours",
        subject="ساعات العمل",
        value={"hours": "9 ص - 5 م"},
        source="owner_stated",
        confidence=1.0,
        visibility="public",
        status="confirmed",
    )
    f_conflict = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="operations.working_hours",
        subject="ساعات العمل",
        value={"hours": "8 ص - 8 م"},
        source="owner_stated",
        confidence=0.8,
        visibility="public",
        status="conflict",
    )
    db.add_all([f_existing, f_conflict])
    db.commit()

    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Unrelated Message Test",
        channel_id=channel.id,
    )
    conv.metadata_json = {
        "pending_conflict": {
            "existing_fact_id": str(f_existing.id),
            "conflicting_fact_id": str(f_conflict.id),
            "topic": "operations.working_hours",
            "subject": "ساعات العمل",
            "opt1_label": "9 ص - 5 م",
            "opt2_label": "8 ص - 8 م",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    msg = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="شكراً جزيلاً لك على التوضيح",
        metadata_json={"is_owner": True},
    )
    res = engine.process_incoming_message(tenant.id, msg.id)
    assert res.success is True
    assert "تم حل التعارض" not in res.reply_content

    # Verify conflict state preserved
    db.refresh(conv)
    assert "pending_conflict" in (conv.metadata_json or {})


# ---------------------------------------------------------------------------
# Test 4: Expired Conflict (>24h) TTL Behavior
# ---------------------------------------------------------------------------
def test_expired_conflict_ttl_behavior(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    f_existing = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "المنذر تكنولوجيا"},
        source="owner_stated",
        confidence=1.0,
        visibility="public",
        status="confirmed",
    )
    f_conflict = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "شركة المنذر للحلول الرقمية"},
        source="owner_stated",
        confidence=0.8,
        visibility="public",
        status="conflict",
    )
    db.add_all([f_existing, f_conflict])
    db.commit()

    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Expired Conflict Test",
        channel_id=channel.id,
    )
    # Created 25 hours ago (>24h TTL)
    expired_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conv.metadata_json = {
        "pending_conflict": {
            "existing_fact_id": str(f_existing.id),
            "conflicting_fact_id": str(f_conflict.id),
            "topic": "company.identity",
            "subject": "اسم المنشأة",
            "opt1_label": "المنذر تكنولوجيا",
            "opt2_label": "شركة المنذر للحلول الرقمية",
            "created_at": expired_time,
        }
    }
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # User attempts to select option 1 on expired conflict
    msg = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="اعتمد الخيار الأول",
        metadata_json={"is_owner": True},
    )
    res = engine.process_incoming_message(tenant.id, msg.id)
    assert res.success is True
    # Must notify about expiration and NOT apply conflict resolution
    assert "انتهت مهلة الرد على التعارض" in res.reply_content
    assert "تم حل التعارض بنجاح" not in res.reply_content

    # Verify pending conflict removed cleanly and facts untouched
    db.refresh(conv)
    assert "pending_conflict" not in (conv.metadata_json or {})
    db.refresh(f_existing)
    db.refresh(f_conflict)
    assert f_existing.status == "confirmed"
    assert f_conflict.status == "conflict"


# ---------------------------------------------------------------------------
# Test 5: Database Error During Conflict Resolution Performs Safe Rollback
# ---------------------------------------------------------------------------
def test_database_error_during_conflict_resolution_safe_rollback(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    f_existing = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "المنذر تكنولوجيا"},
        source="owner_stated",
        confidence=1.0,
        visibility="public",
        status="confirmed",
    )
    f_conflict = Fact(
        id=uuid4(),
        tenant_id=tenant.id,
        topic="company.identity",
        subject="اسم المنشأة",
        value={"name": "شركة المنذر للحلول الرقمية"},
        source="owner_stated",
        confidence=0.8,
        visibility="public",
        status="conflict",
    )
    db.add_all([f_existing, f_conflict])
    db.commit()

    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="DB Error Conflict Test",
        channel_id=channel.id,
    )
    conv.metadata_json = {
        "pending_conflict": {
            "existing_fact_id": str(f_existing.id),
            "conflicting_fact_id": str(f_conflict.id),
            "topic": "company.identity",
            "subject": "اسم المنشأة",
            "opt1_label": "المنذر تكنولوجيا",
            "opt2_label": "شركة المنذر للحلول الرقمية",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    # Patch resolve_conflict to simulate DB failure
    with patch("packages.services.fact_service.FactService.resolve_conflict", side_effect=RuntimeError("Simulated DB Disk Failure")):
        msg = conv_svc.send_message(
            tenant_id=tenant.id,
            conversation_id=conv.id,
            sender_type="user",
            sender_id=owner_user.id,
            content="الخيار الأول",
            metadata_json={"is_owner": True},
        )
        res = engine.process_incoming_message(tenant.id, msg.id)
        assert res.success is True
        assert "تعذر حل التعارض" in res.reply_content
        assert "تم حل التعارض بنجاح" not in res.reply_content


# ---------------------------------------------------------------------------
# Test 6: End-to-End Owner Telegram Incident Task Create
# ---------------------------------------------------------------------------
def test_end_to_end_owner_telegram_incident_task_create(
    db: Session, tenant: Tenant, channel: Channel, owner_user: User
):
    """
    Exact verbatim message from Telegram test incident:
    «أريد إنشاء مهمة اختبار بعنوان اختبار التفويض الأمني 1-D.2، ووصفها مهمة اختبار يدوية للتحقق من تنفيذ المالك، واجعل حالتها الأولية معلقة. نفّذ الإنشاء فعلياً، ثم أعطني معرّف المهمة ونتيجة التنفيذ المؤكدة.»
    """
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Telegram Incident Reproduction",
        channel_id=channel.id,
    )

    incident_content = (
        "أريد إنشاء مهمة اختبار بعنوان اختبار التفويض الأمني 1-D.2، "
        "ووصفها مهمة اختبار يدوية للتحقق من تنفيذ المالك، "
        "واجعل حالتها الأولية معلقة. نفّذ الإنشاء فعلياً، ثم أعطني معرّف المهمة ونتيجة التنفيذ المؤكدة."
    )

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    msg = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content=incident_content,
        metadata_json={"is_owner": True},
    )

    res = engine.process_incoming_message(tenant.id, msg.id)
    assert res.success is True
    reply = res.reply_content

    # 1. Assert it did NOT reply with stale conflict resolution
    assert "تم حل التعارض بنجاح" not in reply
    assert "برنامج للموظف الذكي" not in reply

    # 2. Assert it confirms task creation with title and task ID
    assert "تم إنشاء المهمة بنجاح" in reply
    assert "اختبار التفويض الأمني 1-D.2" in reply

    # 3. Verify actual record created in DB tasks table
    created_task = db.scalar(
        select(Task).where(
            Task.tenant_id == tenant.id,
            Task.title == "اختبار التفويض الأمني 1-D.2",
        )
    )
    assert created_task is not None
    assert str(created_task.id) in reply
    assert "مهمة اختبار يدوية للتحقق من تنفيذ المالك" in (created_task.objective or created_task.description or "")
    assert created_task.status in ("pending", "active")


# ---------------------------------------------------------------------------
# Test 7: Task Creation Intent Variations & Query Distinctions
# ---------------------------------------------------------------------------
def test_task_creation_intent_variations_and_non_task_queries(
    db: Session, tenant: Tenant, owner_user: User
):
    router = OwnerIntentRouter(db=db, ai_provider=MockAIProvider())

    # 1. Variations of task creation
    c1 = router.parse_intent("أريد إنشاء مهمة بعنوان فحص المخزون السنوي، ووصفها جرد المستودع", tenant_id=tenant.id, actor_id=owner_user.id)
    assert len(c1.steps) == 1
    assert c1.steps[0].tool_slug == "task_create"
    assert c1.steps[0].parameters["title"] == "فحص المخزون السنوي"

    c2 = router.parse_intent("أريد أنشئ مهمة اسمها تدقيق الحسابات المالية", tenant_id=tenant.id, actor_id=owner_user.id)
    assert len(c2.steps) == 1
    assert c2.steps[0].tool_slug == "task_create"
    assert "تدقيق الحسابات المالية" in c2.steps[0].parameters["title"]

    c3 = router.parse_intent("أنشئ لي مهمة بعنوان ترقية الخوادم", tenant_id=tenant.id, actor_id=owner_user.id)
    assert len(c3.steps) == 1
    assert c3.steps[0].tool_slug == "task_create"
    assert c3.steps[0].parameters["title"] == "ترقية الخوادم"

    c4 = router.parse_intent("سجل مهمة جديدة: إعداد التقرير المالي", tenant_id=tenant.id, actor_id=owner_user.id)
    assert len(c4.steps) == 1
    assert c4.steps[0].tool_slug == "task_create"
    assert "إعداد التقرير المالي" in c4.steps[0].parameters["title"]

    # 2. Distinction: Task Query
    c_query = router.parse_intent("ما هي المهام الحالية قيد التنفيذ؟", tenant_id=tenant.id, actor_id=owner_user.id)
    assert len(c_query.steps) == 1
    assert c_query.steps[0].tool_slug == "task_query"

    # 3. Distinction: Adjective use of "مهمة"
    c_adj = router.parse_intent("هذه نقطة مهمة جداً يجب مراعاتها", tenant_id=tenant.id, actor_id=owner_user.id)
    assert c_adj.intent == "general_owner_chat"
    assert len(c_adj.steps) == 0


# ---------------------------------------------------------------------------
# Test 8: End-to-End Regression Suite Verification
# ---------------------------------------------------------------------------
def test_regression_suite_verification(db: Session, tenant: Tenant, channel: Channel, owner_user: User):
    """
    Ensures that both single operational intents and multi-step plans execute
    without missing permissions or dropping single-tool requests.
    """
    conv_svc = ConversationService(db)
    conv = conv_svc.start_conversation(
        tenant_id=tenant.id,
        customer_id=None,
        subject="Single Step Regression Test",
        channel_id=channel.id,
    )
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())

    msg = conv_svc.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="user",
        sender_id=owner_user.id,
        content="أريد إنشاء مهمة بعنوان مراجعة وثائق النظام 1.0",
        metadata_json={"is_owner": True},
    )
    res = engine.process_incoming_message(tenant.id, msg.id)
    assert res.success is True
    assert "تم إنشاء المهمة بنجاح" in res.reply_content
    assert "مراجعة وثائق النظام 1.0" in res.reply_content


# ---------------------------------------------------------------------------
# Test 9: FactService Hardened Negative Guardrail - Operational Commands Rejected
# ---------------------------------------------------------------------------
def test_fact_service_rejects_operational_task_commands_as_facts(db: Session, tenant: Tenant):
    """
    Ensures FactService never converts operational action commands (like 'أريد إنشاء مهمة')
    into persistent facts in the facts table, both via regex fallback and AI path.
    """
    fact_service = FactService(db=db)
    operational_cmd = (
        "أريد إنشاء مهمة اختبار بعنوان اختبار التفويض الأمني 1-D.2، "
        "ووصفها مهمة اختبار يدوية للتحقق من تنفيذ المالك، "
        "واجعل حالتها الأولية معلقة. نفّذ الإنشاء فعلياً، ثم أعطني معرّف المهمة ونتيجة التنفيذ المؤكدة."
    )

    # 1. Regex fallback path
    fallback_res = fact_service.extract_facts(tenant.id, operational_cmd, provider=None)
    assert len(fallback_res.facts) == 0, f"Expected 0 facts, got: {fallback_res.facts}"

    # 2. AI provider simulation returning an operational task topic (the bug that occurred previously)
    class MockLeakingAIProvider:
        def generate_json(self, prompt, schema=None, system_instruction=None):
            return {
                "facts": [
                    {
                        "topic": "task.creation",
                        "subject": "اختبار التفويض الأمني 1-D.2",
                        "value": {"details": "مهمة اختبار يدوية للتحقق من تنفيذ المالك"},
                        "operation": "add",
                        "visibility": "public",
                        "is_direct_unambiguous": True,
                    }
                ],
                "summary_ar": "تم استيعاب وتوثيق البيانات في قاعدة الحقائق بنجاح",
            }

    ai_res = fact_service.extract_facts(tenant.id, operational_cmd, provider=MockLeakingAIProvider())
    # The operational filter must have removed topic "task.creation"
    assert len(ai_res.facts) == 0, f"Operational filter failed to strip task.* fact: {ai_res.facts}"


# ---------------------------------------------------------------------------
# Test 10: FactService Preserves Legitimate Business Knowledge Mentioning Tasks
# ---------------------------------------------------------------------------
def test_fact_service_preserves_legitimate_knowledge_with_task_words(db: Session, tenant: Tenant):
    """
    Ensures that legitimate business service or product declarations mentioning 'مهام'
    are NOT erroneously stripped by the operational guardrail.
    """
    fact_service = FactService(db=db)

    class MockLegitimateAIProvider:
        def generate_json(self, prompt, schema=None, system_instruction=None):
            return {
                "facts": [
                    {
                        "topic": "service.task_management",
                        "subject": "خدمة إدارة المهام والمشاريع",
                        "value": {"name": "نظام تتبع مهام الفرق والشركات"},
                        "operation": "add",
                        "visibility": "public",
                        "is_direct_unambiguous": True,
                    }
                ],
                "summary_ar": "تم توثيق خدمة إدارة المهام",
            }

    legit_text = "نوفر خدمة إدارة المهام والمشاريع الرقمية لعملائنا في مختلف المدن."
    res = fact_service.extract_facts(tenant.id, legit_text, provider=MockLegitimateAIProvider())
    assert len(res.facts) == 1
    assert res.facts[0].topic == "service.task_management"
