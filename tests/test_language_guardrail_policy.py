"""
Tests for Language Guardrail Policy in ConversationalAgentEngine:
1. Arabic customer queries require pure Arabic replies (blocking stray Latin hallucinations).
2. English customer queries permit legitimate English replies without false-positive blocks.
3. Mixed queries permit Latin terms matching customer keywords or verified corpus, while blocking unrelated stray Latin words.
4. Commercial security guardrails (prices, unverified discounts, etc.) remain 100% active and enforced across all languages.
"""
from __future__ import annotations

import pytest
from uuid import uuid4
from sqlalchemy.orm import Session

from packages.models.tenant import Tenant
from packages.models.domain import Conversation, Customer, Message, Fact
from packages.context.builder import AgentContext, TaskContext
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.conversation_service import ConversationService


@pytest.fixture
def db(test_db_session: Session) -> Session:
    return test_db_session


@pytest.fixture
def mock_task() -> TaskContext:
    return TaskContext(
        task_id=uuid4(),
        agent_id=None,
        objective="Test interaction",
        title="Test",
        status="active",
        priority="normal",
    )


@pytest.fixture
def sample_tenant(db: Session) -> Tenant:
    t = Tenant(
        name="متجر التقنية المتقدمة",
        slug=f"tech-store-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def agent_engine(db: Session) -> ConversationalAgentEngine:
    return ConversationalAgentEngine(db=db)


def test_arabic_query_with_pure_arabic_reply_allowed(
    agent_engine: ConversationalAgentEngine, sample_tenant: Tenant, mock_task: TaskContext
):
    """1. Arabic customer queries with pure Arabic replies pass guardrails safely."""
    context = AgentContext(
        tenant_id=sample_tenant.id,
        task=mock_task,
        business={"identity": {"name": "متجر التقنية"}},
    )
    reply = "أهلاً بك، يسعدنا تقديم أفضل الخدمات والاستشارات الفنية لعملائنا الكرام."
    customer_query = "ما هي الخدمات المتوفرة لديكم؟"

    is_safe, reason = agent_engine._evaluate_reply_guardrails(
        reply_text=reply,
        agent_context=context,
        customer_query=customer_query,
    )
    assert is_safe is True
    assert reason is None


def test_arabic_query_with_stray_latin_word_blocked(
    agent_engine: ConversationalAgentEngine, sample_tenant: Tenant, mock_task: TaskContext
):
    """2. Arabic customer query with stray Latin hallucination is blocked."""
    context = AgentContext(
        tenant_id=sample_tenant.id,
        task=mock_task,
        business={"identity": {"name": "متجر التقنية"}},
    )
    reply = "مرحبًا بك عزيزي Customer Replay، يسعدنا تواصلك معنا لخدمتك."
    customer_query = "السلام عليكم ورحمة الله"

    is_safe, reason = agent_engine._evaluate_reply_guardrails(
        reply_text=reply,
        agent_context=context,
        customer_query=customer_query,
    )
    assert is_safe is False
    assert reason is not None
    assert "Stray English/Latin word 'Customer'" in reason


def test_english_query_with_english_reply_allowed(
    agent_engine: ConversationalAgentEngine, sample_tenant: Tenant, mock_task: TaskContext
):
    """3. English customer query receives legitimate English response without being blocked."""
    context = AgentContext(
        tenant_id=sample_tenant.id,
        task=mock_task,
        business={"identity": {"name": "Tech Store"}},
    )
    reply = "We are open Monday to Friday from 9 AM to 6 PM."
    customer_query = "What are your business hours?"

    is_safe, reason = agent_engine._evaluate_reply_guardrails(
        reply_text=reply,
        agent_context=context,
        customer_query=customer_query,
    )
    assert is_safe is True
    assert reason is None


def test_mixed_query_with_matching_latin_keyword_allowed(
    agent_engine: ConversationalAgentEngine, sample_tenant: Tenant, mock_task: TaskContext
):
    """4. Customer query with legitimate Latin keyword (e.g. 'API') allows that keyword in Arabic reply."""
    context = AgentContext(
        tenant_id=sample_tenant.id,
        task=mock_task,
        business={
            "identity": {"name": "متجر التقنية"},
            "services": {"api_integration": {"name": "الربط عبر API"}},
        },
    )
    customer_query = "هل المنصة تدعم الربط عبر API المباشر؟"
    reply = "نعم، تدعم المنصة الربط عبر API بشكل مباشر وآمن لجميع العمليات."

    is_safe, reason = agent_engine._evaluate_reply_guardrails(
        reply_text=reply,
        agent_context=context,
        customer_query=customer_query,
    )
    assert is_safe is True
    assert reason is None


def test_mixed_query_with_unrelated_stray_latin_blocked(
    agent_engine: ConversationalAgentEngine, sample_tenant: Tenant, mock_task: TaskContext
):
    """5. Mixed query allows matching keyword but blocks unrelated stray Latin words."""
    context = AgentContext(
        tenant_id=sample_tenant.id,
        task=mock_task,
        business={
            "identity": {"name": "متجر التقنية"},
            "services": {"api_integration": {"name": "الربط عبر API"}},
        },
    )
    customer_query = "هل المنصة تدعم الربط عبر API؟"
    # 'API' is in query, but 'SuperFast' is an unverified stray hallucination
    reply = "نعم، ندعم الربط عبر API مع ميزة SuperFast غير المعتمدة."

    is_safe, reason = agent_engine._evaluate_reply_guardrails(
        reply_text=reply,
        agent_context=context,
        customer_query=customer_query,
    )
    assert is_safe is False
    assert reason is not None
    assert "Stray English/Latin word 'SuperFast'" in reason


def test_english_query_with_unverified_price_still_blocked(
    agent_engine: ConversationalAgentEngine, sample_tenant: Tenant, mock_task: TaskContext
):
    """6. Commercial safety guardrails (prices) remain strictly active even in English queries."""
    context = AgentContext(
        tenant_id=sample_tenant.id,
        task=mock_task,
        business={
            "identity": {"name": "Tech Store"},
            "products": {
                "standard_plan": {"name": "Standard Plan", "price": 100.0, "unit": "SAR"}
            },
        },
    )
    customer_query = "What is the price of the enterprise plan?"
    # 9999 SAR is unverified hallucination
    reply = "The enterprise plan is priced at 9999 SAR."

    is_safe, reason = agent_engine._evaluate_reply_guardrails(
        reply_text=reply,
        agent_context=context,
        customer_query=customer_query,
    )
    assert is_safe is False
    assert reason is not None
    assert "Unverified price 9999.0" in reason
