"""
Phase 3: Adaptive Owner Onboarding Interview Service.

Enables the autonomous Digital Employee to conduct an adaptive onboarding
interview with the business owner, dynamically deciding what it needs to know
based on the owner's free-text answers.

No hardcoded schemas per business domain: a honey shop, software company,
electronics store, or restaurant produces an entirely distinct topic plan.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from packages.ai_providers.base import AIProvider
from packages.models.domain import Fact, InterviewState, InterviewTopic, Message
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService
from packages.services.fact_service import ExtractedFactItem, FactService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured Model Interaction
# ---------------------------------------------------------------------------

class TopicPlanItem(BaseModel):
    slug: str = Field(description="Normalized lowercase slug, e.g. 'identity', 'honey_types', 'delivery_zones'")
    label: str = Field(description="Human-readable Arabic label, e.g. 'أنواع العسل المتوفرة'")
    why_it_matters: str | None = Field(default=None, description="Why this topic matters to customers")
    criticality: int = Field(default=3, ge=1, le=5, description="Criticality rating from 1 to 5")
    question: str = Field(description="Direct, polite Arabic question to ask the owner")
    depends_on: list[str] = Field(default_factory=list, description="List of topic slugs this topic depends on")
    group_name: str = Field(default="universal", description="'universal', 'field_specific', or 'follow_up'")


class InterviewPlanSchema(BaseModel):
    business_tags: list[str] = Field(default_factory=list, description="Multi-label tags describing the business")
    topics: list[TopicPlanItem] = Field(default_factory=list, description="List of planned interview topics")


class ClassificationParseResult(BaseModel):
    owner_name: str | None = None
    owner_role: str | None = None
    entity_type: str | None = None
    country: str | None = None
    field_of_activity: str | None = None
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Default Classification Questions (Stage 1: Exactly 4 Questions)
# ---------------------------------------------------------------------------

CLASSIFICATION_QUESTIONS = {
    "classification_1": (
        "مرحباً بك يا صاحب المنشأة! بصفتي موظفك الرقمي الذكي، سأقوم بالتعرف على نشاطك لخدمة عملائك بدقة.\n\n"
        "دعنا نبدأ بأربعة أسئلة سريعة:\n"
        "1️⃣ ما هو اسمك الكريم؟ (الاسم الذي تحب أن أناديك به)"
    ),
    "classification_2": (
        "أهلاً بك يا {owner_name}! 🤝\n"
        "2️⃣ ما هو دورك أو صفتك في المنشأة؟ (مثلاً: المالك، المؤسس، المدير العام، مسؤول العمليات...)"
    ),
    "classification_3": (
        "3️⃣ ما هو تصنيف وطبيعة منشأتكم؟\n"
        "(مثلاً: شركة، متجر فعلي/محل، متجر إلكتروني، مزود خدمات، أو غير ذلك)"
    ),
    "classification_4": (
        "4️⃣ في أي دولة تعمل منشأتكم، وما هو مجال النشاط الأساسي؟\n"
        "(مثلاً: اليمن - تجارة العسل الطبيعي، أو السعودية - برمجيات وحلول رقمية)"
    ),
}


class InterviewService:
    """
    Manages the adaptive onboarding interview lifecycle:
    Stage 1: 4 classification questions -> multi-label profile facts.
    Stage 2: Dynamic topic planning based on profile tags.
    Stage 3: Conditional follow-up proposal.
    Deterministic next-question selector, multi-topic answer matching,
    pause/resume, and go-live gate enforcement.
    """

    def __init__(self, db: Session):
        self.db = db
        self.audit_service = AuditService(db)
        self.fact_service = FactService(db)

    # -----------------------------------------------------------------------
    # State Management & Helpers
    # -----------------------------------------------------------------------

    def get_or_create_state(self, tenant_id: UUID) -> InterviewState:
        """Retrieves existing interview state or creates a fresh one for the tenant."""
        state = self.db.scalar(
            select(InterviewState).where(InterviewState.tenant_id == tenant_id)
        )
        if state is None:
            state = InterviewState(
                tenant_id=tenant_id,
                stage="classification_1",
                classification_answers={},
                is_active=True,
                last_interaction_at=datetime.now(timezone.utc),
            )
            self.db.add(state)
            self.db.flush()
        return state

    def is_interview_active(self, tenant_id: UUID) -> bool:
        """Returns True if the tenant has an active, incomplete interview."""
        state = self.db.scalar(
            select(InterviewState).where(InterviewState.tenant_id == tenant_id)
        )
        if state is None:
            return False
        return bool(state.is_active and state.stage != "completed")

    def start_interview(self, tenant_id: UUID) -> str:
        """Starts a fresh interview for the tenant from Stage 1 Question 1."""
        state = self.get_or_create_state(tenant_id)
        state.stage = "classification_1"
        state.is_active = True
        state.last_interaction_at = datetime.now(timezone.utc)
        self.db.add(state)
        self.db.flush()
        return CLASSIFICATION_QUESTIONS["classification_1"]

    # -----------------------------------------------------------------------
    # Entry Point Triggers Detection
    # -----------------------------------------------------------------------

    @staticmethod
    def detect_trigger(content: str) -> str | None:
        """
        Detects explicit interview conversational triggers:
        - 'start': 'ابدأ التعارف', 'ابدأ تعارف', 'تعارف'
        - 'resume': 'كمّل التعارف', 'كمل التعارف', 'متابعة التعارف', 'استئناف'
        - 'progress': 'وش باقي؟', 'ايش باقي؟', 'كم باقي؟', 'ماذا تبقى؟'
        """
        c = (content or "").strip().lower()
        if re.search(r"(?:وش|ايش|إيش|كم|ماذا)\s*(?:باقي|متبقي|تبقى|فاضل)", c):
            return "progress"
        if re.search(r"(?:ابدأ|ابدا|بدء|أبدأ)\s*(?:التعارف|تعارف)|^\s*تعارف\s*$", c):
            return "start"
        if re.search(r"(?:كمّل|كمل|تابع|متابعة|استئناف|واصل)\s*(?:التعارف|تعارف)", c):
            return "resume"
        return None

    @staticmethod
    def is_skip_or_na(content: str) -> str | None:
        """
        Checks if owner reply indicates skipping or not applicable:
        - 'not_applicable': 'لا ينطبق', 'غير منطبق', 'ما ينطبق', 'لا يوجد لدينا'
        - 'skip': 'تخطى', 'تخطي', 'لا أعلم', 'لا اعلم', 'ما أعرف', 'بعدين', 'لاحقاً', 'skip'
        """
        c = (content or "").strip().lower()
        if re.search(r"(?:لا\s*ينطبق|غير\s*منطبق|ما\s*ينطبق|لا\s*ينطبق\s*علينا|ما\s*عندنا\s*هذا|لا\s*ينطبق\s*على\s*نشاطنا)", c):
            return "not_applicable"
        if re.search(r"(?:تخطى|تخطي|تجاوز|لا\s*أعلم|لا\s*اعلم|ما\s*أعرف|ما\s*اعرف|مش\s*عارف|لست\s*متأكد|بعدين|لاحقاً|لاحقا|skip)", c):
            return "skip"
        return None

    # -----------------------------------------------------------------------
    # Stage 1: Classification Turn Handler (Exactly 4 Questions)
    # -----------------------------------------------------------------------

    def handle_classification_step(
        self,
        tenant_id: UUID,
        state: InterviewState,
        content: str,
        message_id: UUID,
        ai_provider: AIProvider | None = None,
    ) -> str:
        """
        Processes answers for Stage 1 classification (4 conversational questions).
        Stores extracted values in state.classification_answers and persists
        profile facts once classification completes.
        """
        answers = dict(state.classification_answers or {})
        stage = state.stage

        if stage == "classification_1":
            # Parsing Owner Name
            name = self._clean_name_answer(content)
            answers["owner_name"] = name
            state.classification_answers = answers
            state.stage = "classification_2"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            return CLASSIFICATION_QUESTIONS["classification_2"].format(owner_name=name)

        if stage == "classification_2":
            # Parsing Owner Role
            role = self._clean_role_answer(content)
            answers["owner_role"] = role
            state.classification_answers = answers
            state.stage = "classification_3"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            return CLASSIFICATION_QUESTIONS["classification_3"]

        if stage == "classification_3":
            # Parsing Entity Type
            etype = self._clean_entity_type_answer(content)
            answers["entity_type"] = etype
            state.classification_answers = answers
            state.stage = "classification_4"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            return CLASSIFICATION_QUESTIONS["classification_4"]

        if stage == "classification_4":
            # Parsing Country & Field of Activity
            country, field = self._clean_country_field_answer(content)
            answers["country"] = country
            answers["field_of_activity"] = field

            # Derive multi-label tags
            tags = self._derive_profile_tags(answers)
            answers["tags"] = tags
            state.classification_answers = answers

            # Persist profile facts via FactService
            self._persist_profile_facts(tenant_id, answers)

            # Move to Stage 2: Topic Planning
            plan = self.generate_topic_plan(tenant_id, answers, ai_provider=ai_provider)
            self.store_planned_topics(tenant_id, plan.topics)

            state.stage = "interviewing"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()

            # Read-back of profile + smoothly transition to first topic question
            owner_name = answers.get("owner_name", "صاحب المنشأة")
            readback = (
                f"سعدت بالتعرف عليك يا {owner_name}! 🎉\n"
                f"تم توثيق بيانات ملف المنشأة الأولي:\n"
                f"• الصفة: {answers.get('owner_role')}\n"
                f"• الكيان: {answers.get('entity_type')}\n"
                f"• الدولة: {answers.get('country')}\n"
                f"• النشاط: {answers.get('field_of_activity')}\n"
                f"• التصنيفات: {', '.join(tags)}\n\n"
                "والآن، لنبدأ بالأسئلة التفصيلية الخاصة بنشاطكم:\n"
            )

            next_q = self.get_next_question(tenant_id)
            if next_q:
                return f"{readback}\n{next_q}"
            return f"{readback}\nتم استكمال كافة البيانات الأساسية بنجاح!"

        return "المرحلة غير معروفة."

    # -----------------------------------------------------------------------
    # Stage 2: Dynamic Topic Planning (Model + Deterministic Domain Fallback)
    # -----------------------------------------------------------------------

    def generate_topic_plan(
        self,
        tenant_id: UUID,
        profile: dict[str, Any],
        ai_provider: AIProvider | None = None,
    ) -> InterviewPlanSchema:
        """
        Generates structured interview topics tailored to the business profile.
        Uses AI provider with Pydantic validation if available; falls back to
        deterministic domain topic synthesis.
        """
        tags = [str(t).lower() for t in profile.get("tags", [])]
        field_text = str(profile.get("field_of_activity", "")).lower()
        country_text = str(profile.get("country", "")).lower()

        # If AI Provider is supplied, attempt structured plan generation
        if ai_provider is not None:
            try:
                system_prompt = (
                    "You are the Adaptive Onboarding Topic Planner for an enterprise digital assistant.\n"
                    "Given the business profile (owner role, entity type, country, field of activity, tags), "
                    "generate a strict JSON listing of interview topics.\n"
                    "Requirements:\n"
                    "1. Include universal topics: identity, products_services_prices, ordering_payment, delivery_coverage, "
                    "branches_hours, returns_warranty, authority_limits, tone_voice, unknown_questions_handling.\n"
                    "2. Include field-specific topics (e.g. honey: types, origin, packaging, storage, authenticity; "
                    "software: goals, target clients, licenses, support SLA, partnerships; restaurant: menu, dine-in/takeaway, allergies).\n"
                    "3. Assign criticality 1-5, short clear Arabic questions, normalized lowercase slugs, and depends_on slugs."
                )
                user_prompt = f"Business Profile:\n{json.dumps(profile, ensure_ascii=False)}"
                res = ai_provider.generate_json(
                    user_prompt,
                    schema=InterviewPlanSchema,
                    system_instruction=system_prompt,
                )
                if isinstance(res, dict) and "topics" in res:
                    plan = InterviewPlanSchema.model_validate(res)
                    if plan.topics and len(plan.topics) >= 5:
                        return self._validate_and_normalize_plan(plan)
            except Exception as exc:
                logger.warning("AI topic planning failed for tenant %s: %s. Using domain synthesizer.", tenant_id, exc)

        # Deterministic Domain-Adaptive Topic Synthesizer
        return self._synthesize_domain_plan(tags, field_text, country_text)

    def _synthesize_domain_plan(
        self,
        tags: list[str],
        field_text: str,
        country_text: str,
    ) -> InterviewPlanSchema:
        """Deterministic topic generator tailored to honey, software, retail, or service domains."""
        topics: list[TopicPlanItem] = []

        # 1. Universal Foundations
        topics.append(TopicPlanItem(
            slug="identity",
            label="هوية المنشأة والاسم التجاري",
            why_it_matters="يحتاج العميل لمعرفة اسم المنشأة الرسمي للتحقق من التعامل مع جهة موثوقة",
            criticality=5,
            question="ما هو الاسم التجاري الرسمي المعتمد لمنشأتكم؟",
            depends_on=[],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="products_services_prices",
            label="المنتجات والخدمات والأسعار",
            why_it_matters="الإجابة على استفسارات الأسعار والمبيعات اليومية للعملاء",
            criticality=5,
            question="ما هي أهم المنتجات أو الخدمات التي تقدمونها وقائمتها وأسعارها؟",
            depends_on=["identity"],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="ordering_payment",
            label="طرق الطلب والدفع المعتمدة",
            why_it_matters="توضيح آلية إتمام الشراء ووسائل السداد المتاحة",
            criticality=4,
            question="كيف يمكن للعميل تقديم الطلب وما هي طرق الدفع المعتمدة لديكم؟ (كاش، تحويل بنكي، عند الاستلام...)",
            depends_on=["products_services_prices"],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="delivery_coverage",
            label="نطاق التوصيل والمدن المخدومة",
            why_it_matters="معرفة ما إذا كان العميل داخل نطاق التغطية والشحن",
            criticality=4,
            question="ما هي المدن والمناطق التي تغطيها خدماتكم أو توصيلكم؟",
            depends_on=["identity"],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="branches_hours",
            label="الفروع وساعات العمل",
            why_it_matters="توجيه العملاء لمواقع الفروع ومواعيد الاستقبال الرسمية",
            criticality=3,
            question="هل لديكم فروع أو محلات فعلية، وما هي ساعات وأيام العمل الرسمية؟",
            depends_on=["identity"],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="returns_warranty",
            label="سياسة الاسترجاع والضمان",
            why_it_matters="بناء ثقة العميل وحل أي اعتراضات أو رغبة في الإرجاع",
            criticality=3,
            question="ما هي سياسة الاستبدال، الاسترجاع، والضمان على منتجاتكم وخدماتكم؟",
            depends_on=["products_services_prices"],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="authority_limits",
            label="حدود صلاحيات الموظف الرقمي",
            why_it_matters="ضبط ما يحق للمساعد الآلي إقراره وما يتطلب موافقة المالك",
            criticality=2,
            question="ما هي الصلاحيات المسموحة لي كموظف رقمي؟ (مثلاً: هل يحق لي منح خصومات محددة؟)",
            depends_on=["identity"],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="tone_voice",
            label="نبرة وأسلوب التحدث مع العملاء",
            why_it_matters="ضمان تمثيل المنشأة بالأسلوب الذي يعكس هويتها",
            criticality=1,
            question="ما هي النبرة المفضلة للتواصل مع عملائكم؟ (رسمية، ودية، سريعة ومختصرة...)",
            depends_on=[],
            group_name="universal",
        ))

        topics.append(TopicPlanItem(
            slug="unknown_questions_handling",
            label="التعامل مع الأسئلة غير المسجلة",
            why_it_matters="تفادي الهلوسة عند سؤال العميل عن تفصيل غير مدون",
            criticality=2,
            question="عندما يسأل عميل عن معلومة غير مسجلة لدينا، هل أبلغه بمراجعة الفريق أم أحيل طلبه إليك مباشرة؟",
            depends_on=["identity"],
            group_name="universal",
        ))

        # 2. Field-Specific Enhancements
        is_honey = any(h in tags or h in field_text for h in ("honey", "عسل", "مناحل", "نحل"))
        is_software = any(s in tags or s in field_text for s in ("software", "برمجيات", "تقنية", "أنظمة", "شبكات", "it"))
        is_restaurant = any(r in tags or r in field_text for r in ("restaurant", "مطعم", "أغذية", "كافيه", "مقهى"))

        if is_honey:
            topics.append(TopicPlanItem(
                slug="honey_types",
                label="أنواع العسل ومصادره الطبيعية",
                why_it_matters="عشاق العسل يسألون دوماً عن المصدر ونوع الزهرة",
                criticality=5,
                question="ما هي أنواع العسل المتوفرة لديكم ومصادرها الجغرافية؟ (مثلاً: سدر دوعني، سمر، صال، مراعي...)",
                depends_on=["products_services_prices"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="packaging_sizes",
                label="أحجام العبوات والأسعار الخاصة بكل حجم",
                why_it_matters="توضيح خيارات التعبئة (كيلو، نصف، ربع) لسهولة الاختيار",
                criticality=4,
                question="ما هي أحجام العبوات المتاحة (كيلو، نصف كيلو، ربع) وأسعار كل حجم؟",
                depends_on=["honey_types"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="honey_storage",
                label="إرشادات حفظ وتخزين العسل",
                why_it_matters="توعية العميل بطريقة الحفظ لضمان عدم التبلور والتلف",
                criticality=3,
                question="ما هي إرشادات التخزين المثالية للعسل للحفاظ على جودته وخصائصه العلاجية؟",
                depends_on=["honey_types"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="authenticity_guarantee",
                label="ضمان النقاوة والفحص المخبري",
                why_it_matters="أهم عامل حاسم لشراء العسل هو التأكد من خلوه من التغذية السكرية",
                criticality=4,
                question="هل العسل مفحوص مخبريًا وما هو ضمانكم المعتمد للعملاء في حال التشكيك بالنقاوة؟",
                depends_on=["honey_types"],
                group_name="field_specific",
            ))

        elif is_software:
            topics.append(TopicPlanItem(
                slug="target_clients",
                label="العملاء والقطاعات المستهدفة",
                why_it_matters="تحديد ما إذا كان البرنامج يناسب نشاط العميل وحجم أعماله",
                criticality=4,
                question="من هم العملاء أو القطاعات المستهدفة بحلولكم البرمجية؟ (شركات، متاجر، مصانع...)",
                depends_on=["products_services_prices"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="software_licenses",
                label="أنواع التراخيص ونماذج الاشتراك",
                why_it_matters="توضيح الفروق بين الاشتراكات السحابية والشراء الدائم",
                criticality=4,
                question="كيف يتم ترخيص البرامج لديكم؟ (اشتراك سنوي/شهري، شراء رخصة دائمة، تكلفة المستخدمين...)",
                depends_on=["products_services_prices"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="support_sla_policy",
                label="سياسة الدعم الفني واتفاقيات الخدمة (SLA)",
                why_it_matters="حاجة العملاء لمعرفة سرعة التجاوب وآلية حل المشاكل التقنية",
                criticality=4,
                question="ما هي سياسة الدعم الفني المتبعة وأوقات استجابة الفريق للعملاء وحل المشاكل؟",
                depends_on=["products_services_prices"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="partnerships_certifications",
                label="الشهادات والشراكات والاعتمادات",
                why_it_matters="تعزيز موثوقية الحلول التقنية في بيئات الأعمال المتقدمة",
                criticality=2,
                question="هل تمتلك المنشأة اعتمادات أو شهادات أو شراكات تقنية تحب إبرازها للعملاء؟",
                depends_on=["identity"],
                group_name="field_specific",
            ))

        elif is_restaurant:
            topics.append(TopicPlanItem(
                slug="menu_categories",
                label="أقسام وتصنيفات المنيو",
                why_it_matters="مساعدة العميل على تصفح المنيو واختيار وجبته",
                criticality=5,
                question="ما هي الأقسام والأصناف الرئيسية في قائمة الطعام لديكم؟",
                depends_on=["products_services_prices"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="dine_in_takeaway",
                label="الطلبات الداخلية والسفري والتوصيل",
                why_it_matters="تحديد خيارات تناول الوجبات أو استلامها",
                criticality=4,
                question="هل الخدمة متاحة داخل المطعم، سفري، وتوصيل منازل؟",
                depends_on=["menu_categories"],
                group_name="field_specific",
            ))

        # 3. Country-Specific Branching (e.g. Yemen delivery ladder)
        is_yemen = any(y in tags or y in country_text for y in ("yemen", "اليمن"))
        if is_yemen:
            topics.append(TopicPlanItem(
                slug="delivery_zones_yemen",
                label="مناطق وتكلفة التوصيل داخل المحافظة",
                why_it_matters="معرفة أسعار التوصيل المحلي للمدن الرئيسية",
                criticality=4,
                question="ما هي أسعار التوصيل داخل المدينة (صنعاء أو غيرها) وهل يختلف السعر حسب المنطقة؟",
                depends_on=["delivery_coverage"],
                group_name="follow_up",
            ))
            topics.append(TopicPlanItem(
                slug="between_governorates_yemen",
                label="الشحن بين المحافظات اليمنية",
                why_it_matters="معرفة إمكانية الشحن للمحافظات وشركات النقل المعتمدة",
                criticality=3,
                question="هل تشحنون للمحافظات الأخرى وما هي وسائل الشحن المعتمدة لديكم؟",
                depends_on=["delivery_zones_yemen"],
                group_name="follow_up",
            ))
            topics.append(TopicPlanItem(
                slug="international_shipping",
                label="الشحن الدولي خارج اليمن",
                why_it_matters="التحقق من إمكانية شحن الطلبات للعملاء في الخليج أو الدول الأخرى",
                criticality=2,
                question="هل توفرون شحن دولي خارج اليمن للعملاء والمغتربين؟",
                depends_on=["between_governorates_yemen"],
                group_name="follow_up",
            ))
            topics.append(TopicPlanItem(
                slug="international_shipping_details",
                label="تفاصيل وأسعار الشحن الدولي",
                why_it_matters="تزويد العملاء في الخارج بتكلفة ومدة الشحن",
                criticality=2,
                question="ما هي الدول المتاح الشحن إليها، وتكلفة ومدة وصول الشحنة تقريباً؟",
                depends_on=["international_shipping"],
                group_name="follow_up",
            ))

        return InterviewPlanSchema(business_tags=tags, topics=topics)

    def _validate_and_normalize_plan(self, plan: InterviewPlanSchema) -> InterviewPlanSchema:
        """Validates topic constraints: normalized slugs, no duplicates, bounded count."""
        seen_slugs = set()
        valid_topics = []
        for t in plan.topics[:25]:
            norm_slug = re.sub(r"[^a-z0-9_]+", "_", t.slug.lower().strip()).strip("_")
            if not norm_slug or norm_slug in seen_slugs:
                continue
            seen_slugs.add(norm_slug)
            t.slug = norm_slug
            t.criticality = max(1, min(5, t.criticality))
            valid_topics.append(t)
        return InterviewPlanSchema(business_tags=plan.business_tags, topics=valid_topics)

    def store_planned_topics(self, tenant_id: UUID, topics: list[TopicPlanItem]) -> None:
        """Persists topics into interview_topics table with status 'unknown'."""
        for t in topics:
            existing = self.db.scalar(
                select(InterviewTopic).where(
                    InterviewTopic.tenant_id == tenant_id,
                    InterviewTopic.slug == t.slug,
                )
            )
            if existing is None:
                topic_row = InterviewTopic(
                    tenant_id=tenant_id,
                    slug=t.slug,
                    label=t.label,
                    why_it_matters=t.why_it_matters,
                    criticality=t.criticality,
                    question=t.question,
                    depends_on=t.depends_on,
                    status="unknown",
                    coverage=0.0,
                    group_name=t.group_name,
                )
                self.db.add(topic_row)
        self.db.flush()

    # -----------------------------------------------------------------------
    # Next-Question Selector (Deterministic, NOT the model)
    # -----------------------------------------------------------------------

    def get_next_question_topic(self, tenant_id: UUID) -> InterviewTopic | None:
        """
        Deterministic topic selector:
        Among topics with status 'unknown' whose depends_on prerequisites are all satisfied
        (answered, skipped, or not_applicable), selects highest criticality (tie-break by dependency depth).
        """
        all_topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()

        if not all_topics:
            return None

        status_by_slug = {t.slug: t.status for t in all_topics}
        SATISFIED_STATUSES = {"answered", "skipped", "not_applicable"}

        candidates: list[InterviewTopic] = []
        for t in all_topics:
            if t.status != "unknown":
                continue
            deps = t.depends_on or []
            if all(status_by_slug.get(d) in SATISFIED_STATUSES for d in deps):
                candidates.append(t)

        if not candidates:
            return None

        # Sort: criticality descending, then dependency depth descending, then created_at ascending
        candidates.sort(
            key=lambda t: (
                t.criticality,
                len(t.depends_on or []),
                -t.created_at.timestamp() if t.created_at else 0,
            ),
            reverse=True,
        )
        return candidates[0]

    def get_next_question(self, tenant_id: UUID) -> str | None:
        """Returns the formatted Arabic question for the next selected topic."""
        topic = self.get_next_question_topic(tenant_id)
        if topic is None:
            return None

        # Update topic status to 'asked'
        topic.status = "asked"
        self.db.add(topic)

        # Update current topic in interview state
        state = self.get_or_create_state(tenant_id)
        state.current_topic_slug = topic.slug
        self.db.add(state)
        self.db.flush()

        # Add suggested options if relevant
        options = self._suggest_options(topic.slug)
        if options:
            opts_str = " | ".join(options)
            return f"{topic.question}\n(خيارات سريعة: {opts_str})"
        return topic.question

    @staticmethod
    def _suggest_options(slug: str) -> list[str]:
        """Provides quick-reply suggestions for common topics."""
        mapping = {
            "ordering_payment": ["تحويل بنكي", "دفع عند الاستلام", "كاش بالفرع"],
            "returns_warranty": ["استرجاع خلال 3 أيام", "استبدال فقط", "لا يوجد استرجاع"],
            "branches_hours": ["لدينا فروع ومحلات", "متجر إلكتروني فقط"],
            "international_shipping": ["نعم نوفر شحن دولي", "لا، شحن محلي فقط"],
            "authority_limits": ["صلاحيات كاملة للاستفسارات والأسعار", "يلزم تأكيد المالك للخصومات"],
            "tone_voice": ["رسمية واحترافية", "ودية وترحيبية", "مختصرة ومباشرة"],
            "unknown_questions_handling": ["إبلاغ العميل بمراجعة الفريق", "إحالة فورية للمالك"],
        }
        return mapping.get(slug, [])

    # -----------------------------------------------------------------------
    # Multi-Topic Extraction & Status Update
    # -----------------------------------------------------------------------

    def mark_covered_topics_from_reply(
        self,
        tenant_id: UUID,
        content: str,
        message_id: UUID,
        current_topic_slug: str | None = None,
        extracted_facts: list[ExtractedFactItem] | None = None,
    ) -> list[str]:
        """
        Marks every topic covered by the owner's message.
        An owner may answer multiple topics in a single turn.
        Returns list of newly answered topic slugs.
        """
        newly_covered: list[str] = []
        c_lower = content.lower()

        # Map extracted facts topics to interview topic slugs
        fact_topics = {f.topic for f in (extracted_facts or [])}

        has_identity = any(t in fact_topics for t in ("company.identity", "company.name")) or bool(
            re.search(r"اسم\s*(?:شركتنا|الشركة|المتجر|المحل|منشأتنا)", c_lower)
        )
        has_products = any(t.startswith("product.") or t == "products" for t in fact_topics) or bool(
            re.search(r"(?:نبيع|نوفر|نقدم|منتجاتنا|خدماتنا|سعر|بسعر)\b", c_lower)
        )
        has_coverage = any(t.startswith("operations.") or "coverage" in t or "delivery" in t for t in fact_topics) or bool(
            re.search(r"(?:نخدم|نوصل|فروعنا|تغطيتنا|نغطي|في\s*(?:صنعاء|عدن|الرياض|جدة))\b", c_lower)
        )
        has_payment = any("payment" in t or "pricing" in t for t in fact_topics) or bool(
            re.search(r"(?:تحويل\s*بنكي|دفع\s*عند\s*الاستلام|كاش|سداد|فيزا|مدى)\b", c_lower)
        )
        has_branches = bool(re.search(r"(?:فروعنا|فرع\s*في|ساعات\s*العمل|دوامنا|نفتح\s*من)", c_lower))
        has_honey_types = any("honey" in t for t in fact_topics) or bool(re.search(r"(?:سدر|دوعني|سمر|صال|مراعي|عسل\s*\w+)", c_lower))

        slug_triggers = {
            "identity": has_identity,
            "products_services_prices": has_products,
            "delivery_coverage": has_coverage,
            "delivery_zones_yemen": has_coverage and "اليمن" in c_lower or ("صنعاء" in c_lower or "عدن" in c_lower),
            "between_governorates_yemen": has_coverage and any(w in c_lower for w in ("محافظات", "بين المحافظات", "شحن")),
            "ordering_payment": has_payment,
            "branches_hours": has_branches,
            "honey_types": has_honey_types,
        }

        # Check each open topic
        topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()

        for t in topics:
            if t.status in ("answered", "not_applicable"):
                continue

            should_mark = False
            # If this was the explicitly asked current topic
            if current_topic_slug and t.slug == current_topic_slug:
                should_mark = True
            # Or if content covered its domain
            elif slug_triggers.get(t.slug) is True:
                should_mark = True

            if should_mark:
                t.status = "answered"
                t.coverage = 1.0
                t.source_message_id = message_id
                self.db.add(t)
                newly_covered.append(t.slug)

        self.db.flush()
        return newly_covered

    def handle_branch_closure(self, tenant_id: UUID, closed_slug: str) -> None:
        """When an owner answers negatively (e.g. 'لا' to international shipping), closes dependent topics."""
        all_topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()
        for t in all_topics:
            if t.depends_on and closed_slug in t.depends_on and t.status == "unknown":
                t.status = "not_applicable"
                t.coverage = 0.0
                self.db.add(t)
        self.db.flush()

    # -----------------------------------------------------------------------
    # Main Interview Turn Processor
    # -----------------------------------------------------------------------

    def process_interview_turn(
        self,
        tenant_id: UUID,
        message_id: UUID,
        content: str,
        ai_provider: AIProvider | None = None,
    ) -> tuple[str, bool]:
        """
        Processes an incoming owner message during the adaptive interview.
        Returns (reply_text, is_interview_response).
        If message is off-topic, returns (reply_text, False) so conversational engine
        answers the query while preserving interview state.
        """
        state = self.get_or_create_state(tenant_id)
        content_clean = (content or "").strip()

        # 1. Check for Progress Query ("وش باقي؟")
        trigger = self.detect_trigger(content_clean)
        if trigger == "progress":
            return self.get_progress_summary(tenant_id), True

        # 2. Check for Start / Resume Explicit Commands
        if trigger in ("start", "resume"):
            return self.resume_interview(tenant_id), True

        # 3. Check for Off-Topic Inquiry during topic interview
        if state.stage == "interviewing" and state.current_topic_slug:
            curr_topic = self.db.scalar(
                select(InterviewTopic).where(
                    InterviewTopic.tenant_id == tenant_id,
                    InterviewTopic.slug == state.current_topic_slug,
                )
            )
            curr_q = curr_topic.question if curr_topic else ""
            if self.is_off_topic_message(content_clean, curr_q):
                # Don't swallow off-topic question! Return False to allow engine to answer.
                return "", False

        # 4. Handle Stage 1: Classification Turn
        if state.stage.startswith("classification_"):
            reply = self.handle_classification_step(
                tenant_id, state, content_clean, message_id, ai_provider=ai_provider
            )
            return reply, True

        # 5. Handle Stage 3: Topic Interview Turn
        if state.stage == "interviewing":
            curr_slug = state.current_topic_slug

            # Check skip or not applicable
            skip_type = self.is_skip_or_na(content_clean)
            if skip_type:
                if curr_slug:
                    curr_topic = self.db.scalar(
                        select(InterviewTopic).where(
                            InterviewTopic.tenant_id == tenant_id,
                            InterviewTopic.slug == curr_slug,
                        )
                    )
                    if curr_topic:
                        curr_topic.status = "not_applicable" if skip_type == "not_applicable" else "skipped"
                        curr_topic.source_message_id = message_id
                        self.db.add(curr_topic)
                        self.db.flush()
                        # If not applicable, close dependent branch
                        if skip_type == "not_applicable":
                            self.handle_branch_closure(tenant_id, curr_slug)

                ack = "تم تخطي الموضوع." if skip_type == "skip" else "تم تسجيل أن هذا الموضوع لا ينطبق على منشأتكم."
                next_q = self.get_next_question(tenant_id)
                if next_q:
                    return f"{ack}\n\n{next_q}", True
                state.stage = "completed"
                self.db.add(state)
                self.db.flush()
                return f"{ack}\n\n🎉 تم استكمال جلسة التعارف بنجاح! موظفك الرقمي جاهز الآن لخدمة العملاء.", True

            # Negative closure detection (e.g. "لا" to international shipping or branches)
            if re.search(r"^\s*(?:لا|لا\s*نوفر|غير\s*متاح|ما\s*في|ليس\s*لدينا)\b", content_clean) and curr_slug:
                curr_topic = self.db.scalar(
                    select(InterviewTopic).where(
                        InterviewTopic.tenant_id == tenant_id,
                        InterviewTopic.slug == curr_slug,
                    )
                )
                if curr_topic:
                    curr_topic.status = "answered"
                    curr_topic.source_message_id = message_id
                    self.db.add(curr_topic)
                    self.db.flush()
                    self.handle_branch_closure(tenant_id, curr_slug)

                ack = "تم تسجيل ذلك."
                next_q = self.get_next_question(tenant_id)
                if next_q:
                    return f"{ack}\n\n{next_q}", True
                state.stage = "completed"
                self.db.add(state)
                self.db.flush()
                return f"{ack}\n\n🎉 تم استكمال جلسة التعارف بنجاح!", True

            # Substantive Answer: Run Phase 2 Structured Fact Extraction
            extraction_res = self.fact_service.extract_facts(
                tenant_id=tenant_id,
                message_text=content_clean,
                provider=ai_provider,
            )
            extracted_items = extraction_res.facts if extraction_res else []
            save_result = self.fact_service.save_extracted_facts(
                tenant_id=tenant_id,
                extracted_facts=extracted_items,
                auto_confirm_direct=True,
                message_text=content_clean,
            )
            saved_facts = list(save_result.get("confirmed", [])) + list(save_result.get("pending", []))
            conflicts = list(save_result.get("conflicts", []))

            # Mark all topics covered by this reply
            covered = self.mark_covered_topics_from_reply(
                tenant_id=tenant_id,
                content=content_clean,
                message_id=message_id,
                current_topic_slug=curr_slug,
                extracted_facts=extracted_items,
            )

            # Build read-back acknowledgment
            saved_labels = [f.subject for f in saved_facts]
            if saved_labels:
                ack_lines = [f"✅ تم حفظ وتأكيد: {', '.join(saved_labels)}"]
            else:
                ack_lines = ["✅ تم حفظ وتوثيق إجابتك بنجاح."]

            # Select Next Question
            next_q = self.get_next_question(tenant_id)
            if next_q:
                ack_lines.append(f"\n{next_q}")
                return "\n".join(ack_lines), True

            # All topics covered! Complete interview
            state.stage = "completed"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            ack_lines.append("\n🎉 تم استكمال جلسة التعارف بنجاح! موظفك الرقمي جاهز لخدمة العملاء بكامل طاقته.")
            return "\n".join(ack_lines), True

        return "محادثة التعارف مكتملة. يمكنك السؤال عن أي تفصيل في أي وقت.", True

    # -----------------------------------------------------------------------
    # Progress Summary ("وش باقي؟")
    # -----------------------------------------------------------------------

    def get_progress_summary(self, tenant_id: UUID) -> str:
        """
        Returns a clear progress report:
        - Covered count vs Total count
        - Critical coverage percentage
        - List of open critical topics
        """
        topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()

        if not topics:
            return "لم يتم إنشاء خطة التعارف بعد. يمكنك البدء بقول 'ابدأ التعارف'."

        total_count = len(topics)
        answered_count = sum(1 for t in topics if t.status in ("answered", "not_applicable"))
        skipped_count = sum(1 for t in topics if t.status == "skipped")

        critical_topics = [t for t in topics if t.criticality >= 4]
        total_critical = len(critical_topics)
        answered_critical = sum(1 for t in critical_topics if t.status in ("answered", "not_applicable"))
        critical_pct = (answered_critical / total_critical * 100.0) if total_critical > 0 else 100.0

        open_critical = [t for t in critical_topics if t.status not in ("answered", "not_applicable")]

        lines = [
            f"📊 **ملخص تقدم التعارف:**",
            f"• المواضيع المكتملة: {answered_count} من أصل {total_count} موضوع",
            f"• نسبة المواضيع الحرجة: {critical_pct:.0f}%",
        ]
        if skipped_count:
            lines.append(f"• المواضيع المتخطاة: {skipped_count}")

        if open_critical:
            lines.append("\n⚠️ **المواضيع الحرجة المتبقية:**")
            for t in open_critical[:5]:
                lines.append(f"- {t.label} (أهمية: {t.criticality}/5)")
            lines.append("\nيمكنك إكمالها في أي وقت بالرد على السؤال أو كتابة 'كمّل التعارف'.")
        else:
            lines.append("\n✅ تم تغطية جميع المواضيع الحرجة بنجاح! المنشأة جاهزة لخدمة العملاء.")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Resume / Restart Interview
    # -----------------------------------------------------------------------

    def resume_interview(self, tenant_id: UUID) -> str:
        """Resumes the interview where it paused, returning the appropriate question."""
        state = self.get_or_create_state(tenant_id)
        state.is_active = True
        state.last_interaction_at = datetime.now(timezone.utc)
        self.db.add(state)
        self.db.flush()

        # If still in classification
        if state.stage.startswith("classification_"):
            q_key = state.stage
            owner_name = (state.classification_answers or {}).get("owner_name", "صاحب المنشأة")
            template = CLASSIFICATION_QUESTIONS.get(q_key, CLASSIFICATION_QUESTIONS["classification_1"])
            return f"مرحباً بك مجدداً! لنواصل التعارف:\n\n{template.format(owner_name=owner_name)}"

        # If in topic interview
        next_q = self.get_next_question(tenant_id)
        if next_q:
            return f"مرحباً بك مجدداً! لنواصل التعارف من حيث توقفنا:\n\n{next_q}"

        return "🎉 جميع مواضيع التعارف مكتملة! المنشأة جاهزة للعمل بالكامل."

    # -----------------------------------------------------------------------
    # Go-Live Gate Verification
    # -----------------------------------------------------------------------

    def check_go_live_gate(
        self,
        tenant_id: UUID,
        threshold: float = 80.0,
    ) -> tuple[bool, float, list[str]]:
        """
        Evaluates the go-live gate for customer queries:
        Returns (is_ready, critical_percentage, missing_critical_labels).
        """
        critical_topics = self.db.scalars(
            select(InterviewTopic).where(
                InterviewTopic.tenant_id == tenant_id,
                InterviewTopic.criticality >= 4,
            )
        ).all()

        if not critical_topics:
            return True, 100.0, []

        total_crit = len(critical_topics)
        answered_crit = sum(1 for t in critical_topics if t.status in ("answered", "not_applicable"))
        crit_pct = (answered_crit / total_crit) * 100.0

        missing = [t.label for t in critical_topics if t.status not in ("answered", "not_applicable")]
        is_ready = crit_pct >= threshold
        return is_ready, crit_pct, missing

    def notify_owner_of_unmet_gate(
        self,
        tenant_id: UUID,
        critical_pct: float,
        missing_critical: list[str],
        customer_message: str | None = None,
    ) -> None:
        """Records audit event and alert for tenant owner regarding blocked customer query."""
        missing_str = ", ".join(missing_critical[:3]) if missing_critical else "البيانات الأساسية"
        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="customer_query_blocked_by_interview_gate",
            action="gate_blocked",
            description=f"Customer query blocked: Critical interview coverage {critical_pct:.0f}% is below threshold. Missing: {missing_str}",
            event_metadata={
                "critical_pct": critical_pct,
                "missing_critical": missing_critical,
                "customer_message": customer_message or "",
            },
        )

    # -----------------------------------------------------------------------
    # Off-Topic Detection
    # -----------------------------------------------------------------------

    @staticmethod
    def is_off_topic_message(content: str, current_question: str) -> bool:
        """
        Determines whether the owner message is an off-topic query
        (e.g. asking about tasks, time, platform capabilities, customer messages)
        rather than an answer to the current interview question.
        """
        c = (content or "").strip().lower()
        if not c or len(c) < 3:
            return False

        # If it matches skip or explicit triggers, it's NOT off-topic
        if InterviewService.is_skip_or_na(c) or InterviewService.detect_trigger(c):
            return False

        # Specific off-topic inquiry indicators
        off_topic_patterns = [
            r"^(?:كم|ما\s*هي|ايش|إيش|ماهي|أين|كيف|هل)\s*(?:الساعة|الوقت|التاريخ|المهام|الموجود|عندي|لديك)\b",
            r"(?:عرض\s*المهام|قائمة\s*المهام|المهام\s*المعلقة|الموافقات|طلبات\s*الموافقة)\b",
            r"^(?:من\s*أنت|ماذا\s*تستطيع\s*أن\s*تفعل|من\s*انت|عرفني\s*عن\s*نفسك)\b",
            r"(?:حالة\s*النظام|استهلاك\s*الذكاء|رصيد\s*الحساب)\b",
        ]
        return any(bool(re.search(p, c)) for p in off_topic_patterns)

    # -----------------------------------------------------------------------
    # Private Cleaning & Parsing Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_name_answer(content: str) -> str:
        c = content.strip()
        m = re.search(r"(?:اسمي|أنا|انا|معك|الاسم\s*:?)\s*([^\n,.،]+)", c)
        if m:
            clean = m.group(1).strip()
            clean = re.sub(r"^(?:الأخ|السيد|المهندس|الدكتور|الشيخ)\s+", "", clean)
            if clean:
                return clean
        parts = [p for p in c.split() if p not in ("اسمي", "أنا", "انا", "هو", "الاسم", "حياك", "الله")]
        return " ".join(parts[:3]) if parts else c

    @staticmethod
    def _clean_role_answer(content: str) -> str:
        c = content.strip()
        m = re.search(r"(?:صفتي|دوري|أنا|انا|بصفتي|عملي)\s*(?:هو|هي|يكون)?\s*[:—\-]?\s*([^\n,.،]+)", c)
        if m:
            return m.group(1).strip()
        return c

    @staticmethod
    def _clean_entity_type_answer(content: str) -> str:
        c = content.strip().lower()
        if "شركة" in c:
            return "شركة تجارية"
        if "محل" in c or "متجر فعلي" in c or "دكان" in c:
            return "متجر فعلي"
        if "إلكتروني" in c or "الكتروني" in c or "أونلاين" in c or "اونلاين" in c:
            return "متجر إلكتروني"
        if "خدم" in c or "مؤسسة خدمات" in c:
            return "مزود خدمات"
        return content.strip()

    @staticmethod
    def _clean_country_field_answer(content: str) -> tuple[str, str]:
        c = content.strip()
        country = "اليمن"
        if any(w in c.lower() for w in ("السعودية", "المملكة", "saudi", "ksa")):
            country = "المملكة العربية السعودية"
        elif any(w in c.lower() for w in ("الإمارات", "دبي", "ابوظبي", "uae")):
            country = "الإمارات العربية المتحدة"
        elif any(w in c.lower() for w in ("مصر", "egypt")):
            country = "مصر"
        elif any(w in c.lower() for w in ("اليمن", "صنعاء", "عدن", "yemen")):
            country = "اليمن"

        field = c
        m = re.search(r"(?:مجال\s*(?:النشاط|العمل)?|نشاطنا|نعمل\s*في)\s*[:—\-]?\s*([^\n.]+)", c)
        if m:
            field = m.group(1).strip()
        return country, field

    @staticmethod
    def _derive_profile_tags(answers: dict[str, Any]) -> list[str]:
        """Derives clean lowercase tags describing the business domain."""
        tags = set()
        c = answers.get("country", "")
        f = answers.get("field_of_activity", "")
        e = answers.get("entity_type", "")
        combined = f"{c} {f} {e}".lower()

        if "اليمن" in combined or "yemen" in combined:
            tags.add("Yemen")
        if "السعودية" in combined or "saudi" in combined:
            tags.add("Saudi Arabia")

        if any(w in combined for w in ("عسل", "honey", "مناحل")):
            tags.update(["honey", "retail", "natural_products", "delivery"])
        if any(w in combined for w in ("برمج", "software", "أنظمة", "تقني", "شبكات")):
            tags.update(["software", "company", "b2b", "development", "it"])
        if any(w in combined for w in ("مطعم", "restaurant", "أغذية", "وجبات")):
            tags.update(["restaurant", "food", "hospitality"])
        if any(w in combined for w in ("متجر", "محل", "shop", "store")):
            tags.add("shop")
        if any(w in combined for w in ("شركة", "company")):
            tags.add("company")

        return sorted(list(tags)) or ["general_business"]

    def _persist_profile_facts(self, tenant_id: UUID, answers: dict[str, Any]) -> None:
        """Stores Stage 1 profile answers into the FactService ledger with topic 'profile.*'."""
        facts_to_save = [
            ExtractedFactItem(topic="profile.owner_name", subject="اسم المالك", value={"name": answers.get("owner_name")}),
            ExtractedFactItem(topic="profile.owner_role", subject="صفة المالك", value={"role": answers.get("owner_role")}),
            ExtractedFactItem(topic="profile.entity_type", subject="طبيعة الكيان", value={"type": answers.get("entity_type")}),
            ExtractedFactItem(topic="profile.country", subject="دولة النشاط", value={"country": answers.get("country")}),
            ExtractedFactItem(topic="profile.field", subject="مجال النشاط", value={"field": answers.get("field_of_activity")}),
            ExtractedFactItem(topic="profile.tags", subject="تصنيفات المنشأة", value={"tags": answers.get("tags")}),
        ]
        self.fact_service.save_extracted_facts(
            tenant_id=tenant_id,
            extracted_facts=facts_to_save,
            auto_confirm_direct=True,
        )
