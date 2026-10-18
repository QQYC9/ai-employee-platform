import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage
from packages.connectors.email import EmailConnector
from packages.connectors.telegram import TelegramConnector
from packages.connectors.whatsapp import WhatsAppCloudConnector
from packages.core.crypto import SecretsEncryptionService
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Conversation, Customer, Message, OutboxEvent
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_tenant(db_session: Session):
    tenant = Tenant(
        name=f"Channel Tenant {uuid.uuid4().hex[:6]}",
        slug=f"channel-tenant-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# ==============================================================================
# WhatsApp Cloud API Connector Tests
# ==============================================================================

class TestWhatsAppCloudConnector:
    def test_webhook_challenge_verification_success(self):
        connector = WhatsAppCloudConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            phone_number_id="1000123456789",
            access_token="test-access-token",
            webhook_verify_token="my-secure-verify-token",
        )
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "my-secure-verify-token",
            "hub.challenge": "1158201444",
        }
        valid, challenge = connector.verify_webhook(headers={}, body=b"", params=params)
        assert valid is True
        assert challenge == "1158201444"

    def test_webhook_challenge_verification_failure(self):
        connector = WhatsAppCloudConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            phone_number_id="1000123456789",
            access_token="test-access-token",
            webhook_verify_token="my-secure-verify-token",
        )
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "1158201444",
        }
        valid, challenge = connector.verify_webhook(headers={}, body=b"", params=params)
        assert valid is False

    def test_webhook_signature_hmac_sha256(self):
        app_secret = "meta-app-secret-xyz"
        body = b'{"entry":[{"changes":[{"value":{"messages":[{"id":"wamid.1","from":"966500000000","text":{"body":"Hello"}}]}}]}]}'
        expected_sig = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        connector = WhatsAppCloudConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            phone_number_id="1000123456789",
            access_token="test-token",
            app_secret=app_secret,
        )

        # Valid signature
        headers = {"x-hub-signature-256": f"sha256={expected_sig}"}
        valid, err = connector.verify_webhook(headers=headers, body=body)
        assert valid is True

        # Tampered body
        tampered_body = body + b" "
        valid_bad, err_bad = connector.verify_webhook(headers=headers, body=tampered_body)
        assert valid_bad is False
        assert err_bad == "Signature mismatch"

    def test_parse_inbound_whatsapp_messages(self):
        connector = WhatsAppCloudConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            phone_number_id="1000123456789",
            access_token="token",
        )
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"wa_id": "966501234567", "profile": {"name": "Fahad"}}],
                                "messages": [
                                    {
                                        "id": "wamid.HBgLMjA",
                                        "from": "966501234567",
                                        "type": "text",
                                        "text": {"body": "اريد حجز موعد استشارة"},
                                        "timestamp": "1670000000",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        messages = connector.parse_inbound(payload)
        assert len(messages) == 1
        msg = messages[0]
        assert msg.external_message_id == "wamid.HBgLMjA"
        assert msg.sender_id == "966501234567"
        assert msg.sender_name == "Fahad"
        assert msg.content == "اريد حجز موعد استشارة"
        assert msg.channel_type == "whatsapp"

    def test_send_message_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.OUT123456789"}]},
            request=httpx.Request("POST", "https://graph.facebook.com/v19.0/1000/messages"),
        )
        mock_client.post.return_value = mock_response

        connector = WhatsAppCloudConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            phone_number_id="1000",
            access_token="test-token",
            http_client=mock_client,
        )
        result = connector.send_message(recipient="+966 50 123 4567", content="تم تأكيد موعدك بنجاح")
        assert result.success is True
        assert result.external_message_id == "wamid.OUT123456789"
        assert result.status == "sent"


# ==============================================================================
# Telegram Bot API Connector Tests
# ==============================================================================

class TestTelegramConnector:
    def test_verify_webhook_secret_token(self):
        connector = TelegramConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            bot_token="123456:ABC-DEF1234ghIkl",
            secret_token="telegram-secret-token-999",
        )
        # Valid
        headers = {"x-telegram-bot-api-secret-token": "telegram-secret-token-999"}
        valid, err = connector.verify_webhook(headers=headers, body=b"{}")
        assert valid is True

        # Invalid
        headers_bad = {"x-telegram-bot-api-secret-token": "wrong-secret"}
        valid_bad, err_bad = connector.verify_webhook(headers=headers_bad, body=b"{}")
        assert valid_bad is False

    def test_parse_inbound_telegram_update(self):
        connector = TelegramConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            bot_token="123456:ABC-DEF",
        )
        payload = {
            "update_id": 98765,
            "message": {
                "message_id": 42,
                "from": {"id": 12345678, "first_name": "Khalid", "username": "khalid_dev"},
                "chat": {"id": 12345678, "type": "private"},
                "date": 1670000000,
                "text": "Hello Digital Employee",
            },
        }
        messages = connector.parse_inbound(payload)
        assert len(messages) == 1
        msg = messages[0]
        assert msg.external_message_id == "42"
        assert msg.sender_id == "12345678"
        assert msg.sender_name == "Khalid"
        assert msg.content == "Hello Digital Employee"

    def test_send_message_telegram(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = httpx.Response(
            status_code=200,
            json={"ok": True, "result": {"message_id": 999}},
            request=httpx.Request("POST", "https://api.telegram.org/bot123/sendMessage"),
        )
        mock_client.post.return_value = mock_response

        connector = TelegramConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            bot_token="123:ABC",
            http_client=mock_client,
        )
        result = connector.send_message(recipient="12345678", content="Notification from bot")
        assert result.success is True
        assert result.external_message_id == "999"


