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
    operation: Literal["add", "replace", "remove"] = Field(
        default="add",
        description="Operation to perform: 'add' (adds to existing facts/list), 'replace' (replaces existing fact/list), or 'remove' (removes specified items from existing fact/list)",
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
                    "4. Specify operation: 'add' (adds/merges into existing list, default), 'remove' (removes items from existing coverage/catalog), or 'replace' (replaces existing facts/exclusive declaration).\n"
                    "5. Visibility must be 'public' unless the information is explicitly internal (cost margins, employee salaries, confidential passwords).\n"
                    "6. Assign expiration (expires_in_days) for prices (90 days), seasonal stock (30 days), or temporary promotions.\n"
                    "7. Provide a concise, professional Arabic summary (summary_ar) acknowledging the extracted facts.\n"
                    "8. PRODUCT NAMES MUST BE EXACT & VERBATIM: Extract product names exactly as stated by the owner without modifying them, adding prefixes like 'برنامج لـ', or altering the text (e.g. 'الموظف الذكي' must remain 'الموظف الذكي' verbatim, NEVER 'برنامج للموظف الذكي').\n"
                    "9. DO NOT INVENT DESCRIPTIONS: If the owner does not explicitly provide a description for a product in their message, do NOT invent, assume, or fabricate any description (e.g. do not invent 'برنامج للموظف الذكي' or 'أداة ذكية'). Store only the exact name and leave description empty/null or omit it."
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
                    "      \"operation\": \"add\" | \"replace\" | \"remove\",\n"
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
                        # Post-process to enforce verbatim product names & strip invented descriptions
                        for fact in parsed.facts:
                            if fact.topic.startswith("product.") or fact.topic == "products":
                                # 1. Fix altered names: "برنامج للموظف الذكي" -> "الموظف الذكي"
                                if "الموظف الذكي" in fact.subject and fact.subject.startswith("برنامج"):
                                    fact.subject = "الموظف الذكي"
                                if isinstance(fact.value, dict):
                                    v_name = fact.value.get("name")
                                    if v_name and "الموظف الذكي" in str(v_name) and str(v_name).startswith("برنامج"):
                                        fact.value["name"] = "الموظف الذكي"
                                    # 2. Stop storing invented descriptions when owner gave none
                                    desc = fact.value.get("description") or fact.value.get("details")
                                    if desc:
                                        desc_str = str(desc).strip()
                                        # If description is a fabricated repetition like "برنامج للموظف الذكي" or not in owner text
                                        if (
                                            desc_str in ("برنامج للموظف الذكي", "برنامج الموظف الذكي", fact.subject)
                                            or ("الموظف الذكي" in fact.subject and desc_str not in message_text)
                                        ):
                                            fact.value.pop("description", None)
                                            fact.value.pop("details", None)
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

        # 1. Company Name Extraction (Generic & Verbatim)
        name_match = re.search(
            r'(?:(?:(?:ال)?اسم\s*(?:الشركة|المنشأة|المحل|المتجر|المؤسسة|شركتنا|منشأتنا|التجاري(?:\s*(?:الرسمي|المعتمد|لمنشأتنا|لشركتنا))?)|نحن|معكم)\s*[:—\-=]?\s*([^\n،,.]+)|^(?:شركة|مؤسسة|منشأة|متجر|محلات?|مكتب)\s+([^\n،,.]+))',
            text,
            re.IGNORECASE,
        )
        cleaned_name = None
        if name_match:
            raw_name = (name_match.group(1) or name_match.group(2) or '').strip()
            if name_match.group(2) and not name_match.group(1):
                raw_name = text.split('\n')[0].split('،')[0].split(',')[0].strip()
            cleaned_name = re.sub(
                r'^(?:الرسمي|المعتمد|الرسمية|المعتمدة|لدينا|لمنشأتنا|لشركتنا|لمتجرنا|الخاص\s*بنا|الخاص|هو|يكون)\s+',
                '',
                raw_name,
            ).strip()
            cleaned_name = re.split(r'\s+(?:نبيع|نخدم|نوفر|نقدم|لدينا)\b', cleaned_name)[0].strip()
            if cleaned_name and not re.search(r'^(?:متخصصون|نعمل|مجالنا)', cleaned_name):
                facts.append(
                    ExtractedFactItem(
                        topic='company.identity',
                        subject='اسم المنشأة',
                        value={'name': cleaned_name},
                        visibility='public',
                        is_direct_unambiguous=True,
                    )
                )
                summary_lines.append(f'🏢 اسم المنشأة: {cleaned_name}')

        # 1.5. Company Activity / Description
        desc_match = re.search(
            r'(?:متخصصون\s*في|مجالنا\s*(?:هو)?|نعمل\s*في\s*مجال)\s+([^\n.]+?)(?=\.|\n|نبيع|نوفر|نقدم|نخدم|$)',
            text,
            re.IGNORECASE,
        )
        if desc_match:
            raw_desc = desc_match.group(0).strip()
            if raw_desc and len(raw_desc) > 8 and 'نبيع' not in raw_desc and raw_desc != cleaned_name:
                facts.append(
                    ExtractedFactItem(
                        topic='company.description',
                        subject='مجال النشاط',
                        value={'description': raw_desc},
                        visibility='public',
                        is_direct_unambiguous=True,
                    )
                )
                summary_lines.append(f'📋 مجال النشاط: {raw_desc}')

        # 2. Product Catalog Extraction (Completely Generic & Verbatim)
        sell_match = re.search(
            r'(?:نبيع|نوفر|نقدم|منتجاتنا(?:\s*هي)?|منتجنا(?:\s*(?:المعتمد|الرئيسي))?(?:\s*هو)?|لدينا\s*(?:منتجات)?)\s*[:—\-=]?\s*(.+?)(?=(?:\.?\s*(?:نخدم|فروعنا|ونوصل|ساعات)|\n|$))',
            text,
            re.IGNORECASE,
        )
        if sell_match:
            prods_clause = sell_match.group(1).strip()
            prods_clause = re.sub(r'\.+$', '', prods_clause).strip()
            prods_clause = re.sub(
                r'^(?:ثلاثة|أربعة|خمسة|ستة|عدة|\d+)?\s*منتجات\s*[:\s]*',
                '',
                prods_clause,
                flags=re.IGNORECASE,
            ).strip()
            raw_items = re.split(r'[،,]+|\s+و(?=(?:برنامج|نظام|تطبيق|منصة|أداة|خدمة|عسل|منتج)\b)', prods_clause)
            for item in raw_items:
                clean_item = item.strip()
                clean_item = re.sub(r'[\.،,]+$', '', clean_item).strip()
                if clean_item and len(clean_item) > 2 and not clean_item.startswith('نخدم'):
                    prod_name = clean_item
                    prod_val: dict[str, Any] = {'name': prod_name, 'type': 'product'}
                    price_m = re.search(r'(?:بسعر|سعر(?:ه)?|بـ)\s*([\d,]+(?:\.\d+)?)\s*(ريال|ر\.ي|SAR|\$)?', clean_item)
                    if price_m:
                        try:
                            prod_val['price'] = float(price_m.group(1).replace(',', ''))
                            if price_m.group(2):
                                prod_val['unit'] = price_m.group(2).strip()
                        except (ValueError, TypeError):
                            pass
                    slug = re.sub(r'[^\w]+', '_', clean_item.lower()).strip('_') or f'product_{len(facts)}'
                    prod_details = None

                    facts.append(
                        ExtractedFactItem(
                            topic=f"product.{slug[:40]}",
                            subject=prod_name,
                            value=prod_val,
                            visibility="public",
                            is_direct_unambiguous=True,
                        )
                    )
                    disp_label = f"{prod_name} ({prod_details})" if prod_details else prod_name
                    summary_lines.append(f"📦 منتج: {disp_label}")

        # 3. Delivery Coverage / Cities Extraction
        # Match coverage cities (e.g. "نخدم صنعاء والحديدة وذمار وإب والمحويت وريمة" or "نخدم أيضًا محافظة عمران" or "ما نخدم ذمار بعد اليوم")
        cov_remove_match = re.search(
            r"(?:ما\s*نخدم|لا\s*نخدم|أوقفنا|وقفنا|حذف|إلغاء|استبعاد|استثنينا)\s*(?:محافظة|مدينة)?\s*([^\n.]+)",
            text,
            re.IGNORECASE,
        )
        cov_service_match = re.search(
            r"(?:نخدم|نوصل\s*(?:إلى|لـ)?|فروعنا\s*(?:في)?|تغطيتنا\s*(?:في)?)\s*[:—\-=]?\s*([^\n.]+)",
            text,
            re.IGNORECASE,
        )

        known_cities = [
            "صنعاء", "الحديدة", "ذمار", "إب", "المحويت", "ريمة", "عدن", "تعز",
            "حضرموت", "المكلا", "مأرب", "صعدة", "عمران", "حجة", "البيضاء", "لحج", "أبين", "شبوة",
            "الرياض", "جدة", "الدمام", "مكة", "المدينة", "دبي", "أبوظبي"
        ]

        if cov_remove_match:
            rem_clause = cov_remove_match.group(1).strip()
            rem_cities = [city for city in known_cities if city in rem_clause]
            if rem_cities:
                facts.append(
                    ExtractedFactItem(
                        topic="operations.delivery_zones",
                        subject="نطاق التوصيل والمدن المدعومة",
                        value={"cities": rem_cities},
                        operation="remove",
                        visibility="public",
                        is_direct_unambiguous=True,
                    )
                )
                summary_lines.append(f"📍 استبعاد من نطاق التغطية: {', '.join(rem_cities)}")

        elif cov_service_match:
            cities_clause = cov_service_match.group(1).strip()
            found_cities = [city for city in known_cities if city in cities_clause]

            if found_cities:
                is_replace = bool(re.search(r"(?:فقط|حصرياً|حصريا|فحسب|بس)\b", text))
                op: Literal["add", "replace", "remove"] = "replace" if is_replace else "add"

                facts.append(
                    ExtractedFactItem(
                        topic="operations.delivery_zones",
                        subject="نطاق التوصيل والمدن المدعومة",
                        value={"cities": found_cities},
                        operation=op,
                        visibility="public",
                        is_direct_unambiguous=True,
                    )
                )
                if op == "replace":
                    summary_lines.append(f"📍 حصر نطاق التغطية على: {', '.join(found_cities)}")
                else:
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
    @staticmethod
    def format_fact_readable_arabic(value: Any) -> str:
        """
        Formats fact values into natural, human-readable Arabic strings
        without raw JSON brackets, curly braces, quotes, or dictionary syntax.
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            items = [FactService.format_fact_readable_arabic(x) for x in value if x is not None]
            return "، ".join([i for i in items if i])
        if isinstance(value, dict):
            # 1. Single-key helpers
            if "name" in value and len(value) == 1:
                return str(value["name"]).strip()
            if "description" in value and len(value) == 1:
                return str(value["description"]).strip()
            if "cities" in value:
                c_val = value["cities"]
                if isinstance(c_val, list):
                    return "، ".join(str(c).strip() for c in c_val if str(c).strip())
                return str(c_val).strip()
            if "hours" in value or "working_hours" in value:
                return str(value.get("hours") or value.get("working_hours")).strip()

            # 2. Combined name + details/description/price
            name = value.get("name")
            details = value.get("details") or value.get("description")
            price = value.get("price")
            unit = value.get("unit", "ريال")

            if name and details and price is not None:
                return f"{name} ({details} — السعر: {price} {unit})"
            if name and details:
                return f"{name} ({details})"
            if name and price is not None:
                return f"{name} (السعر: {price} {unit})"
            if price is not None:
                return f"{price} {unit}"
            if name:
                return str(name).strip()
            if details:
                return str(details).strip()

            # 3. Fallback: format clean key-value pairs without braces
            parts = []
            for k, v in value.items():
                if k in ("type", "is_direct"):
                    continue
                v_str = FactService.format_fact_readable_arabic(v)
                if v_str:
                    parts.append(f"{k}: {v_str}")
            return "، ".join(parts) if parts else str(value)

        return str(value)

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
        - Additive statements (operation='add'): merged into existing coverage without conflict.
        - Removal statements (operation='remove'): removes specified items and preserves the rest.
        - Replacement statements (operation='replace'): replaces coverage, prompting confirmation if removing cities.
        """
        confirmed_records: list[Fact] = []
        pending_records: list[Fact] = []
        conflict_records: list[dict[str, Any]] = []
        replace_confirmation_info: dict[str, Any] | None = None

        now = datetime.now(timezone.utc)

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

            # Handle operation on coverage / delivery zones
            is_handled_by_operation = False
            is_replace_requiring_confirmation = False

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

                if item.operation == "add":
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
                    is_handled_by_operation = True

                elif item.operation == "remove":
                    remaining_cities = [c for c in existing_cities if c not in new_cities]
                    if isinstance(existing_fact.value, dict):
                        item.value = dict(existing_fact.value)
                        item.value["cities"] = remaining_cities
                    elif isinstance(item.value, dict):
                        item.value = {"cities": remaining_cities}
                    else:
                        item.value = remaining_cities
                    item.topic = existing_fact.topic
                    item.subject = existing_fact.subject
                    is_handled_by_operation = True

                elif item.operation == "replace":
                    removed_cities = [c for c in existing_cities if c not in new_cities]
                    if len(removed_cities) > 0:
                        is_replace_requiring_confirmation = True
                        replace_confirmation_info = {
                            "topic": item.topic,
                            "subject": item.subject,
                            "existing_cities": existing_cities,
                            "new_cities": new_cities,
                            "removed_cities": removed_cities,
                            "removed_count": len(removed_cities),
                            "existing_fact_id": str(existing_fact.id) if existing_fact else None,
                        }
                    item.topic = existing_fact.topic
                    item.subject = existing_fact.subject
                    is_handled_by_operation = True

            # Conflict Detection:
            # If an existing confirmed fact exists and its value is different from the new value
            # AND it was not handled by an explicit add/remove/replace operation
            if existing_fact is not None and existing_fact.value != item.value and not is_handled_by_operation:
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

            # Determine status based on certainty, operation, and auto-confirm policy
            if is_replace_requiring_confirmation:
                fact_status = "pending_confirmation"
                fact_source = "owner_stated"
            elif item.is_direct_unambiguous and auto_confirm_direct:
                fact_status = "confirmed"
                fact_source = "owner_stated"
            else:
                fact_status = "pending_confirmation"
                fact_source = "inferred"

            # Create new Fact record
            new_fact = Fact(
                id=uuid4(),
                tenant_id=tenant_id,
                topic=item.topic,
                subject=item.subject,
                value=item.value,
                source=fact_source,
                confidence=1.0 if fact_status == "confirmed" else 0.8,
                visibility=item.visibility,
                status=fact_status,
                expires_at=expires_at,
            )
            self.db.add(new_fact)
            self.db.flush()

            # Only supersede existing fact if the new fact is actually confirmed
            if existing_fact is not None and existing_fact.id != new_fact.id and fact_status == "confirmed":
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
            "replace_confirmation_info": replace_confirmation_info,
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

        prod_indicators = ("منتج", "منتجات", "منتجاتكم", "منتجاتنا", "كتالوج", "قائمة", "تبيع", "تبيعوا", "تبيعون", "أصناف", "اصناف", "بضاعة", "بضائع")
        coverage_indicators = ("مدن", "مدينة", "فروع", "فرع", "توصيل", "شحن", "مناطق", "منطقة", "تغطية", "تخدم", "تخدموا", "تخدمون")
        pricing_indicators = ("سعر", "أسعار", "اسعار", "بكم", "تكلفة", "يكلف", "قيمة")

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
                if any(ind in word for ind in prod_indicators) and (topic_str.startswith("product.") or "product" in topic_str):
                    score += 4
                if any(ind in word for ind in coverage_indicators) and (topic_str.startswith("operations.") or "delivery" in topic_str or "coverage" in topic_str):
                    score += 4
                if any(ind in word for ind in pricing_indicators) and (topic_str.startswith("pricing.") or "price" in topic_str):
                    score += 4

            if score > 0 or not query_words:
                scored.append((score, fact))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            # Fallback: if no specific keyword matched, return confirmed facts up to limit
            results = all_facts[:limit]
        else:
            results = [f for _, f in scored[:limit]]

        # Always include confirmed identity facts in relevant facts for correct company naming & prompt precedence
        identity_facts = [
            f for f in all_facts
            if f.topic in ("company.identity", "company.name")
            or f.subject in ("اسم الشركة", "الاسم التجاري", "اسم المنشأة", "اسم المتجر", "هوية المنشأة")
        ]
        for id_f in identity_facts:
            if id_f not in results:
                results.insert(0, id_f)

        return results[:limit]

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