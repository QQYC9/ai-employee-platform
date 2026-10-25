from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.connectors.telegram import TelegramConnector
from packages.core.config import settings
from packages.core.crypto import SecretsEncryptionService
from packages.models.domain import Base, Channel
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService


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


@pytest.fixture
def test_tenant(db_session: Session) -> Tenant:
    tenant = Tenant(
        id=uuid4(),
        name="اختبار تيليجرام ويب هوك",
        slug=f"tg-test-{uuid4().hex[:6]}",
        status="active",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def test_telegram_channel_creation_auto_registers_webhook(db_session: Session, test_tenant: Tenant):
    """
    Test 1: Saving a Telegram channel auto-calls setWebhook with HTTPS URL, secret token,
    and drop_pending_updates=False; and raises clear ValueError if Telegram API rejects it.
    """
    service = ChannelService(db_session)

    # 1. Successful auto-registration
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"ok": True, "description": "Webhook was set"}

    with patch("httpx.Client.post", return_value=mock_post_resp) as mock_post:
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="بوت تيليجرام للتجربة",
            channel_type="telegram",
            config={"bot_token": "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"},
        )
        db_session.commit()
        db_session.refresh(channel)

        assert mock_post.called
        post_kwargs = mock_post.call_args[1]
        payload = post_kwargs["json"]
        expected_url = f"{settings.effective_webhook_base_url.rstrip('/')}/api/v1/webhooks/telegram/{channel.id}"
        assert payload["url"] == expected_url
        assert payload["drop_pending_updates"] is False
        assert "secret_token" in payload and len(payload["secret_token"]) > 10

        # Channel config persisted
        raw_cfg = channel.config or {}
        assert raw_cfg.get("webhook_status") == "active"
        assert raw_cfg.get("webhook_url") == expected_url

    # 2. Failure: Telegram API rejects token or URL
    mock_fail_resp = MagicMock()
    mock_fail_resp.status_code = 400
    mock_fail_resp.text = "Bad Request: bad webhook: HTTPS url must be provided"
    mock_fail_resp.json.return_value = {"ok": False, "description": "bad webhook: HTTPS url must be provided"}

    with patch("httpx.Client.post", return_value=mock_fail_resp):
        with pytest.raises(ValueError, match="Telegram webhook registration failed"):
            service.register_channel(
                tenant_id=test_tenant.id,
                name="بوت فاشل",
                channel_type="telegram",
                config={"bot_token": "987654321:InvalidToken"},
            )


def test_connection_dual_check_probes_both_token_and_webhook():
    """
    Test 2: Test connection verifies BOTH token (getMe) and webhook registration (getWebhookInfo URL
    matches expected and no error). Clearly distinguishes token failure vs webhook failure.
    """
    tenant_id = uuid4()
    channel_id = uuid4()
    expected_url = f"https://api.example.com/api/v1/webhooks/telegram/{channel_id}"

    # Scenario A: Token is invalid (getMe fails)
    mock_client = MagicMock()
    get_me_resp = MagicMock(status_code=401, text="Unauthorized")
    get_me_resp.json.return_value = {"ok": False, "description": "Unauthorized"}
    mock_client.get.return_value = get_me_resp

    connector = TelegramConnector(tenant_id, channel_id, "bad_token", http_client=mock_client)
    res_a = connector.test_connection(expected_webhook_url=expected_url)
    assert res_a.connected is False
    assert res_a.details.get("failure_stage") == "token_verification"
    assert "Token verification failed" in res_a.error

    # Scenario B: Token valid, but Webhook URL is empty or mismatches
    get_me_ok = MagicMock(status_code=200)
    get_me_ok.json.return_value = {"ok": True, "result": {"id": 111, "username": "test_bot"}}
    wh_empty = MagicMock(status_code=200)
    wh_empty.json.return_value = {"ok": True, "result": {"url": "", "pending_update_count": 3}}

    mock_client.get.side_effect = [get_me_ok, wh_empty]
    res_b = connector.test_connection(expected_webhook_url=expected_url)
    assert res_b.connected is False
    assert res_b.details.get("token_verified") is True
    assert res_b.details.get("webhook_verified") is False
    assert res_b.details.get("failure_stage") == "webhook_verification"
    assert "Webhook verification failed" in res_b.error

    # Scenario C: Both Token and Webhook valid & matching
    wh_ok = MagicMock(status_code=200)
    wh_ok.json.return_value = {"ok": True, "result": {"url": expected_url, "pending_update_count": 0}}
    mock_client.get.side_effect = [get_me_ok, wh_ok]
    res_c = connector.test_connection(expected_webhook_url=expected_url)
    assert res_c.connected is True
    assert res_c.details.get("token_verified") is True
    assert res_c.details.get("webhook_verified") is True


def test_re_register_webhook_updates_telegram_and_config(db_session: Session, test_tenant: Tenant):
    """
    Test 3: Re-registering webhook updates channel configuration, calls setWebhook,
    and returns verified connection status.
    """
    service = ChannelService(db_session)

    # Setup existing channel with outdated/empty webhook
    raw_cfg = {
        "bot_token": "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ",
        "webhook_url": "https://old-expired-tunnel.trycloudflare.com/webhook",
        "webhook_status": "outdated",
    }
    encrypted_cfg = service._encrypt_config(raw_cfg)
    channel = Channel(
        tenant_id=test_tenant.id,
        name="بوت إعادة التسجيل",
        channel_type="telegram",
        status="active",
        config=encrypted_cfg,
    )
    db_session.add(channel)
    db_session.commit()
    db_session.refresh(channel)

    new_tunnel_url = "https://new-fresh-tunnel.trycloudflare.com"
    expected_new_wh = f"{new_tunnel_url}/api/v1/webhooks/telegram/{channel.id}"

    mock_post_resp = MagicMock(status_code=200)
    mock_post_resp.json.return_value = {"ok": True, "description": "Webhook registered"}

    get_me_resp = MagicMock(status_code=200)
    get_me_resp.json.return_value = {"ok": True, "result": {"id": 12345, "username": "active_bot"}}
    wh_info_resp = MagicMock(status_code=200)
    wh_info_resp.json.return_value = {"ok": True, "result": {"url": expected_new_wh, "pending_update_count": 0}}

    with patch("httpx.Client.post", return_value=mock_post_resp), patch("httpx.Client.get", side_effect=[get_me_resp, wh_info_resp]):
        res = service.re_register_telegram_webhook(
            tenant_id=test_tenant.id,
            channel_id=channel.id,
            public_base_url=new_tunnel_url,
        )
        db_session.commit()
        db_session.refresh(channel)

        assert res.connected is True
        assert res.details.get("webhook_verified") is True
        assert channel.config["webhook_status"] == "active"
        assert channel.config["webhook_url"] == expected_new_wh
