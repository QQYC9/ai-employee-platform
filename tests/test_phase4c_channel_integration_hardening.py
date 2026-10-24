import base64
import json
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import InboundMessage, OutboundDeliveryResult
from packages.connectors.telegram import TelegramConnector
from packages.connectors.whatsapp import WhatsAppCloudConnector
from packages.core.crypto import DecryptionError, SecretsEncryptionService
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Conversation, Customer, Message, OutboxEvent
from packages.models.tenant import Tenant
from packages.services.channel_service import ChannelService
from packages.services.outbox_worker import OutboxWorker


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
        name=f"Hardened Tenant {uuid.uuid4().hex[:6]}",
        slug=f"hardened-tenant-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# ==============================================================================
# 1. Real AES-256-GCM Encryption Audit & Hardening Tests
# ==============================================================================

class TestSecretsEncryptionServiceHardening:
    def test_real_aes_gcm_authenticated_encryption(self):
        crypto = SecretsEncryptionService()
        raw_secret = "bot_token_secret_123456789!@#$%"

        encrypted_1 = crypto.encrypt(raw_secret)
        encrypted_2 = crypto.encrypt(raw_secret)

        # 1. Must use versioned prefix
        assert encrypted_1.startswith(SecretsEncryptionService.PREFIX)
        assert encrypted_2.startswith(SecretsEncryptionService.PREFIX)

        # 2. Must use distinct random nonces for identical plaintexts (IND-CPA security)
        assert encrypted_1 != encrypted_2

        # 3. Must decrypt accurately
        assert crypto.decrypt(encrypted_1) == raw_secret
        assert crypto.decrypt(encrypted_2) == raw_secret

    def test_tampered_ciphertext_rejection(self):
        crypto = SecretsEncryptionService()
        raw_secret = "super_confidential_api_key_999"
        encrypted = crypto.encrypt(raw_secret)

        prefix = SecretsEncryptionService.PREFIX
        content = encrypted[len(prefix):]
        nonce_b64, ct_b64 = content.split(":")

        ct_bytes = bytearray(base64.b64decode(ct_b64))
        # Tamper with 1 byte of ciphertext
        ct_bytes[0] ^= 0xFF
        tampered_ct_b64 = base64.b64encode(bytes(ct_bytes)).decode("ascii")
        tampered_payload = f"{prefix}{nonce_b64}:{tampered_ct_b64}"

        with pytest.raises(DecryptionError, match="authentication tag mismatch or corrupted data"):
            crypto.decrypt(tampered_payload)

    def test_tampered_nonce_rejection(self):
        crypto = SecretsEncryptionService()
        raw_secret = "secret_to_protect"
        encrypted = crypto.encrypt(raw_secret)

        prefix = SecretsEncryptionService.PREFIX
        content = encrypted[len(prefix):]
        nonce_b64, ct_b64 = content.split(":")

        nonce_bytes = bytearray(base64.b64decode(nonce_b64))
        nonce_bytes[0] ^= 0x01
        tampered_nonce_b64 = base64.b64encode(bytes(nonce_bytes)).decode("ascii")
        tampered_payload = f"{prefix}{tampered_nonce_b64}:{ct_b64}"

        with pytest.raises(DecryptionError):
            crypto.decrypt(tampered_payload)

    def test_wrong_key_rejection(self):
        crypto1 = SecretsEncryptionService(key="master_key_alpha_111111111111111")
        crypto2 = SecretsEncryptionService(key="master_key_beta_2222222222222222")

        encrypted = crypto1.encrypt("confidential_token")
        with pytest.raises(DecryptionError):
            crypto2.decrypt(encrypted)


# ==============================================================================
# 2. Channel Config Masked Secret Preservation
# ==============================================================================

