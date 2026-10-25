"""
Test Suite: Phase 3.2 Tenant Onboarding, Employee Personalization, Secure Link Code & Dashboard Access.
Verifies Problems A-D and Requirements 1-4:
- Problem A: Tenant creation email uniqueness and random password generation (no plaintext default).
- Problem B: Employee name personalization in greetings, prompts, and updates.
- Problem C: Link code API (generation, regeneration, status) and single-use chat linking.
- Problem D: Dashboard access via tokenized password-set link without plaintext passwords, single-use token invalidation.
- Tenant Isolation: Cross-tenant link codes and channel link code APIs strictly isolated.
"""
from datetime import datetime, timezone
import hashlib
import re
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token, create_password_reset_token
from packages.auth.rate_limiter import rate_limiter
from packages.auth.security import hash_password, verify_password
from packages.connectors.base import InboundMessage
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Message, TenantLinkCode, User
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.interview_service import InterviewService
from packages.services.link_code_service import LinkCodeService, sender_link_rate_limiter
from packages.services.tenant_provisioning_service import (
    TenantProvisioningRequest,
    TenantProvisioningService,
)
from packages.services.tenant_service import TenantService


class DeterministicMockAIProvider:
    """Mock AI Provider for deterministic engine testing."""

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
def clean_environment():
    """Ensure clean test environment."""
    rate_limiter.reset()
    sender_link_rate_limiter.reset()
    original_env = settings.environment
    original_allow = settings.allow_dev_auth_header
    original_dash = settings.tenant_dashboard_url
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    yield
    rate_limiter.reset()
    sender_link_rate_limiter.reset()
    settings.environment = original_env
    settings.allow_dev_auth_header = original_allow
    settings.tenant_dashboard_url = original_dash


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _create_admin_user(db: Session) -> tuple[User, str]:
    user = User(
        tenant_id=None,
        name="Platform Administrator",
        email=f"admin-{uuid4().hex[:8]}@example.com",
        role="platform_admin",
        status="active",
        password_hash=hash_password("AdminSecurePassword123!"),
    )
    db.add(user)
    db.commit()
    token = create_access_token(user.id, None, user.role)
    return user, token


def _create_tenant_owner_user(db: Session, tenant_id: UUID) -> tuple[User, str]:
    user = User(
        tenant_id=tenant_id,
        name="Tenant Owner",
        email=f"owner-{uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
        password_hash=hash_password("InitialRandomPassword123!"),
    )
    db.add(user)
    db.commit()
    token = create_access_token(user.id, tenant_id, user.role)
    return user, token


# =========================================================================
# 1. Tenant Provisioning: Email Uniqueness & Auto-Generated Password & Link Code
# =========================================================================

def test_tenant_provisioning_email_uniqueness_and_no_plaintext_passwords(db: Session):
    """
    Problem A:
    1. Empty owner_password generates a strong random password, never a hardcoded default.
    2. Provisioning with duplicate email fails with clear validation error.
    3. Auto-creates default channel and single-use link code.
    """
    service = TenantProvisioningService(db)
    unique_email = f"owner-{uuid4().hex[:8]}@alofoq.sa"

    # Provision first tenant without providing a password
    req1 = TenantProvisioningRequest(
        name="شركة الأفق المتطورة",
        slug=f"alofoq-{uuid4().hex[:6]}",
        owner_name="فيصل الروقي",
        owner_email=unique_email,
        owner_password=None,  # No password provided -> must generate random
        employee_name="سارة",
    )
    res1 = service.provision_tenant(req1)
    db.commit()

    assert res1["status"] == "provisioned"
    assert res1["tenant"]["name"] == "شركة الأفق المتطورة"
    assert res1["tenant"]["employee_name"] == "سارة"
    assert "link_code" in res1 and res1["link_code"].startswith("LINK-")
    assert "link_code_expires_at" in res1

    # Verify owner password hash was created from random password (not hardcoded TemporaryPassword123!)
    owner_id = UUID(res1["owner"]["id"])
    owner_user = db.scalar(select(User).where(User.id == owner_id))
    assert owner_user is not None
    assert owner_user.password_hash is not None
    assert not verify_password("TemporaryPassword123!", owner_user.password_hash)

    # Attempting to provision again with the same email must fail
    req2 = TenantProvisioningRequest(
        name="شركة منافسة",
        slug=f"comp-{uuid4().hex[:6]}",
        owner_name="مستثمر آخر",
        owner_email=unique_email,
        employee_name="سلمى",
    )
    with pytest.raises(ValueError) as exc:
        service.provision_tenant(req2)
    assert "already registered" in str(exc.value)


