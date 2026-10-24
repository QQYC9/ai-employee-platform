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
from packages.models.domain import Campaign, CampaignRecipient, Channel, Conversation, Message, OutboxEvent
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.services.outbox_service import OutboxService, sanitize_error
from sqlalchemy.orm.attributes import flag_modified

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
        channel_service: Any = None,
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
        self.channel_service = channel_service

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

            # Handle escalation notification to owner
            if event.event_type == "notify_owner_escalation":
                success = self._handle_owner_escalation(session, event)
                if success:
                    outbox_service.mark_completed(event_id)
                    session.commit()
                    return True
                else:
                    err_msg = "Failed to deliver escalation alert to owner channel"
                    is_transient = is_transient_error(err_msg)
                    backoff = self.calculate_backoff(attempt_count)
                    self._record_failure(event_id, err_msg, is_transient=is_transient, backoff_seconds=backoff)
                    return False

            # Handle task notification to owner
            if event.event_type == "notify_owner_task_result":
                success = self._handle_owner_task_notification(session, event)
                if success:
                    outbox_service.mark_completed(event_id)
                    session.commit()
                    return True
                else:
                    err_msg = "Failed to deliver task notification to owner channel"
                    is_transient = is_transient_error(err_msg)
                    backoff = self.calculate_backoff(attempt_count)
                    self._record_failure(event_id, err_msg, is_transient=is_transient, backoff_seconds=backoff)
                    return False

            # Handle dedicated channel reply dispatch event
            if event.event_type == "dispatch_channel_reply":
                return self._handle_dispatch_channel_reply(session, event)

            # Handle campaign outbound message dispatch
            if event.event_type == "dispatch_campaign_message":
                return self._handle_dispatch_campaign_message(session, event)

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

            # -------------------------------------------------------------
            # STEP A: Check if a reply was ALREADY generated and committed
            # (e.g. from an earlier attempt whose outbound delivery failed)
            # -------------------------------------------------------------
            existing_reply = session.scalar(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.tenant_id == tenant_id,
                    Message.sender_type == "agent",
                    Message.metadata_json["in_reply_to_message_id"].as_string() == str(message_id),
                )
            )

            if existing_reply is not None:
                # Business transaction was ALREADY executed and committed!
                # Reuse existing reply directly without re-executing business tools or AI.
                reply_rec = existing_reply
                reply_content = existing_reply.content
                reply_message_id = existing_reply.id
                result_skipped = False
                logger.info(
                    "Worker %s: Reusing committed reply %s for event %s (skipping business re-execution)",
                    self.worker_id,
                    existing_reply.id,
                    event_id,
                )
            else:
                # -------------------------------------------------------------
                # STEP B: Execute Business Operations & Generate Reply (Transaction 1)
                # -------------------------------------------------------------
                engine = ConversationalAgentEngine(db=session, ai_provider=self.ai_provider)
                try:
                    result = engine.process_incoming_message(
                        tenant_id=tenant_id,
                        message_id=message_id,
                    )
                except Exception as exc:
                    session.rollback()
                    raw_err = sanitize_error(str(exc))
                    is_transient = is_transient_error(exc)
                    backoff = self.calculate_backoff(attempt_count)
                    self._record_failure(event_id, raw_err, is_transient=is_transient, backoff_seconds=backoff)
                    return False

                if not result.success:
                    session.rollback()
                    error_msg = result.error or "Agent generation failed"
                    is_transient = is_transient_error(error_msg)
                    backoff = self.calculate_backoff(attempt_count)
                    self._record_failure(event_id, error_msg, is_transient=is_transient, backoff_seconds=backoff)
                    return False

                # ATOMIC COMMIT FOR TRANSACTION 1:
                # All business operations, state updates, and reply message
                # are committed to PostgreSQL right here.
                if result.reply_message_id:
                    ep = dict(event.payload or {})
                    ep["reply_message_id"] = str(result.reply_message_id)
                    event.payload = ep
                    flag_modified(event, "payload")

                session.commit()

                reply_content = result.reply_content
                reply_message_id = result.reply_message_id
                result_skipped = result.skipped
                reply_rec = None
                if reply_message_id:
                    reply_rec = session.scalar(select(Message).where(Message.id == reply_message_id))

            # -------------------------------------------------------------
            # STEP C: Channel Delivery (Transaction 2)
            # -------------------------------------------------------------
            if not reply_content or result_skipped:
                outbox_service.mark_completed(event_id)
                session.commit()
                return True

            is_already_delivered = reply_rec and (reply_rec.metadata_json or {}).get("delivery_status") == "delivered"
            if is_already_delivered:
                outbox_service.mark_completed(event_id)
                session.commit()
                return True

            ch_id_val = (event.payload or {}).get("channel_id") or (str(conv.channel_id) if conv.channel_id else None)
            if not ch_id_val:
                outbox_service.mark_completed(event_id)
                session.commit()
                return True

            channel = session.scalar(select(Channel).where(Channel.id == UUID(ch_id_val)))
            if not channel or channel.channel_type not in ("whatsapp", "telegram", "email", "sms"):
                outbox_service.mark_completed(event_id)
                session.commit()
                return True

            # Resolve recipient: chat_id (recipient_id) takes precedence for Telegram, followed by sender_id
            recipient_val = (
                (event.payload or {}).get("recipient_id")
                or (msg.metadata_json or {}).get("recipient_id")
                or (event.payload or {}).get("sender_id")
                or (msg.metadata_json or {}).get("sender_id")
            )

            # Fallback: resolve customer contact details if recipient was not in payload
            if not recipient_val and conv.customer_id:
                cust = session.scalar(
                    select(Customer).where(
                        Customer.id == conv.customer_id,
                        Customer.tenant_id == tenant_id,
                    )
                )
                if cust:
                    if channel.channel_type in ("whatsapp", "sms"):
                        recipient_val = cust.phone
                    elif channel.channel_type == "email":
                        recipient_val = cust.email
                    elif channel.channel_type == "telegram":
                        recipient_val = (cust.metadata_json or {}).get("telegram_id")

            if not recipient_val:
                outbox_service.mark_completed(event_id)
                session.commit()
                return True

            from packages.services.channel_service import ChannelService
            chan_service = self.channel_service or ChannelService(session)

            try:
                deliv_res = chan_service.send_channel_message(
                    tenant_id=tenant_id,
                    channel_id=channel.id,
                    recipient=str(recipient_val),
                    content=reply_content,
                )
                if not deliv_res.success:
                    session.rollback()
                    err_msg = deliv_res.error or "Failed to deliver message to channel"
                    is_transient = is_transient_error(err_msg)
                    backoff = self.calculate_backoff(attempt_count)
                    self._record_failure(event_id, err_msg, is_transient=is_transient, backoff_seconds=backoff)
                    return False

                # Record delivery confirmation
                if reply_rec:
                    rm = dict(reply_rec.metadata_json or {})
                    rm["delivery_status"] = "delivered"
                    rm["external_message_id"] = deliv_res.external_message_id
                    rm["delivered_at"] = datetime.now(timezone.utc).isoformat()
                    reply_rec.metadata_json = rm
                    flag_modified(reply_rec, "metadata_json")
                    session.flush()

                outbox_service.mark_completed(event_id)
                session.commit()
                logger.info(
                    "Worker %s successfully completed event %s for message %s (reply=%s)",
                    self.worker_id,
                    event_id,
                    message_id,
                    reply_message_id,
                )
                return True
            except Exception as exc:
                session.rollback()
                raw_err = sanitize_error(str(exc))
                is_transient = is_transient_error(exc)
                backoff = self.calculate_backoff(attempt_count)
                self._record_failure(event_id, raw_err, is_transient=is_transient, backoff_seconds=backoff)
                return False

    def _handle_dispatch_channel_reply(self, session: Session, event: OutboxEvent) -> bool:
        """
        Dispatches an outbound channel reply independently from business operations.
        Ensures delivery retries never re-execute business logic.
        """
        payload = dict(event.payload or {})
        tenant_id = event.tenant_id
        attempt_count = event.attempt_count
        ch_id_str = payload.get("channel_id")
        recipient = payload.get("recipient") or payload.get("recipient_id") or payload.get("sender_id")
        content = payload.get("content")
        reply_msg_id_str = payload.get("reply_message_id")

        if not ch_id_str or not recipient or not content:
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        reply_rec = None
        if reply_msg_id_str:
            reply_rec = session.scalar(select(Message).where(Message.id == UUID(reply_msg_id_str)))
            if reply_rec and (reply_rec.metadata_json or {}).get("delivery_status") == "delivered":
                OutboxService(session).mark_completed(event.id)
                session.commit()
                return True

        channel = session.scalar(select(Channel).where(Channel.id == UUID(ch_id_str)))
        if not channel or channel.status != "active":
            err_msg = f"Channel {ch_id_str} not found or inactive"
            self._record_failure(event.id, err_msg, is_transient=False, backoff_seconds=0)
            return False

        from packages.services.channel_service import ChannelService
        chan_service = self.channel_service or ChannelService(session)

        try:
            deliv_res = chan_service.send_channel_message(
                tenant_id=tenant_id,
                channel_id=channel.id,
                recipient=str(recipient),
                content=content,
            )
            if not deliv_res.success:
                session.rollback()
                err_msg = deliv_res.error or "Failed to deliver message to channel"
                is_transient = is_transient_error(err_msg)
                backoff = self.calculate_backoff(attempt_count)
                self._record_failure(event.id, err_msg, is_transient=is_transient, backoff_seconds=backoff)
                return False

            if reply_rec:
                rm = dict(reply_rec.metadata_json or {})
                rm["delivery_status"] = "delivered"
                rm["external_message_id"] = deliv_res.external_message_id
                rm["delivered_at"] = datetime.now(timezone.utc).isoformat()
                reply_rec.metadata_json = rm
                flag_modified(reply_rec, "metadata_json")
                session.flush()

            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True
        except Exception as exc:
            session.rollback()
            raw_err = sanitize_error(str(exc))
            is_transient = is_transient_error(exc)
            backoff = self.calculate_backoff(attempt_count)
            self._record_failure(event.id, raw_err, is_transient=is_transient, backoff_seconds=backoff)
            return False

    def _handle_dispatch_campaign_message(self, session: Session, event: OutboxEvent) -> bool:
        """
        Dispatches a campaign message to a recipient via the designated channel.
        Updates recipient delivery status, campaign metrics, and completes campaign
        when all recipients are processed.
        """
        from sqlalchemy import func
        from packages.services.channel_service import ChannelService

        payload = dict(event.payload or {})
        tenant_id = event.tenant_id
        attempt_count = event.attempt_count
        campaign_id_str = payload.get("campaign_id")
        recipient_id_str = payload.get("recipient_id")
        channel_id_str = payload.get("channel_id")
        recipient_address = payload.get("recipient_address")
        content = payload.get("content")
        msg_id_str = payload.get("message_id")

        if not recipient_id_str or not campaign_id_str:
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        campaign_id = UUID(campaign_id_str)
        recipient_id = UUID(recipient_id_str)

        recipient = session.scalar(
            select(CampaignRecipient).where(
                CampaignRecipient.id == recipient_id,
                CampaignRecipient.tenant_id == tenant_id,
            )
        )
        if not recipient:
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        # If already delivered or skipped, do not re-send
        if recipient.status in ("delivered", "skipped"):
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        campaign = session.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_id == tenant_id,
            )
        )
        if not campaign:
            recipient.status = "skipped"
            recipient.skip_reason = "campaign_deleted"
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        if campaign.status == "cancelled":
            recipient.status = "skipped"
            recipient.skip_reason = "campaign_cancelled"
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        if campaign.status == "paused":
            # Postpone dispatch while paused
            return False

        if not channel_id_str or not recipient_address or not content:
            recipient.status = "failed"
            recipient.error_message = "Missing channel, recipient address, or content"
            metrics = dict(campaign.metrics or {})
            metrics["failed_count"] = (metrics.get("failed_count") or 0) + 1
            campaign.metrics = metrics
            flag_modified(campaign, "metrics")
            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        channel = session.scalar(
            select(Channel).where(
                Channel.id == UUID(channel_id_str),
                Channel.tenant_id == tenant_id,
            )
        )
        if not channel or channel.status != "active":
            err_msg = f"Channel {channel_id_str} not found or inactive"
            recipient.status = "failed"
            recipient.error_message = err_msg
            metrics = dict(campaign.metrics or {})
            metrics["failed_count"] = (metrics.get("failed_count") or 0) + 1
            campaign.metrics = metrics
            flag_modified(campaign, "metrics")
            self._record_failure(event.id, err_msg, is_transient=False, backoff_seconds=0)
            return False

        chan_service = self.channel_service or ChannelService(session)

        try:
            deliv_res = chan_service.send_channel_message(
                tenant_id=tenant_id,
                channel_id=channel.id,
                recipient=str(recipient_address),
                content=content,
            )

            if not deliv_res.success:
                session.rollback()
                err_msg = deliv_res.error or "Failed to deliver campaign message to channel"
                is_transient = is_transient_error(err_msg)
                backoff = self.calculate_backoff(attempt_count)

                if not is_transient or (attempt_count + 1 >= event.max_attempts):
                    # Mark recipient failed permanently
                    with self.session_factory() as fail_session:
                        fail_rec = fail_session.scalar(
                            select(CampaignRecipient).where(CampaignRecipient.id == recipient_id)
                        )
                        if fail_rec:
                            fail_rec.status = "failed"
                            fail_rec.error_message = err_msg
                        fail_camp = fail_session.scalar(
                            select(Campaign).where(Campaign.id == campaign_id)
                        )
                        if fail_camp:
                            m = dict(fail_camp.metrics or {})
                            m["failed_count"] = (m.get("failed_count") or 0) + 1
                            fail_camp.metrics = m
                            flag_modified(fail_camp, "metrics")
                        fail_session.commit()

                self._record_failure(event.id, err_msg, is_transient=is_transient, backoff_seconds=backoff)
                return False

            # Delivery succeeded
            recipient.status = "delivered"
            recipient.delivered_at = datetime.now(timezone.utc)

            if msg_id_str:
                reply_rec = session.scalar(select(Message).where(Message.id == UUID(msg_id_str)))
                if reply_rec:
                    rm = dict(reply_rec.metadata_json or {})
                    rm["delivery_status"] = "delivered"
                    rm["external_message_id"] = deliv_res.external_message_id
                    rm["delivered_at"] = datetime.now(timezone.utc).isoformat()
                    reply_rec.metadata_json = rm
                    flag_modified(reply_rec, "metadata_json")

            metrics = dict(campaign.metrics or {})
            metrics["delivered_count"] = (metrics.get("delivered_count") or 0) + 1
            metrics["sent_count"] = (metrics.get("sent_count") or 0) + 1
            campaign.metrics = metrics
            flag_modified(campaign, "metrics")

            session.flush()

            # Check if all recipients for this campaign have completed
            remaining_active = session.scalar(
                select(func.count()).select_from(CampaignRecipient).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.tenant_id == tenant_id,
                    CampaignRecipient.status.in_(["pending", "enqueued"]),
                )
            ) or 0

            if remaining_active == 0 and campaign.status == "running":
                campaign.status = "completed"
                campaign.completed_at = datetime.now(timezone.utc)

            OutboxService(session).mark_completed(event.id)
            session.commit()
            return True

        except Exception as exc:
            session.rollback()
            raw_err = sanitize_error(str(exc))
            is_transient = is_transient_error(exc)
            backoff = self.calculate_backoff(attempt_count)
            self._record_failure(event.id, raw_err, is_transient=is_transient, backoff_seconds=backoff)
            return False

    def _handle_owner_escalation(self, session: Session, event: OutboxEvent) -> bool:
        """Sends an escalation notification alert to the business owner via their channel."""
        payload = dict(event.payload or {})
        tenant_id = event.tenant_id
        channel_id_str = payload.get("channel_id")
        if not channel_id_str:
            return True

        channel = session.scalar(select(Channel).where(Channel.id == UUID(channel_id_str)))
        if not channel:
            return True

        from packages.services.channel_service import ChannelService
        chan_service = self.channel_service or ChannelService(session)

        # Resolve owner identifier from channel config
        config = dict(channel.config or {})
        owner_recipient = (
            config.get("owner_phone")
            or config.get("owner_telegram_id")
            or config.get("owner_id")
        )
        if not owner_recipient:
            raw_ids = config.get("owner_identifiers") or []
            if isinstance(raw_ids, list) and raw_ids:
                owner_recipient = str(raw_ids[0])
            elif isinstance(raw_ids, str):
                owner_recipient = raw_ids

        if not owner_recipient:
            logger.info("Worker %s: No owner recipient configured for channel %s, skipping escalation dispatch", self.worker_id, channel.id)
            return True

        cust_name = payload.get("customer_name") or "عميل"
        cust_sender = payload.get("customer_sender_id") or ""
        msg_preview = payload.get("message_content") or ""
        alert_text = (
            f"🚨 تنبيه تصعيد بشري عاجل:\n"
            f"العميل: {cust_name} ({cust_sender})\n"
            f"طلب التحدث مع شخص حقيقي.\n"
            f"نص الرسالة: \"{msg_preview[:120]}\"\n"
            f"يرجى التواصل مع العميل لمتابعة الطلب."
        )

        try:
            res = chan_service.send_channel_message(
                tenant_id=tenant_id,
                channel_id=channel.id,
                recipient=str(owner_recipient),
                content=alert_text,
            )
            return res.success
        except Exception as exc:
            logger.warning("Worker %s: Failed to send escalation alert to owner: %s", self.worker_id, exc)
            return False

    def _handle_owner_task_notification(self, session: Session, event: OutboxEvent) -> bool:
        """Sends task completion or failure notification to the business owner."""
        payload = dict(event.payload or {})
        tenant_id = event.tenant_id
        channel_id_str = payload.get("channel_id")
        if not channel_id_str:
            return True

        channel = session.scalar(select(Channel).where(Channel.id == UUID(channel_id_str)))
        if not channel:
            return True

        from packages.services.channel_service import ChannelService
        chan_service = self.channel_service or ChannelService(session)

        config = dict(channel.config or {})
        owner_recipient = (
            config.get("owner_phone")
            or config.get("owner_telegram_id")
            or config.get("owner_id")
        )
        if not owner_recipient:
            raw_ids = config.get("owner_identifiers") or []
            if isinstance(raw_ids, list) and raw_ids:
                owner_recipient = str(raw_ids[0])
            elif isinstance(raw_ids, str):
                owner_recipient = raw_ids

        if not owner_recipient:
            return True

        task_title = payload.get("task_title") or "المهمة"
        status_val = payload.get("status") or "مكتملة"
        reason = payload.get("reason") or ""
        alert_text = (
            f"📢 إشعار بنتيجة المهمة:\n"
            f"- المهمة: {task_title}\n"
            f"- الحالة: {status_val}\n"
            + (f"- السبب / التفاصيل: {reason}\n" if reason else "")
        )

        try:
            res = chan_service.send_channel_message(
                tenant_id=tenant_id,
                channel_id=channel.id,
                recipient=str(owner_recipient),
                content=alert_text,
            )
            return res.success
        except Exception as exc:
            logger.warning("Worker %s: Failed to send task notification to owner: %s", self.worker_id, exc)
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

    def process_workflow_run(self, run_id: UUID) -> bool:
        """Process a single proactive workflow run in an independent database transaction."""
        from packages.services.proactive_workflow_service import ProactiveWorkflowService
        with self.session_factory() as session:
            try:
                service = ProactiveWorkflowService(session)
                success = service.execute_run(run_id)
                session.commit()
                return success
            except Exception as exc:
                session.rollback()
                logger.error("Worker %s: error executing proactive workflow run %s: %s", self.worker_id, run_id, exc)
                return False

    def run_once(self) -> int:
        """
        Execute a single polling iteration:
          1. Recovers any stale events/runs left by crashed workers.
          2. Spawns runs for any due proactive workflows (interval/cron).
          3. Safely claims up to batch_size pending outbox events and proactive runs with FOR UPDATE SKIP LOCKED.
          4. Processes each item in an independent session.

        Returns the number of events/runs processed.
        """
        from packages.services.proactive_workflow_service import ProactiveWorkflowService

        # Step 1: Recover stale events and runs
        with self.session_factory() as session:
            service = OutboxService(session)
            service.recover_stale_events(
                tenant_id=self.tenant_id,
                worker_id=self.worker_id,
                lock_timeout_seconds=self.lock_timeout_seconds,
            )
            wf_service = ProactiveWorkflowService(session)
            wf_service.recover_stale_runs(stale_threshold_seconds=self.lock_timeout_seconds)
            session.commit()

        # Step 2: Spawn runs for due proactive workflows
        with self.session_factory() as session:
            wf_service = ProactiveWorkflowService(session)
            wf_service.spawn_due_workflow_runs(limit=self.batch_size)
            session.commit()

        # Step 3: Claim pending outbox events
        claimed_event_ids: list[UUID] = []
        with self.session_factory() as session:
            service = OutboxService(session)
            claimed = service.claim_events(
                self.worker_id,
                tenant_id=self.tenant_id,
                batch_size=self.batch_size,
                lock_timeout_seconds=self.lock_timeout_seconds,
            )
            claimed_event_ids = [e.id for e in claimed]

        # Step 4: Claim pending proactive workflow runs
        claimed_run_ids: list[UUID] = []
        with self.session_factory() as session:
            wf_service = ProactiveWorkflowService(session)
            claimed_runs = wf_service.claim_due_runs(
                worker_id=self.worker_id,
                batch_size=self.batch_size,
                tenant_id=self.tenant_id,
                lock_timeout_seconds=self.lock_timeout_seconds,
            )
            claimed_run_ids = [r.id for r in claimed_runs]
            session.commit()

        processed_count = 0

        # Step 5: Process claimed outbox events independently
        for event_id in claimed_event_ids:
            if self._stop_event.is_set():
                logger.info("Worker %s stopping mid-batch", self.worker_id)
                break
            if self.process_event(event_id):
                processed_count += 1

        # Step 6: Process claimed proactive workflow runs independently
        for run_id in claimed_run_ids:
            if self._stop_event.is_set():
                logger.info("Worker %s stopping mid-batch", self.worker_id)
                break
            if self.process_workflow_run(run_id):
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