class TestChannelConfigSecretPreservation:
    def test_update_channel_preserves_masked_secrets(self, db_session: Session, test_tenant: Tenant):
        service = ChannelService(db_session)
        real_token = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"

        # Register channel with real bot_token
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Telegram Customer Bot",
            channel_type="telegram",
            config={
                "bot_token": real_token,
                "custom_param": "original_val",
            },
        )
        original_encrypted_token = channel.config["bot_token"]
        assert original_encrypted_token.startswith(SecretsEncryptionService.PREFIX)
        assert service.crypto.decrypt(original_encrypted_token) == real_token

        # Client submits update containing masked secret (as returned by sanitize_channel_config)
        sanitized = service.sanitize_channel_config(channel.config)
        assert sanitized["bot_token"] == "********"

        # Update channel sending the masked token back
        updated_channel = service.update_channel(
            tenant_id=test_tenant.id,
            channel_id=channel.id,
            config={
                "bot_token": "********",
                "custom_param": "new_updated_val",
            },
        )

        # The encrypted token must be preserved, NOT overwritten with an encrypted mask
        assert updated_channel.config["bot_token"] == original_encrypted_token
        assert service.crypto.decrypt(updated_channel.config["bot_token"]) == real_token
        assert updated_channel.config["custom_param"] == "new_updated_val"

    def test_update_channel_overwrites_when_real_new_secret_provided(self, db_session: Session, test_tenant: Tenant):
        service = ChannelService(db_session)
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Telegram Bot Old",
            channel_type="telegram",
            config={"bot_token": "old_token_111"},
        )
        assert service.crypto.decrypt(channel.config["bot_token"]) == "old_token_111"

        updated = service.update_channel(
            tenant_id=test_tenant.id,
            channel_id=channel.id,
            config={"bot_token": "new_token_222"},
        )
        assert service.crypto.decrypt(updated.config["bot_token"]) == "new_token_222"


# ==============================================================================
# 3. Telegram Callback Query & Chat ID Routing Tests
# ==============================================================================

class TestTelegramCallbackQueryAndRouting:
    def test_parse_inbound_callback_query(self):
        connector = TelegramConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            bot_token="test_token",
        )
        callback_payload = {
            "update_id": 999999,
            "callback_query": {
                "id": "query_12345",
                "from": {
                    "id": 111222333,
                    "first_name": "Tariq",
                    "username": "tariq_user",
                },
                "message": {
                    "message_id": 888,
                    "chat": {
                        "id": -10099887766,
                        "title": "Support Supergroup",
                        "type": "supergroup",
                    },
                    "text": "Please choose an option:",
                },
                "data": "action_check_order_status",
            },
        }

        messages = connector.parse_inbound(callback_payload)
        assert len(messages) == 1
        inbound = messages[0]

        assert inbound.external_message_id == "cb_query_12345"
        assert inbound.sender_id == "111222333"
        assert inbound.sender_name == "Tariq"
        assert inbound.recipient_id == "-10099887766"
        assert inbound.content == "action_check_order_status"
        assert inbound.content_type == "callback_query"

    def test_telegram_chat_id_recipient_priority_in_outbox(self, db_session: Session, test_tenant: Tenant):
        service = ChannelService(db_session)
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Telegram Group Channel",
            channel_type="telegram",
            config={"bot_token": "mock_bot_token"},
        )

        inbound = InboundMessage(
            channel_type="telegram",
            channel_id=channel.id,
            tenant_id=test_tenant.id,
            external_message_id="msg_9901",
            sender_id="555444",        # User ID
            recipient_id="-100998877",  # Group Chat ID
            content="Hello from Telegram Group",
            content_type="text",
        )

        persisted_msg = service.process_inbound_message(inbound)
        assert persisted_msg.metadata_json["recipient_id"] == "-100998877"
        assert persisted_msg.metadata_json["sender_id"] == "555444"

        # Check OutboxEvent
        outbox_event = db_session.scalar(
            select(OutboxEvent).where(OutboxEvent.message_id == persisted_msg.id)
        )
        assert outbox_event is not None
        assert outbox_event.payload["recipient_id"] == "-100998877"
        assert outbox_event.payload["sender_id"] == "555444"

        # Now test that OutboxWorker uses recipient_id (-100998877) to reply, NOT user_id (555444)
        worker = OutboxWorker(worker_id="test-worker", session_factory=lambda: db_session)
        mock_connector = MagicMock()
        mock_connector.send_message.return_value = OutboundDeliveryResult(
            success=True,
            channel_type="telegram",
            recipient_id="-100998877",
            external_message_id="sent_reply_777",
            status="sent",
            latency_ms=10.5,
            error=None,
        )

        with patch("packages.connectors.factory.ConnectorFactory.create_connector", return_value=mock_connector), \
             patch("packages.services.outbox_worker.ConversationalAgentEngine") as mock_engine_cls:
            mock_engine_cls.ALLOWED_INPUT_SENDERS = {"customer", "user"}
            engine_inst = mock_engine_cls.return_value
            engine_inst.process_incoming_message.return_value = MagicMock(
                success=True,
                reply_content="Welcome to our group support!",
                reply_message_id=None,
                skipped=False,
            )

            # Claim and process
            outbox_event.status = "processing"
            db_session.flush()

            success = worker.process_event(outbox_event.id)
            assert success is True

            # Connector send_message must be called with recipient="-100998877" (the chat_id)
            mock_connector.send_message.assert_called_once()
            called_recipient = mock_connector.send_message.call_args[1].get("recipient") or mock_connector.send_message.call_args[0][0]
            assert called_recipient == "-100998877"