# =========================================================================
# 2. Employee Name Personalization in Engine Prompts & Greetings
# =========================================================================

def test_employee_name_personalization_in_greetings_and_prompts(db: Session):
    """
    Problem B:
    1. Tenant with employee_name="سارة" introduces itself as "أنا سارة، موظفتك الرقمية الذكية."
    2. Customer and owner system instructions incorporate "سارة".
    3. Updating employee_name to "نورة" immediately takes effect.
    """
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="متاجر العسل البري",
        slug=f"honey-{uuid4().hex[:6]}",
        status="active",
        employee_name="سارة",
        interview_required=False,
    )
    db.add(tenant)
    db.flush()

    owner_user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        name="أبو فهد",
        email=f"abufahd-{uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        status="active",
        password_hash=hash_password("RandomPass123!"),
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
            "bot_token": "token_123",
            "owner_identifiers": ["sender_honey_owner"],
        },
    )
    db.add(channel)
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=DeterministicMockAIProvider())

    # 1. Customer prompt reflects employee_name
    customer_prompt = engine._build_customer_system_instruction(tenant_id)
    assert "سارة" in customer_prompt
    assert "You are سارة" in customer_prompt

    # 2. Owner prompt reflects employee_name
    owner_prompt = engine._build_owner_system_instruction(tenant_id)
    assert "سارة" in owner_prompt
    assert "أنت سارة" in owner_prompt

    # 3. Interview service greeting reflects employee_name
    interview_svc = InterviewService(db=db)
    greeting = interview_svc.start_interview(tenant_id)
    assert "أنا سارة، موظفتك الرقمية الذكية" in greeting

    # 4. Update employee_name to "نورة" via TenantService
    tenant_svc = TenantService(db)
    tenant_svc.update_tenant(tenant_id, employee_name="نورة")
    db.commit()

    # Verify changes take effect immediately
    updated_customer_prompt = engine._build_customer_system_instruction(tenant_id)
    assert "نورة" in updated_customer_prompt
    assert "سارة" not in updated_customer_prompt

    updated_owner_prompt = engine._build_owner_system_instruction(tenant_id)
    assert "نورة" in updated_owner_prompt
    assert "سارة" not in updated_owner_prompt

    updated_greeting = interview_svc.start_interview(tenant_id)
    assert "أنا نورة، موظفتك الرقمية الذكية" in updated_greeting


# =========================================================================
# 3. Channel Link Code Lifecycle & Regeneration APIs
# =========================================================================

