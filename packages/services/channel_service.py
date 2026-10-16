from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Channel
from packages.services.audit_service import AuditService


class ChannelService:
    """
    Business logic for communication channel management.

    Channels connect Digital Employees to external messaging platforms
    (WebChat, WhatsApp, Email, Slack, API).
    """

    ALLOWED_CHANNEL_TYPES = {"webchat", "whatsapp", "email", "slack", "api", "telegram", "sms"}
    ALLOWED_STATUSES = {"active", "inactive", "maintenance", "deleted"}

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

    def register_channel(
        self,
        tenant_id: UUID,
        name: str,
        channel_type: str,
        provider: str | None = None,
        config: dict | None = None,
    ) -> Channel:
        """Register and configure a communication channel for the tenant."""
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Channel name cannot be empty")

        clean_type = (channel_type or "").strip().lower()
        if clean_type not in self.ALLOWED_CHANNEL_TYPES:
            raise ValueError(f"Unsupported channel type: '{channel_type}'")

        channel = Channel(
            tenant_id=tenant_id,
            name=clean_name,
            channel_type=clean_type,
            provider=provider.strip() if provider and provider.strip() else None,
            status="active",
            config=config or {},
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
        """Update an existing channel configuration."""
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
            updated_cfg = dict(channel.config or {})
            updated_cfg.update(config)
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
