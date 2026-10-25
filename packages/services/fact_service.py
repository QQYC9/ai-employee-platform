from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProvider
from packages.models.domain import BusinessBrain, Fact, Knowledge
from packages.services.audit_service import AuditService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured Model Fact Extraction
# ---------------------------------------------------------------------------
class ExtractedFactItem(BaseModel):
    topic: str = Field(
        ...,
        description="Hierarchical lowercase slug, e.g. 'company.identity', 'product.nazim.features', 'delivery.coverage.yemen'",
    )
    subject: str = Field(
        ...,
        description="Clear descriptive subject in Arabic or English, e.g. 'اسم الشركة', 'برنامج ناظم المحاسبي', 'نطاق التوصيل'",
    )
    value: Any = Field(
        ...,
        description="Fact value (structured dictionary, list, string, number, or boolean)",
    )
    visibility: Literal["public", "private"] = Field(
        default="public",
        description="'public' may be shared with customers; 'private' is for internal margins, credentials, or internal goals",
    )
    expires_in_days: int | None = Field(
        default=None,
        description="Optional expiration in days (e.g. 90 for prices/stock, 180 for seasonal hours)",
    )
    is_direct_unambiguous: bool = Field(
        default=True,
        description="True if the owner explicitly and directly asserted this fact; False if inferred or ambiguous",
    )


class FactExtractionResponse(BaseModel):
    facts: list[ExtractedFactItem] = Field(default_factory=list)
    summary_ar: str = Field(
        ...,
        description="Clear, short, polite Arabic summary of the extracted facts presented to the owner for confirmation",
    )