# ==============================================================================
# 4. Long Message Safe Chunking (>4000 characters)
# ==============================================================================

class TestConnectorLongMessageChunking:
    def test_telegram_long_message_chunking(self):
        long_text = "A" * 9500  # Exceeds 4096 character limit
        mock_client = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 4321}}
        mock_client.post.return_value = mock_resp

        connector = TelegramConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            bot_token="test_token",
            http_client=mock_client,
        )

        result = connector.send_message(recipient="12345678", content=long_text)
        assert result.success is True
        assert result.metadata.get("chunks_sent") == 3
        assert mock_client.post.call_count == 3

    def test_whatsapp_long_message_chunking(self):
        long_text = "W" * 9500
        mock_client = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "wamid.12345"}]}
        mock_client.post.return_value = mock_resp

        connector = WhatsAppCloudConnector(
            tenant_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            phone_number_id="1234567890",
            access_token="test_token",
            http_client=mock_client,
        )

        result = connector.send_message(recipient="+966500000000", content=long_text)
        assert result.success is True
        assert result.metadata.get("chunks_sent") == 3
        assert mock_client.post.call_count == 3


# ==============================================================================
# 5. Generic Webhook Recipient Resolution & Outbox Dispatch
# ==============================================================================

class TestGenericWebhookRecipientResolution:
    def test_generic_webhook_outbox_sender_and_reply_dispatch(self, db_session: Session, test_tenant: Tenant):
        from fastapi.testclient import TestClient
        from apps.agent.main import app
        from packages.auth.dependencies import get_db

        app.dependency_overrides[get_db] = lambda: db_session
        client = TestClient(app)

        try:
            # 1. Register an email channel
            service = ChannelService(db_session)
            channel = service.register_channel(
                tenant_id=test_tenant.id,
                name="Email Support",
                channel_type="email",
                config={"smtp_host": "mail.example.com", "smtp_user": "support@example.com"},
            )

            # 2. Ingest inbound message via webhook with customer_email
            resp = client.post(
                f"/api/v1/webhooks/channels/{channel.id}",
                json={
                    "content": "Inquiry about pricing",
                    "customer_name": "Sarah",
                    "customer_email": "sarah@client.com",
                    "external_id": "email-msg-001",
                },
            )
            assert resp.status_code == 202
            data = resp.json()
            assert data["status"] == "accepted"
            event_id = uuid.UUID(data["outbox_event_id"])

            # 3. Verify event payload has sender_id populated
            event = db_session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
            assert event is not None
            assert event.payload.get("sender_id") in ("email-msg-001", "sarah@client.com")

            # 4. Process event with OutboxWorker and verify reply is dispatched
            mock_connector = MagicMock()
            mock_connector.send_message.return_value = OutboundDeliveryResult(
                success=True,
                channel_type="email",
                recipient_id="sarah@client.com",
                external_message_id="smtp-out-888",
                status="sent",
                latency_ms=15.0,
                error=None,
            )

            worker = OutboxWorker(worker_id="test-webhook-worker", session_factory=lambda: db_session)
            with patch("packages.connectors.factory.ConnectorFactory.create_connector", return_value=mock_connector), \
                 patch("packages.services.outbox_worker.ConversationalAgentEngine") as mock_engine_cls:
                mock_engine_cls.ALLOWED_INPUT_SENDERS = {"customer", "user"}
                engine_inst = mock_engine_cls.return_value
                engine_inst.process_incoming_message.return_value = MagicMock(
                    success=True,
                    reply_content="Thank you for contacting us!",
                    reply_message_id=None,
                    skipped=False,
                )

                event.status = "processing"
                db_session.flush()

                success = worker.process_event(event.id)
                assert success is True
                mock_connector.send_message.assert_called_once()
        finally:
            app.dependency_overrides.clear()