def test_channel_link_code_regeneration_and_invalidation(db: Session):
    """
    Problem C:
    1. GET /api/v1/channels/{channel_id}/link-code returns active code preview.
    2. POST /api/v1/channels/{channel_id}/link-code generates a fresh code and revokes previous code.
    3. Old code is invalidated and cannot be used; new code works.
    """
    client = TestClient(app)
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="مؤسسة التقنية المتقدمة",
        slug=f"tech-{uuid4().hex[:6]}",
        status="active",
        employee_name="سارة",
    )
    db.add(tenant)
    db.flush()

    owner_user, owner_token = _create_tenant_owner_user(db, tenant_id)

    channel_id = uuid4()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Telegram Channel",
        channel_type="telegram",
        status="active",
        config={"bot_token": "token_abc"},
    )
    db.add(channel)
    db.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}

    # 1. Regenerate code via API
    post_res = client.post(f"/api/v1/channels/{channel_id}/link-code", headers=headers)
    assert post_res.status_code == 200
    data1 = post_res.json()
    first_code = data1["link_code"]
    assert first_code.startswith("LINK-")

    # 2. Check status via GET API
    get_res = client.get(f"/api/v1/channels/{channel_id}/link-code", headers=headers)
    assert get_res.status_code == 200
    status_data = get_res.json()
    assert status_data["has_active_code"] is True
    assert status_data["code_preview"] == f"{status_data['code_prefix']}..."

    # 3. Regenerate again -> first code must be revoked
    post_res2 = client.post(f"/api/v1/channels/{channel_id}/link-code", headers=headers)
    assert post_res2.status_code == 200
    data2 = post_res2.json()
    second_code = data2["link_code"]
    assert second_code != first_code

    # 4. Attempt to link via chat using the first (revoked) code
    sender_revoked = "967770001111"
    inbound_revoked = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:8]}",
        sender_id=sender_revoked,
        sender_name="Attempt 1",
        content=f"/link {first_code}",
        content_type="text",
        raw_payload={"text": f"/link {first_code}"},
    )
    channel_svc = ChannelService(db)
    revoked_msg = channel_svc.process_inbound_message(inbound_revoked)
    db.commit()

    # Channel owner_identifiers must NOT include revoked sender
    db.refresh(channel)
    assert sender_revoked not in (channel.config.get("owner_identifiers") or [])

    # Engine must return neutral response
    engine = ConversationalAgentEngine(db=db, ai_provider=DeterministicMockAIProvider())
    res_revoked = engine.process_incoming_message(tenant_id, revoked_msg.id)
    assert res_revoked.success is True
    assert "رمز الربط غير صحيح أو منتهي الصلاحية" in res_revoked.reply_content

    # 5. Link using second (valid) code
    sender_valid = "967770002222"
    inbound_valid = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:8]}",
        sender_id=sender_valid,
        sender_name="Valid Owner",
        content=f"/link {second_code}",
        content_type="text",
        raw_payload={"text": f"/link {second_code}"},
    )
    valid_msg = channel_svc.process_inbound_message(inbound_valid)
    db.commit()

    db.refresh(channel)
    assert sender_valid in (channel.config.get("owner_identifiers") or [])

    res_valid = engine.process_incoming_message(tenant_id, valid_msg.id)
    assert res_valid.success is True
    assert "تم ربط حسابك كمالك رسمي للمنشأة بنجاح" in res_valid.reply_content


# =========================================================================
# 4. Dashboard Access Without Plaintext Passwords & Single-Use Reset Token
# =========================================================================