# ---------------------------------------------------------------------------
# FactService Implementation
# ---------------------------------------------------------------------------
class FactService:
    """
    Phase 2 Facts Store Service:
    Provides structured knowledge extraction, confirmation workflows, conflict handling,
    expiry management, and tenant-isolated retrieval.
    """

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

    # -----------------------------------------------------------------------
    # 1. Structured Fact Extraction (AI Model Primary + Regex Fallback)
    # -----------------------------------------------------------------------
    def extract_facts(
        self,
        tenant_id: UUID,
        message_text: str,
        provider: AIProvider | None = None,
    ) -> FactExtractionResponse:
        """
        Extracts structured facts from owner message text.
        Primary path: AI Provider structured JSON generation.
        Secondary path: Documented regex extraction fallback if provider is unavailable or fails.
        Handles Arabic dialect text (such as Yemeni Arabic: 'نبيع', 'نخدم', 'حقنا', 'المحل').
        """
        if not message_text or not message_text.strip():
            return FactExtractionResponse(facts=[], summary_ar="لم يتم إرسال أي نص لاستخراج المعلومات.")

        if provider is not None:
            try:
                system_instruction = (
                    "You are an expert enterprise knowledge extraction engine for an autonomous digital employee platform.\n"
                    "Your task is to analyze messages sent by the business owner (including Yemeni and Arab business dialects) "
                    "and extract verified business facts into a structured JSON array conforming to the specified schema.\n\n"
                    "Guidelines:\n"
                    "1. Handle multiple facts in a single sentence (e.g. company name, product catalog, delivery cities, working hours).\n"
                    "2. Support Yemeni Arabic phrases like 'نبيع' (we sell), 'نخدم' (we serve/cover), 'حقنا' (our), 'المحل' (the shop).\n"
                    "3. Assign appropriate topic slugs (e.g. 'company.identity', 'product.<name>', 'service.<name>', 'operations.coverage', 'pricing.<item>', 'policies.<type>').\n"
                    "4. Visibility must be 'public' unless the information is explicitly internal (cost margins, employee salaries, confidential passwords).\n"
                    "5. Assign expiration (expires_in_days) for prices (90 days), seasonal stock (30 days), or temporary promotions.\n"
                    "6. Provide a concise, professional Arabic summary (summary_ar) acknowledging the extracted facts."
                )

                prompt = (
                    f"Owner Message Content:\n\"\"\"{message_text}\"\"\"\n\n"
                    "Extract all business facts and return a valid JSON object matching the FactExtractionResponse schema:\n"
                    "{\n"
                    "  \"facts\": [\n"
                    "    {\n"
                    "      \"topic\": \"<slug>\",\n"
                    "      \"subject\": \"<arabic_or_english_title>\",\n"
                    "      \"value\": <structured_value>,\n"
                    "      \"visibility\": \"public\" | \"private\",\n"
                    "      \"expires_in_days\": <int_or_null>,\n"
                    "      \"is_direct_unambiguous\": true | false\n"
                    "    }\n"
                    "  ],\n"
                    "  \"summary_ar\": \"<arabic_readable_summary>\"\n"
                    "}"
                )

                raw_json = provider.generate_json(
                    prompt,
                    schema=FactExtractionResponse.model_json_schema(),
                    system_instruction=system_instruction,
                )

                if raw_json and isinstance(raw_json, dict) and "facts" in raw_json:
                    parsed = FactExtractionResponse.model_validate(raw_json)
                    if parsed.facts:
                        return parsed
            except Exception as exc:
                logger.warning("AI Model structured fact extraction failed for tenant %s: %s; falling back to regex", tenant_id, exc, exc_info=True)

        # Fallback to deterministic regex extraction
        return self._extract_facts_regex_fallback(message_text)

    def _extract_facts_regex_fallback(self, text: str) -> FactExtractionResponse:
        """
        Documented deterministic fallback extraction for Arabic business declarations.
        Handles company identity, company description, product catalog, and delivery coverage zones.
        """
        facts: list[ExtractedFactItem] = []
        summary_lines: list[str] = []

        # 1. Company Name Extraction
        name_match = re.search(
            r"(?:(?:ال)?اسم\s*(?:الشركة|المنشأة|المحل|المتجر|المؤسسة|شركتنا|منشأتنا|التجاري(?:\s*(?:الرسمي|المعتمد|لمنشأتنا|لشركتنا))?)|نحن|معكم)\s*[:—\-=]?\s*([^\n،,.]+)",
            text,
            re.IGNORECASE,
        )
        cleaned_name = None
        if name_match:
            raw_name = name_match.group(1).strip()
            cleaned_name = re.sub(
                r"^(?:الرسمي|المعتمد|الرسمية|المعتمدة|لدينا|لمنشأتنا|لشركتنا|لمتجرنا|الخاص\s*بنا|الخاص|هو|يكون)\s+",
                "",
                raw_name,
            ).strip()
            # Stop before verbs like "نبيع" or "نخدم" or "شركة"
            cleaned_name = re.split(r"\s+(?:نبيع|نخدم|نوفر|نقدم|لدينا)\b", cleaned_name)[0].strip()
            if cleaned_name:
                facts.append(
                    ExtractedFactItem(
                        topic="company.identity",
                        subject="اسم المنشأة",
                        value={"name": cleaned_name},
                        visibility="public",
                        is_direct_unambiguous=True,
                    )
                )
                summary_lines.append(f"🏢 اسم المنشأة: {cleaned_name}")

        # 1.5. Company Activity / Description
        desc_match = re.search(
            r"(?:شركة|مؤسسة|منشأة|متجر|متخصصون\s*في|مجالنا)\s+([^\n.]+?)(?=\.|\n|نبيع|نوفر|نقدم|نخدم|$)",
            text,
            re.IGNORECASE,
        )
        if desc_match:
            raw_desc = desc_match.group(0).strip()
            # Only add if it's descriptive and not just the company name itself
            if raw_desc and len(raw_desc) > 8 and "نبيع" not in raw_desc and raw_desc != cleaned_name:
                facts.append(
                    ExtractedFactItem(
                        topic="company.description",
                        subject="مجال النشاط",
                        value={"description": raw_desc},
                        visibility="public",
                        is_direct_unambiguous=True,
                    )
                )
                summary_lines.append(f"📋 مجال النشاط: {raw_desc}")

        # 2. Product Catalog Extraction
        # Match sentences declaring selling products (e.g. "نبيع الموظف الذكي وبرنامج ناظم المحاسبي وبرنامج سيرو لإدارة الشبكات")
        sell_match = re.search(
            r"(?:نبيع|نوفر|نقدم|منتجاتنا(?:\s*هي)?|لدينا\s*(?:منتجات)?)\s*[:—\-=]?\s*(.+?)(?=(?:\.?\s*(?:نخدم|فروعنا|ونوصل|ساعات)|\n|$))",
            text,
            re.IGNORECASE,
        )
        if sell_match:
            prods_clause = sell_match.group(1).strip()
            # Strip trailing period if present
            prods_clause = re.sub(r"\.+$", "", prods_clause).strip()
            # Strip introductory quantifiers like "ثلاثة منتجات:" or "قائمة المنتجات:"
            prods_clause = re.sub(
                r"^(?:ثلاثة|أربعة|خمسة|ستة|عدة|\d+)?\s*منتجات\s*[:\s]*",
                "",
                prods_clause,
                flags=re.IGNORECASE,
            ).strip()
            # Split items on comma or 'و'
            raw_items = re.split(r"[،,]+|\s+و(?=\S)", prods_clause)
            for item in raw_items:
                clean_item = item.strip()
                # Clean trailing modifiers like "والتحكم الكامل بها"
                clean_item = re.split(r"\s+(?:والتحكم|بحيث|مع|في)\b", clean_item)[0].strip()
                if clean_item and len(clean_item) > 2 and not clean_item.startswith("نخدم"):
                    if "ناظم" in clean_item:
                        slug = "nazim_accounting"
                    elif "سيرو" in clean_item:
                        slug = "ciro_networks"
                    elif "الموظف الذكي" in clean_item or "موظف ذكي" in clean_item:
                        slug = "smart_employee"
                    else:
                        slug = re.sub(r"[^\w]+", "_", clean_item.lower()).strip("_")
                    facts.append(
                        ExtractedFactItem(
                            topic=f"product.{slug[:40]}",
                            subject=clean_item,
                            value={"name": clean_item, "type": "product"},
                            visibility="public",
                            is_direct_unambiguous=True,
                        )
                    )
                    summary_lines.append(f"📦 منتج: {clean_item}")

        # 3. Delivery Coverage / Cities Extraction
        # Match coverage cities (e.g. "نخدم صنعاء والحديدة وذمار وإب والمحويت وريمة" or "نخدم أيضًا محافظة عمران")
        service_match = re.search(
            r"(?:نخدم|نوصل\s*(?:إلى|لـ)?|فروعنا\s*(?:في)?|تغطيتنا\s*(?:في)?)\s*[:—\-=]?\s*([^\n.]+)",
            text,
            re.IGNORECASE,
        )
        if service_match:
            cities_clause = service_match.group(1).strip()
            known_cities = [
                "صنعاء", "الحديدة", "ذمار", "إب", "المحويت", "ريمة", "عدن", "تعز",
                "حضرموت", "المكلا", "مأرب", "صعدة", "عمران", "حجة", "البيضاء", "لحج", "أبين", "شبوة",
                "الرياض", "جدة", "الدمام", "مكة", "المدينة", "دبي", "أبوظبي"
            ]
            found_cities: list[str] = []
            for city in known_cities:
                if city in cities_clause:
                    found_cities.append(city)

            if found_cities:
                facts.append(
                    ExtractedFactItem(
                        topic="operations.delivery_zones",
                        subject="نطاق التوصيل والمدن المدعومة",
                        value={"cities": found_cities},
                        visibility="public",
                        is_direct_unambiguous=True,
                    )
                )
                summary_lines.append(f"📍 المدن ونطاق التغطية: {', '.join(found_cities)}")

        # 4. Working Hours Extraction
        hours_match = re.search(
            r"(?:أوقات|ساعات|دوام)\s*(?:العمل)?\s*[:—\-=]?\s*([^\n.]+)",
            text,
            re.IGNORECASE,
        )
        if hours_match:
            hours_val = hours_match.group(1).strip()
            facts.append(
                ExtractedFactItem(
                    topic="operations.working_hours",
                    subject="أوقات العمل",
                    value={"hours": hours_val},
                    visibility="public",
                    expires_in_days=180,
                    is_direct_unambiguous=True,
                )
            )
            summary_lines.append(f"⏰ أوقات العمل: {hours_val}")

        summary_text = (
            "تم استيعاب المعلومات التالية وتوثيقها:\n" + "\n".join(summary_lines)
            if summary_lines
            else "تم تسجيل المعلومات بنجاح."
        )

        return FactExtractionResponse(facts=facts, summary_ar=summary_text)

    # -----------------------------------------------------------------------
    # 2. Storage, Confirmation, and Conflict Detection
    # -----------------------------------------------------------------------
    def save_extracted_facts(
        self,
        tenant_id: UUID,
        extracted_facts: list[ExtractedFactItem],
        auto_confirm_direct: bool = True,
        message_text: str | None = None,
    ) -> dict[str, Any]:
        """
        Saves extracted facts into the database while detecting conflicts and managing confirmation.
        - Direct unambiguous statements: saved as 'confirmed' (if auto_confirm_direct=True) with read-back.
        - Inferred or ambiguous statements: saved as 'pending_confirmation'.
        - Contradictory statements against existing confirmed facts on the same topic/subject:
          saved as 'conflict' without silent overwrites, returning a conflict report for owner decision.
        - Additive statements (e.g. adding new delivery zones with 'أيضًا'): merged into existing coverage without conflict.
        """
        confirmed_records: list[Fact] = []
        pending_records: list[Fact] = []
        conflict_records: list[dict[str, Any]] = []

        now = datetime.now(timezone.utc)
        is_additive = bool(
            message_text
            and re.search(
                r"(?:أيضًا|ايضا|كذلك|بالإضافة|إضافة|اضافة|كمان|وايضا|وأيضا|ومعاها|ومعها)",
                message_text,
            )
        )

        for item in extracted_facts:
            is_coverage_item = (
                item.topic in ("operations.delivery_zones", "operations.coverage")
                or (item.topic.startswith("operations.") and any(k in item.subject for k in ["مدن", "تغطية", "نطاق", "فروع", "مناطق"]))
            )

            # Check for existing active confirmed facts on this topic and subject
            if is_coverage_item:
                existing_fact = self.db.scalar(
                    select(Fact).where(
                        Fact.tenant_id == tenant_id,
                        Fact.topic.in_(["operations.delivery_zones", "operations.coverage"]),
                        Fact.status == "confirmed",
                        Fact.superseded_by.is_(None),
                    )
                )
            else:
                existing_fact = self.db.scalar(
                    select(Fact).where(
                        Fact.tenant_id == tenant_id,
                        Fact.topic == item.topic,
                        Fact.status == "confirmed",
                        Fact.superseded_by.is_(None),
                    )
                )
                if not existing_fact:
                    existing_fact = self.db.scalar(
                        select(Fact).where(
                            Fact.tenant_id == tenant_id,
                            Fact.topic == item.topic,
                            Fact.subject == item.subject,
                            Fact.status == "confirmed",
                            Fact.superseded_by.is_(None),
                        )
                    )

            expires_at = None
            if item.expires_in_days:
                expires_at = now + timedelta(days=item.expires_in_days)

            # Handle additive updates for coverage / delivery zones
            is_coverage_additive = False
            if is_coverage_item and existing_fact is not None:
                def _extract_cities_list(val: Any) -> list[str]:
                    if isinstance(val, list):
                        return [str(c).strip() for c in val if str(c).strip()]
                    if isinstance(val, dict):
                        raw = val.get("cities") or val.get("coverage") or val.get("zones") or []
                        if isinstance(raw, list):
                            return [str(c).strip() for c in raw if str(c).strip()]
                        if isinstance(raw, str):
                            return [c.strip() for c in raw.split("،") if c.strip()]
                    if isinstance(val, str):
                        return [c.strip() for c in val.split("،") if c.strip()]
                    return []

                existing_cities = _extract_cities_list(existing_fact.value)
                new_cities = _extract_cities_list(item.value)
                if is_additive or (new_cities and not any(c in existing_cities for c in new_cities)):
                    merged_cities = list(dict.fromkeys(existing_cities + new_cities))
                    if isinstance(existing_fact.value, dict):
                        item.value = dict(existing_fact.value)
                        item.value["cities"] = merged_cities
                    elif isinstance(item.value, dict):
                        item.value = {"cities": merged_cities}
                    else:
                        item.value = merged_cities
                    item.topic = existing_fact.topic
                    item.subject = existing_fact.subject
                    is_coverage_additive = True

            # Conflict Detection:
            # If an existing confirmed fact exists and its value is different from the new value
            if existing_fact is not None and existing_fact.value != item.value and not is_coverage_additive:
                # Store new fact with status='conflict' without deleting existing fact
                conflict_fact = Fact(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    topic=item.topic,
                    subject=item.subject,
                    value=item.value,
                    source="owner_stated",
                    confidence=0.8,
                    visibility=item.visibility,
                    status="conflict",
                    expires_at=expires_at,
                )
                self.db.add(conflict_fact)
                self.db.flush()

                conflict_records.append(
                    {
                        "existing_fact": existing_fact,
                        "conflicting_fact": conflict_fact,
                        "topic": item.topic,
                        "subject": item.subject,
                    }
                )
                continue

            # Determine status based on certainty and auto-confirm policy
            if item.is_direct_unambiguous and auto_confirm_direct:
                fact_status = "confirmed"
                fact_source = "owner_stated"
            else:
                fact_status = "pending_confirmation"
                fact_source = "inferred"

            # If replacing an identical or superseded existing fact
            new_fact = Fact(
                id=uuid4(),
                tenant_id=tenant_id,
                topic=item.topic,
                subject=item.subject,
                value=item.value,
                source=fact_source,
                confidence=1.0 if fact_status == "confirmed" else 0.75,
                visibility=item.visibility,
                status=fact_status,
                expires_at=expires_at,
            )
            self.db.add(new_fact)
            self.db.flush()

            if existing_fact is not None and existing_fact.id != new_fact.id:
                existing_fact.superseded_by = new_fact.id
                existing_fact.status = "superseded"
                self.db.flush()

            if fact_status == "confirmed":
                confirmed_records.append(new_fact)
            else:
                pending_records.append(new_fact)

        self.db.commit()

        return {
            "confirmed": confirmed_records,
            "pending": pending_records,
            "conflicts": conflict_records,
        }

    def confirm_fact(self, tenant_id: UUID, fact_id: UUID) -> Fact:
        """Confirms a pending_confirmation fact and marks it as owner_confirmed."""
        fact = self.db.scalar(
            select(Fact).where(Fact.id == fact_id, Fact.tenant_id == tenant_id)
        )
        if fact is None:
            raise ValueError(f"Fact '{fact_id}' not found for tenant '{tenant_id}'")

        fact.status = "confirmed"
        fact.source = "owner_confirmed"
        fact.confidence = 1.0
        self.db.commit()
        self.db.refresh(fact)
        return fact

    def correct_fact(self, tenant_id: UUID, fact_id: UUID, corrected_value: Any) -> Fact:
        """Replaces a pending or existing fact with a corrected value stated by the owner."""
        fact = self.db.scalar(
            select(Fact).where(Fact.id == fact_id, Fact.tenant_id == tenant_id)
        )
        if fact is None:
            raise ValueError(f"Fact '{fact_id}' not found for tenant '{tenant_id}'")

        new_fact = Fact(
            id=uuid4(),
            tenant_id=tenant_id,
            topic=fact.topic,
            subject=fact.subject,
            value=corrected_value,
            source="owner_confirmed",
            confidence=1.0,
            visibility=fact.visibility,
            status="confirmed",
            expires_at=fact.expires_at,
        )
        self.db.add(new_fact)
        self.db.flush()

        fact.superseded_by = new_fact.id
        fact.status = "superseded"
        self.db.commit()
        self.db.refresh(new_fact)
        return new_fact

    def resolve_conflict(
        self,
        tenant_id: UUID,
        kept_fact_id: UUID,
        rejected_fact_id: UUID,
    ) -> Fact:
        """
        Resolves an active conflict between two facts on the same topic/subject.
        The kept fact is marked as 'confirmed'; the rejected fact is marked as 'superseded'.
        """
        kept = self.db.scalar(
            select(Fact).where(Fact.id == kept_fact_id, Fact.tenant_id == tenant_id)
        )
        rejected = self.db.scalar(
            select(Fact).where(Fact.id == rejected_fact_id, Fact.tenant_id == tenant_id)
        )

        if kept is None or rejected is None:
            raise ValueError("Both facts must exist and belong to the tenant to resolve conflict")

        kept.status = "confirmed"
        kept.source = "owner_confirmed"
        kept.confidence = 1.0

        rejected.status = "superseded"
        rejected.superseded_by = kept.id

        self.db.commit()
        self.db.refresh(kept)
        return kept

    # -----------------------------------------------------------------------
    # 3. Expiry and Stale Facts Detection
    # -----------------------------------------------------------------------
    def list_stale_facts(self, tenant_id: UUID) -> list[Fact]:
        """
        Lists all facts for a tenant that have exceeded their expires_at timestamp.
        Automatically updates their status from 'confirmed' to 'stale'.
        """
        now = datetime.now(timezone.utc)
        statement = select(Fact).where(
            Fact.tenant_id == tenant_id,
            Fact.status.in_(["confirmed", "stale"]),
            Fact.expires_at.is_not(None),
            Fact.expires_at <= now,
            Fact.superseded_by.is_(None),
        ).order_by(Fact.expires_at.desc())

        stale_facts = list(self.db.scalars(statement).all())
        updated = False
        for f in stale_facts:
            if f.status != "stale":
                f.status = "stale"
                updated = True

        if updated:
            self.db.commit()

        return stale_facts

    # -----------------------------------------------------------------------
    # 4. Context Retrieval (Customer Public vs Owner Public+Private)
    # -----------------------------------------------------------------------
    def get_relevant_facts(
        self,
        tenant_id: UUID,
        query: str | None = None,
        include_private: bool = False,
        limit: int = 25,
    ) -> list[Fact]:
        """
        Retrieves relevant confirmed facts for a conversation query.
        - Customer path: Strictly queries visibility='public' and status='confirmed'.
        - Owner path: May query both visibility='public' and visibility='private'.
        - Excludes superseded, conflict, and expired facts.
        """
        now = datetime.now(timezone.utc)
        stmt = select(Fact).where(
            Fact.tenant_id == tenant_id,
            Fact.status == "confirmed",
            Fact.superseded_by.is_(None),
            or_(
                Fact.expires_at.is_(None),
                Fact.expires_at > now,
            ),
        )

        if not include_private:
            stmt = stmt.where(Fact.visibility == "public")

        all_facts = list(self.db.scalars(stmt).all())
        if not query or not query.strip():
            return all_facts[:limit]

        # Case-insensitive term search and relevance scoring across topic, subject, and value
        query_words = [w.lower() for w in re.findall(r"[\w\u0621-\u064A]+", query) if len(w) > 1]
        if not query_words:
            return all_facts[:limit]

        scored: list[tuple[int, Fact]] = []
        for fact in all_facts:
            val_str = json.dumps(fact.value, ensure_ascii=False).lower()
            subject_str = fact.subject.lower()
            topic_str = fact.topic.lower()

            score = 0
            for word in query_words:
                if word in subject_str:
                    score += 5
                if word in val_str:
                    score += 3
                if word in topic_str:
                    score += 2

            if score > 0 or not query_words:
                scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in scored[:limit]]

    # -----------------------------------------------------------------------
    # 5. Backup & Migration from BusinessBrain and Knowledge
    # -----------------------------------------------------------------------
    def backup_data_before_migration(self, output_dir: str = "backups") -> str:
        """
        Creates a verified JSON backup snapshot of all BusinessBrain and Knowledge
        records in the database before running migration. Returns backup file path.
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(output_dir, f"backup_pre_phase2_{timestamp}.json")

        brains = self.db.scalars(select(BusinessBrain)).all()
        knowledge = self.db.scalars(select(Knowledge)).all()

        backup_payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "business_brains_count": len(brains),
            "knowledge_count": len(knowledge),
            "business_brains": [
                {
                    "id": str(b.id),
                    "tenant_id": str(b.tenant_id),
                    "identity": b.identity,
                    "products": b.products,
                    "services": b.services,
                    "pricing": b.pricing,
                    "brand": b.brand,
                    "customers": b.customers,
                    "competitors": b.competitors,
                    "marketing": b.marketing,
                    "sales": b.sales,
                    "operations": b.operations,
                    "policies": b.policies,
                    "people": b.people,
                    "goals": b.goals,
                    "strategy": b.strategy,
                    "preferences": b.preferences,
                    "performance": b.performance,
                    "lessons": b.lessons,
                    "version": b.version,
                }
                for b in brains
            ],
            "knowledge": [
                {
                    "id": str(k.id),
                    "tenant_id": str(k.tenant_id),
                    "title": k.title,
                    "content": k.content,
                    "knowledge_type": k.knowledge_type,
                    "status": k.status,
                    "metadata_json": k.metadata_json,
                    "version": k.version,
                }
                for k in knowledge
            ],
        }

        raw_bytes = json.dumps(backup_payload, ensure_ascii=False, indent=2).encode("utf-8")
        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        backup_payload["sha256"] = sha256_hash

        with open(backup_path, "w", encoding="utf-8") as fp:
            json.dump(backup_payload, fp, ensure_ascii=False, indent=2)

        logger.info(
            "Created pre-migration backup at %s (Brains: %d, Knowledge: %d, SHA256: %s)",
            backup_path,
            len(brains),
            len(knowledge),
            sha256_hash[:12],
        )
        return backup_path

    def migrate_business_brains_and_knowledge_to_facts(
        self,
        tenant_id: UUID | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Migrates existing BusinessBrain and Knowledge rows to the Facts Store with zero data loss.
        Source records remain intact and readable as fallback.
        
        Per Phase 2 specification (Item 3 & 4):
        - Migrated rows get source="migrated" and status="pending_confirmation" (NOT confirmed)
          because legacy data originated from buggy regex extraction.
        - Supports dry_run mode to preview row counts per source table, rows per resulting topic,
          10 sample mappings (before/after), and skipped or malformed rows.
        """
        stmt_brains = select(BusinessBrain)
        stmt_knowledge = select(Knowledge)

        if tenant_id is not None:
            stmt_brains = stmt_brains.where(BusinessBrain.tenant_id == tenant_id)
            stmt_knowledge = stmt_knowledge.where(Knowledge.tenant_id == tenant_id)

        brains = list(self.db.scalars(stmt_brains).all())
        knowledge_rows = list(self.db.scalars(stmt_knowledge).all())

        migrated_facts_count = 0
        topic_counts: dict[str, int] = {}
        sample_mappings: list[dict[str, Any]] = []
        skipped_or_malformed: list[dict[str, Any]] = []

        # 1. Migrate Business Brains
        for brain in brains:
            t_id = brain.tenant_id

            def _add_migrated_fact(
                topic: str,
                subject: str,
                value: Any,
                visibility: str = "public",
                expires_in_days: int | None = None,
                source_field: str = "",
                raw_before: Any = None,
            ):
                nonlocal migrated_facts_count
                if not value:
                    skipped_or_malformed.append({
                        "source_table": "business_brains",
                        "tenant_id": str(t_id),
                        "source_field": source_field or topic,
                        "reason": "Value is empty or evaluates to falsy",
                    })
                    return

                # Check if already migrated
                exists = self.db.scalar(
                    select(Fact).where(
                        Fact.tenant_id == t_id,
                        Fact.topic == topic,
                        Fact.subject == subject,
                        Fact.superseded_by.is_(None),
                    )
                )
                if exists is not None:
                    skipped_or_malformed.append({
                        "source_table": "business_brains",
                        "tenant_id": str(t_id),
                        "source_field": source_field or topic,
                        "reason": f"Fact already exists with id {exists.id}",
                    })
                    return

                expires_at = None
                if expires_in_days:
                    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

                fact = Fact(
                    id=uuid4(),
                    tenant_id=t_id,
                    topic=topic,
                    subject=subject,
                    value=value,
                    source="migrated",
                    confidence=1.0,
                    visibility=visibility,
                    status="pending_confirmation",
                    expires_at=expires_at,
                )

                topic_counts[topic] = topic_counts.get(topic, 0) + 1
                migrated_facts_count += 1

                if len(sample_mappings) < 10:
                    sample_mappings.append({
                        "source_table": "business_brains",
                        "tenant_id": str(t_id),
                        "source_field": source_field,
                        "before": raw_before if raw_before is not None else value,
                        "after": {
                            "topic": fact.topic,
                            "subject": fact.subject,
                            "value": fact.value,
                            "source": fact.source,
                            "status": fact.status,
                            "visibility": fact.visibility,
                            "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
                        },
                    })

                if not dry_run:
                    self.db.add(fact)

            # Identity
            identity = brain.identity or {}
            if identity.get("name") or identity.get("company_name"):
                c_name = identity.get("name") or identity.get("company_name")
                _add_migrated_fact(
                    "company.identity", "اسم المنشأة", {"name": c_name},
                    source_field="identity.name", raw_before=identity,
                )
            else:
                skipped_or_malformed.append({
                    "source_table": "business_brains",
                    "tenant_id": str(t_id),
                    "source_field": "identity",
                    "reason": "Missing 'name' or 'company_name' key in identity JSON",
                })

            if identity.get("description") or identity.get("field"):
                f_desc = identity.get("description") or identity.get("field")
                _add_migrated_fact(
                    "company.description", "مجال النشاط", {"description": f_desc},
                    source_field="identity.description", raw_before=identity,
                )

            # Products
            products = brain.products or {}
            if isinstance(products, dict) and products:
                for p_name, p_data in products.items():
                    slug = re.sub(r"[^\w]+", "_", str(p_name).lower()).strip("_")
                    val = p_data if isinstance(p_data, dict) else {"name": p_name, "details": p_data}
                    _add_migrated_fact(
                        f"product.{slug[:40]}", str(p_name), val,
                        source_field="products", raw_before={p_name: p_data},
                    )
            elif isinstance(products, list) and products:
                for p_item in products:
                    if isinstance(p_item, str):
                        slug = re.sub(r"[^\w]+", "_", p_item.lower()).strip("_")
                        _add_migrated_fact(
                            f"product.{slug[:40]}", p_item, {"name": p_item},
                            source_field="products", raw_before=p_item,
                        )
            else:
                skipped_or_malformed.append({
                    "source_table": "business_brains",
                    "tenant_id": str(t_id),
                    "source_field": "products",
                    "reason": "Products field is empty or unpopulated",
                })

            # Services
            services = brain.services or {}
            if isinstance(services, dict) and services:
                for s_name, s_data in services.items():
                    slug = re.sub(r"[^\w]+", "_", str(s_name).lower()).strip("_")
                    val = s_data if isinstance(s_data, dict) else {"name": s_name, "details": s_data}
                    _add_migrated_fact(
                        f"service.{slug[:40]}", str(s_name), val,
                        source_field="services", raw_before={s_name: s_data},
                    )

            # Pricing
            pricing = brain.pricing or {}
            if pricing:
                _add_migrated_fact(
                    "pricing.general", "الأسعار والتسعير", pricing,
                    expires_in_days=90, source_field="pricing", raw_before=pricing,
                )

            # Operations (Branches, Locations, Hours)
            operations = brain.operations or {}
            if operations.get("branches") or operations.get("locations") or operations.get("cities"):
                branches_val = operations.get("branches") or operations.get("locations") or operations.get("cities")
                _add_migrated_fact(
                    "operations.branches", "الفروع والمواقع", branches_val,
                    source_field="operations.branches", raw_before=branches_val,
                )
            if operations.get("working_hours"):
                _add_migrated_fact(
                    "operations.working_hours", "أوقات العمل", {"working_hours": operations["working_hours"]},
                    expires_in_days=180, source_field="operations.working_hours", raw_before=operations["working_hours"],
                )
            if operations:
                _add_migrated_fact(
                    "operations.general", "العمليات التشغيلية", operations,
                    source_field="operations", raw_before=operations,
                )

            # Policies
            policies = brain.policies or {}
            if policies:
                _add_migrated_fact(
                    "company.policies", "سياسات المنشأة", policies,
                    source_field="policies", raw_before=policies,
                )

            # Brand
            brand = brain.brand or {}
            if brand:
                _add_migrated_fact(
                    "brand.identity", "الهوية والنبرة", brand,
                    source_field="brand", raw_before=brand,
                )

            # Internal / Private Sections
            for sec, vis in [("goals", "private"), ("strategy", "private"), ("competitors", "private"), ("lessons", "private")]:
                val = getattr(brain, sec, None) or {}
                if val:
                    _add_migrated_fact(
                        f"company.{sec}", sec.capitalize(), val,
                        visibility=vis, source_field=sec, raw_before=val,
                    )

        # 2. Migrate Knowledge Rows
        for k_row in knowledge_rows:
            if not k_row.title or not k_row.content:
                skipped_or_malformed.append({
                    "source_table": "knowledge",
                    "tenant_id": str(k_row.tenant_id),
                    "knowledge_id": str(k_row.id),
                    "reason": "Knowledge row lacks title or content",
                })
                continue

            topic_slug = f"knowledge.{k_row.knowledge_type or 'general'}"
            meta = k_row.metadata_json or {}
            is_private = meta.get("visibility") == "private" or meta.get("is_private") is True
            visibility = "private" if is_private else "public"

            exists = self.db.scalar(
                select(Fact).where(
                    Fact.tenant_id == k_row.tenant_id,
                    Fact.topic == topic_slug,
                    Fact.subject == k_row.title,
                    Fact.superseded_by.is_(None),
                )
            )
            if exists is not None:
                skipped_or_malformed.append({
                    "source_table": "knowledge",
                    "tenant_id": str(k_row.tenant_id),
                    "knowledge_id": str(k_row.id),
                    "reason": f"Fact already exists with id {exists.id}",
                })
                continue

            fact = Fact(
                id=uuid4(),
                tenant_id=k_row.tenant_id,
                topic=topic_slug,
                subject=k_row.title,
                value={"content": k_row.content, "metadata": meta},
                source="migrated",
                confidence=1.0,
                visibility=visibility,
                status="pending_confirmation",
            )
            topic_counts[topic_slug] = topic_counts.get(topic_slug, 0) + 1
            migrated_facts_count += 1

            if len(sample_mappings) < 10:
                sample_mappings.append({
                    "source_table": "knowledge",
                    "tenant_id": str(k_row.tenant_id),
                    "source_field": "title & content",
                    "before": {
                        "title": k_row.title,
                        "content": k_row.content[:100] + ("..." if len(k_row.content) > 100 else ""),
                        "knowledge_type": k_row.knowledge_type,
                        "status": k_row.status,
                    },
                    "after": {
                        "topic": fact.topic,
                        "subject": fact.subject,
                        "value": fact.value,
                        "source": fact.source,
                        "status": fact.status,
                        "visibility": fact.visibility,
                        "expires_at": None,
                    },
                })

            if not dry_run:
                self.db.add(fact)

        if not dry_run:
            self.db.commit()

        return {
            "dry_run": dry_run,
            "migrated_facts_count": migrated_facts_count,
            "source_table_counts": {
                "business_brains": len(brains),
                "knowledge": len(knowledge_rows),
            },
            "rows_per_resulting_topic": topic_counts,
            "sample_mappings": sample_mappings,
            "skipped_or_malformed_count": len(skipped_or_malformed),
            "skipped_or_malformed_samples": skipped_or_malformed[:15],
        }
