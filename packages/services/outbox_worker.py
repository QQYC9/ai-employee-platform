from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProvider, AIProviderError, AIProviderTimeoutError
from packages.core.database import SessionLocal
from packages.models.domain import Conversation, Message, OutboxEvent
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.outbox_service import OutboxService, sanitize_error

logger = logging.getLogger(__name__)


def is_transient_error(error: Exception | str) -> bool:
    """
    Classify whether an exception or error string represents a transient/recoverable failure
    or an unrecoverable permanent error.
    """
    if isinstance(error, (AIProviderTimeoutError, TimeoutError)):
        return True

    if isinstance(error, Exception):
        exc_name = type(error).__name__.lower()
        exc_msg = str(error).lower()
        # Permanent python exceptions: Validation, not found, tenant mismatch, bad auth
        if isinstance(error, (ValueError, KeyError, TypeError, AttributeError)):
            return False
    else:
        exc_name = ""
        exc_msg = str(error).lower()

    # Permanent error indicators
    permanent_indicators = [
        "not found",
        "blocked",
        "forbidden",
        "unauthorized",
        "invalid sender",
        "tampering",
        "unsupported",
        "permanent",
        "rejected invalid",
        "validation failure",
        "malformed",
    ]
    for ind in permanent_indicators:
        if ind in exc_msg:
            return False

    # Network / Connection / Timeout indicators
    transient_indicators = [
        "timeout",
        "timed out",
        "connection reset",
        "connection refused",
        "connection error",
        "temporarily unavailable",
        "rate limit",
        "rate_limit",
        "429",
        "502",
        "503",
        "504",
        "overloaded",
        "try again",
        "transient",
        "deadlock detected",
        "lock not available",
    ]
    for ind in transient_indicators:
        if ind in exc_msg or ind in exc_name:
            return True

    if isinstance(error, (AIProviderError, IOError, OSError)):
        return True

    return False



