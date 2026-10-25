"""
Test Suite: Link Code Security, Single-Use Invalidation, Rate Limiting & Tenant Isolation.
Verifies Phase 3.2 Addendum X1 and Problem C requirements.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.core.database import SessionLocal
from packages.models.domain import AuditEvent, Channel, Message, TenantLinkCode, User
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.interview_service import InterviewService
from packages.services.link_code_service import LinkCodeService, sender_link_rate_limiter


class MockAIProvider:
    """Mock AI Provider for deterministic real-path testing."""

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

    def generate_json(self, prompt: str, schema: type = None, **kwargs) -> dict:
        self.call_count += 1
        return {}


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    sender_link_rate_limiter.reset()
    yield
    sender_link_rate_limiter.reset()

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _setup_tenant_and_channel(
    db: Session,
    name: str = "Test Security Tenant",
    owner_sender_id: str = "967770000001",
) -> dict:
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=f"sec-tenant-{uuid4().hex[:8]}",
        status="active",
        interview_required=False,
        interview_threshold=80.0,
    )
    db.add(tenant)
    db.flush()

    owner_user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=f"owner_{uuid4().hex[:8]}@example.com",
        password_hash="hashed_pw_dummy",
        name=f"Owner of {name}",
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
            "bot_token": "token_sec_123",
            "owner_identifiers": [owner_sender_id],
            "owner_sender_ids": [owner_sender_id],
        },
    )
    db.add(channel)
    db.commit()

    return {
        "tenant_id": tenant_id,
        "channel_id": channel_id,
        "owner_user": owner_user,
        "owner_sender_id": owner_sender_id,
    }


def test_valid_link_code_links_owner_and_starts_interview(db: Session):
    """A valid, unexpired code links the sender as channel owner and triggers the adaptive interview."""
    setup = _setup_tenant_and_channel(db, name="منشأة التقنية")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    # Verify link record created with hash and not raw
    assert link_rec.is_used is False
    assert raw_code not in link_rec.code_hash
    assert link_rec.code_hash == LinkCodeService.hash_code(raw_code)

    new_sender = "967778881111"
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=new_sender,
        sender_name="New Owner",
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={"text": f"/link {raw_code}"},
    )

    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    # 1. Channel config must have sender added to owner_identifiers
    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert new_sender in (channel.config.get("owner_identifiers") or [])

    # 2. Database link code record must be marked used
    db.refresh(link_rec)
    assert link_rec.is_used is True
    assert link_rec.used_by_sender_id == new_sender
    assert link_rec.used_at is not None

    # 3. Process through engine
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True
    assert "تم ربط حسابك كمالك رسمي للمنشأة بنجاح" in res.reply_content
    assert "ما هو اسمك الكريم؟" in res.reply_content

    # 4. Audit trail verified
    audit_event = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "link_code_used",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit_event is not None
    assert audit_event.event_metadata["sender_id"] == new_sender


def test_wrong_link_code_rejected_and_neutral_reply(db: Session):
    """An invalid code fails verification, increments attempts, and returns a neutral reply."""
    setup = _setup_tenant_and_channel(db, name="منشأة الأمل")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    attacker_sender = "967779990001"
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=attacker_sender,
        sender_name="Unknown User",
        content="/link LINK-WRONG-CODE",
        content_type="text",
        raw_payload={"text": "/link LINK-WRONG-CODE"},
    )

    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    # Sender must NOT be elevated to owner
    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert attacker_sender not in (channel.config.get("owner_identifiers") or [])

    # Link record must NOT be used, but attempt count incremented
    db.refresh(link_rec)
    assert link_rec.is_used is False
    assert link_rec.attempts_count == 1

    # Engine must return neutral failure message
    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True
    assert "تعذر إتمام عملية الربط" in res.reply_content
    assert "ما هو اسمك الكريم؟" not in res.reply_content


def test_expired_link_code_rejected(db: Session):
    """An expired code fails verification and returns neutral response."""
    setup = _setup_tenant_and_channel(db, name="منشأة النور")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id, expires_in_hours=1)
    # Manually expire the code
    link_rec.expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.add(link_rec)
    db.commit()

    expired_sender = "967779990002"
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=expired_sender,
        sender_name="Late User",
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={"text": f"/link {raw_code}"},
    )

    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert expired_sender not in (channel.config.get("owner_identifiers") or [])

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True
    assert "تعذر إتمام عملية الربط" in res.reply_content


def test_reused_link_code_rejected(db: Session):
    """A link code can only be used ONCE. A second attempt fails."""
    setup = _setup_tenant_and_channel(db, name="منشأة البركة")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    channel_svc = ChannelService(db)

    # First attempt: SUCCESS
    inbound1 = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id="967778881111",
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={},
    )
    channel_svc.process_inbound_message(inbound1)
    db.commit()

    # Second attempt with same code: REJECTED
    inbound2 = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id="967778882222",
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={},
    )
    msg2 = channel_svc.process_inbound_message(inbound2)
    db.commit()

    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert "967778882222" not in (channel.config.get("owner_identifiers") or [])

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    res2 = engine.process_incoming_message(tenant_id, msg2.id)
    assert res2.success is True
    assert "تعذر إتمام عملية الربط" in res2.reply_content


def test_tenant_isolation_code_cross_tenant_fails(db: Session):
    """A link code generated for Tenant A cannot be used on Tenant B's channel."""
    tenant_a = _setup_tenant_and_channel(db, name="منشأة أ")
    tenant_b = _setup_tenant_and_channel(db, name="منشأة ب")

    link_svc = LinkCodeService(db)
    raw_code_a, _ = link_svc.generate_link_code(tenant_a["tenant_id"], tenant_a["channel_id"])
    db.commit()

    # Attacker tries to use code_a on Tenant B's channel
    inbound_b = InboundMessage(
        tenant_id=tenant_b["tenant_id"],
        channel_id=tenant_b["channel_id"],
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id="967779995555",
        content=f"/link {raw_code_a}",
        content_type="text",
        raw_payload={},
    )

    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound_b)
    db.commit()

    # Must NOT elevate on Tenant B
    channel_b = db.scalar(select(Channel).where(Channel.id == tenant_b["channel_id"]))
    assert "967779995555" not in (channel_b.config.get("owner_identifiers") or [])

    # Tenant A channel must also remain unaffected
    channel_a = db.scalar(select(Channel).where(Channel.id == tenant_a["channel_id"]))
    assert "967779995555" not in (channel_a.config.get("owner_identifiers") or [])


