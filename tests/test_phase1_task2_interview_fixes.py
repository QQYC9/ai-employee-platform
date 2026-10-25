"""
Test Suite: Phase 1 Task 2 - Adaptive Interview Coverage & Resilience Fixes
Verifies:
1. Fallback evaluator caps at partial (never covered/answered).
2. business_identity gating (requires company.identity fact), tone_voice mapping ("نفضل نبرة رسمية ومهنية"), and source_message_id persistence only on covered topics.
3. Model rate limit (429) or failure emits Arabic delay notice without guessing fallback.
"""
from uuid import uuid4
import pytest
from sqlalchemy import select

from packages.ai_providers.base import AIRateLimitError
from packages.core.database import SessionLocal
from packages.models.domain import Conversation, InterviewState, InterviewTopic, Message
from packages.models.tenant import Tenant
from packages.services.fact_service import ExtractedFactItem
from packages.services.interview_service import (
    InterviewService,
    ModelServiceError,
    ReplyCoverageEvaluation,
    TopicCoverageItem,
)


class FailingAIProvider:
    """Mock AI Provider that simulates rate-limit (429) or runtime failure."""

    def __init__(self, fail_with: str = "429"):
        self.fail_with = fail_with

    def generate_json(self, *args, **kwargs):
        if self.fail_with == "429":
            raise AIRateLimitError("HTTP 429: Rate limit exceeded")
        raise RuntimeError("Model upstream provider failure 500")

    def generate_text(self, *args, **kwargs):
        if self.fail_with == "429":
            raise AIRateLimitError("HTTP 429: Rate limit exceeded")
        raise RuntimeError("Model upstream provider failure 500")


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_fallback_evaluator_never_marks_answered(db_session):
    """Fallback evaluator caps matched topics at partial (coverage=0.5) and never marks covered."""
    svc = InterviewService(db_session)
    topic_pay = InterviewTopic(
        id=uuid4(),
        tenant_id=uuid4(),
        slug="ordering_payment",
        label="طرق الطلب والدفع المعتمدة",
        question="كيف يتم الدفع؟",
        status="unknown",
        criticality=4,
    )

    evaluation = svc.evaluate_reply_coverage(
        tenant_id=topic_pay.tenant_id,
        content="نوفر تحويل بنكي ودفع عند الاستلام",
        open_topics=[topic_pay],
        current_topic_slug="ordering_payment",
        ai_provider=None,  # Forces fallback evaluator
    )

    assert evaluation.decided_by == "fallback"
    pay_eval = next((e for e in evaluation.evaluations if e.slug == "ordering_payment"), None)
    assert pay_eval is not None
    # Must be partial, never covered
    assert pay_eval.status == "partial"
    assert pay_eval.coverage == 0.5