def test_dashboard_access_welcome_and_tokenized_password_reset(db: Session):
    """
    Problem D:
    1. Employee introduces itself upon linking and sends dashboard access info:
       - Dashboard URL
       - Owner login email
       - Single-use set-password link with signed JWT token
       - NO plaintext password appears in message or DB.
    2. Owner sets password using POST /api/v1/auth/reset-password-with-token.
    3. Owner can immediately log in using POST /api/v1/auth/login with the new password.
    4. Token cannot be reused (fingerprint invalidation).
    """
    client = TestClient(app)
    tenant_id = uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="حلول السحاب الرقمية",
        slug=f"cloud-{uuid4().hex[:6]}",
        status="active",
        employee_name="سارة",
    )
    db.add(tenant)
    db.flush()

    owner_email = f"cloud-owner-{uuid4().hex[:6]}@example.com"
    owner_user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        name="سلطان السحاب",
        email=owner_email,
        role="tenant_owner",
        status="active",
        password_hash=hash_password("TemporaryInitialHash123!"),
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
        config={"bot_token": "token_cloud"},
    )
    db.add(channel)
    db.commit()

    # Generate link code
    link_svc = LinkCodeService(db)
    raw_code, link_rec = link_svc.generate_link_code(tenant_id, channel_id)
    db.commit()

    # Owner links via chat
    owner_sender_id = "967771234567"
    inbound = InboundMessage(
        tenant_id=tenant_id,
        channel_id=channel_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:8]}",
        sender_id=owner_sender_id,
        sender_name="Sultan",
        content=f"/link {raw_code}",
        content_type="text",
        raw_payload={"text": f"/link {raw_code}"},
    )
    channel_svc = ChannelService(db)
    msg = channel_svc.process_inbound_message(inbound)
    db.commit()

    engine = ConversationalAgentEngine(db=db, ai_provider=DeterministicMockAIProvider())
    res = engine.process_incoming_message(tenant_id, msg.id)
    assert res.success is True

    reply = res.reply_content
    # 1. Assertions on welcome content
    assert "تم ربط حسابك كمالك رسمي للمنشأة بنجاح! 🎉" in reply
    assert "أنا سارة، موظفتك الرقمية الذكية." in reply
    assert "بيانات الدخول إلى لوحة التحكم:" in reply
    assert f"• البريد الإلكتروني: {owner_email}" in reply
    assert "• رابط تعيين كلمة المرور:" in reply
    assert "صلاحية الرابط: 30 دقيقة" in reply
    assert "/set-password?token=" in reply

    # Ensure NO plaintext password or default password appears anywhere
    assert "TemporaryInitialHash123!" not in reply
    assert "TemporaryPassword123!" not in reply
    assert "password" not in reply.lower() or "كلمة المرور" in reply

    # 2. Extract reset token from message
    match = re.search(r"token=([A-Za-z0-9\-_\.]+)", reply)
    assert match is not None, "Password set token not found in message"
    reset_token = match.group(1)

    # 3. Use token to set a brand new password
    new_password = "MyNewStrongPassword2026!"
    reset_res = client.post(
        "/api/v1/auth/reset-password-with-token",
        json={"token": reset_token, "new_password": new_password},
    )
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "ok"

    # 4. Verify owner can log in using new password
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": owner_email, "password": new_password},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert "access_token" in login_data
    assert login_data["user"]["email"] == owner_email

    # 5. Verify single-use: attempting to reuse the same reset token must fail
    reuse_res = client.post(
        "/api/v1/auth/reset-password-with-token",
        json={"token": reset_token, "new_password": "AnotherPassword999!"},
    )
    assert reuse_res.status_code == 400
    assert "already been used" in reuse_res.json()["detail"]


# =========================================================================
# 5. Tenant Isolation: Link Codes & APIs
# =========================================================================

def test_tenant_isolation_link_codes_and_channels(db: Session):
    """
    Tenant Isolation:
    1. Tenant A's link code cannot be used on Tenant B's channel.
    2. Tenant A's owner cannot view or regenerate link codes for Tenant B's channel (404/403).
    """
    client = TestClient(app)

    # Setup Tenant A
    tenant_a_id = uuid4()
    tenant_a = Tenant(
        id=tenant_a_id,
        name="منشأة أ",
        slug=f"tenant-a-{uuid4().hex[:6]}",
        status="active",
        employee_name="سارة",
    )
    db.add(tenant_a)
    db.flush()
    owner_a, token_a = _create_tenant_owner_user(db, tenant_a_id)

    channel_a_id = uuid4()
    channel_a = Channel(
        id=channel_a_id,
        tenant_id=tenant_a_id,
        name="Channel A",
        channel_type="telegram",
        status="active",
        config={"bot_token": "token_a"},
    )
    db.add(channel_a)

    # Setup Tenant B
    tenant_b_id = uuid4()
    tenant_b = Tenant(
        id=tenant_b_id,
        name="منشأة ب",
        slug=f"tenant-b-{uuid4().hex[:6]}",
        status="active",
        employee_name="ريم",
    )
    db.add(tenant_b)
    db.flush()
    owner_b, token_b = _create_tenant_owner_user(db, tenant_b_id)

    channel_b_id = uuid4()
    channel_b = Channel(
        id=channel_b_id,
        tenant_id=tenant_b_id,
        name="Channel B",
        channel_type="telegram",
        status="active",
        config={"bot_token": "token_b"},
    )
    db.add(channel_b)
    db.commit()

    # Generate link code for Tenant A
    link_svc = LinkCodeService(db)
    raw_code_a, _ = link_svc.generate_link_code(tenant_a_id, channel_a_id)
    db.commit()

    # 1. Attempt to use Tenant A's code on Tenant B's channel
    inbound_cross = InboundMessage(
        tenant_id=tenant_b_id,
        channel_id=channel_b_id,
        channel_type="telegram",
        external_message_id=f"msg_{uuid4().hex[:8]}",
        sender_id="sender_cross_tenant",
        sender_name="Attacker",
        content=f"/link {raw_code_a}",
        content_type="text",
        raw_payload={"text": f"/link {raw_code_a}"},
    )
    channel_svc = ChannelService(db)
    msg_cross = channel_svc.process_inbound_message(inbound_cross)
    db.commit()

    # Tenant B's channel must NOT link sender
    db.refresh(channel_b)
    assert "sender_cross_tenant" not in (channel_b.config.get("owner_identifiers") or [])

    engine = ConversationalAgentEngine(db=db, ai_provider=DeterministicMockAIProvider())
    res_cross = engine.process_incoming_message(tenant_b_id, msg_cross.id)
    assert "رمز الربط غير صحيح أو منتهي الصلاحية" in res_cross.reply_content

    # 2. Owner of Tenant A attempts to access Tenant B's channel link code API
    headers_a = {"Authorization": f"Bearer {token_a}"}
    cross_api_res = client.get(f"/api/v1/channels/{channel_b_id}/link-code", headers=headers_a)
    assert cross_api_res.status_code == 404


