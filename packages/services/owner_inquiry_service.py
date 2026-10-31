from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from packages.models.domain import Channel, Conversation, Fact, Message, OwnerInquiry
from packages.services.audit_service import AuditService
from packages.services.fact_service import ExtractedFactItem, FactService

logger = logging.getLogger(__name__)

DEFAULT_HOLDING_SENTENCE = "سؤالك مهم جداً! سأتحقق من المسؤول وأوافيك بالإجابة الدقيقة فوراً."


def _is_valid_uuid(val: Any) -> bool:
    try:
        UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


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

        dispatched = False
        if notif_count < 20:
            dispatched = self._dispatch_owner_notification(inquiry)

        if dispatched:
            inquiry.status = "asked"
            inquiry.asked_at = datetime.now(timezone.utc)
        else:
            inquiry.status = "open"
            inquiry.asked_at = None
        self.db.flush()

        return inquiry, DEFAULT_HOLDING_SENTENCE

    def _find_owner_conversation(self, tenant_id: UUID) -> tuple[Conversation | None, str | None]:
        """
        Locates the verified owner management conversation and recipient identifier for a tenant.
        Matches active owner conversation via metadata, customer_id is None, and active channel.
        Returns (conversation, recipient_id).
        """
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.customer_id.is_(None),
                or_(
                    Conversation.metadata_json["conversation_type"].as_string() == "owner_management",
                    Conversation.metadata_json["is_owner"].as_boolean() == True,
                    Conversation.status == "owner_management",
                ),
            )
            .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.started_at.desc())
        )
        owner_conv = self.db.scalar(stmt)
        if owner_conv and owner_conv.channel_id:
            channel = self.db.scalar(
                select(Channel).where(
                    Channel.id == owner_conv.channel_id,
                    Channel.tenant_id == tenant_id,
                    Channel.status == "active",
                )
            )
            if channel:
                cfg = dict(channel.config or {})
                recipient = (
                    (owner_conv.metadata_json or {}).get("sender_id")
                    or cfg.get("owner_telegram_id")
                    or cfg.get("owner_phone")
                    or cfg.get("owner_id")
                )
                if not recipient:
                    raw_owners = cfg.get("owner_identifiers") or cfg.get("owner_sender_ids") or []
                    if isinstance(raw_owners, list) and raw_owners:
                        recipient = str(raw_owners[0])
                    elif isinstance(raw_owners, str) and raw_owners:
                        recipient = raw_owners
                if recipient:
                    return owner_conv, str(recipient)

        # Fallback: Check if tenant has an active channel with configured owner identifiers
        active_channel = self.db.scalar(
            select(Channel).where(
                Channel.tenant_id == tenant_id,
                Channel.status == "active",
            ).order_by(Channel.created_at.asc())
        )
        if active_channel:
            cfg = dict(active_channel.config or {})
            recipient = (
                cfg.get("owner_telegram_id")
                or cfg.get("owner_phone")
                or cfg.get("owner_id")
            )
            if not recipient:
                raw_owners = cfg.get("owner_identifiers") or cfg.get("owner_sender_ids") or []
                if isinstance(raw_owners, list) and raw_owners:
                    recipient = str(raw_owners[0])
                elif isinstance(raw_owners, str) and raw_owners:
                    recipient = raw_owners
            if recipient:
                conv = Conversation(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    channel_id=active_channel.id,
                    customer_id=None,
                    subject=f"Owner Management ({active_channel.name})",
                    status="open",
                    metadata_json={
                        "is_owner": True,
                        "conversation_type": "owner_management",
                        "channel_type": active_channel.channel_type,
                        "sender_id": str(recipient),
                    },
                )
                self.db.add(conv)
                self.db.flush()
                return conv, str(recipient)

        return None, None

    def _dispatch_owner_notification(self, inquiry: OwnerInquiry) -> bool:
        """
        Formats, persists, and queues inquiry notification to the tenant owner via Outbox.
        Returns True if the notification message and OutboxEvent were successfully created, False otherwise.
        """
        owner_conv, owner_recipient = self._find_owner_conversation(inquiry.tenant_id)
        if not owner_conv or not owner_recipient or not owner_conv.channel_id:
            logger.warning(
                "Owner notification cannot be dispatched for inquiry %s: no active owner channel/recipient for tenant %s",
                inquiry.id,
                inquiry.tenant_id,
            )
            return False

        notif_text = (
            f"❓ استفسار جديد من عميل (#{inquiry.inquiry_number}):\n"
            f"\"{inquiry.question}\"\n\n"
            f"للرد على العميل، يرجى الرد المباشر على هذه الرسالة أو إرسال:\n"
            f"جواب {inquiry.inquiry_number}: [إجابتك هنا]"
        )

        owner_msg = Message(
            id=uuid4(),
            tenant_id=inquiry.tenant_id,
            conversation_id=owner_conv.id,
            sender_type="agent",
            content=notif_text,
            metadata_json={
                "inquiry_id": str(inquiry.id),
                "inquiry_number": inquiry.inquiry_number,
                "delivery_status": "pending_dispatch",
                "is_owner_notification": True,
            },
        )
        self.db.add(owner_msg)
        self.db.flush()
        inquiry.owner_notification_message_id = str(owner_msg.id)

        from packages.services.outbox_service import OutboxService
        outbox_svc = OutboxService(self.db, self.audit_service)
        outbox_svc.create_event(
            tenant_id=inquiry.tenant_id,
            conversation_id=owner_conv.id,
            message_id=owner_msg.id,
            idempotency_key=f"outbox:inquiry_ask:{inquiry.id}:{owner_msg.id}",
            event_type="dispatch_channel_reply",
            payload={
                "channel_id": str(owner_conv.channel_id),
                "recipient": str(owner_recipient),
                "content": notif_text,
                "reply_message_id": str(owner_msg.id),
            },
        )
        self.db.flush()
        return True

    # -----------------------------------------------------------------------
    # Owner Path: Answer Matching & Persistence
    # -----------------------------------------------------------------------

    def _find_inquiry_number_in_text(self, content: str) -> int | None:
        """Extracts explicit inquiry number from text if present anywhere."""
        # Matches: "رد على استفسار 6", "استفسار رقم 6", "#6", "جواب 6:", "رد 6:"
        m = re.search(r"(?:^|[^\w])(?:جواب|رد|إجابة)?\s*(?:على\s*)?(?:الاستفسار\s*)?(?:#|رقم\s*)?(\d+)\b", content, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return None

    def match_owner_answer(
        self,
        tenant_id: UUID,
        content: str,
        reply_to_message_id: str | None = None,
    ) -> tuple[OwnerInquiry | None, str | None]:
        """
        Matches incoming owner message to an active inquiry safely using:
        1. reply-to-message matching (DB Message ID or external channel message ID)
        2. explicit inquiry number anywhere in message (#6, استفسار 6, جواب 6: ...)
        3. single pending inquiry fallback when owner message has explicit reply intent
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
            if not inq_reply:
                notif_msg = self.db.scalar(
                    select(Message).where(
                        Message.tenant_id == tenant_id,
                        or_(
                            Message.id == (UUID(reply_to_message_id) if _is_valid_uuid(reply_to_message_id) else None),
                            Message.metadata_json["external_message_id"].as_string() == str(reply_to_message_id),
                        ),
                    )
                )
                if notif_msg and notif_msg.metadata_json:
                    inq_id_meta = notif_msg.metadata_json.get("inquiry_id")
                    if inq_id_meta and _is_valid_uuid(inq_id_meta):
                        inq_reply = self.db.scalar(
                            select(OwnerInquiry).where(
                                OwnerInquiry.tenant_id == tenant_id,
                                OwnerInquiry.id == UUID(inq_id_meta),
                                OwnerInquiry.status.in_(["open", "asked"]),
                            )
                        )
            if inq_reply:
                return inq_reply, content_clean

        # 2. Inquiry number pattern at start of message
        m = re.match(r"^(?:جواب|رد|إجابة)?\s*(?:على\s*)?(?:الاستفسار\s*)?(?:#|رقم\s*)?(\d+)[:\s]+(.+)$", content_clean, re.DOTALL | re.IGNORECASE)
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

        # 2.B Check if inquiry number is explicitly referenced anywhere in command
        inq_num = self._find_inquiry_number_in_text(content_clean)
        if inq_num:
            inq_num_match = self.db.scalar(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.inquiry_number == inq_num,
                    OwnerInquiry.status.in_(["open", "asked"]),
                )
            )
            if inq_num_match:
                cleaned = re.sub(
                    rf"^(?:جواب|رد|إجابة)?\s*(?:على\s*)?(?:الاستفسار\s*)?(?:#|رقم\s*)?{inq_num}[:\s\-]+",
                    "",
                    content_clean,
                    flags=re.IGNORECASE,
                ).strip()
                return inq_num_match, cleaned or content_clean

        # 3. Single pending inquiry fallback (Zero guesswork: ONLY if exactly 1 inquiry is open)
        open_inqs = self.db.scalars(
            select(OwnerInquiry).where(
                OwnerInquiry.tenant_id == tenant_id,
                OwnerInquiry.status.in_(["open", "asked"]),
            )
        ).all()

        if len(open_inqs) == 1:
            if not re.match(r"^(?:الاستفسارات|تجاهل\b|/link|ابدأ|وش باقي|كمّل|للجميع|لهذا العميل|إلغاء\b|الغاء\b|cancel\b|(?:نعم|موافق|أوافق|تأكيد|confirm|approve)\s+[2-79AC-HJ-KM-NP-Z]{6})", content_clean, re.I):
                return open_inqs[0], content_clean

        # Zero guesswork: multiple inquiries without explicit reference return (None, None)
        return None, None

    def _persist_classified_product_knowledge(self, tenant_id: UUID, content: str) -> list[Fact]:
        """
        Parses and stores modular product knowledge into FactService with granular classification:
        - Sections 1-12: Available confirmed product features (visibility='public', feature_status='available')
        - Section 13: External benchmark comparisons (visibility='private', feature_status='benchmark_only')
        - Section 14: Future development priorities / roadmap (visibility='private', feature_status='planned_roadmap')
        """
        module_specs = [
            ("accounting", "المحاسبة المالية في برنامج ناظم", "public", "available", [
                "دليل حسابات هرمي قابل للتخصيص", "القيود اليومية المزدوجة والترحيل الآلي",
                "دفتر الأستاذ العام وميزان المراجعة", "الميزانية العمومية وقائمة الأرباح والخسائر والتدفقات النقدية",
                "إدارة الفترات المالية والإقفال المحاسبي", "الأرصدة الافتتاحية والتسويات المحاسبية"
            ]),
            ("sales_purchases", "المبيعات والمشتريات والديون في برنامج ناظم", "public", "available", [
                "عروض الأسعار وأوامر البيع والشراء", "فواتير المبيعات والمشتريات والإشعارات الدائنة والمدينة",
                "المرتجعات والخصومات والعروض", "البيع النقدي والآجل والسداد الجزئي",
                "إدارة العملاء والموردين وحدود الائتمان", "متابعة الديون والمستحقات والتنبيهات بمواعيد السداد"
            ]),
            ("treasury_banks", "الصناديق والبنوك في برنامج ناظم", "public", "available", [
                "إدارة عدة صناديق وحسابات بنكية", "سندات القبض والصرف والتحويلات المالية",
                "تسوية ومطابقة الحسابات البنكية", "إدارة العهد والسلف",
                "إقفال ورديات الصندوق ومطابقة الرصيد الفعلي", "تقارير الحركة النقدية والتدفقات المالية"
            ]),
            ("inventory", "المخزون والمستودعات في برنامج ناظم", "public", "available", [
                "إدارة عدة مستودعات وفروع", "تحويل البضائع والجرد وتسويات المخزون",
                "الباركود والأرقام التسلسلية والدفعات والصلاحية", "وحدات القياس والتحويل بينها",
                "الحد الأدنى للمخزون والتنبيه لإعادة الطلب", "تقييم المخزون وحساب تكلفة البضاعة المباعة",
                "تحليل الأصناف الراكدة وسرعة دوران المخزون"
            ]),
            ("multi_currency", "العملات المتعددة في برنامج ناظم", "public", "available", [
                "التعامل مع الريال اليمني والدولار والعملات الأخرى", "تحديد سعر الصرف لكل معاملة",
                "حساب فروق أسعار الصرف", "عرض الأرصدة بالعملة الأصلية والعملة الأساسية",
                "تقارير مالية متعددة العملات"
            ]),
            ("fixed_assets", "الأصول الثابتة في برنامج ناظم", "public", "available", [
                "تسجيل الأصول والمعدات", "احتساب الإهلاك وفق السياسات المحاسبية",
                "متابعة نقل الأصول وصيانتها والتخلص منها", "تسجيل القيود المحاسبية المتعلقة بالأصول"
            ]),
            ("reports", "التقارير والتحليلات والأرباح في برنامج ناظم", "public", "available", [
                "تقارير مالية وتشغيلية تفصيلية", "تحليل الأرباح حسب الفرع والمنتج والمستودع",
                "تحليل هامش الربح لكل فاتورة وصنف", "تقارير أعمار الديون والمستحقات",
                "مقارنة الموازنات بالمصروفات الفعلية", "تقارير قابلة للتصفية والتصدير إلى Excel وPDF",
                "لوحات مؤشرات تفاعلية للإدارة"
            ]),
            ("security_permissions", "المستخدمون والصلاحيات والأمان في برنامج ناظم", "public", "available", [
                "صلاحيات دقيقة حسب المستخدم والدور والفرع", "اعتماد المصروفات والمشتريات والخصومات",
                "سجل تدقيق للعمليات والتعديلات والإلغاءات", "حماية القيود المرحلة ومنع حذفها دون أثر محاسبي",
                "إقفال الفترات المالية والنسخ الاحتياطي"
            ]),
            ("automation_ai", "الأتمتة والذكاء الاصطناعي في برنامج ناظم", "public", "available", [
                "إنشاء القيود تلقائيًا عند تنفيذ المعاملات", "قواعد آلية لتصنيف الحركات المالية",
                "استخراج بيانات الفواتير والإيصالات من الصور", "اكتشاف العمليات غير المعتادة والتكرار المحتمل",
                "تنبيهات الديون والمخزون والسيولة"
            ]),
            ("integration", "التكامل وإدارة الأعمال في برنامج ناظم", "public", "available", [
                "تكامل المحاسبة مع المبيعات والمشتريات والمخزون ونقاط البيع", "إدارة متعددة الفروع والشركات",
                "واجهات API للتكامل مع الأنظمة الخارجية", "تصدير واستيراد البيانات وإدارة مراكز التكلفة"
            ]),
            ("pos", "نقاط البيع في برنامج ناظم", "public", "available", [
                "واجهة بيع سريعة تدعم الباركود", "تعليق الفواتير واستئنافها وطرق دفع متعددة",
                "إدارة الورديات والكاشير وأسعار الجملة والتجزئة", "طباعة الفواتير الحرارية وتحديث المخزون آلياً"
            ]),
            ("yemeni_market", "متطلبات السوق اليمني في برنامج ناظم", "public", "available", [
                "واجهة عربية كاملة من اليمين إلى اليسار", "فواتير وسندات قابلة للطباعة محليًا",
                "العملة المحلية والعملات الأجنبية", "إمكانية العمل دون إنترنت عند الحاجة ومزامنة الفروع",
                "دعم تعدد الأسعار والفروع والمستودعات والضرائب المحلية"
            ]),
            ("benchmarks", "مقارنات مرجعية مع برامج عالمية", "private", "benchmark_only", [
                "Odoo: تكامل المحاسبة مع منظومة ERP", "ERPNext: المحاسبة والمخزون وقابلية التخصيص",
                "QuickBooks: سهولة الاستخدام وإدارة الفواتير", "Xero: المحاسبة السحابية والتسويات البنكية",
                "Zoho Books: الأتمتة والتقارير", "Sage Intacct: المحاسبة المؤسسية والتحليل المالي"
            ]),
            ("roadmap", "أولويات التطوير المقترحة لبرنامج ناظم", "private", "planned_roadmap", [
                "الأولوية الأولى: سلامة القيود والترحيل، الصناديق والبنوك، العملاء والموردون، الصلاحيات وسجل التدقيق",
                "الأولوية الثانية: المخزون وتكلفة البضاعة، التقارير المالية، العملات المتعددة، تعدد الفروع والمستودعات"
            ]),
        ]

        extracted = []
        extracted.append(
            ExtractedFactItem(
                topic="product.nazem.overview",
                subject="برنامج ناظم المحاسبي",
                value={
                    "name": "برنامج ناظم المحاسبي",
                    "product_name": "ناظم",
                    "description": "نظام محاسبي وإداري متكامل يدعم إدارة المستودعات المتعددة، المبيعات والمشتريات، متابعة المخزون والأرباح والديون، ونقاط البيع ومتطلبات السوق اليمني.",
                    "status": "available",
                    "source": "owner_management",
                },
                visibility="public",
                is_direct_unambiguous=True,
            )
        )

        for slug, subject, visibility, status, default_features in module_specs:
            extracted.append(
                ExtractedFactItem(
                    topic=f"product.nazem.{slug}",
                    subject=subject,
                    value={
                        "product": "ناظم",
                        "module": slug,
                        "title": subject,
                        "features": default_features,
                        "feature_status": status,
                        "notes": "أمثلة ومقارنات مرجعية وليست دليلاً على وجود الميزة في ناظم" if status == "benchmark_only" else ("ميزات مستقبلية مقترحة قيد التطوير" if status == "planned_roadmap" else "ميزة مؤكدة ومتاحة حالياً في برنامج ناظم"),
                        "source": "owner_management",
                    },
                    visibility=visibility,
                    is_direct_unambiguous=True,
                )
            )

        self.fact_service.save_extracted_facts(
            tenant_id=tenant_id,
            extracted_facts=extracted,
            auto_confirm_direct=True,
            message_text=content,
        )
        self.db.flush()
        return extracted

    def _synthesize_tailored_customer_reply(self, inquiry: OwnerInquiry, answer: str) -> str:
        """
        Drafts a courteous, tailored customer response addressing their specific needs
        dynamically synthesized from verified public facts (FactService) and owner guidance,
        without rigid templates, unrequested feature dumping, roadmap plans, or external benchmarks.
        """
        q = inquiry.question or ""
        q_norm = self.normalize_question(q)

        # 1. Fetch confirmed public facts for this tenant
        all_nazem_facts = self.db.scalars(
            select(Fact).where(
                Fact.tenant_id == inquiry.tenant_id,
                Fact.topic.like("product.nazem.%"),
                Fact.visibility == "public",
                Fact.status == "confirmed",
                Fact.superseded_by.is_(None),
            )
        ).all()
        facts_by_topic: dict[str, Fact] = {f.topic: f for f in all_nazem_facts}

        # 2. Deconstruct customer needs and question facets
        wants_warehouses = any(w in q_norm for w in ["مستودع", "مستودعات", "مستودعين", "فرع", "فروع"])
        wants_inventory = any(w in q_norm for w in ["مخزون", "بضاعه", "بضائع", "جرد", "تسويات", "باركود", "اصناف", "تحويل"])
        wants_debts = any(w in q_norm for w in ["دين", "ديون", "مديونيه", "مستحقات", "سداد", "عملاء", "موردين", "ائتمان", "اجل"])
        wants_profits = any(w in q_norm for w in ["ربح", "ارباح", "هامش", "خسائر", "قوائم ماليه", "ميزانيه"])
        wants_sales_purchases = any(w in q_norm for w in ["مبيعات", "مشتريات", "فواتير", "عروض اسعار"])
        wants_pos = any(w in q_norm for w in ["نقاط بيع", "كاشير", "نقطه بيع", "pos"])
        asks_separate_inventory = any(
            w in q_norm for w in [
                "منفصل", "مستقل", "برنامج مخزون منفصل", "برنامج اخر", "برنامج مستقل",
                "نظام منفصل", "نظام مستقل", "احتاج برنامج", "برنامج اضافي"
            ]
        )
        is_general_product_q = (
            any(w in q_norm for w in ["مميزات", "خدمات", "عن ناظم", "وش ناظم", "ماهو ناظم", "برنامج ناظم"])
            and not (wants_warehouses or wants_debts or wants_profits or wants_sales_purchases)
        )

        # If question is specifically about Nazem or matched our product facts
        is_product_inquiry = bool(
            facts_by_topic
            and (
                wants_warehouses
                or wants_inventory
                or wants_debts
                or wants_profits
                or wants_sales_purchases
                or asks_separate_inventory
                or is_general_product_q
                or "ناظم" in q_norm
                or "مميزات" in answer
            )
        )

        if is_product_inquiry:
            points = []

            # 1. Warehouses & Transfers (إدارة المستودعات والمخزون)
            if wants_warehouses or wants_inventory:
                if "مستودعين" in q_norm:
                    points.append((
                        "إدارة المستودعات",
                        "يدعم برنامج ناظم إدارة عدة مستودعات وفروع بشكل متكامل، بما في ذلك متجرك بالمستودعين، "
                        "ويتيح التحويل المباشر للبضائع بين المستودعات، والجرد الدوري، والتسويات المخزنية بدقة، "
                        "مع متابعة الأصناف بالباركود والأرقام التسلسلية والتنبيه التلقائي عند وصول المخزون للحد الأدنى لإعادة الطلب.\n"
                        "💡 الفائدة العملية: تمنحك رقابة تامة على حركة المخزون، وتمنع تضارب الأرصدة أو عجز البضاعة في أي مستودع، وتضمن استمرار المبيعات دون انقطاع."
                    ))
                else:
                    points.append((
                        "إدارة المستودعات",
                        "يدعم برنامج ناظم إدارة عدة مستودعات وفروع، ويتيح تحويل البضائع بين المستودعات، "
                        "والجرد الدوري، والتسويات المخزنية، ومتابعة الأصناف بالباركود وتنبيهات الحد الأدنى للمخزون.\n"
                        "💡 الفائدة العملية: ضبط دقيق لمخزون الفروع، وتفادي هدر البضاعة وتسهيل مطابقة الجرد الدوري بأقل جهد."
                    ))

            # 2. Sales & Purchases (المبيعات والمشتريات وتكامل المخزون)
            if wants_sales_purchases:
                points.append((
                    "المبيعات والمشتريات وتكامل المخزون",
                    "يربط النظام دورة المبيعات والمشتريات بالمخزون بصورة آلية وفورية؛ حيث يتم تحديث أرصدة المخزون "
                    "واحتساب تكلفة البضاعة المباعة تلقائياً عند إصدار الفواتير النقدية والآجلة مع دعم عروض الأسعار والمرتجعات.\n"
                    "💡 الفائدة العملية: أتمتة حساب تكاليف البضاعة المباعة وتحديث المخزون فورياً، مما يوفر وقتك ويمنع أخطاء الإدخال اليدوي المكرر."
                ))

            # 3. Debts & Receivables/Payables (حسابات الديون والعملاء والموردين)
            if wants_debts:
                points.append((
                    "متابعة ديون العملاء والموردين",
                    "يتضمن ناظم إدارة شاملة لحسابات العملاء والموردين وضبط حدود الائتمان، "
                    "مع متابعة دقيقة لكافة الديون والمستحقات، وإصدار كشوفات الحساب التفصيلية، والتنبيه بمواعيد الاستحقاق والسداد، "
                    "بالإضافة إلى تقارير تفصيلية لأعمار الديون للحفاظ على سلامة السيولة النقدية.\n"
                    "💡 الفائدة العملية: تسريع عمليات التحصيل وتقليل مخاطر الديون المتعثرة، مع وضوح كامل في تسوية مستحقات الموردين ومواعيد التزاماتك."
                ))

            # 4. Profits & Financial Reports (الأرباح والتقارير المالية)
            if wants_profits:
                points.append((
                    "الأرباح والتقارير المالية",
                    "يوفر ناظم تقارير مالية تفصيلية توضح أرباح متجرك وقائمة الأرباح والخسائر، "
                    "مع تحليل فوري ودقيق لهامش الربح لكل فاتورة وصنف، وتقارير أداء المستودعات لمعرفة الأرباح بوضوح وموثوقية.\n"
                    "💡 الفائدة العملية: معرفة صافي أرباحك الحقيقية بدقة، مما يساعدك على اتخاذ قرارات تسعير مدروسة وتحديد الأصناف والمستودعات الأكثر إنتاجية لمتجرك."
                ))

            # 5. POS (نقاط البيع) - Only if explicitly requested
            if wants_pos:
                points.append((
                    "نقاط البيع (POS)",
                    "واجهة بيع سريعة تدعم قارئ الباركود، وإدارة ورديات الكاشير، والطباعة الفورية للفواتير مع تحديث المخزون آلياً.\n"
                    "💡 الفائدة العملية: سرعة خدمة الزبائن في المتجر وإحكام الرقابة التامة على الصندوق والمطابقة النقدية مع كل إقفال وردية."
                ))

            # 6. General overview fallback (if customer asked broadly about Nazem without specific sub-facets)
            if is_general_product_q and not points:
                points.append((
                    "إدارة المستودعات والمخزون",
                    "دعم الفروع والمستودعات المتعددة، التحويل بين المستودعات، والجرد والتسويات بالباركود لضبط حركة البضاعة."
                ))
                points.append((
                    "المبيعات والمشتريات",
                    "فواتير نقدية وآجلة، عروض أسعار، ومتابعة فورية للمخزون واحتساب التكاليف آلياً."
                ))
                points.append((
                    "الأرباح وحسابات الديون",
                    "متابعة مديونيات العملاء والموردين، كشوفات الحساب، وتقارير الأرباح والخسائر لحماية السيولة وتحسين الأداء."
                ))

            sections = []
            # Opening
            if asks_separate_inventory:
                sections.append(
                    "أهلاً بك! يسعدنا توضيح تفاصيل ومميزات برنامج ناظم المحاسبي بالنسبة لمتجرك واحتياجاتك:\n\n"
                    "نعم، يلبي برنامج ناظم كافة متطلبات نشاطك بدقة وبصورة متكاملة؛ "
                    "حيث يدمج وظائف إدارة المستودعات والمخزون بالكامل مع المبيعات والمشتريات والمحاسبة المالية، "
                    "وبالتالي لا تحتاج إطلاقاً إلى شراء أو استخدام برنامج منفصل للمخزون."
                )
            else:
                sections.append(
                    "أهلاً بك! يسعدنا توضيح تفاصيل ومميزات برنامج ناظم المحاسبي بالنسبة لمتجرك واحتياجاتك:"
                )

            # Formatted numbered points
            for idx, (title, body) in enumerate(points, 1):
                sections.append(f"{idx}. {title}:\n{body}")

            # Closing follow-up question tailored to context
            if wants_debts or wants_profits:
                closing = "هل تود استعراض تفاصيل إضافية حول تقارير الديون والأرباح، أو ترغب في التنسيق لتجربة نسخة تجريبية من النظام لمتجرك؟"
            elif wants_warehouses:
                closing = "هل تود استعراض تفاصيل إضافية حول آلية التحويل والجرد بين المستودعين، أو تجربة نسخة تجريبية من النظام؟"
            else:
                closing = "هل تود التنسيق لتجربة نسخة تجريبية من النظام، أو تفضل استعراض كيفية إعداد فواتير المبيعات ونقاط البيع؟"

            sections.append(closing)
            return "\n\n".join(sections)

        # For other customer questions: strip owner meta commands if any and provide clean answer
        cleaned_answer = re.sub(
            r"^(?:احفظ\s+[^.\n]+(?:ورد\s+عليه)?|رد\s+عليه|جاوب\s+العميل)[.\s:\-]+",
            "",
            answer,
            flags=re.IGNORECASE,
        ).strip()
        cleaned_answer = re.sub(
            r"عشان\s+لو\s+جا\s+استفسار\s+مشابه.+",
            "",
            cleaned_answer,
            flags=re.DOTALL,
        ).strip()

        return f"مرحباً بك مجدداً! بخصوص استفسارك: '{inquiry.question}'\n\n{cleaned_answer or answer}"

    def _dispatch_tailored_reply_to_waiting_customers(
        self,
        inquiry: OwnerInquiry,
        tailored_reply: str,
    ) -> int:
        """
        Dispatches tailored reply to waiting customer conversations via Transactional Outbox,
        with strict idempotency guards:
        1. Suppresses dispatch if an inquiry reply for this inquiry was already sent in the conversation.
        2. Suppresses dispatch if an agent inquiry reply was already sent after the customer's last message
           (closing the conversation turn until the customer sends a new message).
        3. Supersedes any other older open/asked inquiries for that customer conversation.
        Returns the number of messages successfully created and queued for dispatch.
        """
        tenant_id = inquiry.tenant_id
        waiting = list(inquiry.waiting_customers or [])
        if not waiting and inquiry.customer_conversation_id:
            waiting = [{
                "conversation_id": str(inquiry.customer_conversation_id),
                "customer_sender": inquiry.customer_sender,
            }]

        from packages.services.outbox_service import OutboxService
        outbox_svc = OutboxService(self.db, self.audit_service)
        dispatched_count = 0

        for cust in waiting:
            conv_id_str = cust.get("conversation_id")
            if not conv_id_str:
                continue
            try:
                conv_id = UUID(conv_id_str)
                cust_conv = self.db.scalar(
                    select(Conversation).where(
                        Conversation.id == conv_id,
                        Conversation.tenant_id == tenant_id,
                    )
                )
                if not cust_conv:
                    logger.warning("Cannot dispatch reply to customer %s: conversation not found", cust)
                    continue

                # A. Guard against re-dispatching reply for the same inquiry
                existing_inq_reply = self.db.scalar(
                    select(Message).where(
                        Message.conversation_id == conv_id,
                        Message.tenant_id == tenant_id,
                        Message.metadata_json["inquiry_id"].as_string() == str(inquiry.id),
                    )
                )
                if existing_inq_reply:
                    logger.info("Inquiry %s reply already exists in conversation %s. Skipping duplicate.", inquiry.id, conv_id)
                    continue

                # B. Conversation turn guard: If conversation already received an inquiry reply AFTER
                # the customer's latest message, suppress duplicate dispatch until customer sends a new message.
                last_cust_msg = self.db.scalar(
                    select(Message).where(
                        Message.conversation_id == conv_id,
                        Message.tenant_id == tenant_id,
                        Message.sender_type == "customer",
                    ).order_by(Message.created_at.desc())
                )
                last_agent_inquiry_reply = self.db.scalar(
                    select(Message).where(
                        Message.conversation_id == conv_id,
                        Message.tenant_id == tenant_id,
                        Message.sender_type == "agent",
                        Message.metadata_json["is_inquiry_reply"].as_boolean() == True,
                    ).order_by(Message.created_at.desc())
                )
                if (
                    last_cust_msg
                    and last_agent_inquiry_reply
                    and last_agent_inquiry_reply.created_at > last_cust_msg.created_at
                ):
                    logger.info(
                        "Conversation %s already received an inquiry reply at %s after customer message at %s. Suppressing duplicate reply for inquiry %s.",
                        conv_id,
                        last_agent_inquiry_reply.created_at,
                        last_cust_msg.created_at,
                        inquiry.id,
                    )
                    continue

                # C. Supersede any other older open/asked inquiries for this same customer conversation
                other_stale_inqs = self.db.scalars(
                    select(OwnerInquiry).where(
                        OwnerInquiry.tenant_id == tenant_id,
                        OwnerInquiry.customer_conversation_id == conv_id,
                        OwnerInquiry.id != inquiry.id,
                        OwnerInquiry.status.in_(["open", "asked"]),
                    )
                ).all()
                for stale in other_stale_inqs:
                    stale.status = "superseded"
                    stale.owner_answer = f"تم تجاوزه بحل الاستفسار #{inquiry.inquiry_number}"
                    self.db.add(stale)

                cust_recipient = (
                    cust.get("customer_sender")
                    or (cust_conv.metadata_json or {}).get("sender_id")
                    or inquiry.customer_sender
                )

                effective_channel_id = cust_conv.channel_id
                if not effective_channel_id:
                    active_chan = self.db.scalar(
                        select(Channel).where(Channel.tenant_id == tenant_id, Channel.status == "active")
                    )
                    if active_chan:
                        effective_channel_id = active_chan.id

                cust_reply = Message(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    conversation_id=conv_id,
                    sender_type="agent",
                    customer_id=cust_conv.customer_id,
                    content=tailored_reply,
                    metadata_json={
                        "inquiry_id": str(inquiry.id),
                        "inquiry_number": inquiry.inquiry_number,
                        "delivery_status": "pending_dispatch" if effective_channel_id else "delivered",
                        "is_inquiry_reply": True,
                    },
                )
                self.db.add(cust_reply)
                self.db.flush()

                if effective_channel_id and cust_recipient:
                    outbox_svc.create_event(
                        tenant_id=tenant_id,
                        conversation_id=conv_id,
                        message_id=cust_reply.id,
                        idempotency_key=f"outbox:inquiry_reply:{inquiry.id}:{conv_id}:{cust_reply.id}",
                        event_type="dispatch_channel_reply",
                        payload={
                            "channel_id": str(effective_channel_id),
                            "recipient": str(cust_recipient),
                            "content": tailored_reply,
                            "reply_message_id": str(cust_reply.id),
                        },
                    )
                dispatched_count += 1
            except Exception as err:
                logger.warning("Error dispatching answer to customer %s: %s", cust, err)

        return dispatched_count

    def answer_inquiry(
        self,
        tenant_id: UUID,
        inquiry: OwnerInquiry,
        answer: str,
    ) -> str:
        """
        Persists owner's answer as confirmed facts, generates tailored reply for waiting customer(s),
        dispatches via Transactional Outbox, and prompts owner for confirmation.
        """
        if inquiry.status in ("answered", "delivered"):
            logger.info("Inquiry %s is already %s. Skipping duplicate resolution.", inquiry.id, inquiry.status)
            return f"✅ الاستفسار (#{inquiry.inquiry_number}) تم الرد عليه مسبقاً وحالته: {inquiry.status}."

        now = datetime.now(timezone.utc)
        inquiry.owner_answer = answer
        inquiry.status = "answered"
        inquiry.answered_at = now

        # 1. If answer contains Nazem features list, structure and save modular facts
        if "مميزات ناظم" in answer or "المحاسبة المالية" in answer or "المخزون" in answer:
            self._persist_classified_product_knowledge(tenant_id, answer)
        else:
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

        # 2. Synthesize tailored customer reply
        tailored_reply = self._synthesize_tailored_customer_reply(inquiry, answer)

        # 3. Dispatch to waiting customers with strict idempotency
        self._dispatch_tailored_reply_to_waiting_customers(inquiry, tailored_reply)

        # Do NOT set inquiry.status = 'delivered' here!
        # The OutboxWorker will update status to 'delivered' upon successful delivery.
        inquiry.status = "answered"
        self.db.flush()

        # 4. Prompt owner for scope confirmation
        return "✅ تم إرسال الإجابة للعميل وحفظها.\n\nأحفظها للجميع أم لهذا العميل فقط؟"

    def handle_knowledge_teaching(self, tenant_id: UUID, content: str) -> str | None:
        """
        Handles owner teaching product knowledge (e.g. features list) directly.
        If owner instructs 'رد عليه' but there are multiple open inquiries, asks for clarification
        instead of guessing an arbitrary customer!
        """
        c_lower = content.lower()
        is_knowledge_teaching = bool(
            re.search(
                r"احفظ\s+(?:مميزات|معلومات|بيانات|هذه\s+المميزات)|ملخص\s+مميزات|مميزات\s+برنامج\s+ناظم|هذه\s+مميزات\s+ناظم",
                c_lower,
            )
        )
        if not is_knowledge_teaching:
            return None

        # 1. Persist classified knowledge
        self._persist_classified_product_knowledge(tenant_id, content)

        # 2. Check if there was an order to reply to a customer ('رد عليه')
        has_reply_order = bool(re.search(r"(?:رد\s+عليه|رد\s+على\s+العميل|جاوب\s+العميل)", c_lower))
        if has_reply_order:
            open_inqs = self.db.scalars(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.status.in_(["open", "asked"]),
                ).order_by(OwnerInquiry.inquiry_number.asc())
            ).all()

            if len(open_inqs) == 1:
                # Single pending inquiry -> answer it directly!
                return self.answer_inquiry(tenant_id, open_inqs[0], content)
            elif len(open_inqs) > 1:
                inq_nums_str = ", ".join(f"#{i.inquiry_number}" for i in open_inqs)
                return (
                    f"✅ تم استيعاب وتوثيق مميزات برنامج ناظم في قاعدة الحقائق المعتمدة بنجاح.\n\n"
                    f"⚠️ نظراً لوجود عدة استفسارات معلقة ({inq_nums_str})، يرجى تحديد رقم الاستفسار الذي ترغب بالرد عليه (مثال: رد {open_inqs[-1].inquiry_number}: اعتمد الرد)."
                )

        return "✅ تم استيعاب وتوثيق مميزات برنامج ناظم في قاعدة الحقائق المعتمدة بنجاح."

    def handle_owner_feature_reference(
        self,
        tenant_id: UUID,
        content: str,
        conversation_id: UUID | None = None,
    ) -> tuple[OwnerInquiry | None, str | None]:
        """
        Detects if owner affirms that the answer to an open inquiry is already documented
        in product features/knowledge (e.g. 'هذا الموضوع ذكرته لك انا في المميزات').
        Identifies the targeted open inquiry and resolves it using documented knowledge.
        """
        c_lower = content.strip().lower()
        is_feature_ref = bool(
            re.search(
                r"(?:(?:هذا\s+)?(?:الموضوع|الأمر|الكلام)\s+)?(?:ذكرت|وضحت|قلت|سجلت|بينت|مكتوب|موجود|محفوظ|مسجل|موثق).*(?:مميزات|حقائق|معلومات|ناظم)|(?:معلومات|مميزات|إجابة|اجابة).*(?:موجود|محفوظ|مسجل|موثق)|(?:سبق\s+(?:و)?(?:ذكرت|وضحت|سجلت|بينت))|(?:جاوب\s+العميل\s+من\s+(?:المميزات|المعلومات))",
                c_lower,
            )
        )
        if not is_feature_ref:
            return None, None

        # 1. Check if inquiry number is specified in content (e.g. "في استفسار 7")
        inq_num = self._find_inquiry_number_in_text(content)
        target_inquiry = None
        if inq_num:
            target_inquiry = self.db.scalar(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.inquiry_number == inq_num,
                    OwnerInquiry.status.in_(["open", "asked"]),
                )
            )

        # 2. Check the most recent inquiry notified in this conversation
        if not target_inquiry and conversation_id:
            recent_notif = self.db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.tenant_id == tenant_id,
                    Message.metadata_json["is_owner_notification"].as_boolean() == True,
                ).order_by(Message.created_at.desc())
            )
            if recent_notif and recent_notif.metadata_json:
                inq_id_meta = recent_notif.metadata_json.get("inquiry_id")
                if inq_id_meta:
                    target_inquiry = self.db.scalar(
                        select(OwnerInquiry).where(
                            OwnerInquiry.tenant_id == tenant_id,
                            OwnerInquiry.id == UUID(str(inq_id_meta)),
                            OwnerInquiry.status.in_(["open", "asked"]),
                        )
                    )

        # 3. Check open inquiries across tenant (Zero Guesswork)
        if not target_inquiry:
            open_inqs = self.db.scalars(
                select(OwnerInquiry).where(
                    OwnerInquiry.tenant_id == tenant_id,
                    OwnerInquiry.status.in_(["open", "asked"]),
                ).order_by(OwnerInquiry.inquiry_number.asc())
            ).all()

            if len(open_inqs) == 1:
                target_inquiry = open_inqs[0]
            elif len(open_inqs) > 1:
                inq_nums_str = ", ".join(f"#{i.inquiry_number}" for i in open_inqs)
                return None, (
                    f"✅ تم تأكيد وجود المعرفة في مميزات برنامج ناظم المحفوظة.\n\n"
                    f"⚠️ نظراً لوجود عدة استفسارات معلقة ({inq_nums_str})، يرجى تحديد رقم الاستفسار المقصود بالرد (مثال: رد {open_inqs[-1].inquiry_number}: اعتمد الرد من المميزات)."
                )
            else:
                return None, "✅ تم مراجعة المميزات المحفوظة، ولا توجد استفسارات معلقة حالياً بانتظار الإجابة."

        if not target_inquiry:
            return None, None

        owner_ack_reply = self.resolve_inquiry_from_stored_knowledge(
            tenant_id=tenant_id,
            inquiry=target_inquiry,
            owner_instruction=content,
        )
        return target_inquiry, owner_ack_reply

    def resolve_inquiry_from_stored_knowledge(
        self,
        tenant_id: UUID,
        inquiry: OwnerInquiry,
        owner_instruction: str,
    ) -> str:
        """
        Resolves an open inquiry by retrieving documented public facts,
        synthesizing the tailored customer reply, enqueuing it in Outbox,
        and updating the inquiry state.
        """
        if inquiry.status in ("answered", "delivered"):
            logger.info("Inquiry %s is already %s. Skipping duplicate resolution.", inquiry.id, inquiry.status)
            return f"✅ الاستفسار (#{inquiry.inquiry_number}) تم الرد عليه مسبقاً وحالته: {inquiry.status}."

        now = datetime.now(timezone.utc)
        inquiry.owner_answer = f"تم الاعتماد من مميزات ناظم المحفوظة بناءً على توجيه المالك: {owner_instruction}"
        inquiry.status = "answered"
        inquiry.answered_at = now

        # Synthesize tailored customer reply from stored product knowledge
        tailored_reply = self._synthesize_tailored_customer_reply(inquiry, "مميزات برنامج ناظم")

        # Dispatch to waiting customers with strict idempotency
        self._dispatch_tailored_reply_to_waiting_customers(inquiry, tailored_reply)

        inquiry.status = "answered"
        self.db.flush()

        return f"✅ تم استرجاع مميزات برنامج ناظم المعتمدة وإرسال الرد المفصل للعميل (#{inquiry.inquiry_number}) عبر تيليجرام بنجاح."

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
            owner_conv, owner_recipient = self._find_owner_conversation(inq.tenant_id)
            if owner_conv and owner_recipient and owner_conv.channel_id:
                inq.reminded_at = now
                reminded_count += 1
                remind_text = f"⏰ تذكير: الاستفسار #{inq.inquiry_number} بانتظار ردك:\n\"{inq.question}\""
                msg = Message(
                    id=uuid4(),
                    tenant_id=inq.tenant_id,
                    conversation_id=owner_conv.id,
                    sender_type="agent",
                    content=remind_text,
                    metadata_json={
                        "inquiry_id": str(inq.id),
                        "inquiry_number": inq.inquiry_number,
                        "delivery_status": "pending_dispatch",
                        "is_reminder": True,
                    },
                )
                self.db.add(msg)
                self.db.flush()

                from packages.services.outbox_service import OutboxService
                outbox_svc = OutboxService(self.db, self.audit_service)
                outbox_svc.create_event(
                    tenant_id=inq.tenant_id,
                    conversation_id=owner_conv.id,
                    message_id=msg.id,
                    idempotency_key=f"outbox:inquiry_remind:{inq.id}:{msg.id}",
                    event_type="dispatch_channel_reply",
                    payload={
                        "channel_id": str(owner_conv.channel_id),
                        "recipient": str(owner_recipient),
                        "content": remind_text,
                        "reply_message_id": str(msg.id),
                    },
                )

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
