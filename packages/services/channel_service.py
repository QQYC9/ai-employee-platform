from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    InboundMessage,
    OutboundDeliveryResult,
)
from packages.connectors.factory import ConnectorFactory
from packages.core.crypto import SecretsEncryptionService
from packages.models.domain import Channel, Conversation, Customer, Message, OutboxEvent
from packages.services.audit_service import AuditService
from packages.services.idempotency_service import IdempotencyService
from packages.services.outbox_service import OutboxService

logger = logging.getLogger(__name__)


class ChannelService:
    """
    Business logic for communication channel management and connector routing.

    Channels connect Digital Employees to external messaging platforms
    (WebChat, WhatsApp, Email, Slack, Telegram, SMS).
    Handles secret encryption at rest, connection diagnostics, message dispatch,
    and inbound message deduplication.
    """

    ALLOWED_CHANNEL_TYPES = {"webchat", "whatsapp", "email", "slack", "api", "telegram", "sms"}
    ALLOWED_STATUSES = {"active", "inactive", "maintenance", "deleted"}
    SECRET_CONFIG_KEYS = {
        "access_token",
        "bot_token",
        "smtp_password",
        "app_secret",
        "client_secret",
        "secret_token",
        "api_key",
        "token",
        "password",
        "webhook_verify_token",
        "verify_token",
        "secret",
        "private_key",
    }

    def __init__(
        self,
        db: Session,
        audit_service: AuditService | None = None,
        crypto: SecretsEncryptionService | None = None,
        idempotency_service: IdempotencyService | None = None,
    ):
        self.db = db
        self.audit_service = audit_service or AuditService(db)
        self.crypto = crypto or SecretsEncryptionService()
        self.idempotency_service = idempotency_service or IdempotencyService(db)
        self.connector_factory = ConnectorFactory(self.crypto)

    def _encrypt_config(self, config: dict[str, Any] | None) -> dict[str, Any]:
        """Encrypts sensitive authentication fields before persisting into JSONB."""
        if not config:
            return {}
        encrypted_cfg = dict(config)
        for key, val in config.items():
            k_lower = key.lower().strip()
            if k_lower in self.SECRET_CONFIG_KEYS and isinstance(val, str) and val.strip():
                if not val.startswith(SecretsEncryptionService.PREFIX):
                    encrypted_cfg[key] = self.crypto.encrypt(val.strip())
        return encrypted_cfg

    def sanitize_channel_config(self, config: dict[str, Any] | None) -> dict[str, Any]:
        """Masks secret keys for safe serialization in API responses and logs."""
        if not config:
            return {}
        sanitized = dict(config)
        for key in config:
            k_lower = key.lower().strip()
            if k_lower in self.SECRET_CONFIG_KEYS:
                sanitized[key] = "********"
        return sanitized

    def register_channel(
        self,
        tenant_id: UUID,
        name: str,
        channel_type: str,
        provider: str | None = None,
        config: dict | None = None,
    ) -> Channel:
        """Register and configure a communication channel for the tenant with encrypted secrets."""
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Channel name cannot be empty")

        clean_type = (channel_type or "").strip().lower()
        if clean_type not in self.ALLOWED_CHANNEL_TYPES:
            raise ValueError(f"Unsupported channel type: '{channel_type}'")

        encrypted_config = self._encrypt_config(config)

        channel = Channel(
            tenant_id=tenant_id,
            name=clean_name,
            channel_type=clean_type,
            provider=provider.strip() if provider and provider.strip() else None,
            status="active",
            config=encrypted_config,
        )

        self.db.add(channel)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="channel_registered",
            action="register_channel",
            description=f"Registered {clean_type} channel '{clean_name}'",
            event_metadata={
                "channel_id": str(channel.id),
                "channel_type": clean_type,
                "provider": channel.provider,
            },
        )

        return channel

    def get_channel(
        self,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> Channel | None:
        """Retrieve a channel scoped to the tenant."""
        return self.db.scalar(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
                Channel.status != "deleted",
            )
        )

    def list_channels(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        channel_type: str | None = None,
    ) -> list[Channel]:
        """List all channels configured for the tenant."""
        stmt = select(Channel).where(Channel.tenant_id == tenant_id)

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in self.ALLOWED_STATUSES:
                raise ValueError(f"Invalid channel status filter: {status}")
            stmt = stmt.where(Channel.status == clean_status)
        else:
            stmt = stmt.where(Channel.status != "deleted")

        if channel_type is not None:
            clean_type = channel_type.strip().lower()
            stmt = stmt.where(Channel.channel_type == clean_type)

        stmt = stmt.order_by(Channel.created_at.asc())
        return list(self.db.scalars(stmt).all())

    def update_channel(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        provider: str | None = None,
        config: dict | None = None,
    ) -> Channel:
        """Update an existing channel configuration with encrypted secrets."""
        channel = self.get_channel(tenant_id, channel_id)
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("Channel name cannot be empty")
            channel.name = clean_name

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in self.ALLOWED_STATUSES:
                raise ValueError(f"Invalid channel status: {status}")
            channel.status = clean_status

        if provider is not None:
            channel.provider = provider.strip() if provider.strip() else None

        if config is not None:
            encrypted_config = self._encrypt_config(config)
            updated_cfg = dict(channel.config or {})
            updated_cfg.update(encrypted_config)
            channel.config = updated_cfg

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="channel_updated",
            action="update_channel",
            description=f"Updated channel '{channel.name}'",
            event_metadata={
                "channel_id": str(channel.id),
                "status": channel.status,
            },
        )

        return channel

    def delete_channel(
        self,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> Channel:
        """Soft-delete a channel."""
        channel = self.get_channel(tenant_id, channel_id)
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found")

        channel.status = "deleted"
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="channel_deleted",
            action="delete_channel",
            description=f"Deleted channel '{channel.name}'",
            event_metadata={"channel_id": str(channel.id)},
        )

        return channel

    def get_connector(self, tenant_id: UUID, channel_id: UUID) -> BaseConnector:
        """Resolves and returns the instantiated BaseConnector for the given channel."""
        channel = self.get_channel(tenant_id, channel_id)
        if channel is None:
            raise ValueError(f"Channel '{channel_id}' not found for tenant '{tenant_id}'")
        return self.connector_factory.create_connector(channel)

    def test_channel_connection(self, tenant_id: UUID, channel_id: UUID) -> ConnectionTestResult:
        """Probes channel connectivity and logs audit event."""
        connector = self.get_connector(tenant_id, channel_id)
        result = connector.test_connection()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="channel_connection_tested",
            action="test_connection",
            description=f"Channel {channel_id} connection test: {result.status}",
            event_metadata={
                "channel_id": str(channel_id),
                "connected": result.connected,
                "status": result.status,
                "latency_ms": result.latency_ms,
                "error": result.error,
            },
        )
        return result

    def send_channel_message(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        """Dispatches an outbound message to recipient through the channel."""
        connector = self.get_connector(tenant_id, channel_id)
        result = connector.send_message(recipient, content, **kwargs)

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="channel_message_dispatched",
            action="send_message",
            description=f"Outbound message dispatch: {result.status}",
            event_metadata={
                "channel_id": str(channel_id),
                "recipient": recipient,
                "success": result.success,
                "external_message_id": result.external_message_id,
                "latency_ms": result.latency_ms,
                "error": result.error,
            },
        )
        return result

    def process_inbound_message(self, inbound: InboundMessage) -> Message:
        """
        Processes an incoming message from a connector:
          1. Enforces idempotency via IdempotencyService using external_message_id.
          2. Finds or creates the customer profile.
          3. Finds or creates an active conversation.
          4. Persists the incoming Message.
          5. Queues an atomic OutboxEvent for background processing.
        """
        tenant_id = inbound.tenant_id
        channel_id = inbound.channel_id
        idem_key = f"{inbound.channel_type}:{inbound.external_message_id}"

        # 1. Idempotency Check
        status, cached = self.idempotency_service.acquire_or_check(
            tenant_id=tenant_id,
            idempotency_key=idem_key,
            action="inbound_channel_message",
            resource=f"channel:{channel_id}",
            parameters={"external_id": inbound.external_message_id},
        )
        if status == "completed" and cached and "message_id" in cached:
            # Already processed
            existing_msg = self.db.scalar(
                select(Message).where(Message.id == UUID(cached["message_id"]))
            )
            if existing_msg:
                return existing_msg

        # 2. Find or Create Customer
        customer = None
        if inbound.channel_type in ("whatsapp", "sms"):
            customer = self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.phone == inbound.sender_id,
                    Customer.status != "deleted",
                )
            )
        elif inbound.channel_type == "email":
            customer = self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.email == inbound.sender_id.lower(),
                    Customer.status != "deleted",
                )
            )

        if customer is None:
            # Check by metadata external ID
            customer = self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.status != "deleted",
                    Customer.metadata_json[f"{inbound.channel_type}_id"].as_string() == inbound.sender_id,
                )
            )

        if customer is None:
            # Create new customer
            cust_name = inbound.sender_name or f"User {inbound.sender_id[:8]}"
            customer = Customer(
                tenant_id=tenant_id,
                name=cust_name,
                phone=inbound.sender_id if inbound.channel_type in ("whatsapp", "sms") else None,
                email=inbound.sender_id.lower() if inbound.channel_type == "email" else None,
                status="active",
                metadata_json={
                    f"{inbound.channel_type}_id": inbound.sender_id,
                    "created_via_channel": str(channel_id),
                },
            )
            self.db.add(customer)
            self.db.flush()

        # 3. Find or Create Active Conversation
        conversation = self.db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_id == channel_id,
                Conversation.customer_id == customer.id,
                Conversation.status.in_(["open", "active"]),
            ).order_by(Conversation.started_at.desc())
        )

        if conversation is None:
            conversation = Conversation(
                tenant_id=tenant_id,
                channel_id=channel_id,
                customer_id=customer.id,
                subject=f"{inbound.channel_type.capitalize()} Chat with {customer.name}",
                status="open",
                metadata_json={
                    "channel_type": inbound.channel_type,
                    "sender_id": inbound.sender_id,
                },
            )
            self.db.add(conversation)
            self.db.flush()


        # 4. Persist Inbound Message
        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            sender_type="customer",
            customer_id=customer.id,
            content=inbound.content,
            message_type=inbound.content_type,
            metadata_json={
                "external_message_id": inbound.external_message_id,
                "channel_id": str(channel_id),
                "channel_type": inbound.channel_type,
                "sender_id": inbound.sender_id,
                "raw_payload": inbound.raw_payload,
            },
        )
        self.db.add(message)
        self.db.flush()

        # 5. Atomic Outbox Event for Background Processing
        outbox_service = OutboxService(self.db)
        outbox_event = outbox_service.create_event(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            message_id=message.id,
            idempotency_key=f"outbox:inbound:{message.id}",
            event_type="process_incoming_message",
            payload={
                "message_id": str(message.id),
                "conversation_id": str(conversation.id),
                "tenant_id": str(tenant_id),
                "customer_id": str(customer.id),
                "channel_id": str(channel_id),
                "channel_type": inbound.channel_type,
                "content": inbound.content,
                "external_message_id": inbound.external_message_id,
            },
        )


        # 6. Complete Idempotency
        self.idempotency_service.complete(
            tenant_id=tenant_id,
            idempotency_key=idem_key,
            result={
                "message_id": str(message.id),
                "conversation_id": str(conversation.id),
                "outbox_event_id": str(outbox_event.id),
            },
        )

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="inbound_message_ingested",
            action="process_inbound_message",
            description=f"Ingested message {inbound.external_message_id} from {inbound.channel_type}",
            event_metadata={
                "message_id": str(message.id),
                "conversation_id": str(conversation.id),
                "channel_id": str(channel_id),
                "channel_type": inbound.channel_type,
            },
        )

        return message
