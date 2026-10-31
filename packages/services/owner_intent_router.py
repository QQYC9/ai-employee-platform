from __future__ import annotations

from enum import Enum
import hashlib
import json
import logging
import re
from typing import Any, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProvider
from packages.models.domain import Approval, Conversation, Knowledge, Message, Tool, User
from packages.services.approval_service import (
    ApprovalService,
    ApprovalTokenMismatchError,
    ApprovalExhaustedError,
    ApprovalExpiredError,
    ApprovalCancelledError,
    ApprovalPayloadMismatchError,
)
from packages.services.business_brain_service import BusinessBrainService
from packages.services.knowledge_service import KnowledgeService
from packages.tools.contract import ToolExecutionContext
from packages.tools.executor import ToolExecutionResult
from packages.tools.registry import ToolRegistry, create_default_registry

logger = logging.getLogger(__name__)


# ===========================================================================
# Pydantic Structured Intent Contracts
# ===========================================================================

class IntentCategory(str, Enum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"
    APPROVAL = "approval"
    CLARIFICATION = "clarification"
    KNOWLEDGE = "knowledge"
    GENERAL = "general"


class IntentStep(BaseModel):
    """
    Represents a single executable operation within an owner's request.
    Strictly bound to registered tools; cannot execute arbitrary Python code.
    """
    step_id: str = Field(..., description="Unique step identifier, e.g. 'step_1'")
    tool_slug: str = Field(..., description="Registered platform tool slug, e.g. 'product_add_or_update'")
    category: IntentCategory = Field(default=IntentCategory.READ)
    description: str = Field(..., description="Human-readable description in Arabic")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Validated tool arguments")
    requires_approval: bool = Field(default=False)
    approval_action: Optional[str] = None
    depends_on: Optional[str] = Field(default=None, description="step_id that must succeed before this step")

    @field_validator("tool_slug")
    @classmethod
    def validate_tool_slug(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
            raise ValueError(f"Invalid tool slug format: '{v}'")
        return clean


class OwnerIntentContract(BaseModel):
    """
    Structured, schema-validated contract representing an authenticated owner intent.
    Never trusts actor_id or tenant_id from user text; strictly uses internal context.
    """
    raw_query: str
    intent: str = Field(..., description="Primary classified intent name")
    category: IntentCategory = Field(default=IntentCategory.GENERAL)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    clarification_required: bool = False
    clarification_question: Optional[str] = None
    requires_approval: bool = False
    approval_action: Optional[str] = None
    entities: dict[str, Any] = Field(default_factory=dict)
    steps: list[IntentStep] = Field(default_factory=list)

    # Trusted internal context (injected by system, ignored from user input)
    tenant_id: UUID
    actor_id: Optional[UUID] = None


class StepExecutionResult(BaseModel):
    step_id: str
    tool_slug: str
    status: str  # "executed", "failed", "skipped", "blocked", "awaiting_approval"
    output: Any = None
    error: Optional[str] = None
    requires_approval: bool = False
    approval_id: Optional[UUID] = None


class RouterExecutionResult(BaseModel):
    success: bool
    contract: OwnerIntentContract
    step_results: list[StepExecutionResult] = Field(default_factory=list)
    reply_text: str
    has_failed_step: bool = False
    clarification_required: bool = False


# ===========================================================================
# OwnerIntentRouter Implementation
# ===========================================================================

class OwnerIntentRouter:
    """
    Structured intent classification, multi-step decomposition, and tool routing
    for business owner requests.

    Guarantees:
      1. Schema-validated intent representation (Pydantic v2).
      2. Strict binding to registered tools; rejects arbitrary Python execution.
      3. Sequential execution of multi-intent requests with dependency enforcement.
      4. Halts dependent steps upon earlier step failure without claiming false success.
      5. Enforces RBAC and human-in-the-loop approvals for sensitive/destructive operations.
      6. Strictly derives tenant_id and actor_id from authenticated system context.
      7. Built-in idempotency per mutating step.
    """

    ALLOWED_TOOL_SLUGS = {
        "product_add_or_update",
        "product_list",
        "business_summary",
        "task_query",
        "task_create",
        "customer_search",
        "customer_get",
        "customer_create_or_update",
        "conversation_search",
        "conversation_get_messages",
        "conversation_summarize",
        "conversation_summarize_all",
        "conversation_escalation_status",
        "generate_document",
        "document_generator",
        "http_request",
    }

    def __init__(
        self,
        db: Session,
        tool_registry: ToolRegistry | None = None,
        ai_provider: AIProvider | None = None,
    ):
        self.db = db
        self.tool_registry = tool_registry or create_default_registry(db)
        self.ai_provider = ai_provider
        self.approval_service = ApprovalService(db)

    # -----------------------------------------------------------------------
    # 1. Intent Parsing & Multi-Step Decomposition
    # -----------------------------------------------------------------------

    def parse_intent(
        self,
        content: str,
        *,
        tenant_id: UUID,
        actor_id: UUID | None = None,
    ) -> OwnerIntentContract:
        """
        Parses raw Arabic or English owner input into a structured OwnerIntentContract.
        Applies deterministic decomposition and ambiguity detection.
        """
        text = (content or "").strip()
        text_lower = text.lower()

        # Step 0: Check for Destructive / Sensitive Operations (Mandatory Approval Gate)
        sensitive_patterns = [
            r"حذف\s+(جميع|كل)\s+(العملاء|البيانات|المحادثات|المهام)",
            r"تصفير\s+(النظام|قاعدة البيانات|البيانات)",
            r"delete\s+all\s+(customers|data|tasks|conversations)",
            r"مسح\s+كل\s+شيء",
        ]
        if any(re.search(pat, text_lower) for pat in sensitive_patterns):
            return OwnerIntentContract(
                raw_query=text,
                intent="bulk_destructive_operation",
                category=IntentCategory.SENSITIVE,
                requires_approval=True,
                approval_action="bulk_destructive_operation",
                confidence=1.0,
                tenant_id=tenant_id,
                actor_id=actor_id,
                steps=[
                    IntentStep(
                        step_id="step_sensitive_1",
                        tool_slug="business_summary",  # Safe surrogate, actual execution blocked until approval
                        category=IntentCategory.SENSITIVE,
                        description="عملية حذف أو تصفير شاملة تتطلب موافقة المالك",
                        requires_approval=True,
                        approval_action="bulk_destructive_operation",
                    )
                ],
            )

        # Step 0.5: Check for Explicit Challenge Response (CR-05-01 Anti-Hijack)
        challenge_approve_m = re.match(
            r"^(?:نعم|أوافق|موافق|تأكيد|confirm|approve)\s+([2-79AC-HJ-KM-NP-Z]{6})[\.!\s]*$",
            text,
            re.IGNORECASE,
        )
        challenge_reject_m = re.match(
            r"^(?:لا|أرفض|مرفوض|رفض|reject|deny)\s+([2-79AC-HJ-KM-NP-Z]{6})[\.!\s]*$",
            text,
            re.IGNORECASE,
        )
        cancel_m = re.match(
            r"^(?:إلغاء|الغاء|cancel)\s+([0-9a-fA-F-]{36}|[A-Za-z0-9_-]+)[\.!\s]*$",
            text,
            re.IGNORECASE,
        )
        if challenge_approve_m:
            code = challenge_approve_m.group(1).upper()
            return OwnerIntentContract(
                raw_query=text,
                intent="challenge_response",
                category=IntentCategory.APPROVAL,
                confidence=1.0,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entities={"token": code, "action": "approve"},
            )
        if challenge_reject_m:
            code = challenge_reject_m.group(1).upper()
            return OwnerIntentContract(
                raw_query=text,
                intent="challenge_response",
                category=IntentCategory.APPROVAL,
                confidence=1.0,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entities={"token": code, "action": "reject"},
            )
        if cancel_m:
            app_id = cancel_m.group(1)
            return OwnerIntentContract(
                raw_query=text,
                intent="approval_cancel",
                category=IntentCategory.APPROVAL,
                confidence=1.0,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entities={"approval_id": app_id},
            )

        # Step 1: Check for Approval Confirmation ("أوافق على الطلب...")
        is_approval_disqualified = bool(
            re.search(
                r"(?:اطلب|طلب|تتطلب|يتطلب|يلزم|يلزمنا|تحتاج|نحتاج|بدون|دون|في\s*انتظار|بانتظار)\s*(?:ذلك\s*)?(?:الموافقة|موافقة|موافقتي|موافقتك)|(?:هل\s*توجد|ما\s*هي|عرض|قائمة)\s*(?:طلبات\s*)?الموافق",
                text_lower,
            )
        )
        uuid_matches = re.findall(r"[0-9a-fA-F-]{36}", text)
        slug_match = re.search(r"(?:تفعيل|اعتماد)\s*(?:القدرة|الأداة|المهارة)?\s*([a-zA-Z0-9_-]+)", text_lower)
        affirmative_patterns = [
            r"(?<![\u0621-\u064A])(?:نعم\s+)?(?:أوافق|موافق|تأكيد|تمت\s*الموافقة|نفذ\s*الأمر|اعتمد|اعتمدت|اعتمدت\s*التنفيذ)(?![\u0621-\u064A])",
            r"\b(approve|confirm|proceed|authorized)\b",
        ]
        has_affirmative = any(re.search(pat, text_lower) for pat in affirmative_patterns)
        is_concise_affirmation = bool(
            re.search(
                r"^\s*(?:نعم(?:\s+(?:أوافق|موافق|تأكيد|تمت\s*الموافقة|اعتمد|اعتمدت|نفذ\s*الأمر))?|أوافق|موافق|تأكيد|تمت\s*الموافقة|اعتمد|اعتمدت|نفذ\s*الأمر)(?:\s+(?:على\s+الطلب|التنفيذ))?[\.!\s]*$",
                text_lower,
            )
            or re.search(
                r"^\s*(?:yes(?:\s+(?:approve|confirm|proceed|authorized))?|approve|confirm|proceed|authorized)[\.!\s]*$",
                text_lower,
            )
        )

        # CR-05-01: Bare affirmation block when challenge approval is pending
        if is_concise_affirmation:
            pending_app = self.db.scalar(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.status == "pending",
                ).order_by(Approval.created_at.desc())
            )
            if pending_app:
                # NEVER disclose or repeat the challenge code!
                guidance_msg = (
                    "⚠️ **العملية المطلوبة حساسة وتتطلب رمز التأكيد الخاص بها.**\n"
                    f"- الطلب: [{pending_app.action}]\n"
                    f"- المعرف: [{pending_app.id}]\n\n"
                    "يرجى إدخال رمز التأكيد المرسل لك في رسالة الطلب الأصلية (مثال: 'نعم XXXXXX').\n"
                    f"في حال فقدان الرمز، أرسل: 'إلغاء {pending_app.id}' لطلب موافقة جديد برمز جديد."
                )
                return OwnerIntentContract(
                    raw_query=text,
                    intent="bare_affirmation_blocked",
                    category=IntentCategory.APPROVAL,
                    confidence=1.0,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    clarification_required=True,
                    clarification_question=guidance_msg,
                )

        is_approval = (
            not is_approval_disqualified
            and (
                bool(uuid_matches and has_affirmative)
                or bool(slug_match and has_affirmative)
                or is_concise_affirmation
            )
        )
        if is_approval:
            approval_id_str = uuid_matches[0] if uuid_matches else None
            return OwnerIntentContract(
                raw_query=text,
                intent="approval_response",
                category=IntentCategory.APPROVAL,
                confidence=1.0,
                tenant_id=tenant_id,
                actor_id=actor_id,
                entities={"approval_id": approval_id_str},
            )

        # Step 2: Check for Policy Ambiguity or Contradiction
        if ("مسموح" in text_lower or "يمكن" in text_lower) and ("ممنوع" in text_lower or "لا يمكن" in text_lower) and ("استرجاع" in text_lower or "استبدال" in text_lower):
            return OwnerIntentContract(
                raw_query=text,
                intent="clarification_needed",
                category=IntentCategory.CLARIFICATION,
                confidence=0.9,
                clarification_required=True,
                clarification_question=(
                    "⚠️ لوحظ تعارض في شروط الاسترجاع المذكورة (بين السماح والمنع).\n"
                    "يرجى توضيح السياسة الدقيقة المعتمدة لحفظها كحقيقة رسمية دون تخمين."
                ),
                tenant_id=tenant_id,
                actor_id=actor_id,
            )

        # Step 2.1: Check for Vague / Incomplete Commands
        vague_patterns = [
            r"^احذف\s*$",
            r"^عدل\s*$",
            r"^أضف\s*$",
            r"^delete\s*$",
            r"^غير\s*السعر\s*$",
            r"^احذف\s+(?:الطلب|المنتج|المهمة)\s*$",
        ]
        if any(re.match(p, text_lower) for p in vague_patterns):
            return OwnerIntentContract(
                raw_query=text,
                intent="vague_command",
                category=IntentCategory.CLARIFICATION,
                confidence=0.95,
                clarification_required=True,
                clarification_question="⚠️ الطلب غير مكتمل. يرجى تحديد التفاصيل أو الاسم المطلوب للتمكن من التنفيذ بدقة.",
                tenant_id=tenant_id,
                actor_id=actor_id,
            )

        # Step 3: Multi-intent decomposition check
        # Look for conjunctions: "ثم", "و بعد ذلك", "وبعد ذلك", "بعدين"
        multi_parts = self._split_multi_intent(text)
        if len(multi_parts) > 1:
            steps: list[IntentStep] = []
            prev_step_id: str | None = None
            for idx, part in enumerate(multi_parts):
                s_id = f"step_{idx + 1}"
                sub_step = self._classify_single_part(part, s_id, depends_on=prev_step_id)
                if sub_step:
                    steps.append(sub_step)
                    prev_step_id = s_id

            if steps:
                return OwnerIntentContract(
                    raw_query=text,
                    intent="multi_step_workflow",
                    category=IntentCategory.WRITE if any(s.category == IntentCategory.WRITE for s in steps) else IntentCategory.READ,
                    confidence=0.95,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    steps=steps,
                )

        # Step 4: Single Part Classification
        step = self._classify_single_part(text, "step_1", depends_on=None)
        if step:
            return OwnerIntentContract(
                raw_query=text,
                intent=f"single_{step.tool_slug}",
                category=step.category,
                confidence=1.0,
                tenant_id=tenant_id,
                actor_id=actor_id,
                steps=[step],
            )

        # Step 5: Check for Business Knowledge Teaching (Identity, Policy, Services, Operations)
        learning = self._extract_business_knowledge(text)
        if learning:
            return OwnerIntentContract(
                raw_query=text,
                intent="business_learning",
                category=IntentCategory.KNOWLEDGE,
                confidence=0.95,
                clarification_required=learning.get("needs_clarification", False),
                clarification_question=learning.get("clarification_question"),
                entities=learning,
                tenant_id=tenant_id,
                actor_id=actor_id,
            )

        # Step 6: General owner chat / guidance
        return OwnerIntentContract(
            raw_query=text,
            intent="general_owner_chat",
            category=IntentCategory.GENERAL,
            confidence=0.8,
            tenant_id=tenant_id,
            actor_id=actor_id,
        )

    def _split_multi_intent(self, text: str) -> list[str]:
        """Splits multi-intent Arabic sentences using sequential connectors."""
        delimiters = [
            r"\s*،?\s*ثم\s+",
            r"\s*،?\s*وبعد\s*ذلك\s+",
            r"\s*،?\s*بعد\s*ذلك\s+",
            r"\s*،?\s*بعدين\s+",
            r"\s*،\s*و?(?=(?:اعرض|أعرض|استعرض|جهز|جهّز|صمم|أنشئ|أضف|سجل|لخص|احذف))",
        ]
        pattern = "|".join(delimiters)
        parts = re.split(pattern, text, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    def _classify_single_part(
        self,
        part: str,
        step_id: str,
        depends_on: str | None = None,
    ) -> IntentStep | None:
        """Classifies a single intent part into a registered tool step."""
        part_lower = part.lower().strip()

        # 1. Product Addition / Update
        from packages.tools.business_tools import parse_arabic_products
        extracted_products = parse_arabic_products(part)
        is_add_product = bool(
            re.search(r"أضف|سجل|تحديث|أدخل|جديد|منتج|بسعر|سعره", part_lower)
        ) and bool(extracted_products)

        if is_add_product:
            return IntentStep(
                step_id=step_id,
                tool_slug="product_add_or_update",
                category=IntentCategory.WRITE,
                description="إضافة وتحديث المنتجات في الكتالوج المعتمد",
                parameters={"raw_text": part},
                depends_on=depends_on,
            )

        # 2. Product List / Catalog Query
        is_product_list = bool(
            re.search(
                r"(?:قائمة|عرض|ماهي|ما\s*هي|ايش|إيش|وش|شو|كم|اعطني|أعطني|استعرض)\s*(?:كل\s*)?(?:المنتجات|منتجاتنا|منتجاتكم|الأسعار|أسعاركم|المنيو|كتالوج|اللي\s*عندكم|المتوفرة)|(?:منتجات|أسعار)\s*(?:المتجر|المنشأة)|ما\s*هي\s*قائمة\s*منتجات|(?:وش|ايش|إيش|شو|ماذا)\s*(?:تبيعوا|تبيعون|تقدموا|تقدمون|عندكم)|عدد\s*المنتجات",
                part_lower,
            )
        ) and not bool(re.search(r"أضف|سجل|تحديث|بسعر|سعره|نبيع|نوفر|نقدم|نخدم|اسم\s*شركتنا", part_lower))
        if is_product_list:
            return IntentStep(
                step_id=step_id,
                tool_slug="product_list",
                category=IntentCategory.READ,
                description="استعراض قائمة وعدد المنتجات المعتمدة",
                parameters={},
                depends_on=depends_on,
            )

        # 3. Document / Ad Draft Generation
        is_doc_or_ad = bool(
            re.search(
                r"(?:جهّز|جهز|صمم|اكتب|مسودة|صيغة)\s*(?:إعلان|اعلان|تسويق|بوست|منشور|وثيقة|تقرير)",
                part_lower,
            )
        )
        if is_doc_or_ad:
            return IntentStep(
                step_id=step_id,
                tool_slug="generate_document",
                category=IntentCategory.WRITE,
                description="تجهيز مسودة إعلان تسويقية للمنتجات والخدمات",
                parameters={
                    "title": "مسودة تسويقية وإعلانية",
                    "document_type": "marketing_draft",
                    "content": part,
                },
                depends_on=depends_on,
            )

        # 4. Business Summary
        is_biz_summary = bool(
            re.search(
                r"(?:ملخص|تقرير|احصائيات)\s*(?:النشاط|الأعمال|المبيعات|المنشأة|المتجر|العمليات)|(?:نشاط|أعمال)\s*اليوم|business\s*summary",
                part_lower,
            )
        ) and not re.search(r"محادث|زبائن|عملاء", part_lower)
        if is_biz_summary:
            return IntentStep(
                step_id=step_id,
                tool_slug="business_summary",
                category=IntentCategory.READ,
                description="استخراج تقرير وملخص نشاط المنشأة اليوم",
                parameters={},
                depends_on=depends_on,
            )

        # 5. Task Query
        if re.search(r"حالة\s*المهام|ما\s*هي\s*المهام|استفسر\s*عن\s*المهام|قائمة\s*المهام|list\s*tasks", part_lower):
            return IntentStep(
                step_id=step_id,
                tool_slug="task_query",
                category=IntentCategory.READ,
                description="الاستعلام عن المهام قيد التنفيذ في النظام",
                parameters={"limit": 5},
                depends_on=depends_on,
            )

        # 6. Task Creation
        is_task_query = bool(re.search(r"حالة\s*المهام|ما\s*هي\s*المهام|استفسر\s*عن\s*المهام|قائمة\s*المهام|list\s*tasks|عرض\s*المهام", part_lower))
        is_adjective_task = bool(re.search(r"(?:هذه|تلك|المسألة|النقطة)\s*مهمة\s*(?:جداً|جدا)?", part_lower))

        if not is_task_query and not is_adjective_task:
            create_prefix = re.search(
                r"(?:(?:أريد|اريد|يرجى|قم\s*بـ?|اعمل|حابب|ودّي|ودي)\s+)?"
                r"(?:إنشاء|انشاء|أنشئ|انشئ|سجل|أضف|اضف|عمل)"
                r"(?:\s+لي)?"
                r"\s+مهمة"
                r"(?:\s+(?:اختبار(?:ية)?|جديدة|إدارية|تشغيلية))?"
                r"[\s:]*",
                part,
                re.IGNORECASE,
            )
            if create_prefix and not (re.search(r"منتج|سعر|سياسة", part_lower) and not re.search(r"مهمة", part_lower)):
                remainder = part[create_prefix.end():].strip()
                if remainder:
                    quoted_matches = re.findall(r"[«\"'“]([^»\"'”]+)[»\"'”]", remainder)
                    title = ""
                    description = ""
                    priority = "normal"

                    # 1. Title extraction
                    title_match = re.search(
                        r"(?:بعنوان|باسم|عنوانها|اسمها)\s*[:\s]?\s*([«\"'“][^»\"'”]+[»\"'”]|[^،,\n]+(?:\.[0-9a-zA-Z_-]+)*)",
                        remainder,
                    )
                    if title_match:
                        raw_title = title_match.group(1).strip()
                        title = re.sub(r"^[«\"'“]|[\"'»”]$", "", raw_title).strip()
                        title = re.sub(r"\s+(?:و?وصفها|و?بحالة|و?حالتها|و?نفذ|و?اجعل|و?بأولوية|و?أولوية).*$", "", title).strip()
                        title = re.sub(r"\.(?:\s+.*|$)", "", title).strip()
                    elif quoted_matches:
                        title = quoted_matches[0].strip()
                    else:
                        parts = re.split(r"[،,\n]|(?:\s+(?:و?وصفها|و?بحالة|و?حالتها|و?نفذ|و?اجعل)\s+)", remainder)
                        title = parts[0].strip() if parts else remainder[:50].strip()

                    # 2. Description extraction
                    desc_match = re.search(
                        r"(?:و?وصفها|و?تفاصيلها|و?الهدف\s*منها|و?المطلوب)\s*[:\s]?\s*([«\"'“][^»\"'”]+[»\"'”]|[^،,\n]+)",
                        remainder,
                    )
                    if desc_match:
                        raw_desc = desc_match.group(1).strip()
                        description = re.sub(r"^[«\"'“]|[\"'»”]$", "", raw_desc).strip()
                        description = re.sub(r"\s+(?:و?بحالة|و?حالتها|و?نفذ|و?اجعل|و?بأولوية|و?أولوية).*$", "", description).strip()
                        description = re.sub(r"\.(?:\s+.*|$)", "", description).strip()
                    elif len(quoted_matches) >= 2:
                        description = quoted_matches[1].strip()

                    # 3. Priority extraction
                    if re.search(r"عاجل|طارئ|urgent", part_lower):
                        priority = "urgent"
                    elif re.search(r"عالية|مرتفعة|high", part_lower):
                        priority = "high"
                    elif re.search(r"منخفضة|low", part_lower):
                        priority = "low"

                    if not title:
                        title = remainder[:50].strip()

                    return IntentStep(
                        step_id=step_id,
                        tool_slug="task_create",
                        category=IntentCategory.WRITE,
                        description=f"إنشاء مهمة جديدة: {title}",
                        parameters={
                            "title": title,
                            "objective": description or f"مهمة من المالك: {part}",
                            "description": description or f"مهمة من المالك: {part}",
                            "priority": priority,
                        },
                        depends_on=depends_on,
                    )

        # 7. Conversation Summaries
        if re.search(r"(?:لخص|ملخص|تقرير).*(?:كل|جميع)\s*(?:الزبائن|العملاء|المحادثات)", part_lower):
            return IntentStep(
                step_id=step_id,
                tool_slug="conversation_summarize_all",
                category=IntentCategory.READ,
                description="تلخيص شامل لجميع محادثات الزبائن",
                parameters={},
                depends_on=depends_on,
            )
        elif re.search(r"(?:لخص|ملخص|تقرير|استعرض)\s*(?:لي\s*)?(?:محادث|شات|رسائل)|محادثة\s*العميل", part_lower):
            return IntentStep(
                step_id=step_id,
                tool_slug="conversation_summarize",
                category=IntentCategory.READ,
                description="تلخيص محادثة عميل محددة",
                parameters={"query": part},
                depends_on=depends_on,
            )

        # 8. Escalation Status
        if re.search(r"حالات\s*التصعيد|طلبات\s*الموظف\s*البشري|المحادثات\s*المصعدة", part_lower):
            return IntentStep(
                step_id=step_id,
                tool_slug="conversation_escalation_status",
                category=IntentCategory.READ,
                description="فحص حالات التصعيد المعلقة بانتظار تدخل بشري",
                parameters={},
                depends_on=depends_on,
            )

        # 9. Customer Search
        cust_match = re.search(r"(?:ابحث\s*عن\s*عميل|معلومات\s*العميل|بيانات\s*العميل|بحث\s*عن)\s*[:\s]?\s*(.+)", part, re.IGNORECASE)
        if cust_match and not re.search(r"منتج|سعر|مهمة", part_lower):
            query = cust_match.group(1).strip()
            return IntentStep(
                step_id=step_id,
                tool_slug="customer_search",
                category=IntentCategory.READ,
                description=f"البحث عن عميل: {query}",
                parameters={"query": query},
                depends_on=depends_on,
            )

        return None

    def _extract_business_knowledge(self, content: str) -> dict[str, Any] | None:
        """Extracts identity, store name, or business policies taught conversationally."""
        text = (content or "").strip()
        text_lower = text.lower()

        # Business Identity / Name
        name_match = re.search(
            r"(?:اسم\s*(?:المتجر|متجرنا|المنشأة|منشأتنا|الشركة|شركتنا|المحل|محلنا)|الاسم\s*التجاري)\s*(?:هو|يكون|=|\s*:)?\s*([^،,.\n]+)",
            text,
            re.IGNORECASE,
        )
        if name_match and not re.search(r"ما\s*هو|كم|أخبرني|ايش|إيش", text_lower):
            raw_name = name_match.group(1).strip()
            cleaned = re.sub(r"^[:—\-=]+\s*", "", raw_name).strip()
            filler_pattern = r"^(?:الرسمي|المعتمد|الرسمية|المعتمدة|لدينا|لمنشأتنا|لشركتنا|لمتجرنا|الخاص\s*بنا|الخاص|هو|يكون)\s+"
            while True:
                subbed = re.sub(filler_pattern, "", cleaned, flags=re.IGNORECASE).strip()
                if subbed == cleaned:
                    break
                cleaned = subbed
            name = re.sub(r"^[:—\-=]+\s*", "", cleaned).strip()
            if name:
                return {
                    "category": "identity",
                    "category_label": "هوية المنشأة والاسم التجاري",
                    "title": f"اسم المنشأة: {name}",
                    "details": f"اسم المنشأة التجاري المعتمد: {name}",
                    "data": {"name": name, "legal_name": name},
                }

        # Policy
        policy_match = re.search(
            r"(?:سياسة|شروط|نظام)\s*(?:الاسترجاع|الاستبدال|التوصيل|العمل|الدفع)\s*(?:هي|هو|يكون|=|\s*:)?\s*([^،,.\n]+)",
            text,
            re.IGNORECASE,
        )
        if policy_match and not re.search(r"ما\s*هي|ايش|إيش", text_lower):
            pol_desc = policy_match.group(0).strip()
            return {
                "category": "policies",
                "category_label": "السياسات المعتمدة",
                "title": f"سياسة: {pol_desc[:50]}",
                "details": pol_desc,
                "data": {"policy": pol_desc},
            }

        return None

    # -----------------------------------------------------------------------
    # 2. Execution Engine with Sequential Dependency & Idempotency
    # -----------------------------------------------------------------------

    def execute_plan(
        self,
        contract: OwnerIntentContract,
        *,
        conversation_id: UUID,
        message_id: UUID,
        engine: Any,
    ) -> RouterExecutionResult:
        """
        Executes an OwnerIntentContract step-by-step:
          - Validates tools against ToolRegistry (rejects unregistered tools).
          - Enforces step dependencies: halts if a prerequisite step fails.
          - Injects deterministic idempotency keys for write operations.
          - Aggregates results into a professional Arabic response.
          - NEVER claims success for a failed or unexecuted step.
        """
        if contract.clarification_required:
            return RouterExecutionResult(
                success=True,
                contract=contract,
                clarification_required=True,
                reply_text=contract.clarification_question or "⚠️ يرجى توضيح طلبكم بتفاصيل أكثر.",
            )

        if contract.requires_approval:
            # Sensitive operation: create formal Challenge Approval record under CR-05-01
            payload = {"raw_query": contract.raw_query, "action": contract.approval_action}
            if contract.steps:
                payload["steps"] = [s.model_dump() for s in contract.steps]
            app, raw_code = self.approval_service.create_approval_challenge(
                tenant_id=contract.tenant_id,
                requested_for="tenant_owner",
                action=contract.approval_action or "sensitive_operation",
                description=contract.raw_query,
                parameters=payload,
            )
            reply = (
                f"⚠️ **طلب موافقة رسمي لإجراء إداري حساس:**\n"
                f"- العملية: {contract.approval_action}\n"
                f"- التفاصيل: \"{contract.raw_query}\"\n"
                f"- المعرف: [{app.id}]\n"
                f"- رمز التأكيد الخاص بك: [{raw_code}]\n"
                f"- الصلاحية: 15 دقيقة (3 محاولات كحد أقصى)\n\n"
                f"لحماية بيانات منشأتكم، لم يتم تنفيذ أي إجراء حتى الآن.\n"
                f"للموافقة (أوافق على الطلب) والتأكيد النهائي، يرجى الرد بـ: 'نعم {raw_code}'\n"
                f"للإلغاء، أرسل: 'إلغاء {app.id}'."
            )
            return RouterExecutionResult(
                success=True,
                contract=contract,
                reply_text=reply,
            )

        if contract.intent == "challenge_response":
            token = contract.entities.get("token", "")
            action_type = contract.entities.get("action", "approve")
            pendings = self.approval_service.list_approvals(contract.tenant_id, status="pending")

            matched = None
            for p in pendings:
                if p.token and ApprovalService.verify_token(token, p.token, contract.tenant_id):
                    matched = p
                    break

            if matched:
                if action_type == "approve":
                    try:
                        app = self.approval_service.verify_and_approve_challenge(
                            tenant_id=contract.tenant_id,
                            approval_id=matched.id,
                            submitted_token=token,
                            decision_by_user_id=contract.actor_id or uuid4(),
                            runtime_parameters=matched.parameters_json,
                        )
                        return RouterExecutionResult(
                            success=True,
                            contract=contract,
                            reply_text=f"✅ **تم التحقق من رمز التأكيد بنجاح للموافقة [{app.action}]:**\nتمت الموافقة الرسمية وجارٍ تنفيذ العملية فوراً عبر نظام Outbox.",
                        )
                    except Exception as exc:
                        return RouterExecutionResult(
                            success=False,
                            contract=contract,
                            reply_text=f"⛔ **تعذر اعتماد الموافقة:** {str(exc)}",
                        )
                else:
                    self.approval_service.reject(
                        tenant_id=contract.tenant_id,
                        approval_id=matched.id,
                        decision_by_user_id=contract.actor_id or uuid4(),
                        reason="Rejected via challenge command",
                    )
                    return RouterExecutionResult(
                        success=True,
                        contract=contract,
                        reply_text="⛔ **تم رفض طلب الموافقة وإلغاء تنفيذ العملية بنجاح.**",
                    )
            else:
                # Token did not match active pending approval
                if pendings:
                    target = pendings[0]
                    try:
                        self.approval_service.verify_and_approve_challenge(
                            tenant_id=contract.tenant_id,
                            approval_id=target.id,
                            submitted_token=token,
                            decision_by_user_id=contract.actor_id or uuid4(),
                        )
                    except ApprovalTokenMismatchError as err:
                        return RouterExecutionResult(
                            success=False,
                            contract=contract,
                            reply_text=f"❌ **رمز التأكيد غير صحيح:** {str(err)}",
                        )
                    except ApprovalExhaustedError as err:
                        return RouterExecutionResult(
                            success=False,
                            contract=contract,
                            reply_text=f"⛔ **تم استنفاد المحاولات:** {str(err)}",
                        )
                    except Exception as err:
                        return RouterExecutionResult(
                            success=False,
                            contract=contract,
                            reply_text=f"❌ **خطأ في التحقق من الرمز:** {str(err)}",
                        )
                return RouterExecutionResult(
                    success=False,
                    contract=contract,
                    reply_text="⚠️ **رمز التأكيد غير مطابق لأي طلب موافقة معلق نشط.**",
                )

        if contract.intent == "approval_cancel":
            app_id_ref = contract.entities.get("approval_id")
            pendings = self.approval_service.list_approvals(contract.tenant_id, status="pending")
            target = None
            for p in pendings:
                if str(p.id) == app_id_ref or str(p.id).startswith(str(app_id_ref)):
                    target = p
                    break
            if target:
                self.approval_service.cancel(contract.tenant_id, target.id, user_id=contract.actor_id)
                return RouterExecutionResult(
                    success=True,
                    contract=contract,
                    reply_text=f"ℹ️ **تم إلغاء طلب الموافقة [{target.action}] بنجاح.**\nيمكنك إعادة طلب الإجراء من جديد لتوليد رمز تأكيد جديد.",
                )
            else:
                return RouterExecutionResult(
                    success=False,
                    contract=contract,
                    reply_text="⚠️ لم يتم العثور على طلب موافقة معلق مطابق للإلغاء.",
                )

        if not contract.steps:
            return RouterExecutionResult(
                success=True,
                contract=contract,
                reply_text="أهلاً بك يا صاحب العمل! كيف يمكنني مساعدتك في إدارة المتجر أو مراجعة المنتجات والمهام اليوم؟",
            )

        step_results: list[StepExecutionResult] = []
        failed_step_ids: set[str] = set()
        step_outputs: dict[str, Any] = {}
        has_failed = False
        reply_sections: list[str] = []

        for step in contract.steps:
            # Check dependency failure
            if step.depends_on and step.depends_on in failed_step_ids:
                failed_step_ids.add(step.step_id)
                step_res = StepExecutionResult(
                    step_id=step.step_id,
                    tool_slug=step.tool_slug,
                    status="skipped",
                    error=f"تم إيقاف هذه الخطوة لأن الخطوة المعتمد عليها [{step.depends_on}] لم تكتمل بنجاح.",
                )
                step_results.append(step_res)
                reply_sections.append(f"⚠️ **الخطوة [{step.description}]:** تم تخطيها لعدم اكتمال الخطوة السابقة.")
                continue

            # Verify tool is registered
            if step.tool_slug not in self.ALLOWED_TOOL_SLUGS and self.tool_registry.get(step.tool_slug) is None:
                has_failed = True
                failed_step_ids.add(step.step_id)
                err_msg = f"الأداة المطلوبة [{step.tool_slug}] غير مسجلة في نظام المنصة ومحظور تنفيذها."
                step_res = StepExecutionResult(
                    step_id=step.step_id,
                    tool_slug=step.tool_slug,
                    status="failed",
                    error=err_msg,
                )
                step_results.append(step_res)
                reply_sections.append(f"❌ **الخطوة [{step.description}]:** {err_msg}")
                continue

            # Prepare parameters and enrich with previous step output if available
            params = dict(step.parameters or {})
            if step.tool_slug in ("generate_document", "document_generator") and "step_1" in step_outputs:
                p1_out = step_outputs["step_1"]
                if isinstance(p1_out, dict) and "saved_products" in p1_out:
                    prods = p1_out["saved_products"]
                    names_str = "، ".join([f"{p['name']} ({p['price']} {p.get('unit', 'ريال')})" for p in prods])
                    params["content"] = f"مسودة إعلان للمنتجات التالية: {names_str}. " + str(params.get("content", ""))

            # Generate Idempotency Key for write operations
            step_idem_key = None
            if step.category == IntentCategory.WRITE:
                step_idem_key = f"owner:step:{contract.tenant_id}:{message_id}:{step.step_id}"

            # Execute via engine.execute_tool_action
            # Authority for permissions, policies, and approvals is strictly delegated
            # to DecisionEngine, PermissionService, and ActionPolicyService.
            # No automatic permanent "allow" permissions are created by the router.
            effective_actor = contract.actor_id
            if effective_actor is None:
                owner_user = self.db.scalar(
                    select(User).where(
                        User.tenant_id == contract.tenant_id,
                        User.role == "tenant_owner",
                    )
                )
                if owner_user:
                    effective_actor = owner_user.id

            try:
                t_res: ToolExecutionResult = engine.execute_tool_action(
                    tenant_id=contract.tenant_id,
                    tool_slug=step.tool_slug,
                    parameters=params,
                    conversation_id=conversation_id,
                    agent_id=None,
                    idempotency_key=step_idem_key,
                    actor_id=effective_actor,
                    is_owner=True,
                )

                if t_res.status == "executed":
                    step_outputs[step.step_id] = t_res.output
                    step_res = StepExecutionResult(
                        step_id=step.step_id,
                        tool_slug=step.tool_slug,
                        status="executed",
                        output=t_res.output,
                    )
                    step_results.append(step_res)
                    formatted_line = self._format_step_output(step, t_res.output)
                    reply_sections.append(formatted_line)
                elif t_res.status == "blocked":
                    has_failed = True
                    failed_step_ids.add(step.step_id)
                    step_res = StepExecutionResult(
                        step_id=step.step_id,
                        tool_slug=step.tool_slug,
                        status="blocked",
                        error=t_res.reason or "غير مصرح بتنفيذ هذه العملية",
                    )
                    step_results.append(step_res)
                    reply_sections.append(f"⛔ **الخطوة [{step.description}]:** تم حظر التنفيذ: {t_res.reason}")
                else:
                    has_failed = True
                    failed_step_ids.add(step.step_id)
                    step_res = StepExecutionResult(
                        step_id=step.step_id,
                        tool_slug=step.tool_slug,
                        status="failed",
                        error=t_res.reason or "فشل في تنفيذ الأداة",
                    )
                    step_results.append(step_res)
                    reply_sections.append(f"❌ **الخطوة [{step.description}]:** فشل التنفيذ: {t_res.reason or 'خطأ غير متوقع'}")

            except Exception as exc:
                has_failed = True
                failed_step_ids.add(step.step_id)
                step_res = StepExecutionResult(
                    step_id=step.step_id,
                    tool_slug=step.tool_slug,
                    status="failed",
                    error=str(exc),
                )
                step_results.append(step_res)
                reply_sections.append(f"❌ **الخطوة [{step.description}]:** تعذر التنفيذ: {str(exc)}")

        final_reply = "\n\n".join(reply_sections)
        if len(contract.steps) > 1:
            header = "🎯 **نتائج تنفيذ طلباتك المتعددة:**\n" if not has_failed else "⚠️ **تمت معالجة الطلب مع وجود تنبيهات:**\n"
            final_reply = header + final_reply

        return RouterExecutionResult(
            success=not has_failed,
            contract=contract,
            step_results=step_results,
            reply_text=final_reply,
            has_failed_step=has_failed,
        )

    def _format_step_output(self, step: IntentStep, output: Any) -> str:
        """Formats the output of a single tool execution into user-friendly Arabic text."""
        slug = step.tool_slug
        if slug == "product_add_or_update":
            saved = output.get("saved_products", []) if isinstance(output, dict) else []
            lines = [f"{i+1}. {p['name']} — {p['price']:g} {p.get('unit', 'ريال')}" for i, p in enumerate(saved)]
            return (
                f"✅ **تم حفظ وتحديث معلومات النشاط التجاري بنجاح:**\n"
                f"📦 تم حفظ {len(saved)} منتج بنجاح في قاعدة البيانات الرسمية:\n"
                + "\n".join(lines)
            )

        if slug == "product_list":
            data = output if isinstance(output, dict) else {}
            cat = data.get("catalog_text") or "لا توجد منتجات مسجلة."
            return f"📋 **كتالوج المنتجات الحالي:**\n{cat}"

        if slug in ("generate_document", "document_generator"):
            doc_id = (output or {}).get("document_id", "") if isinstance(output, dict) else ""
            return f"📝 **تم تجهيز مسودة الإعلان بنجاح** [رقم الوثيقة: {doc_id}]."

        if slug == "business_summary":
            raw_data = output if isinstance(output, dict) else {}
            m = raw_data.get("metrics") or raw_data
            tot_tasks = m.get("total_tasks", m.get("pending_tasks", 0) + m.get("completed_tasks", 0))
            return (
                f"📊 **ملخص نشاط المنشأة اليوم:**\n"
                f"- إجمالي العملاء: {m.get('total_customers', 0)}\n"
                f"- المحادثات النشطة: {m.get('active_conversations', 0)}\n"
                f"- إجمالي المهام: {tot_tasks} (المكتملة: {m.get('completed_tasks', 0)})\n"
                f"- طلبات الموافقة المعلقة: {m.get('pending_approvals', 0)}"
            )

        if slug == "task_query":
            tasks = (output or {}).get("tasks", []) if isinstance(output, dict) else []
            if tasks:
                t_lines = [f"- [{t.get('status', 'active')}] {t.get('title')}" for t in tasks[:5]]
                return "📋 **قائمة المهام في النظام:**\n" + "\n".join(t_lines)
            return "📋 لا توجد مهام قيد التنفيذ حالياً."

        if slug == "task_create":
            tid = (output or {}).get("task_id", "") if isinstance(output, dict) else ""
            t_title = (output or {}).get("title", "") if isinstance(output, dict) else ""
            t_status = (output or {}).get("status", "pending") if isinstance(output, dict) else "pending"
            msg = "✅ **تم إنشاء المهمة بنجاح**"
            if t_title:
                msg += f" بعنوان: «{t_title}»"
            if tid:
                msg += f" برقم [{tid}]"
            if t_status:
                msg += f" (الحالة: {t_status})"
            return msg + "."

        if slug == "conversation_summarize_all":
            summary = (output or {}).get("summary", "لم يتم العثور على محادثات.") if isinstance(output, dict) else str(output)
            return f"📋 **ملخص محادثات العملاء:**\n{summary}"

        if slug == "conversation_summarize":
            summary = (output or {}).get("summary", "لم يتم العثور على محادثات مطابقة.") if isinstance(output, dict) else str(output)
            return f"📋 **ملخص المحادثة:**\n{summary}"

        if slug == "conversation_escalation_status":
            data = output if isinstance(output, dict) else {}
            tot = data.get("total_pending_escalations", 0)
            if tot > 0:
                lines = [f"- العميل: {e.get('customer_name')} | السبب: {e.get('reason')}" for e in data.get("escalations", [])]
                return f"🚨 **يوجد {tot} محادثة بانتظار تدخل بشري:**\n" + "\n".join(lines)
            return "✅ لا توجد محادثات عملاء معلقة بانتظار تدخل بشري حالياً."

        if slug == "customer_search":
            results = (output or {}).get("customers", []) if isinstance(output, dict) else []
            if results:
                c = results[0]
                return f"👤 **بيانات العميل:**\n- الاسم: {c.get('name')}\n- الهاتف: {c.get('phone') or 'غير متوفر'}\n- البريد: {c.get('email') or 'غير متوفر'}"
            return "لم يتم العثور على أي عميل مطابق للبحث."

        return f"تم تنفيذ الخطوة [{step.description}] بنجاح."
