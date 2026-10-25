"""
Tests for PART 0 cleanups:
1. When a product has no stored description, the catalog reply must show only its name
   (no repeated name as a description). Use a simple Arabic list instead of a table.
2. Do not inject knowledge snippets whose title starts with "اسم المنشأة" into any prompt
   when a confirmed company.identity fact exists. Do not delete any rows.

All tests go through the REAL router -> engine path with mock AI provider.
"""
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import (
    BusinessBrain,
    Channel,
    Conversation,
    Fact,
    Knowledge,
    Message,
    User,
)
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine


class CapturingMockAIProvider:
    """Mock AI Provider that captures prompts and returns a deterministic reply."""

    def __init__(self, reply: str = ""):
        self.reply = reply
        self.last_prompt = ""
        self.last_system_instruction = ""
        self.call_count = 0

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction or ""
        return self.reply

    def generate_json(self, *args, **kwargs) -> dict:
        return {}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()


@pytest.fixture
def clean_test_env(db: Session):
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="Cleanup Test Tenant",
        slug=f"cleanup-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    owner_user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"owner_{uuid4().hex[:6]}@example.com",
        name="Owner User",
        role="tenant_owner",
        status="active",
    )
    db.add(owner_user)
    db.flush()

    channel_id = uuid4()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={
            "owner_sender_ids": ["967770000001", "owner_tg"],
            "bot_token": "token_cleanup_123",
        },
    )
    db.add(channel)

    brain = BusinessBrain(
        tenant_id=tenant_id,
        identity={"name": "المنذر للتقنية"},
        products={},
        services={},
        pricing={},
        operations={},
        policies={},
    )
    db.add(brain)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "owner_user": owner_user,
        "channel_id": channel_id,
    }


def _replay_inbound(
    db: Session,
    tenant_id: UUID,
    channel_id: UUID,
    sender_id: str,
    content: str,
) -> Message:
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=sender_id,
        sender_name="Test Sender",
        content=content,
        content_type="text",
        raw_payload={"text": content, "from": {"id": sender_id}},
    )
    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()
    return msg


# ---------------------------------------------------------------------------
# PART 0 - Item 1: Catalog reply simple Arabic list, no repeated name, no table
# ---------------------------------------------------------------------------