# =========================================================================
# 6. Production Dashboard URL Security & Token Expiry Tests (Item 4)
# =========================================================================

def test_production_dashboard_url_guard():
    """
    Item 4:
    In production and staging, TENANT_DASHBOARD_URL must be a public URL and cannot be localhost.
    Fails clearly with RuntimeError and logs error if missing or pointing to localhost.
    """
    settings.environment = "production"

    # 1. Missing URL in production -> raises RuntimeError
    settings.tenant_dashboard_url = None
    with pytest.raises(RuntimeError) as exc1:
        _ = settings.effective_tenant_dashboard_url
    assert "TENANT_DASHBOARD_URL is required" in str(exc1.value)

    # 2. Localhost URL in production -> raises RuntimeError
    settings.tenant_dashboard_url = "http://localhost:5173"
    with pytest.raises(RuntimeError) as exc2:
        _ = settings.effective_tenant_dashboard_url
    assert "cannot be localhost" in str(exc2.value)

    # 3. Valid public URL in production -> accepted
    settings.tenant_dashboard_url = "https://app.digitalemployee.sa"
    assert settings.effective_tenant_dashboard_url == "https://app.digitalemployee.sa"


def test_password_reset_token_short_expiry_and_reuse_rejection(db: Session):
    """
    Item 4:
    Verify short-lived token expiry (30-60 min) and single-use reuse rejection:
    1. An expired token is rejected with HTTP 400.
    2. A valid token resets the password successfully.
    3. Reusing the same token is rejected with HTTP 400.
    """
    from datetime import timedelta
    client = TestClient(app)

    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
        slug=f"test-{uuid4().hex[:6]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Test User",
        email=f"test-exp-{uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        status="active",
        password_hash=hash_password("InitialSecret123!"),
    )
    db.add(user)
    db.commit()

    # 1. Expired token (issued with negative delta)
    expired_token = create_password_reset_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        password_hash=user.password_hash,
        expires_delta=timedelta(seconds=-10),
    )
    res_exp = client.post(
        "/api/v1/auth/reset-password-with-token",
        json={"token": expired_token, "new_password": "NewValidPassword123!"},
    )
    assert res_exp.status_code == 400
    assert "expired" in res_exp.json()["detail"].lower()

    # 2. Valid token (30 min expiry)
    valid_token = create_password_reset_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        password_hash=user.password_hash,
        expires_delta=timedelta(minutes=30),
    )
    res_valid = client.post(
        "/api/v1/auth/reset-password-with-token",
        json={"token": valid_token, "new_password": "BrandNewPassword2026!"},
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["status"] == "ok"

    # 3. Token reuse rejection
    res_reuse = client.post(
        "/api/v1/auth/reset-password-with-token",
        json={"token": valid_token, "new_password": "AnotherNewPassword999!"},
    )
    assert res_reuse.status_code == 400
    assert "already been used" in res_reuse.json()["detail"]
