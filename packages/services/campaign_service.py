from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from packages.models.domain import (
    Approval,
    Campaign,
    CampaignRecipient,
    Channel,
    Conversation,
    Customer,
    Message,
    OutboxEvent,
)

logger = logging.getLogger(__name__)


class CampaignError(Exception):
    """Base exception for campaign errors."""
    pass


class InvalidStateTransitionError(CampaignError):
    """Raised when an illegal status transition is requested."""
    pass


class ApprovalRequiredError(CampaignError):
    """Raised when a campaign requires approval but is not approved."""
    pass


class CampaignService:
    """
    Manages the lifecycle, audience filtering, and dispatch orchestration of
    outbound campaigns and proactive communications.
    """

    VALID_TRANSITIONS: dict[str, set[str]] = {
        "draft": {"scheduled", "running", "cancelled"},
        "scheduled": {"running", "paused", "cancelled"},
        "running": {"paused", "completed", "cancelled"},
        "paused": {"running", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }

    def __init__(self, session: Session):
        self.session = session

    # -------------------------------------------------------------------------
    # Campaign CRUD
    # -------------------------------------------------------------------------

    def create_campaign(
        self,
        *,
        tenant_id: UUID,
        name: str,
        message_template: str,
        goal: str | None = None,
        channel_id: UUID | None = None,
        audience_filter: dict[str, Any] | None = None,
        scheduled_at: datetime | None = None,
        requires_approval: bool = False,
        rate_limit_per_minute: int = 60,
        batch_size: int = 50,
        metadata_json: dict[str, Any] | None = None,
    ) -> Campaign:
        """Create a new campaign in draft status."""
        # Validate channel if provided
        if channel_id:
            channel = self.session.scalar(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                )
            )
            if not channel:
                raise CampaignError(f"Channel {channel_id} not found for this tenant.")
            if channel.status != "active":
                raise CampaignError(f"Channel {channel_id} is not active.")

        initial_metrics = {
            "total_recipients": 0,
            "enqueued_count": 0,
            "sent_count": 0,
            "delivered_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
        }

        campaign = Campaign(
            tenant_id=tenant_id,
            name=name.strip(),
            goal=goal.strip() if goal else None,
            message_template=message_template.strip(),
            channel_id=channel_id,
            status="draft",
            audience_filter=audience_filter or {},
            scheduled_at=scheduled_at,
            requires_approval=requires_approval,
            rate_limit_per_minute=max(1, rate_limit_per_minute),
            batch_size=max(1, batch_size),
            metrics=initial_metrics,
            metadata_json=metadata_json or {},
        )
        self.session.add(campaign)
        self.session.flush()
        return campaign

    def get_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign | None:
        """Retrieve a campaign ensuring tenant isolation."""
        return self.session.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_id == tenant_id,
            )
        )

    def list_campaigns(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Campaign]:
        """List campaigns for a tenant with optional status filtering."""
        stmt = select(Campaign).where(Campaign.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Campaign.status == status)
        stmt = stmt.order_by(Campaign.created_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all())

    def update_campaign(
        self,
        *,
        tenant_id: UUID,
        campaign_id: UUID,
        name: str | None = None,
        goal: str | None = None,
        message_template: str | None = None,
        channel_id: UUID | None = None,
        audience_filter: dict[str, Any] | None = None,
        scheduled_at: datetime | None = None,
        requires_approval: bool | None = None,
        rate_limit_per_minute: int | None = None,
        batch_size: int | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> Campaign:
        """Update campaign details (only editable in draft or scheduled state)."""
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        if campaign.status not in ("draft", "scheduled"):
            raise CampaignError(f"Cannot update campaign in '{campaign.status}' status.")

        if channel_id is not None:
            channel = self.session.scalar(
                select(Channel).where(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                )
            )
            if not channel:
                raise CampaignError(f"Channel {channel_id} not found for this tenant.")
            if channel.status != "active":
                raise CampaignError(f"Channel {channel_id} is not active.")
            campaign.channel_id = channel_id

        if name is not None:
            campaign.name = name.strip()
        if goal is not None:
            campaign.goal = goal.strip() if goal else None
        if message_template is not None:
            campaign.message_template = message_template.strip()
        if audience_filter is not None:
            campaign.audience_filter = audience_filter
        if scheduled_at is not None:
            campaign.scheduled_at = scheduled_at
        if requires_approval is not None:
            campaign.requires_approval = requires_approval
        if rate_limit_per_minute is not None:
            campaign.rate_limit_per_minute = max(1, rate_limit_per_minute)
        if batch_size is not None:
            campaign.batch_size = max(1, batch_size)
        if metadata_json is not None:
            campaign.metadata_json = metadata_json

        self.session.flush()
        return campaign

    # -------------------------------------------------------------------------
    # Lifecycle Transitions
    # -------------------------------------------------------------------------

    def _transition(self, campaign: Campaign, target_status: str) -> None:
        """Validates and applies a state transition."""
        allowed = self.VALID_TRANSITIONS.get(campaign.status, set())
        if target_status not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition campaign from '{campaign.status}' to '{target_status}'. "
                f"Allowed target states: {sorted(list(allowed))}"
            )
        campaign.status = target_status

    def schedule_campaign(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        scheduled_at: datetime,
    ) -> Campaign:
        """Schedule a campaign for future execution."""
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        if not campaign.channel_id:
            raise CampaignError("Cannot schedule campaign without an assigned channel.")

        self._transition(campaign, "scheduled")
        campaign.scheduled_at = scheduled_at
        self.session.flush()
        return campaign

    def start_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign:
        """
        Start campaign execution.
        Verifies approval if requires_approval is enabled,
        resolves audience, enrolls recipients, and begins running.
        """
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        if not campaign.channel_id:
            raise CampaignError("Cannot start campaign without an assigned active channel.")

        # Check channel status
        channel = self.session.scalar(
            select(Channel).where(
                Channel.id == campaign.channel_id,
                Channel.tenant_id == tenant_id,
            )
        )
        if not channel or channel.status != "active":
            raise CampaignError(f"Assigned channel {campaign.channel_id} is not active.")

        # Check approval requirement
        if campaign.requires_approval:
            if not campaign.approval_id:
                raise ApprovalRequiredError("Campaign requires approval before starting.")
            approval = self.session.scalar(
                select(Approval).where(
                    Approval.id == campaign.approval_id,
                    Approval.tenant_id == tenant_id,
                )
            )
            if not approval or approval.status != "approved":
                raise ApprovalRequiredError(
                    f"Campaign approval status is '{approval.status if approval else 'missing'}', must be 'approved'."
                )

        self._transition(campaign, "running")
        if not campaign.started_at:
            campaign.started_at = datetime.now(timezone.utc)

        # Enroll audience if not already enrolled
        recipient_count = self.session.scalar(
            select(func.count()).select_from(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.tenant_id == tenant_id,
            )
        ) or 0

        if recipient_count == 0:
            self.enroll_audience(tenant_id, campaign.id)

        self.session.flush()
        return campaign

    def pause_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign:
        """Pause a running or scheduled campaign."""
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        self._transition(campaign, "paused")
        self.session.flush()
        return campaign

    def resume_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign:
        """Resume a paused campaign."""
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        self._transition(campaign, "running")
        self.session.flush()
        return campaign

    def cancel_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign:
        """Cancel a campaign and skip pending/enqueued recipients."""
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        self._transition(campaign, "cancelled")
        campaign.completed_at = datetime.now(timezone.utc)

        # Mark any remaining pending recipients as skipped
        pending_recipients = self.session.scalars(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.tenant_id == tenant_id,
                CampaignRecipient.status.in_(["pending", "enqueued"]),
            )
        ).all()

        for rec in pending_recipients:
            rec.status = "skipped"
            rec.skip_reason = "campaign_cancelled"

        metrics = dict(campaign.metrics or {})
        metrics["skipped_count"] = (metrics.get("skipped_count") or 0) + len(pending_recipients)
        campaign.metrics = metrics
        flag_modified(campaign, "metrics")

        self.session.flush()
        return campaign

    # -------------------------------------------------------------------------
    # Audience Resolution & Enrollment
    # -------------------------------------------------------------------------

    def resolve_recipient_address(self, customer: Customer, channel_type: str) -> str | None:
        """
        Determines the appropriate destination address for a customer on a given channel.
        Returns None if no valid destination is found.
        """
        ctype = (channel_type or "").lower().strip()
        metadata = customer.metadata_json or {}
        profile = customer.profile or {}

        if ctype in ("whatsapp", "sms"):
            phone = customer.phone or metadata.get("phone") or profile.get("phone")
            if phone and re.sub(r"[^\d+]", "", str(phone)).strip():
                return str(phone).strip()
            return None

        elif ctype == "telegram":
            tg_id = (
                metadata.get("telegram_chat_id")
                or metadata.get("chat_id")
                or metadata.get("telegram_id")
                or profile.get("telegram_chat_id")
            )
            if tg_id:
                return str(tg_id).strip()
            # If phone is available, telegram might allow lookup or bot interaction
            phone = customer.phone or metadata.get("phone")
            if phone:
                return str(phone).strip()
            return None

        elif ctype in ("email", "mail"):
            email = customer.email or metadata.get("email") or profile.get("email")
            if email and "@" in str(email):
                return str(email).strip()
            return None

        # Generic webhook / external channel
        dest = (
            metadata.get("recipient_id")
            or metadata.get("external_id")
            or customer.phone
            or customer.email
        )
        return str(dest).strip() if dest else None

    def enroll_audience(self, tenant_id: UUID, campaign_id: UUID) -> int:
        """
        Evaluates the campaign's audience_filter, applies consent and safety checks,
        and creates CampaignRecipient records.
        Returns total number of eligible recipients enrolled.
        """
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        if not campaign.channel_id:
            raise CampaignError("Campaign has no channel configured.")

        channel = self.session.scalar(
            select(Channel).where(
                Channel.id == campaign.channel_id,
                Channel.tenant_id == tenant_id,
            )
        )
        if not channel:
            raise CampaignError(f"Channel {campaign.channel_id} not found.")

        filter_criteria = campaign.audience_filter or {}
        required_status = filter_criteria.get("status", "active")
        required_customer_type = filter_criteria.get("customer_type")
        filter_tags = filter_criteria.get("tags")
        opt_in_only = filter_criteria.get("opt_in_only", False)

        # 1. Fetch all customers for tenant matching base constraints
        stmt = select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.status == required_status,
        )
        if required_customer_type:
            stmt = stmt.where(Customer.customer_type == required_customer_type)

        candidates = list(self.session.scalars(stmt).all())

        # 2. Existing recipients to prevent duplicate enrollment
        existing_customer_ids = set(
            self.session.scalars(
                select(CampaignRecipient.customer_id).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.tenant_id == tenant_id,
                )
            ).all()
        )

        enrolled_count = 0
        skipped_count = 0

        for cust in candidates:
            if cust.id in existing_customer_ids:
                continue

            metadata = cust.metadata_json or {}
            profile = cust.profile or {}

            # Safety check 1: Explicit opt-out
            if metadata.get("opted_out") is True or profile.get("opted_out") is True:
                # Customer opted out
                rec = CampaignRecipient(
                    tenant_id=tenant_id,
                    campaign_id=campaign.id,
                    customer_id=cust.id,
                    channel_id=channel.id,
                    recipient_address="",
                    status="skipped",
                    skip_reason="opted_out",
                )
                self.session.add(rec)
                skipped_count += 1
                continue

            # Safety check 2: Opt-in only requirement
            if opt_in_only:
                has_consent = (
                    metadata.get("consent") is True
                    or metadata.get("opted_in") is True
                    or profile.get("consent") is True
                )
                if not has_consent:
                    rec = CampaignRecipient(
                        tenant_id=tenant_id,
                        campaign_id=campaign.id,
                        customer_id=cust.id,
                        channel_id=channel.id,
                        recipient_address="",
                        status="skipped",
                        skip_reason="no_consent",
                    )
                    self.session.add(rec)
                    skipped_count += 1
                    continue

            # Safety check 3: Tags match
            if filter_tags:
                cust_tags = set(metadata.get("tags") or profile.get("tags") or [])
                req_tags = set(filter_tags)
                if not cust_tags.intersection(req_tags):
                    # Does not match tag filter - do not enroll
                    continue

            # Safety check 4: Channel address validity
            address = self.resolve_recipient_address(cust, channel.channel_type)
            if not address:
                rec = CampaignRecipient(
                    tenant_id=tenant_id,
                    campaign_id=campaign.id,
                    customer_id=cust.id,
                    channel_id=channel.id,
                    recipient_address="",
                    status="skipped",
                    skip_reason="missing_channel_address",
                )
                self.session.add(rec)
                skipped_count += 1
                continue

            # Eligible! Enroll with pending status
            rec = CampaignRecipient(
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                customer_id=cust.id,
                channel_id=channel.id,
                recipient_address=address,
                status="pending",
            )
            self.session.add(rec)
            enrolled_count += 1

        metrics = dict(campaign.metrics or {})
        metrics["total_recipients"] = (metrics.get("total_recipients") or 0) + enrolled_count + skipped_count
        metrics["skipped_count"] = (metrics.get("skipped_count") or 0) + skipped_count
        campaign.metrics = metrics
        flag_modified(campaign, "metrics")

        self.session.flush()
        return enrolled_count

    # -------------------------------------------------------------------------
    # Batch Dispatch & Outbox Enqueueing
    # -------------------------------------------------------------------------

    def render_message(self, template: str, customer: Customer) -> str:
        """Personalize the message template with customer variables."""
        rendered = template
        metadata = customer.metadata_json or {}
        profile = customer.profile or {}

        replacements = {
            "{{name}}": customer.name or "عميلنا العزيز",
            "{{customer_name}}": customer.name or "عميلنا العزيز",
            "{{phone}}": customer.phone or "",
            "{{email}}": customer.email or "",
            "{{customer_type}}": customer.customer_type or "",
        }
        # Also allow custom profile fields
        for k, v in profile.items():
            if isinstance(v, (str, int, float)):
                replacements[f"{{{{{k}}}}}"] = str(v)
        for k, v in metadata.items():
            if isinstance(v, (str, int, float)):
                replacements[f"{{{{{k}}}}}"] = str(v)

        for key, val in replacements.items():
            rendered = rendered.replace(key, val)

        return rendered

    def process_campaign_batch(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        batch_size: int | None = None,
    ) -> int:
        """
        Fetches up to batch_size pending recipients, creates Conversations, Messages,
        and OutboxEvents for transactional asynchronous dispatch.
        Updates campaign status to completed when all recipients are processed.
        Returns number of enqueued messages.
        """
        campaign = self.get_campaign(tenant_id, campaign_id)
        if not campaign:
            raise CampaignError(f"Campaign {campaign_id} not found.")

        if campaign.status != "running":
            logger.info("Campaign %s is in state '%s', skipping batch dispatch", campaign_id, campaign.status)
            return 0

        effective_batch = batch_size or campaign.batch_size or 50

        # Query pending recipients with row locking if possible
        recipients = list(
            self.session.scalars(
                select(CampaignRecipient)
                .where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.tenant_id == tenant_id,
                    CampaignRecipient.status == "pending",
                )
                .order_by(CampaignRecipient.created_at.asc())
                .limit(effective_batch)
            ).all()
        )

        if not recipients:
            # Check if all recipients are done
            total_recipients = (campaign.metrics or {}).get("total_recipients", 0)
            remaining_active = self.session.scalar(
                select(func.count()).select_from(CampaignRecipient).where(
                    CampaignRecipient.campaign_id == campaign.id,
                    CampaignRecipient.tenant_id == tenant_id,
                    CampaignRecipient.status.in_(["pending", "enqueued"]),
                )
            ) or 0

            if total_recipients > 0 and remaining_active == 0:
                campaign.status = "completed"
                campaign.completed_at = datetime.now(timezone.utc)
                self.session.flush()
                logger.info("Campaign %s completed successfully", campaign.id)
            return 0

        enqueued_count = 0

        for rec in recipients:
            cust = self.session.scalar(
                select(Customer).where(
                    Customer.id == rec.customer_id,
                    Customer.tenant_id == tenant_id,
                )
            )
            if not cust:
                rec.status = "skipped"
                rec.skip_reason = "customer_deleted"
                continue

            # Render message
            rendered_content = self.render_message(campaign.message_template, cust)
            rec.rendered_content = rendered_content

            # Get or create conversation for customer on this channel
            conv = self.session.scalar(
                select(Conversation).where(
                    Conversation.customer_id == cust.id,
                    Conversation.tenant_id == tenant_id,
                    Conversation.channel_id == campaign.channel_id,
                )
            )
            if not conv:
                conv = Conversation(
                    tenant_id=tenant_id,
                    customer_id=cust.id,
                    channel_id=campaign.channel_id,
                    status="active",
                    subject=f"Campaign: {campaign.name}",
                    metadata_json={
                        "campaign_id": str(campaign.id),
                        "origin": "campaign",
                    },
                )
                self.session.add(conv)
                self.session.flush()

            # Create Message
            msg = Message(
                tenant_id=tenant_id,
                conversation_id=conv.id,
                sender_type="agent",
                sender_id=None,
                content=rendered_content,
                metadata_json={
                    "campaign_id": str(campaign.id),
                    "recipient_id": str(rec.id),
                    "delivery_status": "enqueued",
                },
            )
            self.session.add(msg)
            self.session.flush()

            # Create OutboxEvent
            idempotency_key = f"campaign:{campaign.id}:recipient:{rec.id}"
            outbox_event = OutboxEvent(
                tenant_id=tenant_id,
                conversation_id=conv.id,
                message_id=msg.id,
                event_type="dispatch_campaign_message",
                idempotency_key=idempotency_key,
                payload={
                    "campaign_id": str(campaign.id),
                    "recipient_id": str(rec.id),
                    "customer_id": str(cust.id),
                    "channel_id": str(campaign.channel_id),
                    "recipient_address": rec.recipient_address,
                    "content": rendered_content,
                    "message_id": str(msg.id),
                },
                status="pending",
                attempt_count=0,
                max_attempts=5,
            )
            self.session.add(outbox_event)
            self.session.flush()

            rec.status = "enqueued"
            rec.message_id = msg.id
            rec.outbox_event_id = outbox_event.id
            rec.sent_at = datetime.now(timezone.utc)
            enqueued_count += 1

        metrics = dict(campaign.metrics or {})
        metrics["enqueued_count"] = (metrics.get("enqueued_count") or 0) + enqueued_count
        campaign.metrics = metrics
        flag_modified(campaign, "metrics")

        self.session.flush()
        return enqueued_count

    # -------------------------------------------------------------------------
    # Recipient Listing & Metrics
    # -------------------------------------------------------------------------

    def get_recipients(
        self,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CampaignRecipient]:
        """List recipients of a campaign with optional status filtering."""
        stmt = select(CampaignRecipient).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.tenant_id == tenant_id,
        )
        if status:
            stmt = stmt.where(CampaignRecipient.status == status)
        stmt = stmt.order_by(CampaignRecipient.created_at.asc()).limit(limit).offset(offset)
        return list(self.session.scalars(stmt).all())