# ==============================================================================
# Email Connector Tests
# ==============================================================================

class TestEmailConnector:
    def test_reject_invalid_recipient_email(self):
        connector = EmailConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            smtp_host="smtp.example.com",
            from_address="ai@example.com",
        )
        result = connector.send_message(recipient="invalid-email-address", content="hello")
        assert result.success is False
        assert "Invalid recipient email" in result.error

    def test_parse_inbound_mime_email(self):
        connector = EmailConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            smtp_host="smtp.example.com",
            from_address="support@example.com",
        )
        raw_email = (
            b"From: John Doe <john@example.com>\r\n"
            b"To: support@example.com\r\n"
            b"Subject: Inquiry regarding SaaS pricing\r\n"
            b"Message-ID: <unique-email-1234@example.com>\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Could you please share your enterprise tier details?\r\n"
        )
        messages = connector.parse_inbound(raw_email)
        assert len(messages) == 1
        msg = messages[0]
        assert msg.external_message_id == "<unique-email-1234@example.com>"
        assert msg.sender_id == "john@example.com"
        assert msg.sender_name == "John Doe"
        assert "Subject: Inquiry regarding SaaS pricing" in msg.content
        assert "enterprise tier details" in msg.content

    def test_send_email_smtp_mocked(self):
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value = mock_server

            connector = EmailConnector(
                tenant_id=uuid.uuid4(),
                channel_id=uuid.uuid4(),
                smtp_host="smtp.mailtrap.io",
                smtp_port=587,
                smtp_user="user123",
                smtp_password="password123",
                from_address="employee@company.com",
                from_name="Digital Employee",
            )
            result = connector.send_message(
                recipient="client@domain.com",
                content="Here is your requested monthly statement.",
                subject="Monthly Statement",
            )
            assert result.success is True
            assert result.status == "sent"
            assert mock_server.send_message.called


# ==============================================================================
# ChannelService & End-to-End Connector Tests
# ==============================================================================

class TestChannelServiceIntegration:
    def test_register_channel_encrypts_secrets_at_rest(self, db_session: Session, test_tenant: Tenant):
        service = ChannelService(db_session)
        raw_token = "EAABwzL_meta_graph_secret_token_9999"
        raw_secret = "app_secret_12345"

        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Official WhatsApp",
            channel_type="whatsapp",
            provider="meta",
            config={
                "phone_number_id": "10987654321",
                "access_token": raw_token,
                "app_secret": raw_secret,
                "webhook_verify_token": "verify-123",
            },
        )
        db_session.commit()
        db_session.refresh(channel)

        # Check DB config: access_token, app_secret, and webhook_verify_token must be encrypted with AES-256-GCM
        assert channel.config["access_token"].startswith(SecretsEncryptionService.PREFIX)
        assert channel.config["app_secret"].startswith(SecretsEncryptionService.PREFIX)
        assert channel.config["webhook_verify_token"].startswith(SecretsEncryptionService.PREFIX)
        assert raw_token not in json.dumps(channel.config)

        # Sanitize check: API response must mask secrets
        sanitized = service.sanitize_channel_config(channel.config)
        assert sanitized["access_token"] == "********"
        assert sanitized["app_secret"] == "********"
        assert sanitized["webhook_verify_token"] == "********"
        assert sanitized["phone_number_id"] == "10987654321"

        # Connector Factory can instantiate with decrypted secrets
        connector = service.get_connector(test_tenant.id, channel.id)
        assert isinstance(connector, WhatsAppCloudConnector)
        assert connector.access_token == raw_token
        assert connector.app_secret == raw_secret
        assert connector.webhook_verify_token == "verify-123"

    def test_process_inbound_message_with_idempotency_and_outbox(
        self, db_session: Session, test_tenant: Tenant
    ):
        service = ChannelService(db_session)
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Support WhatsApp",
            channel_type="whatsapp",
            config={"phone_number_id": "1001", "access_token": "token"},
        )
        db_session.commit()

        inbound = InboundMessage(
            channel_type="whatsapp",
            channel_id=channel.id,
            tenant_id=test_tenant.id,
            external_message_id="wamid.UNIQUE_ID_888",
            sender_id="+966509999999",
            sender_name="Mona",
            content="استفسار عن الخدمة",
        )

        # Process first time
        msg1 = service.process_inbound_message(inbound)
        db_session.commit()

        assert msg1.id is not None
        assert msg1.content == "استفسار عن الخدمة"
        assert msg1.sender_type == "customer"

        # Verify Customer was created/linked
        customer = db_session.scalar(select(Customer).where(Customer.phone == "+966509999999"))
        assert customer is not None
        assert customer.name == "Mona"

        # Verify OutboxEvent was created atomically
        outbox_event = db_session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.event_type == "process_incoming_message",
                OutboxEvent.tenant_id == test_tenant.id,
            )
        )

        assert outbox_event is not None
        assert outbox_event.payload["message_id"] == str(msg1.id)

        # Process second time with same external_message_id (idempotency deduplication)
        msg2 = service.process_inbound_message(inbound)
        assert msg2.id == msg1.id  # Same message returned without duplicating
