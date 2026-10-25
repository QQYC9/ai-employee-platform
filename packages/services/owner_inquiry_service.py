from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from packages.models.domain import Conversation, Fact, Message, OwnerInquiry
from packages.services.audit_service import AuditService
from packages.services.fact_service import ExtractedFactItem, FactService

logger = logging.getLogger(__name__)

DEFAULT_HOLDING_SENTENCE = "سؤالك مهم جداً! سأتحقق من المسؤول وأوافيك بالإجابة الدقيقة فوراً."


class OwnerInquiryService:
    """
    Phase 1: Owner Inquiry Loop Engine.
    Handles customer unrecorded knowledge inquiries, owner alerts, multi-customer deduplication,
    answer matching (reply-to, inquiry #, single pending), fact persistence, and customer replies.
    """

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)
        self.fact_service = FactService(db, self.audit_service)

    # -----------------------------------------------------------------------
    # Question Normalization & Deduplication
    # -----------------------------------------------------------------------

    @staticmethod
    def normalize_question(text: str) -> str:
        """Normalizes Arabic text to unify repeated or slightly varied customer questions."""
        if not text:
            return ""
        q = text.strip().lower()
        q = re.sub(r"[\u064B-\u065F\u0670]", "", q)  # Diacritics
        q = re.sub(r"[إأآا]", "ا", q)  # Alef
        q = re.sub(r"[ة]", "ه", q)  # Teh marbuta
        q = re.sub(r"[ىي]", "ي", q)  # Yeh
        q = re.sub(r"[؟?!\.,،:;\"\'\-—()\[\]]", " ", q)  # Punctuation
        q = re.sub(r"\s+", " ", q).strip()
        return q

    # -----------------------------------------------------------------------
    # Customer Path: Create or Deduplicate Inquiry
    # -----------------------------------------------------------------------

    def handle_customer_inquiry(
        self,
        tenant_id: UUID,
        customer_conversation_id: UUID,
        customer_sender: str,
        question: str,
    ) -> tuple[OwnerInquiry, str]:
        """
        Creates a new owner inquiry or deduplicates against an existing pending inquiry.
        Replies once with the holding sentence.
        Notifies owner with inquiry # (rate-limited to 20/hr per tenant).
        """
        norm_q = self.normalize_question(question)

        # Check existing open/asked inquiry for this tenant
        existing = self.db.scalar(
            select(OwnerInquiry).where(
                OwnerInquiry.tenant_id == tenant_id,
                OwnerInquiry.normalized_question == norm_q,
                OwnerInquiry.status.in_(["open", "asked"]),
            ).order_by(OwnerInquiry.created_at.desc())
        )

        if existing:
            # Deduplicate: append waiting customer
            waiting = list(existing.waiting_customers or [])
            already_in = any(
                w.get("conversation_id") == str(customer_conversation_id)
                and w.get("customer_sender") == str(customer_sender)
                for w in waiting
            )
            if not already_in:
                waiting.append({
                    "conversation_id": str(customer_conversation_id),
                    "customer_sender": str(customer_sender),
                    "added_at": datetime.now(timezone.utc).isoformat(),
                })
                existing.waiting_customers = waiting
                flag_modified(existing, "waiting_customers")
                self.db.flush()
            return existing, DEFAULT_HOLDING_SENTENCE

        # Create fresh inquiry
        inquiry = OwnerInquiry(
            id=uuid4(),
            tenant_id=tenant_id,
            customer_conversation_id=customer_conversation_id,
            customer_sender=str(customer_sender or "customer"),
            question=question.strip(),
            normalized_question=norm_q,
            status="open",
            scope="public",
            waiting_customers=[{
                "conversation_id": str(customer_conversation_id),
                "customer_sender": str(customer_sender),
                "added_at": datetime.now(timezone.utc).isoformat(),
            }],
        )
        self.db.add(inquiry)
        self.db.flush()

        # Enforce rate limit: max 20 owner notifications / hour per tenant
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        notif_count = self.db.scalar(
            select(func.count(OwnerInquiry.id)).where(
                OwnerInquiry.tenant_id == tenant_id,
                OwnerInquiry.asked_at >= one_hour_ago,
            )
        ) or 0

        if notif_count < 20:
            inquiry.status = "asked"
            inquiry.asked_at = datetime.now(timezone.utc)
            self._dispatch_owner_notification(inquiry)
            self.db.flush()

        return inquiry, DEFAULT_HOLDING_SENTENCE

    def _dispatch_owner_notification(self, inquiry: OwnerInquiry) -> None:
        """Formats and sends inquiry notification to the tenant owner."""
        notif_text = (
            f"❓ استفسار جديد من عميل (#{inquiry.inquiry_number}):\n"
            f"\"{inquiry.question}\"\n\n"
            f"للرد على العميل، يرجى الرد المباشر على هذه الرسالة أو إرسال:\n"
            f"جواب {inquiry.inquiry_number}: [إجابتك هنا]"
        )

        owner_conv = self.db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == inquiry.tenant_id,
                Conversation.status == "owner_management",
            ).order_by(Conversation.started_at.desc())
        )

        if owner_conv:
            owner_msg = Message(
                id=uuid4(),
                tenant_id=inquiry.tenant_id,
                conversation_id=owner_conv.id,
                sender_type="agent",
                content=notif_text,
            )
            self.db.add(owner_msg)
            self.db.flush()
            inquiry.owner_notification_message_id = str(owner_msg.id)
        else:
            inquiry.owner_notification_message_id = str(uuid4())

    # -----------------------------------------------------------------------
    # Owner Path: Answer Matching & Persistence
    # -----------------------------------------------------------------------

    def match_owner_answer(
        self,
        tenant_id: UUID,
        content: str,
        reply_to_message_id: str | None = None,
    ) -> tuple[OwnerInquiry | None, str | None]:
        """
        Matches incoming owner message to an active inquiry using:
        1. reply-to-message matching
        2. inquiry number pattern (جواب 12: ...)
        3. single pending inquiry fallback
        """
        content_clean = content.strip()

        # 1. Reply-to matching
        if reply_to_message_id:
            inq_reply = self.db.scalar(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.owner_notification_message_id == str(reply_to_message_id),
                    OwnerInquiry.status.in_(["open", "asked"]),
                )
            )
            if inq_reply:
                return inq_reply, content_clean

        # 2. Inquiry number pattern
        m = re.match(r"^(?:جواب|رد|إجابة)\s*#?(\d+)[:\s]+(.+)$", content_clean, re.DOTALL | re.IGNORECASE)
        if not m:
            m = re.match(r"^#?(\d+)[:\s]+(.+)$", content_clean, re.DOTALL)
        if m:
            inq_num = int(m.group(1))
            ans_text = m.group(2).strip()
            inq_num_match = self.db.scalar(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.inquiry_number == inq_num,
                    OwnerInquiry.status.in_(["open", "asked"]),
                )
            )
            if inq_num_match:
                return inq_num_match, ans_text

        # 3. Single pending inquiry
        open_inqs = self.db.scalars(
            select(OwnerInquiry).where(
                OwnerInquiry.tenant_id == tenant_id,
                OwnerInquiry.status.in_(["open", "asked"]),
            )
        ).all()

        if len(open_inqs) == 1:
            # Exclude other known commands
            if not re.match(r"^(?:الاستفسارات|تجاهل\b|/link|ابدأ|وش باقي|كمّل|للجميع|لهذا العميل)", content_clean):
                return open_inqs[0], content_clean

        return None, None

    def answer_inquiry(
        self,
        tenant_id: UUID,
        inquiry: OwnerInquiry,
        answer: str,
    ) -> str:
        """
        Persists owner's answer as a confirmed fact, immediately dispatches answers
        to all waiting customers, and prompts owner for visibility scope.
        """
        now = datetime.now(timezone.utc)
        inquiry.owner_answer = answer
        inquiry.status = "answered"
        inquiry.answered_at = now

        # 1. Save fact via Phase 2 FactService
        fact_item = ExtractedFactItem(
            topic=f"faq.inquiry_{inquiry.inquiry_number}",
            subject=inquiry.question,
            value={"question": inquiry.question, "answer": answer},
            visibility="public",
            is_direct_unambiguous=True,
        )
        self.fact_service.save_extracted_facts(
            tenant_id=tenant_id,
            extracted_facts=[fact_item],
            auto_confirm_direct=True,
            message_text=answer,
        )

        # 2. Immediately reply to waiting customers
        waiting = list(inquiry.waiting_customers or [])
        if not waiting:
            waiting = [{
                "conversation_id": str(inquiry.customer_conversation_id),
                "customer_sender": inquiry.customer_sender,
            }]

        for cust in waiting:
            conv_id_str = cust.get("conversation_id")
            if conv_id_str:
                try:
                    conv_id = UUID(conv_id_str)
                    cust_reply = Message(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        conversation_id=conv_id,
                        sender_type="agent",
                        content=f"مرحباً بك مجدداً! بخصوص استفسارك: '{inquiry.question}'\n\n{answer}",
                    )
                    self.db.add(cust_reply)
                except Exception as err:
                    logger.warning("Error dispatching answer to customer %s: %s", cust, err)

        inquiry.status = "delivered"
        inquiry.delivered_at = now
        self.db.flush()

        # 3. Prompt owner for scope confirmation
        return "✅ تم إرسال الإجابة للعميل وحفظها.\n\nأحفظها للجميع أم لهذا العميل فقط؟"

    def handle_scope_reply(self, tenant_id: UUID, content: str) -> str | None:
        """Handles owner follow-up: 'للجميع' or 'لهذا العميل فقط'."""
        c = content.strip().lower()
        if c not in ("للجميع", "لهذا العميل فقط", "للعميل فقط"):
            return None

        recent_inquiry = self.db.scalar(
            select(OwnerInquiry).where(
                OwnerInquiry.tenant_id == tenant_id,
                OwnerInquiry.status.in_(["answered", "delivered"]),
            ).order_by(OwnerInquiry.answered_at.desc())
        )
        if not recent_inquiry:
            return None

        scope_choice = "public" if c == "للجميع" else "customer_only"
        recent_inquiry.scope = scope_choice

        fact_topic = f"faq.inquiry_{recent_inquiry.inquiry_number}"
        fact = self.db.scalar(
            select(Fact).where(
                Fact.tenant_id == tenant_id,
                Fact.topic == fact_topic,
            )
        )
        if fact:
            fact.visibility = "public" if scope_choice == "public" else "internal"
            self.db.add(fact)

        self.db.flush()
        scope_label = "للجميع" if scope_choice == "public" else "لهذا العميل فقط"
        return f"تم حفظ المعلومة {scope_label} بنجاح."

    # -----------------------------------------------------------------------
    # Owner Commands: 'الاستفسارات' & 'تجاهل 12'
    # -----------------------------------------------------------------------

    def handle_command(self, tenant_id: UUID, content: str) -> str | None:
        """Handles administrative commands for inquiries."""
        c = content.strip()
        if c in ("الاستفسارات", "استفسارات", "قائمة الاستفسارات"):
            open_inqs = self.db.scalars(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.status.in_(["open", "asked"]),
                ).order_by(OwnerInquiry.inquiry_number.asc())
            ).all()
            if not open_inqs:
                return "لا توجد استفسارات معلقة حالياً."
            lines = ["📋 الاستفسارات المعلقة:"]
            for inq in open_inqs:
                lines.append(f"#{inq.inquiry_number}: {inq.question}")
            return "\n".join(lines)

        m = re.match(r"^تجاهل\s*#?(\d+)$", c)
        if m:
            num = int(m.group(1))
            inquiry = self.db.scalar(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.inquiry_number == num,
                )
            )
            if inquiry:
                inquiry.status = "ignored"
                self.db.flush()
                return f"تم تجاهل الاستفسار #{num}."
            return f"الاستفسار #{num} غير موجود."

        return None

    # -----------------------------------------------------------------------
    # Reminders & 24h Timeout Status Updates
    # -----------------------------------------------------------------------

    def check_reminders_and_timeouts(self, tenant_id: UUID | None = None) -> dict[str, int]:
        """
        Runs periodic checks:
        - 2h reminder to owner
        - 24h timeout status update to waiting customers
        """
        now = datetime.now(timezone.utc)
        two_hours_ago = now - timedelta(hours=2)
        twenty_four_hours_ago = now - timedelta(hours=24)

        reminded_count = 0
        timeout_count = 0

        # 1. 2h Reminders to owner
        stmt_remind = select(OwnerInquiry).where(
            OwnerInquiry.status.in_(["open", "asked"]),
            OwnerInquiry.asked_at <= two_hours_ago,
            OwnerInquiry.reminded_at.is_(None),
        )
        if tenant_id:
            stmt_remind = stmt_remind.where(OwnerInquiry.tenant_id == tenant_id)
        to_remind = self.db.scalars(stmt_remind).all()

        for inq in to_remind:
            inq.reminded_at = now
            reminded_count += 1
            owner_conv = self.db.scalar(
                select(Conversation).where(
                    Conversation.tenant_id == inq.tenant_id,
                    Conversation.status == "owner_management",
                )
            )
            if owner_conv:
                msg = Message(
                    id=uuid4(),
                    tenant_id=inq.tenant_id,
                    conversation_id=owner_conv.id,
                    sender_type="agent",
                    content=f"⏰ تذكير: الاستفسار #{inq.inquiry_number} بانتظار ردك:\n\"{inq.question}\"",
                )
                self.db.add(msg)

        # 2. 24h Timeouts to waiting customers
        stmt_timeout = select(OwnerInquiry).where(
            OwnerInquiry.status.in_(["open", "asked"]),
            OwnerInquiry.created_at <= twenty_four_hours_ago,
            OwnerInquiry.timeout_at.is_(None),
        )
        if tenant_id:
            stmt_timeout = stmt_timeout.where(OwnerInquiry.tenant_id == tenant_id)
        to_timeout = self.db.scalars(stmt_timeout).all()

        for inq in to_timeout:
            inq.timeout_at = now
            inq.status = "timeout"
            timeout_count += 1
            waiting = list(inq.waiting_customers or [])
            if not waiting:
                waiting = [{
                    "conversation_id": str(inq.customer_conversation_id),
                    "customer_sender": inq.customer_sender,
                }]
            for cust in waiting:
                conv_id_str = cust.get("conversation_id")
                if conv_id_str:
                    try:
                        cmsg = Message(
                            id=uuid4(),
                            tenant_id=inq.tenant_id,
                            conversation_id=UUID(conv_id_str),
                            sender_type="agent",
                            content="نعتذر عن التأخير في الرد على استفسارك، جاري متابعة الإدارة وسنوافيك فور توفر التفاصيل.",
                        )
                        self.db.add(cmsg)
                    except Exception:
                        pass

        self.db.flush()
        return {"reminded": reminded_count, "timeout": timeout_count}
