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

    @staticmethod
    def sanitize_audit_metadata(metadata: dict | None) -> dict:
        """
        Sanitize audit metadata to strictly prevent leaking message text,
        customer credentials, API keys, or raw payloads.
        """
        if not metadata or not isinstance(metadata, dict):
            return {}

        sensitive_substrings = {
            "content", "message", "body", "text", "password", "token",
            "secret", "api_key", "authorization", "bearer", "raw_payload"
        }

        sanitized: dict = {}
        for key, value in metadata.items():
            norm_key = str(key).strip().lower()
            if any(sub in norm_key for sub in sensitive_substrings):
                continue

            if isinstance(value, dict):
                sanitized[key] = AuditService.sanitize_audit_metadata(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    AuditService.sanitize_audit_metadata(item) if isinstance(item, dict) else str(item)[:100]
                    for item in value[:20]
                ]
            elif isinstance(value, (int, float, bool)) or value is None:
                sanitized[key] = value
            else:
                str_val = str(value)
                if any(sub in str_val.lower() for sub in ("bearer ", "sk-", "token=")):
                    continue
                sanitized[key] = str_val[:200]

        return sanitized

    def record_access_event(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        resource_type: str,
        resource_id: UUID | str,
        action: str = "access_requested",
        reason: str | None = None,
        event_metadata: dict | None = None,
    ) -> AuditEvent:
        """
        Pre-fetch audit recording for sensitive data access.
        Enforces strict metadata sanitization to prevent leaks.
        """
        clean_metadata = self.sanitize_audit_metadata(event_metadata)
        clean_metadata["resource_type"] = resource_type
        clean_metadata["resource_id"] = str(resource_id)
        if reason:
            clean_metadata["access_reason"] = str(reason)[:250]

        description = (
            f"Administrative access to {resource_type} '{resource_id}' "
            f"requested by user '{user_id}' for tenant '{tenant_id}'."
        )

        return self.record_event(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=f"admin.{resource_type}.read",
            action=action,
            description=description,
            event_metadata=clean_metadata,
        )

    def update_access_event_status(
        self,
        event_id: UUID,
        status: str,
        extra_metadata: dict | None = None,
    ) -> AuditEvent | None:
        """
        Update the lifecycle status of an existing access audit record
        (e.g. from 'attempted' to 'disclosed' or 'fetch_failed').
        """
        statement = select(AuditEvent).where(AuditEvent.id == event_id)
        event = self.db.scalar(statement)
        if event is None:
            return None

        clean_extra = self.sanitize_audit_metadata(extra_metadata)
        updated_meta = dict(event.event_metadata or {})
        updated_meta["status"] = status
        updated_meta.update(clean_extra)
        event.event_metadata = updated_meta

        from sqlalchemy.orm.attributes import flag_modified
        try:
            flag_modified(event, "event_metadata")
        except Exception:
            pass

        self.db.flush()
        return event

