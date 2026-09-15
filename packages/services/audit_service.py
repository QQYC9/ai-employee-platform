from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import AuditEvent


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def record_event(
        self,
        *,
        tenant_id: UUID | None = None,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        event_type: str,
        action: str | None = None,
        description: str | None = None,
        event_metadata: dict | None = None,
    ) -> AuditEvent:
        event_type = event_type.strip()

        if not event_type:
            raise ValueError("Event type cannot be empty")

        event = AuditEvent(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            event_type=event_type,
            action=action,
            description=description,
            event_metadata=event_metadata or {},
        )

        self.db.add(event)
        self.db.flush()

        return event

    def list_events(
        self,
        tenant_id: UUID,
        *,
        event_type: str | None = None,
        action: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        if limit < 1:
            raise ValueError("Limit must be greater than zero")

        if limit > 500:
            limit = 500

        statement = (
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )

        if event_type is not None:
            statement = statement.where(
                AuditEvent.event_type == event_type
            )

        if action is not None:
            statement = statement.where(
                AuditEvent.action == action
            )

        if agent_id is not None:
            statement = statement.where(
                AuditEvent.agent_id == agent_id
            )

        return list(self.db.scalars(statement).all())

    def get_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
    ) -> AuditEvent | None:
        statement = select(AuditEvent).where(
            AuditEvent.id == event_id,
            AuditEvent.tenant_id == tenant_id,
        )

        return self.db.scalar(statement)