def test_business_identity_gating_tone_mapping_and_source_message_id(db_session):
    """
    Verifies:
    1. 'نفضل نبرة رسمية ومهنية' maps to tone_voice and NOT branches_hours.
    2. business_identity is covered ONLY when company.identity fact was extracted.
    3. source_message_id is assigned only to covered topics; uncovered topics remain None.
    """
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Test Tenant {uid}", slug=f"tenant-{uid}")
    db_session.add(tenant)
    db_session.flush()

    conv = Conversation(id=uuid4(), tenant_id=tenant.id)
    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="owner",
        content="نفضل نبرة رسمية ومهنية",
    )
    db_session.add_all([conv, msg])
    db_session.flush()

    svc = InterviewService(db_session)
    t_branches = InterviewTopic(
        tenant_id=tenant.id,
        slug="branches_hours",
        label="الفروع وساعات العمل",
        question="ما هي فروعكم وساعات العمل الرسمية؟",
        status="asked",
        criticality=3,
    )
    t_tone = InterviewTopic(
        tenant_id=tenant.id,
        slug="tone_voice",
        label="نبرة وأسلوب التحدث مع العملاء",
        question="ما هي النبرة المفضلة للتواصل؟",
        status="unknown",
        criticality=1,
    )
    t_identity = InterviewTopic(
        tenant_id=tenant.id,
        slug="identity",
        label="هوية المنشأة والاسم التجاري",
        question="ما هو الاسم التجاري الرسمي؟",
        status="asked",
        criticality=5,
    )
    db_session.add_all([t_branches, t_tone, t_identity])

    state = svc.get_or_create_state(tenant.id)
    state.stage = "interviewing"
    state.current_topic_slug = "branches_hours"
    db_session.flush()

    # Owner replies about tone while branches_hours was asked
    reply_text, handled = svc.process_interview_turn(
        tenant_id=tenant.id,
        message_id=msg.id,
        content=msg.content,
        ai_provider=None,
    )

    db_session.refresh(t_branches)
    db_session.refresh(t_tone)

    # branches_hours was NOT covered; its source_message_id must remain None
    assert t_branches.status in ("asked", "unknown")
    assert t_branches.source_message_id is None

    # tone_voice was matched; its source_message_id is set to msg.id
    assert t_tone.status == "partial"
    assert t_tone.source_message_id == msg.id

    # Verify identity gating: a fake model evaluation claiming covered without identity fact gets downgraded
    fake_eval = ReplyCoverageEvaluation(
        evaluations=[
            TopicCoverageItem(slug="identity", status="covered", coverage=1.0)
        ],
        extracted_facts=[],  # No company.identity fact extracted!
        decided_by="model",
    )
    state.current_topic_slug = "identity"
    db_session.flush()

    msg2 = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="owner",
        content="نحن ممتازون جداً",
    )
    db_session.add(msg2)
    db_session.flush()

    class ModelGatedProvider:
        def generate_json(self, *args, **kwargs):
            return fake_eval.model_dump()

    turn_reply, _ = svc.process_interview_turn(
        tenant_id=tenant.id,
        message_id=msg2.id,
        content=msg2.content,
        ai_provider=ModelGatedProvider(),
    )
    db_session.refresh(t_identity)
    # Gating prevented marking answered because no company.identity fact was extracted
    assert t_identity.status != "answered"


def test_model_failure_emits_delay_notice_without_guessing(db_session):
    """When AI provider hits HTTP 429 or fails, emits Arabic delay notice without semantic guessing."""
    uid = uuid4().hex[:6]
    tenant = Tenant(id=uuid4(), name=f"Test Tenant {uid}", slug=f"tenant-{uid}")
    db_session.add(tenant)
    db_session.flush()

    conv = Conversation(id=uuid4(), tenant_id=tenant.id)
    msg = Message(
        id=uuid4(),
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="owner",
        content="نبيع عسل سدر دوعني بسعر 100 ريال",
    )
    db_session.add_all([conv, msg])
    db_session.flush()

    svc = InterviewService(db_session)
    topic = InterviewTopic(
        tenant_id=tenant.id,
        slug="products_services_prices",
        label="المنتجات والخدمات",
        question="ما هي المنتجات؟",
        status="asked",
        criticality=5,
    )
    db_session.add(topic)

    state = svc.get_or_create_state(tenant.id)
    state.stage = "interviewing"
    state.current_topic_slug = "products_services_prices"
    db_session.flush()

    # 1. Test 429
    provider_429 = FailingAIProvider(fail_with="429")
    reply, handled = svc.process_interview_turn(
        tenant_id=tenant.id,
        message_id=msg.id,
        content=msg.content,
        ai_provider=provider_429,
    )
    assert handled is True
    assert "تأخير مؤقت" in reply or "ضغط" in reply
    db_session.refresh(topic)
    assert topic.status == "asked"  # Not guessed or advanced!

    # 2. Test 500 runtime failure
    provider_500 = FailingAIProvider(fail_with="500")
    reply2, handled2 = svc.process_interview_turn(
        tenant_id=tenant.id,
        message_id=msg.id,
        content=msg.content,
        ai_provider=provider_500,
    )
    assert handled2 is True
    assert "تأخير مؤقت" in reply2
    db_session.refresh(topic)
    assert topic.status == "asked"  # Still not guessed!