class OutboxWorker:
    """
    Background worker for asynchronous customer message processing via transactional outbox.

    Features:
      - PostgreSQL FOR UPDATE SKIP LOCKED concurrency control.
      - Independent, correctly scoped database session per event.
      - Tenant isolation enforcement.
      - Stale worker crash recovery.
      - Bounded exponential backoff for transient failures.
      - Immediate permanent failure handling.
      - Graceful shutdown support.
      - Complete secret sanitization in logs and records.
    """

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        tenant_id: UUID | None = None,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 10,
        lock_timeout_seconds: int = 300,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 300.0,
        backoff_factor: float = 2.0,
        session_factory: Callable[[], Session] = SessionLocal,
        ai_provider: AIProvider | None = None,
    ):
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.tenant_id = tenant_id
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self.lock_timeout_seconds = lock_timeout_seconds
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.backoff_factor = backoff_factor
        self.session_factory = session_factory
        self.ai_provider = ai_provider

        self._stop_event = threading.Event()
        self._is_running = False


    def stop(self) -> None:
        """Signal the worker to stop gracefully."""
        self._stop_event.set()
        self._is_running = False
        logger.info("Worker %s stop requested", self.worker_id)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def calculate_backoff(self, attempt_count: int) -> float:
        """Calculate bounded exponential backoff delay in seconds."""
        delay = self.base_backoff_seconds * (self.backoff_factor ** max(0, attempt_count - 1))
        return min(delay, self.max_backoff_seconds)

    def process_event(self, event_id: UUID) -> bool:
        """
        Process a single claimed outbox event within its tenant context using an
        isolated database session.
        """
        # Session 1: Process and record
        with self.session_factory() as session:
            outbox_service = OutboxService(session)
            event = session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
            if event is None:
                logger.warning("Worker %s: event %s not found", self.worker_id, event_id)
                return False

            tenant_id = event.tenant_id
            message_id = event.message_id
            conversation_id = event.conversation_id
            attempt_count = event.attempt_count

            # 1. Tenant boundary validation
            msg = session.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.tenant_id == tenant_id,
                )
            )
            conv = session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )

            if msg is None or conv is None:
                err_msg = f"Tenant boundary violation or entity not found (message={message_id}, conv={conversation_id})"
                logger.error("Worker %s: %s", self.worker_id, err_msg)
                outbox_service.mark_failed(event_id, err_msg, is_transient=False)
                session.commit()
                return False

            # 2. Prevent re-ingesting agent-generated replies as incoming customer messages
            sender_type = (msg.sender_type or "").strip().lower()
            if sender_type not in ConversationalAgentEngine.ALLOWED_INPUT_SENDERS:
                err_msg = f"Skipping event: sender_type '{sender_type}' is not an inbound customer message"
                logger.info("Worker %s: %s", self.worker_id, err_msg)
                outbox_service.mark_completed(event_id)
                session.commit()
                return True

            # 3. Call ConversationalAgentEngine
            engine = ConversationalAgentEngine(db=session, ai_provider=self.ai_provider)
            try:
                result = engine.process_incoming_message(
                    tenant_id=tenant_id,
                    message_id=message_id,
                )

                if result.success:
                    # Successfully processed or safely skipped (e.g. duplicate or blocked customer)
                    outbox_service.mark_completed(event_id)
                    session.commit()
                    logger.info(
                        "Worker %s successfully completed event %s for message %s (reply=%s, skipped=%s)",
                        self.worker_id,
                        event_id,
                        message_id,
                        result.reply_message_id,
                        result.skipped,
                    )
                    return True
                else:
                    # Engine reported an unhandled failure
                    session.rollback()
                    error_msg = result.error or "Agent generation failed"
                    is_transient = is_transient_error(error_msg)
                    backoff = self.calculate_backoff(attempt_count)
                    self._record_failure(event_id, error_msg, is_transient=is_transient, backoff_seconds=backoff)
                    return False


            except Exception as exc:
                session.rollback()
                raw_err = sanitize_error(str(exc))
                is_transient = is_transient_error(exc)
                backoff = self.calculate_backoff(attempt_count)
                logger.warning(
                    "Worker %s: error processing event %s (attempt %d, transient=%s): %s",
                    self.worker_id,
                    event_id,
                    attempt_count,
                    is_transient,
                    raw_err,
                )
                self._record_failure(event_id, raw_err, is_transient=is_transient, backoff_seconds=backoff)
                return False

    def _record_failure(
        self,
        event_id: UUID,
        error_message: str,
        *,
        is_transient: bool,
        backoff_seconds: float,
    ) -> None:
        """Record event failure in a clean database transaction."""
        with self.session_factory() as session:
            service = OutboxService(session)
            service.mark_failed(
                event_id,
                error_message,
                is_transient=is_transient,
                backoff_seconds=backoff_seconds,
            )
            session.commit()

    def run_once(self) -> int:
        """
        Execute a single polling iteration:
          1. Recovers any stale events left by crashed workers.
          2. Safely claims up to batch_size pending events with FOR UPDATE SKIP LOCKED.
          3. Processes each event in an independent session.

        Returns the number of events processed.
        """
        # Step 1: Recover stale events
        with self.session_factory() as session:
            service = OutboxService(session)
            service.recover_stale_events(
                tenant_id=self.tenant_id,
                worker_id=self.worker_id,
                lock_timeout_seconds=self.lock_timeout_seconds,
            )

        # Step 2: Claim events
        claimed_ids: list[UUID] = []
        with self.session_factory() as session:
            service = OutboxService(session)
            claimed = service.claim_events(
                self.worker_id,
                tenant_id=self.tenant_id,
                batch_size=self.batch_size,
                lock_timeout_seconds=self.lock_timeout_seconds,
            )
            claimed_ids = [e.id for e in claimed]


        if not claimed_ids:
            return 0

        # Step 3: Process each claimed event independently
        processed_count = 0
        for event_id in claimed_ids:
            if self._stop_event.is_set():
                logger.info("Worker %s stopping mid-batch", self.worker_id)
                break
            success = self.process_event(event_id)
            if success:
                processed_count += 1

        return processed_count

    def run(self, max_iterations: int | None = None) -> None:
        """
        Continuously poll and process events until stopped or max_iterations reached.
        """
        self._is_running = True
        self._stop_event.clear()
        iterations = 0

        logger.info("Starting outbox worker %s", self.worker_id)
        try:
            while not self._stop_event.is_set():
                if max_iterations is not None and iterations >= max_iterations:
                    break

                try:
                    count = self.run_once()
                    iterations += 1
                    if count == 0:
                        # Back off slightly when queue is empty
                        time.sleep(self.poll_interval_seconds)
                except Exception as exc:
                    logger.error("Unexpected worker loop error in %s: %s", self.worker_id, exc)
                    time.sleep(self.poll_interval_seconds)
        finally:
            self._is_running = False
            logger.info("Outbox worker %s stopped", self.worker_id)


def main() -> None:
    from apps.worker import main as worker_main
    worker_main()


if __name__ == "__main__":
    main()