def test_rate_limiting_per_sender_blocks_attacker_and_keeps_code_valid_for_owner(db: Session):
    """
    Phase 3.2 Design Fix (Item 3):
    An attacker sending 5 wrong guesses is temporarily blocked via exponential backoff.
    Crucially, the legitimate owner's code remains completely VALID and can be consumed
    immediately from the owner's chat, preventing DoS lockout.
    """
    setup = _setup_tenant_and_channel(db, name="منشأة الحماية")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    channel_svc = ChannelService(db)
    attacker_sender = "attacker_967770001111"

    # Attacker makes 5 failed attempts from their sender_id
    for i in range(5):
        inb = InboundMessage(
            tenant_id=tenant_id,
            channel_id=channel_id,
            channel_type="telegram",
            external_message_id=f"msg_guess_{i}_{uuid4().hex[:6]}",
            sender_id=attacker_sender,
            content=f"/link WRONG-CODE-{i}",
            content_type="text",
            raw_payload={},
        )
        msg_guess = channel_svc.process_inbound_message(inb)
        db.commit()

    # Attacker is now temporarily blocked on 6th attempt
    inb_attacker_blocked = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_guess_6_{uuid4().hex[:6]}",
        sender_id=attacker_sender,
        content=f"/link WRONG-CODE-6",
        content_type="text",
        raw_payload={},
    )
    msg_blocked = channel_svc.process_inbound_message(inb_attacker_blocked)
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=MockAIProvider())
    res_blocked = engine.process_incoming_message(tenant_id, msg_blocked.id)
    assert res_blocked.success is True
    assert "تم تجاوز الحد المسموح" in res_blocked.reply_content

    # Verify link code itself was NOT locked or marked used/revoked
    db.refresh(link_rec)
    assert link_rec.is_used is False
    assert link_rec.is_revoked is False

    # Legitimate owner sends the valid link code from their own sender_id
    owner_sender = "owner_967778887777"
    inb_owner = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_owner_{uuid4().hex[:6]}",
        sender_id=owner_sender,
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={"text": f"/link {raw_code}"},
    )
    msg_owner = channel_svc.process_inbound_message(inb_owner)
    db.commit()

    # Owner is successfully linked!
    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert owner_sender in (channel.config.get("owner_identifiers") or [])
    assert attacker_sender not in (channel.config.get("owner_identifiers") or [])

    db.refresh(link_rec)
    assert link_rec.is_used is True
    assert link_rec.used_by_sender_id == owner_sender

    res_owner = engine.process_incoming_message(tenant_id, msg_owner.id)
    assert res_owner.success is True
    assert "تم ربط حسابك كمالك رسمي للمنشأة بنجاح" in res_owner.reply_content


def test_customer_random_message_never_treated_as_owner(db: Session):
    """Regular customer chat messages are never treated as owner link codes."""
    setup = _setup_tenant_and_channel(db, name="منشأة التجارة")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    customer_sender = "967711223344"
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:10]}",
        sender_id=customer_sender,
        sender_name="Customer User",
        content="السلام عليكم، بكم سعر العسل الدوعني؟",
        content_type="text",
        raw_payload={"text": "السلام عليكم، بكم سعر العسل الدوعني؟"},
    )

    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    # Message must be sender_type="customer"
    assert msg.sender_type == "customer"
    assert (msg.metadata_json or {}).get("is_owner") is False
    assert (msg.metadata_json or {}).get("link_code_failure") is None

    # Channel owner config must NOT be modified
    channel = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert customer_sender not in (channel.config.get("owner_identifiers") or [])


def test_link_code_regeneration_revokes_old_code(db: Session):
    """Generating a new link code revokes previously active ones."""
    setup = _setup_tenant_and_channel(db, name="منشأة التجديد")
    tenant_id = setup["tenant_id"]
    channel_id = setup["channel_id"]

    link_svc = LinkCodeService(db)
    raw_code_1, rec_1 = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    # Regenerate
    raw_code_2, rec_2 = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    db.refresh(rec_1)
    db.refresh(rec_2)
    assert rec_1.is_revoked is True
    assert rec_2.is_revoked is False

    # Attempting old code must fail
    success, reason, _ = link_svc.verify_and_consume_code(
        tenant_id=tenant_id,
        channel_id=channel_id,
        sender_id="967770001111",
        candidate_code=raw_code_1,
    )
    assert success is False
    assert reason == "revoked"

    # Attempting new code must succeed
    success2, reason2, _ = link_svc.verify_and_consume_code(
        tenant_id=tenant_id,
        channel_id=channel_id,
        sender_id="967770001111",
        candidate_code=raw_code_2,
    )
    assert success2 is True
    assert reason2 == "success"
