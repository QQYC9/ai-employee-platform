from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Channel, Conversation, Customer, Message
from packages.services.audit_service import AuditService


class ConversationService:
    """
    Business logic for omni-channel customer conversations and messaging.

    Handles conversation sessions, message routing, chronological history,
    and participant attribution across digital employees and human customers.
    """

    ALLOWED_STATUSES = {"open", "pending", "resolved", "closed"}
    ALLOWED_SENDER_TYPES = {"customer", "agent", "user", "system"}
    ALLOWED_MESSAGE_TYPES = {"text", "tool_result", "event", "attachment"}

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

    def start_conversation(
        self,
        tenant_id: UUID,
        *,
        customer_id: UUID | None = None,
        channel_id: UUID | None = None,
        subject: str | None = None,
        external_id: str | None = None,
        metadata_json: dict | None = None,
    ) -> Conversation:
        """Start a new conversation thread."""
        if customer_id is not None:
            customer = self.db.scalar(
                select(Customer).where(
                    Customer.id == customer_id,
                    Customer.tenant_id == tenant_id,
                    Customer.status != "deleted",
                )
            )
            if customer is None:
                raise ValueError(f"Customer '{customer_id}' not found in this tenant")
            if customer.status == "blocked":
                raise ValueError(f"Customer '{customer_id}' is blocked from starting conversations")

        if channel_id is not None:
            channel = self.db.scalar(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                    Channel.status != "deleted",
                )
            )
            if channel is None:
                raise ValueError(f"Channel '{channel_id}' not found in this tenant")

        clean_subject = subject.strip() if subject and subject.strip() else None
        clean_ext_id = external_id.strip() if external_id and external_id.strip() else None

        conversation = Conversation(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel_id=channel_id,
            subject=clean_subject,
            external_id=clean_ext_id,
            status="open",
            metadata_json=metadata_json or {},
        )

        self.db.add(conversation)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="conversation_started",
            action="start_conversation",
            description=f"Started conversation '{clean_subject or conversation.id}'",
            event_metadata={
                "conversation_id": str(conversation.id),
                "customer_id": str(customer_id) if customer_id else None,
                "channel_id": str(channel_id) if channel_id else None,
            },
        )

        return conversation

    def get_conversation(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
    ) -> Conversation | None:
        """Retrieve a conversation belonging to the tenant."""
        return self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )

    def list_conversations(
        self,
        tenant_id: UUID,
        *,
        customer_id: UUID | None = None,
        channel_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Conversation]:
        """List conversations scoped to tenant with optional filters."""
        if limit < 1:
            raise ValueError("Limit must be greater than zero")
        if limit > 200:
            limit = 200

        stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)

        if customer_id is not None:
            stmt = stmt.where(Conversation.customer_id == customer_id)

        if channel_id is not None:
            stmt = stmt.where(Conversation.channel_id == channel_id)

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in self.ALLOWED_STATUSES:
                raise ValueError(f"Invalid conversation status filter: {status}")
            stmt = stmt.where(Conversation.status == clean_status)

        stmt = stmt.order_by(
            Conversation.last_message_at.desc().nullslast(),
            Conversation.started_at.desc(),
        ).offset(offset).limit(limit)

        return list(self.db.scalars(stmt).all())

    def update_status(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        status: str,
    ) -> Conversation:
        """Update conversation lifecycle status."""
        conversation = self.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation '{conversation_id}' not found")

        clean_status = (status or "").strip().lower()
        if clean_status not in self.ALLOWED_STATUSES:
            raise ValueError(f"Invalid conversation status: {status}")

        now = datetime.now(timezone.utc)
        if clean_status in ("closed", "resolved"):
            conversation.closed_at = now
        else:
            conversation.closed_at = None

        conversation.status = clean_status
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="conversation_status_updated",
            action="update_status",
            description=f"Conversation status changed to '{clean_status}'",
            event_metadata={
                "conversation_id": str(conversation.id),
                "new_status": clean_status,
            },
        )

        return conversation

    def send_message(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        sender_type: str,
        content: str | None = None,
        sender_id: UUID | None = None,
        customer_id: UUID | None = None,
        message_type: str = "text",
        external_id: str | None = None,
        metadata_json: dict | None = None,
    ) -> Message:
        """Append an incoming or outgoing message to a conversation."""
        conversation = self.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation '{conversation_id}' not found")

        clean_sender = (sender_type or "").strip().lower()
        if clean_sender not in self.ALLOWED_SENDER_TYPES:
            raise ValueError(f"Invalid sender type: {sender_type}")

        clean_msg_type = (message_type or "text").strip().lower()
        if clean_msg_type not in self.ALLOWED_MESSAGE_TYPES:
            raise ValueError(f"Invalid message type: {message_type}")

        if not content and not metadata_json:
            raise ValueError("Message must have either content or metadata")

        # Auto-reopen closed/resolved conversations when a customer sends a new message
        if conversation.status in ("closed", "resolved") and clean_sender == "customer":
            conversation.status = "open"
            conversation.closed_at = None

        now = datetime.now(timezone.utc)
        conversation.last_message_at = now

        msg = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id or conversation.customer_id,
            sender_type=clean_sender,
            sender_id=sender_id,
            message_type=clean_msg_type,
            content=content,
            external_id=external_id.strip() if external_id and external_id.strip() else None,
            metadata_json=metadata_json or {},
            created_at=now,
        )

        self.db.add(msg)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="message_sent",
            action="send_message",
            description=f"Message sent by {clean_sender} in conversation {conversation.id}",
            event_metadata={
                "conversation_id": str(conversation.id),
                "message_id": str(msg.id),
                "sender_type": clean_sender,
                "message_type": clean_msg_type,
            },
        )

        return msg

    def list_messages(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """List messages in chronological order for a conversation."""
        conversation = self.get_conversation(tenant_id, conversation_id)
        if conversation is None:
            raise ValueError(f"Conversation '{conversation_id}' not found")

        if limit < 1:
            raise ValueError("Limit must be greater than zero")
        if limit > 200:
            limit = 200

        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.tenant_id == tenant_id,
            )
            .order_by(Message.created_at.asc())
            .offset(offset)
            .limit(limit)
        )

        return list(self.db.scalars(stmt).all())
