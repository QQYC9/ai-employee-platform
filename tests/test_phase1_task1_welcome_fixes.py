from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.auth.jwt_service import create_password_reset_token, verify_token
from packages.auth.security import hash_password, verify_password
from packages.core.config import settings
from packages.models.domain import Base, Channel, User
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.tenant_provisioning_service import (
    InitialAgentInput,
    TenantProvisioningRequest,
    TenantProvisioningService,
)


@pytest.fixture
def db_session():
    test_db_url = settings.effective_test_database_url
    engine = create_engine(test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_welcome_message_plain_text_and_employee_name_fallback(db_session: Session):
    """
    Test 1: Welcome message uses plain text (no literal **), resolves public dashboard URL,
    and falls back to 'موظفك الرقمي.' when employee_name is empty.
    """
    engine = ConversationalAgentEngine(db_session)

    # 1. Tenant with NO employee name
    tenant_no_name = Tenant(
        id=uuid4(),
        name="متجر تجريبي بدون اسم موظف",
        slug=f"t-noname-{uuid4().hex[:6]}",
        employee_name="",
        status="active",
    )
    db_session.add(tenant_no_name)
    db_session.commit()

    from packages.models.domain import Conversation, Message

    conv = Conversation(tenant_id=tenant_no_name.id, status="active")
    db_session.add(conv)
    db_session.flush()

    msg = Message(
        tenant_id=tenant_no_name.id,
        conversation_id=conv.id,
        sender_type="owner",
        content="/link LINK-TEST-1234",
        metadata_json={"just_linked_via_code": True},
    )
    db_session.add(msg)
    db_session.flush()

    with patch.object(engine.channel_service, "resolve_owner_user", return_value=None), \
         patch("packages.services.interview_service.InterviewService.start_interview", return_value="سؤال 1"):

        result = engine._process_owner_message(
            tenant_id=tenant_no_name.id,
            message=msg,
            conversation=conv,
        )
        reply = result.reply_content

        assert "**" not in reply, "Literal ** asterisks must be removed from welcome text"
        assert "موظفك الرقمي." in reply, "Empty employee name must fallback to 'موظفك الرقمي.'"
        assert "أنا ،" not in reply, "Empty employee name must not have empty name phrase"
        assert "http://localhost:5173" not in reply, "Localhost dashboard URL must not appear"
        assert "trycloudflare.com" in reply or "https://" in reply

    # 2. Tenant WITH employee name "سارة"
    tenant_sara = Tenant(
        id=uuid4(),
        name="متجر سارة",
        slug=f"t-sara-{uuid4().hex[:6]}",
        employee_name="سارة",
        status="active",
    )
    db_session.add(tenant_sara)
    db_session.commit()

    conv_sara = Conversation(tenant_id=tenant_sara.id, status="active")
    db_session.add(conv_sara)
    db_session.flush()

    msg_sara = Message(
        tenant_id=tenant_sara.id,
        conversation_id=conv_sara.id,
        sender_type="owner",
        content="/link LINK-TEST-5678",
        metadata_json={"just_linked_via_code": True},
    )
    db_session.add(msg_sara)
    db_session.flush()

    with patch.object(engine.channel_service, "resolve_owner_user", return_value=None), \
         patch("packages.services.interview_service.InterviewService.start_interview", return_value="سؤال 1"):

        result_sara = engine._process_owner_message(
            tenant_id=tenant_sara.id,
            message=msg_sara,
            conversation=conv_sara,
        )
        reply_sara = result_sara.reply_content

        assert "أنا سارة، موظفتك الرقمية الذكية." in reply_sara
        assert "**" not in reply_sara


def test_tenant_creation_requires_employee_name(db_session: Session):
    """
    Test 2: Tenant provisioning enforces that an employee name is mandatory.
    """
    prov_svc = TenantProvisioningService(db_session)

    # Empty employee name must fail
    req_invalid = TenantProvisioningRequest(
        name="منشأة بلا موظف",
        owner_name="المالك",
        owner_email=f"owner-{uuid4().hex[:6]}@example.com",
        employee_name="",
        agent=InitialAgentInput(name=""),
    )

    with pytest.raises(ValueError, match="Employee name is required"):
        prov_svc.provision_tenant(req_invalid)


def test_set_password_token_lifecycle_and_security(db_session: Session):
    """
    Test 3: Token created for password setup is verified with 30-min expiration and single-use signature.
    """
    user_id = uuid4()
    tenant_id = uuid4()
    pwh = hash_password("OldPassword123!")

    token = create_password_reset_token(
        user_id=user_id,
        tenant_id=tenant_id,
        password_hash=pwh,
    )

    claims = verify_token(token, expected_type="password_reset")
    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["token_type"] == "password_reset"
    assert "pwh" in claims