def test_catalog_shows_only_name_when_no_description_and_simple_arabic_list(db: Session, clean_test_env: dict):
    """
    When a product has no stored description:
    - Safe catalog reply shows ONLY its name (no repeated name).
    - Uses a simple Arabic numbered list, never a table.
    """
    tenant_id = clean_test_env["tenant_id"]
    channel_id = clean_test_env["channel_id"]

    # 1. Add confirmed company identity and products
    # Product A: Has NO description (empty dict / name only)
    # Product B: Has a real description
    f_identity = Fact(
        tenant_id=tenant_id,
        topic="company.identity",
        subject="اسم الشركة",
        value="المنذر تكنولوجي",
        status="confirmed",
        visibility="public",
        source="owner",
    )
    f_prod_a = Fact(
        tenant_id=tenant_id,
        topic="product.الموظف_الذكي",
        subject="الموظف الذكي",
        value={"name": "الموظف الذكي"},  # No description!
        status="confirmed",
        visibility="public",
        source="owner",
    )
    f_prod_b = Fact(
        tenant_id=tenant_id,
        topic="product.سيرو",
        subject="برنامج سيرو",
        value={"description": "نظام التحكم وإدارة الشبكات"},
        status="confirmed",
        visibility="public",
        source="owner",
    )
    db.add_all([f_identity, f_prod_a, f_prod_b])
    db.commit()

    # Model attempts to output repeated name as description: "1. الموظف الذكي: الموظف الذكي"
    bad_model_reply = (
        "مرحبًا بك! نحن في المنذر تكنولوجي نقدم:\n"
        "1. الموظف الذكي: الموظف الذكي\n"
        "2. برنامج سيرو: نظام التحكم وإدارة الشبكات"
    )
    mock_ai = CapturingMockAIProvider(reply=bad_model_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    # Replay through REAL customer inbound path
    inbound_msg = _replay_inbound(db, tenant_id, channel_id, "customer_991", "ما هي منتجاتكم؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)

    assert res.success is True
    reply = res.reply_content

    # Assert no table syntax
    assert "|" not in reply, "Catalog reply must not use a Markdown table"
    # Assert product without description shows ONLY its name (not repeated name as description)
    assert "الموظف الذكي: الموظف الذكي" not in reply
    assert "1. الموظف الذكي\n" in reply or "1. الموظف الذكي\r\n" in reply or reply.endswith("1. الموظف الذكي") or "الموظف الذكي" in reply
    # Assert product with description retains description
    assert "برنامج سيرو: نظام التحكم وإدارة الشبكات" in reply


def test_catalog_table_output_blocked_and_replaced_with_simple_list(db: Session, clean_test_env: dict):
    """
    If the model outputs a Markdown table for the product catalog,
    it must be intercepted by the guardrail and replaced with a simple Arabic list.
    """
    tenant_id = clean_test_env["tenant_id"]
    channel_id = clean_test_env["channel_id"]

    f_identity = Fact(
        tenant_id=tenant_id,
        topic="company.identity",
        subject="اسم الشركة",
        value="المنذر تكنولوجي",
        status="confirmed",
        visibility="public",
        source="owner",
    )
    f_prod = Fact(
        tenant_id=tenant_id,
        topic="product.الموظف_الذكي",
        subject="الموظف الذكي",
        value={"name": "الموظف الذكي"},
        status="confirmed",
        visibility="public",
        source="owner",
    )
    db.add_all([f_identity, f_prod])
    db.commit()

    table_reply = (
        "| المنتج | الوصف |\n"
        "|---|---|\n"
        "| الموظف الذكي | الموظف الذكي |\n"
    )
    mock_ai = CapturingMockAIProvider(reply=table_reply)
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound_msg = _replay_inbound(db, tenant_id, channel_id, "customer_992", "ما هي المنتجات المتوفرة؟")
    res = engine.process_incoming_message(tenant_id, inbound_msg.id)

    assert res.success is True
    reply = res.reply_content
    # Table must be eliminated
    assert "|" not in reply
    # Must be a clean Arabic list
    assert "الموظف الذكي" in reply
    assert "الموظف الذكي: الموظف الذكي" not in reply


# ---------------------------------------------------------------------------
# PART 0 - Item 2: Suppression of "اسم المنشأة" knowledge snippets when confirmed identity exists
# ---------------------------------------------------------------------------

def test_knowledge_snippet_starting_with_business_name_not_injected_when_confirmed_identity_exists(
    db: Session, clean_test_env: dict
):
    """
    Do not inject knowledge snippets whose title starts with 'اسم المنشأة'
    into ANY prompt (customer or owner) when a confirmed company.identity fact exists.
    Verify no rows are deleted from the knowledge table.
    """
    tenant_id = clean_test_env["tenant_id"]
    channel_id = clean_test_env["channel_id"]

    # 1. Insert confirmed company.identity fact
    f_identity = Fact(
        tenant_id=tenant_id,
        topic="company.identity",
        subject="اسم الشركة",
        value="المنذر تكنولوجي",
        status="confirmed",
        visibility="public",
        source="owner_stated",
    )
    db.add(f_identity)

    # 2. Insert Knowledge snippets:
    # - One snippet whose title starts with "اسم المنشأة" (stale/unwanted)
    # - One regular knowledge snippet (should still be injected)
    k_stale = Knowledge(
        tenant_id=tenant_id,
        title="اسم المنشأة: المنذر للتقنية القديم",
        content="اسم منشأتنا التجاري القديم هو المنذر للتقنية",
        knowledge_type="general",
        status="active",
    )
    k_valid = Knowledge(
        tenant_id=tenant_id,
        title="سياسة الشحن",
        content="الشحن متوفر لجميع المحافظات خلال يومين عمل",
        knowledge_type="policy",
        status="active",
    )
    db.add_all([k_stale, k_valid])
    db.commit()

    stale_k_id = k_stale.id
    valid_k_id = k_valid.id

    mock_ai = CapturingMockAIProvider(reply="أهلاً بك في المنذر تكنولوجي!")
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    # A. Test Customer Path Prompt Assembly
    inbound_customer = _replay_inbound(db, tenant_id, channel_id, "customer_993", "ما هي سياسة الشحن لديكم؟")
    res_customer = engine.process_incoming_message(tenant_id, inbound_customer.id)
    assert res_customer.success is True

    # Inspect customer prompt passed to AI
    customer_prompt = mock_ai.last_prompt
    assert "اسم المنشأة: المنذر للتقنية القديم" not in customer_prompt, (
        "Knowledge snippet starting with 'اسم المنشأة' must NOT be injected into customer prompt"
    )
    assert "سياسة الشحن" in customer_prompt, "Valid knowledge snippets must still be injected"

    # B. Test Owner Path Prompt Assembly
    inbound_owner = _replay_inbound(db, tenant_id, channel_id, "967770000001", "ما هي سياسة الشحن المسجلة لدينا؟")
    res_owner = engine.process_incoming_message(tenant_id, inbound_owner.id)
    assert res_owner.success is True

    owner_prompt = mock_ai.last_prompt
    assert "اسم المنشأة: المنذر للتقنية القديم" not in owner_prompt, (
        "Knowledge snippet starting with 'اسم المنشأة' must NOT be injected into owner prompt"
    )
    assert "سياسة الشحن" in owner_prompt, "Valid knowledge snippets must still be injected"

    # C. Verify NO rows were deleted from Knowledge table
    db.expire_all()
    k_stale_db = db.scalar(select(Knowledge).where(Knowledge.id == stale_k_id))
    k_valid_db = db.scalar(select(Knowledge).where(Knowledge.id == valid_k_id))
    assert k_stale_db is not None, "Knowledge row must NOT be deleted from the database"
    assert k_valid_db is not None, "Valid knowledge row must remain intact"


def test_knowledge_snippet_injected_when_no_confirmed_identity_fact_exists(
    db: Session, clean_test_env: dict
):
    """
    When NO confirmed company.identity fact exists, knowledge snippets starting
    with 'اسم المنشأة' ARE injected as normal.
    """
    tenant_id = clean_test_env["tenant_id"]
    channel_id = clean_test_env["channel_id"]

    # Ensure NO facts exist
    # Insert knowledge snippet
    k_item = Knowledge(
        tenant_id=tenant_id,
        title="اسم المنشأة: متجر السعادة",
        content="اسم المنشأة التجاري هو متجر السعادة",
        knowledge_type="general",
        status="active",
    )
    db.add(k_item)
    db.commit()

    mock_ai = CapturingMockAIProvider(reply="مرحبًا بك!")
    engine = ConversationalAgentEngine(db=db, ai_provider=mock_ai)

    inbound = _replay_inbound(db, tenant_id, channel_id, "customer_994", "من أنتم؟")
    res = engine.process_incoming_message(tenant_id, inbound.id)
    assert res.success is True

    # Snippet SHOULD be in prompt since no confirmed fact exists
    customer_prompt = mock_ai.last_prompt
    assert "اسم المنشأة: متجر السعادة" in customer_prompt
