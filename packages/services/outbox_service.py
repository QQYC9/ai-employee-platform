from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session

from packages.models.domain import Conversation, Message, OutboxEvent
from packages.services.audit_service import AuditService

logger = logging.getLogger(__name__)

# Sensitive credential patterns to redact from safe error logs
SENSITIVE_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"sk-[0-9A-Za-z]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
    re.compile(r"(api[_-]?key|secret|password|access[_-]?token|auth)\s*[:=]\s*['\"]?[^'\"\s,;]+['\"]?", re.IGNORECASE),
]


def sanitize_error(text: str | None) -> str:
    """Mask credentials and authorization tokens from error messages."""
    if not text:
        return ""
    sanitized = str(text)
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


class OutboxService:
    """
    Manages persistent outbox events for asynchronous reliable messaging.

    Provides atomic event creation, PostgreSQL FOR UPDATE SKIP LOCKED concurrency control,
    stale worker crash recovery, bounded retry scheduling, and safe error recording.
    """

    ALLOWED_STATUSES = {"pending", "processing", "completed", "failed"}

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

    def create_event(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        idempotency_key: str,
        event_type: str = "process_incoming_message",
        payload: dict[str, Any] | None = None,
        scheduled_at: datetime | None = None,
        max_attempts: int = 5,
    ) -> OutboxEvent:
        """
        Record an outbox event in the current transaction.

        Does not commit; caller is responsible for committing atomically with
        the corresponding message.
        """
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            raise ValueError("idempotency_key cannot be empty")

        # 1. Check idempotency within tenant scope
        existing = self.db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.idempotency_key == clean_key,
            )
        )
        if existing is not None:
            logger.info(
                "Outbox event already exists for tenant %s with key %s (status=%s)",
                tenant_id,
                clean_key,
                existing.status,
            )
            return existing

        # 2. Validate conversation and message tenant boundaries
        conv = self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
        if conv is None:
            raise ValueError(f"Conversation '{conversation_id}' not found for tenant '{tenant_id}'")

        msg = self.db.scalar(
            select(Message).where(
                Message.id == message_id,
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
            )
        )
        if msg is None:
            raise ValueError(f"Message '{message_id}' not found in conversation '{conversation_id}' for tenant '{tenant_id}'")

        now = datetime.now(timezone.utc)
        event = OutboxEvent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            idempotency_key=clean_key,
            event_type=event_type,
            payload=payload or {},
            status="pending",
            attempt_count=0,
            max_attempts=max(1, max_attempts),
            scheduled_at=scheduled_at or now,
            created_at=now,
            updated_at=now,
        )

        self.db.add(event)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="outbox_event_created",
            action="create_outbox_event",
            description=f"Created outbox event for message {message_id}",
            event_metadata={
                "outbox_event_id": str(event.id),
                "conversation_id": str(conversation_id),
                "message_id": str(message_id),
                "idempotency_key": clean_key,
                "event_type": event_type,
            },
        )

        return event

    def get_event(self, tenant_id: UUID, event_id: UUID) -> OutboxEvent | None:
        """Fetch an outbox event strictly scoped to a tenant."""
        return self.db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.tenant_id == tenant_id,
            )
        )

    def get_event_by_idempotency_key(
        self, tenant_id: UUID, idempotency_key: str
    ) -> OutboxEvent | None:
        """Fetch an outbox event by tenant and idempotency key."""
        return self.db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.idempotency_key == idempotency_key.strip(),
            )
        )

    def claim_events(
        self,
        worker_id: str,
        *,
        tenant_id: UUID | None = None,
        batch_size: int = 10,
        lock_timeout_seconds: int = 300,
    ) -> list[OutboxEvent]:
        """
        Safely claim pending outbox events using PostgreSQL concurrency control.

        Uses FOR UPDATE SKIP LOCKED on PostgreSQL to prevent race conditions
        and deadlocks across multiple workers.
        Immediately commits the lock acquisition.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                OutboxEvent.scheduled_at <= now,
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(OutboxEvent.tenant_id == tenant_id)

        stmt = stmt.order_by(OutboxEvent.scheduled_at.asc(), OutboxEvent.created_at.asc()).limit(batch_size)


        # Use SKIP LOCKED on PostgreSQL
        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        else:
            # Fallback for SQLite in lightweight tests
            try:
                stmt = stmt.with_for_update()
            except Exception:
                pass

        claimed_rows = list(self.db.scalars(stmt).all())
        if not claimed_rows:
            return []

        lock_expiry = now + timedelta(seconds=lock_timeout_seconds)
        for row in claimed_rows:
            row.status = "processing"
            row.attempt_count += 1
            row.locked_at = now
            row.locked_by = worker_id
            row.lock_expires_at = lock_expiry
            row.updated_at = now

        self.db.commit()
        return claimed_rows

    def mark_completed(
        self,
        event_id: UUID,
        *,
        processed_at: datetime | None = None,
    ) -> OutboxEvent | None:
        """Mark an outbox event as successfully completed."""
        event = self.db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
        if event is None:
            return None

        now = processed_at or datetime.now(timezone.utc)
        event.status = "completed"
        event.processed_at = now
        event.locked_at = None
        event.locked_by = None
        event.lock_expires_at = None
        event.error_message = None
        event.updated_at = now
        self.db.flush()
        return event

    def mark_failed(
        self,
        event_id: UUID,
        error_message: str,
        *,
        is_transient: bool = True,
        backoff_seconds: float | None = None,
    ) -> OutboxEvent | None:
        """
        Record failure for an event.

        If transient and within max_attempts, schedules for retry with backoff.
        If permanent or retry limit exceeded, marks as failed.
        """
        event = self.db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
        if event is None:
            return None

        now = datetime.now(timezone.utc)
        clean_error = sanitize_error(error_message)

        if is_transient and event.attempt_count < event.max_attempts:
            delay = backoff_seconds if backoff_seconds is not None else 2.0
            event.status = "pending"
            event.scheduled_at = now + timedelta(seconds=delay)
            event.error_message = clean_error
            event.locked_at = None
            event.locked_by = None
            event.lock_expires_at = None
            event.updated_at = now
            logger.info(
                "Scheduled retry %d/%d for event %s in %.1fs: %s",
                event.attempt_count,
                event.max_attempts,
                event_id,
                delay,
                clean_error,
            )
        else:
            event.status = "failed"
            prefix = "Permanent failure" if not is_transient else f"Max retry attempts ({event.max_attempts}) exceeded"
            event.error_message = f"{prefix}: {clean_error}"
            event.locked_at = None
            event.locked_by = None
            event.lock_expires_at = None
            event.updated_at = now
            logger.warning("Event %s marked failed: %s", event_id, event.error_message)

        self.db.flush()
        return event

    def recover_stale_events(
        self,
        *,
        tenant_id: UUID | None = None,
        worker_id: str | None = None,
        lock_timeout_seconds: int = 300,
    ) -> list[OutboxEvent]:
        """
        Recover events left in 'processing' status after worker crash or stall.

        Identifies events where lock_expires_at <= now().
        Resets retryable events to 'pending' and exhausts ones that reached max_attempts.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "processing",
                or_(
                    OutboxEvent.lock_expires_at <= now,
                    and_(
                        OutboxEvent.lock_expires_at.is_(None),
                        OutboxEvent.locked_at <= now - timedelta(seconds=lock_timeout_seconds),
                    ),
                ),
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(OutboxEvent.tenant_id == tenant_id)

        stmt = stmt.order_by(OutboxEvent.locked_at.asc())


        bind = self.db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        else:
            try:
                stmt = stmt.with_for_update()
            except Exception:
                pass

        stale_events = list(self.db.scalars(stmt).all())
        if not stale_events:
            return []

        recovered: list[OutboxEvent] = []
        for event in stale_events:
            event.locked_at = None
            event.locked_by = None
            event.lock_expires_at = None
            event.updated_at = now

            if event.attempt_count < event.max_attempts:
                event.status = "pending"
                # Schedule for immediate recovery retry
                event.scheduled_at = now
                event.error_message = f"Recovered from stalled worker crash at {now.isoformat()}"
                recovered.append(event)
                logger.info("Recovered crashed event %s back to pending", event.id)
            else:
                event.status = "failed"
                event.error_message = f"Worker crash recovery exceeded max attempts ({event.max_attempts})"
                recovered.append(event)
                logger.warning("Crashed event %s marked failed after exceeding max attempts", event.id)

        self.db.commit()
        return recovered
