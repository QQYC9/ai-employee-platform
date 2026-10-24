from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import (
    Approval,
    Channel,
    Conversation,
    Customer,
    Message,
    OutboxEvent,
)
from packages.services.approval_service import ApprovalService
from packages.services.campaign_service import CampaignService

logger = logging.getLogger(__name__)


class ProactiveNotificationService:
    """
    Handles proactive outbound customer notifications (appointment reminders,
    service follow-ups, inactivity re-engagement) and internal business owner alerts
    with approval gating and tenant boundary enforcement.
    """

    def __init__(self, session: Session):
        self.session = session
        self.campaign_service = CampaignService(session)
        self.approval_service = ApprovalService(session)

    def send_proactive_customer_message(
        self,
        *,
        tenant_id: UUID,
        customer_id: UUID,
        channel_id: UUID,
        content: str,
        notification_type: str = "custom",
        requires_approval: bool = False,
        agent_id: UUID | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Sends a proactive message to an external customer across a selected channel.
        Respects opt-outs, consent, and approval policies.
        """
        # 1. Tenant boundary: Channel verification
        channel = self.session.scalar(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
            )
        )
        if not channel:
            raise ValueError(f"Channel {channel_id} not found for this tenant.")
        if channel.status != "active":
            raise ValueError(f"Channel {channel_id} is not active.")

        # 2. Tenant boundary: Customer verification
        customer = self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
        if not customer:
            raise ValueError(f"Customer {customer_id} not found for this tenant.")
        if customer.status != "active":
            raise ValueError(f"Customer {customer_id} is not active.")

        # 3. Consent & Opt-out enforcement
        cust_meta = customer.metadata_json or {}
        cust_prof = customer.profile or {}
        if cust_meta.get("opted_out") is True or cust_prof.get("opted_out") is True:
            logger.warning("Customer %s opted out of proactive messages", customer_id)
            return {
                "status": "skipped",
                "reason": "customer_opted_out",
                "customer_id": str(customer_id),
            }

        # 4. Resolve address on channel
        recipient_address = self.campaign_service.resolve_recipient_address(
            customer, channel.channel_type
        )
        if not recipient_address:
            logger.warning(
                "Customer %s missing valid address for channel type %s",
                customer_id,
                channel.channel_type,
            )
            return {
                "status": "skipped",
                "reason": "missing_channel_address",
                "customer_id": str(customer_id),
            }

        # 5. Approval gating
        if requires_approval:
            approval = self.approval_service.create_approval(
                tenant_id=tenant_id,
                requested_for="tenant_owner",
                action=f"proactive_{notification_type}",
                description=f"Send proactive {notification_type} message to {customer.name} ({recipient_address})",
                requested_by_agent_id=agent_id,
            )
            return {
                "status": "pending_approval",
                "approval_id": str(approval.id),
                "customer_id": str(customer_id),
                "channel_id": str(channel_id),
            }

        # 6. Conversation & Message creation
        conv = self.session.scalar(
            select(Conversation).where(
                Conversation.customer_id == customer.id,
                Conversation.tenant_id == tenant_id,
                Conversation.channel_id == channel.id,
            )
        )
        if not conv:
            conv = Conversation(
                tenant_id=tenant_id,
                customer_id=customer.id,
                channel_id=channel.id,
                status="active",
                subject=f"Proactive: {notification_type}",
                metadata_json={"origin": "proactive_notification", "type": notification_type},
            )
            self.session.add(conv)
            self.session.flush()

        msg_meta = {
            "notification_type": notification_type,
            "origin": "proactive_notification",
            "recipient_address": recipient_address,
            **(metadata_json or {}),
        }

        msg = Message(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            sender_type="agent",
            sender_id=agent_id,
            content=content,
            metadata_json=msg_meta,
        )
        self.session.add(msg)
        self.session.flush()

        # 7. Outbox event enqueueing
        idempotency_key = f"proactive:{tenant_id}:{customer_id}:{uuid4().hex[:12]}"
        outbox_event = OutboxEvent(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            message_id=msg.id,
            event_type="dispatch_channel_reply",
            idempotency_key=idempotency_key,
            payload={
                "channel_id": str(channel.id),
                "recipient": recipient_address,
                "content": content,
                "reply_message_id": str(msg.id),
                "notification_type": notification_type,
                "customer_id": str(customer.id),
            },
            status="pending",
            attempt_count=0,
            max_attempts=5,
        )
        self.session.add(outbox_event)
        self.session.flush()

        return {
            "status": "dispatched",
            "message_id": str(msg.id),
            "outbox_event_id": str(outbox_event.id),
            "conversation_id": str(conv.id),
            "customer_id": str(customer.id),
            "channel_id": str(channel.id),
            "recipient_address": recipient_address,
        }

    # -------------------------------------------------------------------------
    # Structured Proactive Customer Triggers
    # -------------------------------------------------------------------------

    def send_appointment_reminder(
        self,
        *,
        tenant_id: UUID,
        customer_id: UUID,
        channel_id: UUID,
        appointment_time: str,
        service_name: str,
        requires_approval: bool = False,
        agent_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Sends an appointment reminder notification to a customer."""
        customer = self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
        cust_name = customer.name if customer else "عميلنا العزيز"
        content = (
            f"مرحباً {cust_name}، نود تذكيركم بموعدكم القادم لـ ({service_name}) "
            f"بتاريخ {appointment_time}. نتطلع لخدمتكم!"
        )
        return self.send_proactive_customer_message(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel_id=channel_id,
            content=content,
            notification_type="appointment_reminder",
            requires_approval=requires_approval,
            agent_id=agent_id,
            metadata_json={
                "appointment_time": appointment_time,
                "service_name": service_name,
            },
        )

    def send_service_followup(
        self,
        *,
        tenant_id: UUID,
        customer_id: UUID,
        channel_id: UUID,
        service_name: str,
        feedback_url: str | None = None,
        requires_approval: bool = False,
        agent_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Sends a post-service customer follow-up / feedback request."""
        customer = self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
        cust_name = customer.name if customer else "عميلنا العزيز"
        content = (
            f"مرحباً {cust_name}، نأمل أن تكون تجربتكم مع خدمة ({service_name}) نالت رضاكم التام! "
            f"يسعدنا جداً تلقي ملاحظاتكم لتطوير خدماتنا باستمرار."
        )
        if feedback_url:
            content += f"\nرابط التقييم: {feedback_url}"

        return self.send_proactive_customer_message(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel_id=channel_id,
            content=content,
            notification_type="service_followup",
            requires_approval=requires_approval,
            agent_id=agent_id,
            metadata_json={
                "service_name": service_name,
                "feedback_url": feedback_url,
            },
        )

    def send_inactivity_reengagement(
        self,
        *,
        tenant_id: UUID,
        customer_id: UUID,
        channel_id: UUID,
        offer_details: str | None = None,
        requires_approval: bool = False,
        agent_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Sends an inactivity re-engagement notification with optional offer details."""
        customer = self.session.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
            )
        )
        cust_name = customer.name if customer else "عميلنا العزيز"
        content = (
            f"مرحباً {cust_name}، اشتقنا لتواجدك معنا! يسعدنا تقديم أحدث العروض والخدمات المصممة لأجلك."
        )
        if offer_details:
            content += f"\nعرض خاص: {offer_details}"

        return self.send_proactive_customer_message(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel_id=channel_id,
            content=content,
            notification_type="inactivity_reengagement",
            requires_approval=requires_approval,
            agent_id=agent_id,
            metadata_json={"offer_details": offer_details},
        )

    # -------------------------------------------------------------------------
    # Internal Owner Alerts (Clean Separation from External Customer Messaging)
    # -------------------------------------------------------------------------

    def notify_owner_internal(
        self,
        *,
        tenant_id: UUID,
        channel_id: UUID,
        alert_title: str,
        alert_body: str,
        alert_type: str = "owner_alert",
    ) -> dict[str, Any]:
        """
        Sends an internal administrative notification strictly to the business owner,
        completely segregated from external customer conversations.
        """
        channel = self.session.scalar(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
            )
        )
        if not channel:
            raise ValueError(f"Channel {channel_id} not found for this tenant.")

        # Get or create dedicated internal owner conversation
        owner_conv = self.session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_id == channel.id,
                Conversation.customer_id.is_(None),
            )
        )
        if not owner_conv:
            owner_conv = Conversation(
                tenant_id=tenant_id,
                channel_id=channel.id,
                customer_id=None,
                status="active",
                subject="Internal Owner Alerts",
                metadata_json={"is_owner": True, "origin": "internal_alert"},
            )
            self.session.add(owner_conv)
            self.session.flush()

        # Create internal alert Message
        alert_msg = Message(
            tenant_id=tenant_id,
            conversation_id=owner_conv.id,
            sender_type="system",
            sender_id=None,
            content=f"[{alert_title}] {alert_body}",
            metadata_json={"is_owner": True, "alert_type": alert_type},
        )
        self.session.add(alert_msg)
        self.session.flush()

        idempotency_key = f"owner_alert:{tenant_id}:{uuid4().hex[:12]}"
        outbox_event = OutboxEvent(
            tenant_id=tenant_id,
            conversation_id=owner_conv.id,
            message_id=alert_msg.id,
            event_type="notify_owner_task_result",
            idempotency_key=idempotency_key,
            payload={
                "channel_id": str(channel.id),
                "task_title": alert_title,
                "status": alert_type,
                "reason": alert_body,
            },
            status="pending",
            attempt_count=0,
            max_attempts=5,
        )
        self.session.add(outbox_event)
        self.session.flush()

        return {
            "status": "enqueued",
            "outbox_event_id": str(outbox_event.id),
            "alert_title": alert_title,
            "channel_id": str(channel_id),
        }
