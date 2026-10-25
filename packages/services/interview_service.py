from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from packages.ai_providers.base import AIProvider, AIRateLimitError
import time
from packages.services.fact_service import ExtractedFactItem, FactService
from packages.models.domain import Fact, InterviewState, InterviewTopic
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService
from packages.services.fact_service import ExtractedFactItem, FactService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Schemas for Structured Topic Planning & Evaluation
# ---------------------------------------------------------------------------

class TopicPlanItem(BaseModel):
    """Schema for a planned interview topic."""

    slug: str
    label: str
    why_it_matters: str
    criticality: int = Field(ge=1, le=5)
    question: str
    depends_on: list[str] = Field(default_factory=list)
    condition: str | None = None
    group_name: str = "universal"


class InterviewPlanSchema(BaseModel):
    """Schema for the complete onboarding interview topic plan."""

    business_tags: list[str] = Field(default_factory=list)
    topics: list[TopicPlanItem] = Field(default_factory=list)


class TopicCoverageItem(BaseModel):
    """Model evaluation for a single open topic against owner reply."""

    slug: str
    status: Literal["covered", "partial", "not_covered", "skipped", "not_applicable"]
    coverage: float = 1.0
    extracted_details: str | None = None
    missing_details: str | None = None


class ReplyCoverageEvaluation(BaseModel):
    """Structured response from the LLM evaluating owner message coverage and extracted facts."""

    evaluations: list[TopicCoverageItem] = Field(default_factory=list)
    extracted_facts: list[ExtractedFactItem] = Field(default_factory=list)
    acknowledged_summary: str | None = None
    missing_details_prompt: str | None = None
    decided_by: str = "model" 


# ---------------------------------------------------------------------------
# Stage 1: Fixed Foundational Classification Questions
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

ARABIC_TAG_LABELS: dict[str, str] = {
    "yemen": "اليمن",
    "saudi arabia": "السعودية",
    "shop": "متجر فعلي",
    "store": "متجر",
    "company": "شركة",
    "honey": "عسل طبيعي ومناحل",
    "natural_products": "منتجات طبيعية",
    "retail": "تجارة تجزئة",
    "software": "برمجيات وأنظمة",
    "b2b": "خدمات أعمال (B2B)",
    "development": "تطوير حلول",
    "it": "تقنية معلومات",
    "restaurant": "مطعم",
    "food": "أغذية ومأكولات",
    "hospitality": "ضيافة",
    "delivery": "خدمات توصيل",
}


class InterviewService:
    """
    Core engine for Phase 3: Adaptive Owner Onboarding Interview.
    Autonomously guides the business owner through onboarding, classifies business profile,
    plans industry-specific topics, evaluates answer coverage, selects deterministic next questions,
    and gates customer go-live until critical knowledge is satisfied.
    """

    ARABIC_TAG_LABELS = ARABIC_TAG_LABELS

    def __init__(self, db: Session):
        self.db = db
        self.fact_service = FactService(db)
        self.audit_service = AuditService(db)

    def format_question_with_quick_replies(self, topic: Any, tags: list[str]) -> str:
        """Returns the polite question text including dynamic quick-replies tailored to business profile."""
        if hasattr(topic, "question"):
            return topic.question
        return str(topic)

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
        """Starts a fresh interview for the tenant from Stage 1 Question 1 without duplicate greetings."""
        state = self.get_or_create_state(tenant_id)
        state.stage = "classification_1"
        state.is_active = True
        state.last_interaction_at = datetime.now(timezone.utc)
        self.db.add(state)
        self.db.flush()
        return CLASSIFICATION_QUESTIONS["classification_1"]

    def resume_interview(self, tenant_id: UUID) -> str:
        """Resumes an interview in progress from where it stopped."""
        state = self.get_or_create_state(tenant_id)
        owner_name = (state.classification_answers or {}).get("owner_name", "صاحب المنشأة")

        if state.stage == "classification_1":
            # Starting fresh: do not duplicate greeting!
            return self.start_interview(tenant_id)

        if state.stage in CLASSIFICATION_QUESTIONS:
            template = CLASSIFICATION_QUESTIONS[state.stage]
            return f"مرحباً بك مجدداً يا {owner_name}! لنواصل التعارف:\n\n{template.format(owner_name=owner_name)}"

        if state.stage == "interviewing":
            next_q = self.get_next_question(tenant_id)
            if next_q:
                return f"مرحباً بك مجدداً! لنواصل التعارف من حيث توقفنا:\n\n{next_q}"

        if state.stage == "completed":
            return f"مرحباً بك يا {owner_name}! جلسة التعارف مكتملة وموظفك الرقمي جاهز للعمل. يمكنك السؤال عن أي تفصيل في أي وقت."

        return self.start_interview(tenant_id)

    # -----------------------------------------------------------------------
    # Entry Point Triggers Detection
    # -----------------------------------------------------------------------

    @staticmethod
    def detect_trigger(content: str) -> str | None:
        """Detects explicit interview conversational triggers."""
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
        """Checks if owner reply indicates skipping or not applicable."""
        c = (content or "").strip().lower()
        if re.search(r"(?:لا\s*ينطبق|غير\s*منطبق|ما\s*ينطبق|لا\s*ينطبق\s*علينا|ما\s*عندنا\s*هذا|لا\s*ينطبق\s*على\s*نشاطنا)", c):
            return "not_applicable"
        if re.search(r"(?:تخطى|تخطي|تجاوز|لا\s*أعلم|لا\s*اعلم|ما\s*أعرف|ما\s*اعرف|مش\s*عارف|لست\s*متأكد|بعدين|لاحقاً|لاحقا|skip)", c):
            return "skip"
        return None

    @classmethod
    def format_tags_arabic(cls, tags: list[str]) -> str:
        """Translates internal tags to clean Arabic labels for the owner."""
        arabic_labels = []
        for t in tags:
            clean_t = t.lower().strip()
            arabic_labels.append(cls.ARABIC_TAG_LABELS.get(clean_t, t))
        return "، ".join(dict.fromkeys(arabic_labels))

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
        """Processes answers for Stage 1 classification."""
        answers = dict(state.classification_answers or {})
        stage = state.stage

        if stage == "classification_1":
            name = self._clean_name_answer(content)
            answers["owner_name"] = name
            state.classification_answers = answers
            state.stage = "classification_2"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            return CLASSIFICATION_QUESTIONS["classification_2"].format(owner_name=name)

        if stage == "classification_2":
            role = self._clean_role_answer(content)
            answers["owner_role"] = role
            state.classification_answers = answers
            state.stage = "classification_3"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            return CLASSIFICATION_QUESTIONS["classification_3"]

        if stage == "classification_3":
            etype = self._clean_entity_type_answer(content)
            answers["entity_type"] = etype
            state.classification_answers = answers
            state.stage = "classification_4"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            return CLASSIFICATION_QUESTIONS["classification_4"]

        if stage == "classification_4":
            country, field = self._clean_country_field_answer(content)
            answers["country"] = country
            answers["field_of_activity"] = field

            # Derive stated tags without unstated assumptions
            stated_tags, inferred_tags = self._derive_profile_tags(answers)
            answers["tags"] = stated_tags
            answers["inferred_tags"] = inferred_tags
            state.classification_answers = answers

            # Persist profile facts via FactService
            self._persist_profile_facts(tenant_id, answers)

            # Move to Stage 2: Topic Planning (plan ONLY from stated facts)
            plan = self.generate_topic_plan(tenant_id, answers, ai_provider=ai_provider)
            self.store_planned_topics(tenant_id, plan.topics)

            state.stage = "interviewing"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()

            # Read-back with clean Arabic tags (NO raw English tags)
            owner_name = answers.get("owner_name", "صاحب المنشأة")
            arabic_tags_str = self.format_tags_arabic(stated_tags)
            readback = (
                f"سعدت بالتعرف عليك يا {owner_name}! 🎉\n"
                f"تم توثيق بيانات ملف المنشأة الأولي:\n"
                f"• الصفة: {answers.get('owner_role')}\n"
                f"• الكيان: {answers.get('entity_type')}\n"
                f"• الدولة: {answers.get('country')}\n"
                f"• النشاط: {answers.get('field_of_activity')}\n"
                f"• التصنيفات: {arabic_tags_str}\n\n"
                "والآن، لنبدأ بالأسئلة التفصيلية الخاصة بنشاطكم:\n"
            )

            next_q = self.get_next_question(tenant_id)
            if next_q:
                return f"{readback}\n{next_q}"
            return f"{readback}\nتم استكمال كافة البيانات الأساسية بنجاح!"

        return "المرحلة غير معروفة."

    # -----------------------------------------------------------------------
    # Stage 2: Dynamic Topic Planning (Model + Domain Fallback)
    # -----------------------------------------------------------------------

    def generate_topic_plan(
        self,
        tenant_id: UUID,
        profile: dict[str, Any],
        ai_provider: AIProvider | None = None,
    ) -> InterviewPlanSchema:
        """Generates structured interview topics tailored to the business profile."""
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
                    "CRITICAL RULES:\n"
                    "1. Adapt topics to business field: software/cloud companies must get service-coverage topics and digital payment options (NO cash on delivery or physical delivery zones!).\n"
                    "2. Physical stores / honey shops get delivery coverage, local governorate delivery zones, and COD/cash payment options.\n"
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
        combined = f"{' '.join(tags)} {field_text}".lower()

        is_software = any(s in combined for s in ("software", "برمج", "تقني", "أنظمة", "شبكات", "it", "سحابي", "cloud"))
        is_honey = any(h in combined for h in ("honey", "عسل", "مناحل", "نحل"))
        is_restaurant = any(r in combined for r in ("restaurant", "مطعم", "أغذية", "كافيه", "مقهى"))

        # 1. Universal Identity
        topics.append(TopicPlanItem(
            slug="identity",
            label="هوية المنشأة والاسم التجاري",
            why_it_matters="يحتاج العميل لمعرفة اسم المنشأة الرسمي للتحقق من التعامل مع جهة موثوقة",
            criticality=5,
            question="ما هو الاسم التجاري الرسمي المعتمد لمنشأتكم؟",
            depends_on=[],
            group_name="universal",
        ))

        # 2. Products / Services & Prices
        prod_q = "ما هي أهم الأنظمة والحلول البرمجية التي تقدمونها وباقات أسعارها؟" if is_software else "ما هي أهم المنتجات أو الخدمات التي تقدمونها وقائمتها وأسعارها؟"
        topics.append(TopicPlanItem(
            slug="products_services_prices",
            label="المنتجات والخدمات والأسعار",
            why_it_matters="الإجابة على استفسارات الأسعار والمبيعات اليومية للعملاء",
            criticality=5,
            question=prod_q,
            depends_on=["identity"],
            group_name="universal",
        ))

        # 3. Ordering & Payment (Adaptive Quick Replies!)
        if is_software:
            payment_q = "كيف يتم التعاقد والاشتراك في أنظمتكم وما هي وسائل الدفع والسداد المعتمدة؟\n(خيارات سريعة: تحويل بنكي | سداد إلكتروني | عقد سنوي / فواتير)"
        else:
            payment_q = "كيف يمكن للعميل تقديم الطلب وما هي طرق الدفع المعتمدة لديكم؟\n(خيارات سريعة: تحويل بنكي | دفع عند الاستلام | كاش بالفرع)"

        topics.append(TopicPlanItem(
            slug="ordering_payment",
            label="طرق الطلب والدفع المعتمدة",
            why_it_matters="توضيح آلية إتمام الشراء ووسائل السداد المتاحة",
            criticality=4,
            question=payment_q,
            depends_on=["products_services_prices"],
            group_name="universal",
        ))

        # 4. Delivery vs Service Coverage (Adaptive Domain Transformation!)
        if is_software:
            cov_q = "ما هي الدول والمناطق التي تغطيها خدماتكم السحابية والتقنية؟\n(خيارات سريعة: اليمن وكافة دول الخليج | عالمياً عبر السحابة | اليمن فقط)"
            topics.append(TopicPlanItem(
                slug="service_coverage",
                label="نطاق تقديم الخدمة والتغطية السحابية",
                why_it_matters="معرفة ما إذا كان العميل داخل نطاق تقديم الخدمة والدعم",
                criticality=4,
                question=cov_q,
                depends_on=["identity"],
                group_name="universal",
            ))
        else:
            cov_q = "ما هي المدن والمناطق التي تغطيها خدماتكم أو توصيلكم؟\n(خيارات سريعة: صنعاء وعدن وباقي المحافظات | داخل المدينة فقط | شحن لجميع المحافظات)"
            topics.append(TopicPlanItem(
                slug="delivery_coverage",
                label="نطاق التوصيل والمدن المخدومة",
                why_it_matters="معرفة ما إذا كان العميل داخل نطاق التغطية والشحن",
                criticality=4,
                question=cov_q,
                depends_on=["identity"],
                group_name="universal",
            ))

        # 5. Branches & Working Hours
        branches_q = "هل لديكم مقر رئيسي أو فروع يمكن للعملاء زيارتها، وما هي ساعات العمل؟" if is_software else "هل لديكم فروع أو محلات فعلية، وما هي ساعات وأيام العمل الرسمية؟"
        topics.append(TopicPlanItem(
            slug="branches_hours",
            label="الفروع وساعات العمل",
            why_it_matters="توجيه العملاء لمواقع الفروع ومواعيد الاستقبال الرسمية",
            criticality=3,
            question=branches_q,
            depends_on=["identity"],
            group_name="universal",
        ))

        # 6. Returns & Warranty / Support Policy
        warranty_q = "ما هي سياسة الضمان وحل المشكلات الفنية أو استرداد الاشتراك؟" if is_software else "ما هي سياسة الاستبدال، الاسترجاع، والضمان على منتجاتكم؟"
        topics.append(TopicPlanItem(
            slug="returns_warranty",
            label="سياسة الاسترجاع والضمان",
            why_it_matters="بناء ثقة العميل وحل أي اعتراضات",
            criticality=3,
            question=warranty_q,
            depends_on=["products_services_prices"],
            group_name="universal",
        ))

        # 7. Authority Limits & Tone
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

        # Field-Specific Topics:
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
                slug="authenticity_guarantee",
                label="ضمان النقاوة والفحص المخبري",
                why_it_matters="تأكيد جودة العسل وخلوه من التغذية السكرية",
                criticality=4,
                question="هل العسل مفحوص مخبريًا وما هو ضمانكم المعتمد للعملاء في حال التشكيك بالنقاوة؟",
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

        elif is_software:
            topics.append(TopicPlanItem(
                slug="target_clients",
                label="العملاء والقطاعات المستهدفة",
                why_it_matters="تحديد نوع المنشآت التي تخدمها الحلول البرمجية",
                criticality=4,
                question="من هم العملاء أو القطاعات المستهدفة بحلولكم البرمجية؟ (شركات، متاجر، مصانع...)",
                depends_on=["products_services_prices"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="software_licenses",
                label="أنواع التراخيص ونماذج الاشتراك",
                why_it_matters="شرح باقات الترخيص للعملاء (سنوي، شهري، ترخيص دائم)",
                criticality=4,
                question="ما هي نماذج الترخيص المتاحة لأنظمتكم؟ (اشتراك سنوي سحابي، ترخيص دائم...)",
                depends_on=["target_clients"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="support_sla_policy",
                label="سياسة الدعم الفني واتفاقيات الخدمة (SLA)",
                why_it_matters="طرق وقنوات المساعدة الفنية للعملاء بعد البيع",
                criticality=4,
                question="ما هي قنوات وأوقات الدعم الفني المتاحة للعملاء، وهل يشمل ذلك التحديثات المستمرة؟",
                depends_on=["software_licenses"],
                group_name="field_specific",
            ))
            topics.append(TopicPlanItem(
                slug="partnerships_certifications",
                label="الشهادات والشراكات والاعتمادات",
                why_it_matters="تعزيز موثوقية الشركة وحلولها التقنية",
                criticality=2,
                question="هل تمتلكون شهادات اعتماد تقنية أو شراكات مع مزودي خدمات سحابية معتمدين؟",
                depends_on=["identity"],
                group_name="field_specific",
            ))

        # Country-Specific Follow-ups (Yemen for physical goods):
        is_yemen = any(y in tags or y in country_text for y in ("yemen", "اليمن"))
        if is_yemen and not is_software:
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
    # Next-Question Selector (Deterministic Highest Criticality)
    # -----------------------------------------------------------------------

    def get_next_question_topic(self, tenant_id: UUID) -> InterviewTopic | None:
        """Determines the next best topic to ask based on dependencies and criticality."""
        all_topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()

        if not all_topics:
            return None

        status_map = {t.slug: t.status for t in all_topics}
        candidates = []

        for t in all_topics:
            if t.status != "unknown":
                continue

            deps_satisfied = True
            for d in (t.depends_on or []):
                dep_status = status_map.get(d, "unknown")
                if dep_status not in ("answered", "not_applicable", "skipped"):
                    deps_satisfied = False
                    break

            if deps_satisfied:
                candidates.append(t)

        if not candidates:
            return None

        # Sort: highest criticality first, then dependency depth
        candidates.sort(
            key=lambda item: (item.criticality, len(item.depends_on or [])),
            reverse=True,
        )
        return candidates[0]

    def get_next_question(self, tenant_id: UUID) -> str | None:
        """Emits the next single Arabic question."""
        best_topic = self.get_next_question_topic(tenant_id)
        if best_topic is None:
            return None

        state = self.get_or_create_state(tenant_id)
        state.current_topic_slug = best_topic.slug
        best_topic.status = "asked"
        self.db.add(state)
        self.db.add(best_topic)
        self.db.flush()

        return best_topic.question

    # -----------------------------------------------------------------------
    # Content-Driven Topic Coverage Evaluation (AI Model + Semantic Fallback)
    # -----------------------------------------------------------------------

    def evaluate_reply_coverage(
        self,
        tenant_id: UUID,
        content: str,
        open_topics: list[InterviewTopic],
        current_topic_slug: str | None = None,
        ai_provider: AIProvider | None = None,
    ) -> ReplyCoverageEvaluation:
        """
        Evaluates owner reply content against open topics via strict model call
        with deterministic semantic fallback.
        Merges coverage evaluation and fact extraction into a single call.
        Includes exponential backoff retry loop on AIRateLimitError.
        """
        content_clean = (content or "").strip()
        c_lower = content_clean.lower()

        # Check skip and not_applicable first, then negative rejection
        is_skip = bool(self.is_skip_or_na(content_clean) == "skip")
        is_na = bool(self.is_skip_or_na(content_clean) == "not_applicable")
        is_negative = not is_skip and bool(re.search(r"^\s*(?:لا(?!\s*(?:أعلم|اعلم|أعرف|اعرف|أدري|ادري))\b|لا\s*نوفر|غير\s*متاح|ما\s*في|ليس\s*لدينا|ما\s*عندنا|لا\s*يوجد)\b", content_clean))

        # Cap open topics to at most 10 (ensuring current topic is included first)
        ordered_topics = []
        if current_topic_slug:
            ordered_topics.extend([t for t in open_topics if t.slug == current_topic_slug])
            ordered_topics.extend([t for t in open_topics if t.slug != current_topic_slug])
        else:
            ordered_topics = list(open_topics)
        capped_open_topics = ordered_topics[:10]

        # 1. Attempt Live AI Provider evaluation if available and not a simple negative/skip
        if ai_provider is not None and not (is_negative or is_skip or is_na):
            max_retries = 3
            backoff_sec = 1.0
            for attempt in range(max_retries):
                try:
                    system_instruction = (
                        "You are the Adaptive Onboarding Topic Evaluation and Fact Extraction Engine.\n"
                        "Analyze the owner's message and perform TWO tasks simultaneously:\n"
                        "1. Determine coverage status for each open interview topic ('covered', 'partial', 'not_covered', 'skipped', 'not_applicable').\n"
                        "   - If the reply provides only partial information for a topic (e.g. mentions cities without prices/delivery times, or products without prices), mark status='partial', coverage=0.5, and populate missing_details.\n"
                        "   - If fully answered, mark status='covered', coverage=1.0.\n"
                        "   - Answering one topic does NOT cover another (e.g. stating honey types does NOT cover payment methods).\n"
                        "   - If the currently asked topic was NOT addressed, status MUST be 'not_covered'.\n"
                        "2. Extract atomic business facts into extracted_facts (topics like company.identity, products.catalog, etc.) with exact verbatim names.\n"
                    )
                    topics_payload = [
                        {"slug": t.slug, "label": t.label, "question": t.question}
                        for t in capped_open_topics
                    ]
                    user_prompt = (
                        f"Owner Message Content:\n\"\"\"{content_clean}\"\"\"\n\n"
                        f"Currently Asked Topic Slug: {current_topic_slug or 'none'}\n\n"
                        f"Open Topics (max 10):\n{json.dumps(topics_payload, ensure_ascii=False, indent=2)}"
                    )
                    res = ai_provider.generate_json(
                        user_prompt,
                        schema=ReplyCoverageEvaluation,
                        system_instruction=system_instruction,
                    )
                    if isinstance(res, dict) and "evaluations" in res:
                        parsed = ReplyCoverageEvaluation.model_validate(res)
                        if parsed.evaluations:
                            parsed.decided_by = "model"
                            for ev in parsed.evaluations:
                                if ev.status == "covered":
                                    ev.coverage = 1.0
                                elif ev.status == "partial":
                                    ev.coverage = 0.5
                                else:
                                    ev.coverage = 0.0
                            return parsed
                    break
                except AIRateLimitError as rle:
                    if attempt < max_retries - 1:
                        logger.warning("Rate limit hit in interview evaluation (attempt %s/%s), backing off %ss: %s", attempt + 1, max_retries, backoff_sec, rle)
                        time.sleep(backoff_sec)
                        backoff_sec *= 2.0
                    else:
                        logger.error("Rate limit exhausted after %s attempts in interview evaluation for tenant %s: %s", max_retries, tenant_id, rle)
                        raise
                except Exception as exc:
                    logger.warning("AI model coverage evaluation failed for tenant %s: %s; using semantic fallback", tenant_id, exc)
                    break

        # 2. Deterministic Semantic Fallback Evaluator
        evaluations: list[TopicCoverageItem] = []
        acknowledged_points: list[str] = []

        # Content detection triggers
        has_payment = bool(re.search(r"(?:تحويل\s*بنكي|دفع\s*عند\s*الاستلام|كاش|سداد|فيزا|مدى|فواتير|عقد\s*سنوي|شيك|طرق\s*الدفع)\b", c_lower))
        has_honey_types = bool(re.search(r"(?:سدر|دوعني|سمر|صال|مراعي|زهور|جبلي|عسل\s*\w+)", c_lower)) and "عسل" in c_lower
        has_target_clients = bool(re.search(r"(?:مؤسسات|شركات|قطاعات|جهات|أفراد|تجار|عملاء|مصانع|متاجر)\b", c_lower)) and any(w in c_lower for w in ("موجهة", "نستهدف", "عملاؤنا", "للمؤسسات", "للشركات", "للمتاجر"))
        has_software_licenses = bool(re.search(r"(?:تراخيص|ترخيص|اشتراك|سنوي|شهري|مدى\s*الحياة|سحابي|باقات)\b", c_lower)) and any(w in c_lower for w in ("ترخيص", "تراخيص", "اشتراك", "سنوية", "شهرية"))
        has_support = bool(re.search(r"(?:دعم\s*فني|صيانة|متابعة|مستمر|طوال\s*الأسبوع|خدمة\s*العملاء|sla)\b", c_lower))
        has_packaging = bool(re.search(r"(?:كيلو|نصف|ربع|جرام|عبوات|حجم|أحجام|علبة|علب)\b", c_lower))
        has_coverage = bool(re.search(r"(?:نخدم|نوصل|توصيل|التوصيل|فروعنا|تغطيتنا|نغطي|في\s*(?:صنعاء|عدن|الرياض|جدة|الخليج|المحافظات)|سحابيا|عالميا)\b", c_lower))
        has_branches = bool(re.search(r"(?:فروعنا|فرع\s*في|ساعات\s*العمل|دوامنا|نفتح\s*من|مقرنا|مقر\s*رئيسي)", c_lower))
        has_warranty = bool(re.search(r"(?:استرجاع|استبدال|ضمان|كفالة|استرداد|مشكلات\s*فنية)", c_lower))
        has_authenticity = bool(re.search(r"(?:مفحوص|مخبريا|فحص|نقي|أصلي|مضمون|نقاوة|مختبر)", c_lower))
        has_identity = bool(re.search(r"(?:اسمنا|اسم\s*(?:الشركة|المنشأة|المتجر)|نحن\s*شركة|شركة\s+\w+|منشأة\s+\w+|متجر\s+\w+)", c_lower))
        has_products = bool(re.search(r"(?:نبيع|نوفر|نقدم|منتجنا|منتجاتنا|أنظمتنا|حلولنا|برامجنا|خدماتنا|سعر|بسعر|باقاتنا)\b", c_lower))

        # Check for partial delivery/products detail (e.g. mentions cities without prices/delivery times)
        has_delivery_prices = bool(re.search(r"(?:ريال|رس|مجاني|مجانا|تكلفة|رسوم|شحن\s*بـ|\d+\s*ريال)", c_lower))
        has_product_prices = bool(re.search(r"(?:ريال|دولار|\$|ر\.س|\d+\s*(?:ريال|الف|ألف))", c_lower))

        trigger_map = {
            "ordering_payment": has_payment,
            "honey_types": has_honey_types,
            "target_clients": has_target_clients,
            "software_licenses": has_software_licenses,
            "support_sla_policy": has_support,
            "packaging_sizes": has_packaging,
            "delivery_coverage": has_coverage,
            "service_coverage": has_coverage,
            "delivery_zones_yemen": has_coverage and ("صنعاء" in c_lower or "عدن" in c_lower),
            "between_governorates_yemen": has_coverage and any(w in c_lower for w in ("محافظات", "بين المحافظات", "شحن")),
            "branches_hours": has_branches,
            "returns_warranty": has_warranty,
            "authenticity_guarantee": has_authenticity,
            "identity": has_identity,
            "products_services_prices": has_products,
        }

        for t in open_topics:
            status = "not_covered"
            coverage_val = 0.0
            extracted_val = None
            missing_val = None

            if current_topic_slug and t.slug == current_topic_slug:
                if is_skip:
                    status = "skipped"
                    coverage_val = 0.0
                elif is_na or is_negative:
                    status = "not_applicable"
                    coverage_val = 0.0
                elif trigger_map.get(t.slug) is True:
                    # Check partial conditions
                    if t.slug in ("delivery_coverage", "delivery_zones_yemen", "between_governorates_yemen") and not has_delivery_prices:
                        status = "partial"
                        coverage_val = 0.5
                        extracted_val = content_clean
                        missing_val = "تكلفة التوصيل ومواعيده التقريبية"
                    elif t.slug == "products_services_prices" and not has_product_prices:
                        status = "partial"
                        coverage_val = 0.5
                        extracted_val = content_clean
                        missing_val = "أسعار المنتجات المذكورة"
                    else:
                        status = "covered"
                        coverage_val = 1.0
                        extracted_val = content_clean
                else:
                    status = "not_covered"
                    coverage_val = 0.0
            else:
                if trigger_map.get(t.slug) is True:
                    status = "covered"
                    coverage_val = 1.0
                    extracted_val = content_clean

            if status in ("covered", "partial"):
                acknowledged_points.append(t.label)

            evaluations.append(TopicCoverageItem(
                slug=t.slug,
                status=status,
                coverage=coverage_val,
                extracted_details=extracted_val,
                missing_details=missing_val,
            ))

        ack_summary = "، ".join(dict.fromkeys(acknowledged_points)) if acknowledged_points else None
        return ReplyCoverageEvaluation(
            evaluations=evaluations,
            acknowledged_summary=ack_summary,
            decided_by="fallback",
        )

    def handle_branch_closure(self, tenant_id: UUID, closed_slug: str) -> None:
        """When an owner answers negatively (e.g. 'لا'), marks dependent topics as not_applicable."""
        all_topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()
        for t in all_topics:
            if t.depends_on and closed_slug in t.depends_on and t.status in ("unknown", "asked"):
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
        """Processes an incoming owner message during the adaptive interview."""
        state = self.get_or_create_state(tenant_id)
        content_clean = (content or "").strip()

        # 1. Progress Query ("وش باقي؟")
        trigger = self.detect_trigger(content_clean)
        if trigger == "progress":
            return self.get_progress_summary(tenant_id), True

        # 2. Start / Resume Commands
        if trigger in ("start", "resume"):
            return self.resume_interview(tenant_id), True

        # 3. Handle Stage 1: Classification Turn
        if state.stage.startswith("classification_"):
            reply = self.handle_classification_step(
                tenant_id, state, content_clean, message_id, ai_provider=ai_provider
            )
            return reply, True

        # 4. Handle Stage 3: Topic Interview Turn
        if state.stage == "interviewing":
            curr_slug = state.current_topic_slug

            # Fetch open topics
            open_topics = self.db.scalars(
                select(InterviewTopic).where(
                    InterviewTopic.tenant_id == tenant_id,
                    InterviewTopic.status.in_(["unknown", "asked", "partial"]),
                )
            ).all()

            if not open_topics and not curr_slug:
                state.stage = "completed"
                self.db.add(state)
                self.db.flush()
                return "🎉 تم استكمال جلسة التعارف بنجاح! موظفك الرقمي جاهز الآن لخدمة العملاء.", True

            # Evaluate content coverage across all open topics with backoff / delay notice on rate limit
            try:
                evaluation = self.evaluate_reply_coverage(
                    tenant_id=tenant_id,
                    content=content_clean,
                    open_topics=open_topics,
                    current_topic_slug=curr_slug,
                    ai_provider=ai_provider,
                )
            except AIRateLimitError:
                logger.warning("AIRateLimitError in interview turn for tenant %s, returning neutral delay notice", tenant_id)
                return "نواجه ضغطاً مؤقتاً في معالجة طلبك، يرجى المحاولة بعد لحظات.", True

            curr_eval = next((e for e in evaluation.evaluations if e.slug == curr_slug), None) if curr_slug else None
            curr_status = curr_eval.status if curr_eval else "not_covered"
            decided_by = getattr(evaluation, "decided_by", None) or "model"

            # Check negative answer ("لا") on current topic
            if curr_status == "not_applicable" and curr_slug:
                curr_topic = self.db.scalar(
                    select(InterviewTopic).where(
                        InterviewTopic.tenant_id == tenant_id,
                        InterviewTopic.slug == curr_slug,
                    )
                )
                if curr_topic:
                    curr_topic.status = "not_applicable"
                    curr_topic.coverage = 0.0
                    curr_topic.source_message_id = message_id
                    curr_topic.decided_by = decided_by
                    self.db.add(curr_topic)
                    self.db.flush()
                    self.handle_branch_closure(tenant_id, curr_slug)

                ack = "تم تسجيل ذلك كـ (لا ينطبق)."
                next_q = self.get_next_question(tenant_id)
                if next_q:
                    return f"{ack}\n\n{next_q}", True
                state.stage = "completed"
                self.db.add(state)
                self.db.flush()
                return f"{ack}\n\n🎉 تم استكمال جلسة التعارف بنجاح!", True

            # Check skip
            if curr_status == "skipped" and curr_slug:
                curr_topic = self.db.scalar(
                    select(InterviewTopic).where(
                        InterviewTopic.tenant_id == tenant_id,
                        InterviewTopic.slug == curr_slug,
                    )
                )
                if curr_topic:
                    curr_topic.status = "skipped"
                    curr_topic.coverage = 0.0
                    curr_topic.source_message_id = message_id
                    curr_topic.decided_by = decided_by
                    self.db.add(curr_topic)
                    self.db.flush()

                ack = "تم تسجيل تخطي هذا الموضوع."
                next_q = self.get_next_question(tenant_id)
                if next_q:
                    return f"{ack}\n\n{next_q}", True
                state.stage = "completed"
                self.db.add(state)
                self.db.flush()
                return f"{ack}\n\n🎉 تم استكمال جلسة التعارف بنجاح!", True

            # Check partial answer on current topic (Phase 3.1 / Addendum X2)
            if curr_status == "partial" and curr_slug:
                curr_topic = self.db.scalar(
                    select(InterviewTopic).where(
                        InterviewTopic.tenant_id == tenant_id,
                        InterviewTopic.slug == curr_slug,
                    )
                )
                if curr_topic:
                    curr_topic.status = "partial"
                    curr_topic.coverage = 0.5
                    curr_topic.source_message_id = message_id
                    curr_topic.decided_by = decided_by
                    self.db.add(curr_topic)
                    self._save_covered_topic_facts(tenant_id, curr_slug, content_clean, message_id)

                # Also mark other topics that were covered in this reply
                for e in evaluation.evaluations:
                    if e.slug != curr_slug and e.status == "covered":
                        ot = next((t for t in open_topics if t.slug == e.slug), None)
                        if ot:
                            ot.status = "answered"
                            ot.coverage = 1.0
                            ot.source_message_id = message_id
                            ot.decided_by = decided_by
                            self.db.add(ot)
                            self._save_covered_topic_facts(tenant_id, ot.slug, content_clean, message_id)
                self.db.flush()

                # Save unified extracted facts or fallback extract
                if getattr(evaluation, "extracted_facts", None):
                    self.fact_service.save_extracted_facts(
                        tenant_id=tenant_id,
                        extracted_facts=evaluation.extracted_facts,
                        auto_confirm_direct=True,
                        message_text=content_clean,
                    )
                else:
                    try:
                        ext_res = self.fact_service.extract_facts(
                            tenant_id=tenant_id,
                            message_text=content_clean,
                            provider=ai_provider,
                        )
                        if ext_res and ext_res.facts:
                            self.fact_service.save_extracted_facts(
                                tenant_id=tenant_id,
                                extracted_facts=ext_res.facts,
                                auto_confirm_direct=True,
                                message_text=content_clean,
                            )
                    except Exception as err:
                        logger.warning("Fact extraction in partial turn failed: %s", err)

                missing_part = curr_eval.missing_details if (curr_eval and curr_eval.missing_details) else None
                ack_prefix = f"✅ تم تسجيل ما ذكرته بخصوص **{curr_topic.label}**." if curr_topic else "✅ تم تسجيل إجابتك."
                if missing_part:
                    return f"{ack_prefix}\nولكن هل يمكنك توضيح: **{missing_part}**؟", True
                else:
                    return f"{ack_prefix}\nولكن لاستكمال التفاصيل بخصوص هذا الموضوع:\n{curr_topic.question if curr_topic else ''}", True

            # Check if currently asked topic was NOT covered by the reply
            if curr_status == "not_covered" and curr_slug:
                curr_topic = self.db.scalar(
                    select(InterviewTopic).where(
                        InterviewTopic.tenant_id == tenant_id,
                        InterviewTopic.slug == curr_slug,
                    )
                )
                if curr_topic:
                    answers_copy = dict(state.classification_answers or {})
                    topic_attempts = dict(answers_copy.get("topic_attempts", {}))
                    attempts = topic_attempts.get(curr_slug, 0) + 1
                    topic_attempts[curr_slug] = attempts
                    answers_copy["topic_attempts"] = topic_attempts
                    state.classification_answers = answers_copy
                    flag_modified(state, "classification_answers")

                    # Mark other topics that WERE covered in this reply
                    covered_other = [e for e in evaluation.evaluations if e.slug != curr_slug and e.status == "covered"]
                    for e in covered_other:
                        ot = next((t for t in open_topics if t.slug == e.slug), None)
                        if ot:
                            ot.status = "answered"
                            ot.coverage = 1.0
                            ot.source_message_id = message_id
                            ot.decided_by = decided_by
                            self.db.add(ot)
                            self._save_covered_topic_facts(tenant_id, ot.slug, content_clean, message_id)
                    self.db.flush()

                    # Save unified facts or extract
                    if getattr(evaluation, "extracted_facts", None):
                        self.fact_service.save_extracted_facts(
                            tenant_id=tenant_id,
                            extracted_facts=evaluation.extracted_facts,
                            auto_confirm_direct=True,
                        )
                    else:
                        try:
                            ext_res = self.fact_service.extract_facts(
                                tenant_id=tenant_id,
                                message_text=content_clean,
                                provider=ai_provider,
                            )
                            if ext_res and ext_res.facts:
                                self.fact_service.save_extracted_facts(
                                    tenant_id=tenant_id,
                                    extracted_facts=ext_res.facts,
                                    auto_confirm_direct=True,
                                )
                        except Exception as err:
                            logger.warning("Fact extraction in not_covered turn failed: %s", err)

                    ack_text = ""
                    if covered_other:
                        labels = [next((t.label for t in open_topics if t.slug == e.slug), e.slug) for e in covered_other]
                        ack_text = f"✅ تم توثيق ما ذكرته بخصوص: {', '.join(labels)}.\n\n"

                    if attempts < 2:
                        curr_topic.status = "asked"
                        curr_topic.decided_by = decided_by
                        curr_topic.source_message_id = message_id
                        self.db.add(curr_topic)
                        self.db.flush()
                        reask = f"ولكن بالنسبة لـ **{curr_topic.label}**:\n{curr_topic.question}"
                        return f"{ack_text}{reask}".strip(), True
                    else:
                        # Park topic after 2 attempts
                        curr_topic.status = "unknown"
                        curr_topic.decided_by = decided_by
                        curr_topic.source_message_id = message_id
                        self.db.add(curr_topic)
                        self.db.flush()
                        next_q = self.get_next_question(tenant_id)
                        if next_q:
                            return f"{ack_text}سننتقل للموضوع التالي وسنعود لهذا لاحقاً:\n\n{next_q}".strip(), True

            # If current topic was covered
            if curr_status == "covered" and curr_slug:
                curr_topic = self.db.scalar(
                    select(InterviewTopic).where(
                        InterviewTopic.tenant_id == tenant_id,
                        InterviewTopic.slug == curr_slug,
                    )
                )
                if curr_topic:
                    curr_topic.status = "answered"
                    curr_topic.coverage = 1.0
                    curr_topic.source_message_id = message_id
                    curr_topic.decided_by = decided_by
                    self.db.add(curr_topic)
                    self._save_covered_topic_facts(tenant_id, curr_slug, content_clean, message_id)

            # Mark all other topics that were covered or not applicable in this reply
            for e in evaluation.evaluations:
                if e.slug == curr_slug:
                    continue
                if e.status == "covered":
                    ot = next((t for t in open_topics if t.slug == e.slug), None)
                    if ot:
                        ot.status = "answered"
                        ot.coverage = 1.0
                        ot.source_message_id = message_id
                        ot.decided_by = decided_by
                        self.db.add(ot)
                        self._save_covered_topic_facts(tenant_id, ot.slug, content_clean, message_id)
                elif e.status == "partial":
                    ot = next((t for t in open_topics if t.slug == e.slug), None)
                    if ot:
                        ot.status = "partial"
                        ot.coverage = 0.5
                        ot.source_message_id = message_id
                        ot.decided_by = decided_by
                        self.db.add(ot)
                        self._save_covered_topic_facts(tenant_id, ot.slug, content_clean, message_id)
                elif e.status == "not_applicable":
                    ot = next((t for t in open_topics if t.slug == e.slug), None)
                    if ot:
                        ot.status = "not_applicable"
                        ot.coverage = 0.0
                        ot.source_message_id = message_id
                        ot.decided_by = decided_by
                        self.db.add(ot)
                        self.handle_branch_closure(tenant_id, e.slug)

            # Save unified facts or extract
            if getattr(evaluation, "extracted_facts", None):
                save_result = self.fact_service.save_extracted_facts(
                    tenant_id=tenant_id,
                    extracted_facts=evaluation.extracted_facts,
                    auto_confirm_direct=True,
                    message_text=content_clean,
                )
            else:
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

            # Build read-back acknowledgment
            saved_labels = [f.subject for f in saved_facts if hasattr(f, "subject")]
            if saved_labels:
                ack_lines = [f"✅ تم حفظ وتأكيد: {', '.join(saved_labels)}"]
            elif evaluation.acknowledged_summary:
                ack_lines = [f"✅ تم توثيق ما ذكرته بخصوص: {evaluation.acknowledged_summary}"]
            else:
                ack_lines = ["✅ تم توثيق إجابتك بنجاح."]

            # Select Next Question (covered topics will NEVER be asked again!)
            next_q = self.get_next_question(tenant_id)
            if next_q:
                ack_lines.append(f"\n{next_q}")
                return "\n".join(ack_lines), True

            # All topics covered! Complete interview
            state.stage = "completed"
            state.last_interaction_at = datetime.now(timezone.utc)
            self.db.add(state)
            self.db.flush()
            ack_lines.append("\n🎉 تم استكمال كافة مواضيع التعارف بنجاح! موظفك الرقمي جاهز لخدمة العملاء بكامل طاقته.")
            return "\n".join(ack_lines), True

        return "محادثة التعارف مكتملة. يمكنك السؤال عن أي تفصيل في أي وقت.", True

    def _save_covered_topic_facts(
        self,
        tenant_id: UUID,
        slug: str,
        content: str,
        message_id: UUID,
    ) -> None:
        """Stores structured confirmed facts for domain-specific topics."""
        c = content.strip()
        facts_to_save: list[ExtractedFactItem] = []

        if slug == "identity":
            # Extract verbatim company name
            clean_name = re.sub(r"^(?:اسمنا|اسم\s*(?:الشركة|المنشأة|المتجر)|الاسم\s*الرسمي)\s*[:—\-=]?\s*", "", c).strip()
            clean_name = re.sub(r"^(?:الرسمي|المعتمد)\s+", "", clean_name).strip()
            facts_to_save.append(
                ExtractedFactItem(
                    topic="company.identity",
                    subject="اسم المنشأة",
                    value={"name": clean_name or c},
                    visibility="public",
                    is_direct_unambiguous=True,
                )
            )

        elif slug == "target_clients":
            facts_to_save.append(
                ExtractedFactItem(
                    topic="company.target_clients",
                    subject="العملاء المستهدفون",
                    value={"target_clients": c},
                    visibility="public",
                    is_direct_unambiguous=True,
                )
            )

        elif slug == "software_licenses":
            facts_to_save.append(
                ExtractedFactItem(
                    topic="software.licenses",
                    subject="نماذج التراخيص",
                    value={"licenses": c},
                    visibility="public",
                    is_direct_unambiguous=True,
                )
            )

        elif slug == "support_sla_policy":
            facts_to_save.append(
                ExtractedFactItem(
                    topic="operations.support",
                    subject="سياسة الدعم الفني",
                    value={"support_policy": c},
                    visibility="public",
                    is_direct_unambiguous=True,
                )
            )

        elif slug == "honey_types":
            facts_to_save.append(
                ExtractedFactItem(
                    topic="honey.types",
                    subject="أنواع العسل المتوفرة",
                    value={"types": c},
                    visibility="public",
                    is_direct_unambiguous=True,
                )
            )

        elif slug in ("service_coverage", "delivery_coverage"):
            facts_to_save.append(
                ExtractedFactItem(
                    topic="operations.coverage",
                    subject="نطاق التغطية والخدمة",
                    value={"coverage": c},
                    visibility="public",
                    is_direct_unambiguous=True,
                )
            )

        if facts_to_save:
            self.fact_service.save_extracted_facts(
                tenant_id=tenant_id,
                extracted_facts=facts_to_save,
                auto_confirm_direct=True,
                message_text=c,
            )

    # -----------------------------------------------------------------------
    # Progress Summary ("وش باقي؟")
    # -----------------------------------------------------------------------

    def get_progress_summary(self, tenant_id: UUID) -> str:
        """Returns progress report."""
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

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Go-Live Gate Evaluation
    # -----------------------------------------------------------------------

    def check_go_live_gate(self, tenant_id: UUID, threshold: float = 80.0) -> tuple[bool, float, list[str]]:
        """Evaluates whether the tenant's critical interview coverage meets go-live threshold."""
        topics = self.db.scalars(
            select(InterviewTopic).where(InterviewTopic.tenant_id == tenant_id)
        ).all()

        if not topics:
            return False, 0.0, ["لم يتم بدء المقابلة التكيفية"]

        critical_topics = [t for t in topics if t.criticality >= 4]
        if not critical_topics:
            return True, 100.0, []

        total_critical = len(critical_topics)
        answered_critical = sum(1 for t in critical_topics if t.status in ("answered", "not_applicable"))
        critical_pct = (answered_critical / total_critical) * 100.0

        missing = [t.label for t in critical_topics if t.status not in ("answered", "not_applicable")]
        is_ready = bool(critical_pct >= threshold)

        return is_ready, critical_pct, missing

    def notify_owner_of_unmet_gate(
        self,
        tenant_id: UUID,
        critical_pct: float,
        missing_critical: list[str],
        customer_message: str | None = None,
    ) -> None:
        """Sends an urgent reminder to the tenant owner when customer messages are held by the gate."""
        missing_str = "\n".join(f"- {m}" for m in missing_critical[:4])
        cust_clause = f"\n📩 رسالة العميل المعلقة:\n\"{customer_message}\"" if customer_message else ""
        notification_text = (
            f"⚠️ **تنبيه الموظف الرقمي:**\n"
            f"وصلت رسالة من عميل ولكن تم الرد عليها برسالة انتظار مؤقتة؛ نظراً لعدم اكتمال جلسة التعارف الأساسية.\n"
            f"• نسبة تغطية المواضيع الحرجة: {critical_pct:.0f}%\n"
            f"• المواضيع الحرجة المتبقية المطلوبة:\n{missing_str}\n"
            f"{cust_clause}\n\n"
            f"يرجى إرسال 'كمّل التعارف' للإجابة وتفعيل الردود التلقائية الكاملة لعملائك."
        )

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
    # Cleaning & Helper Methods
    # -----------------------------------------------------------------------

    @staticmethod
    def _clean_name_answer(content: str) -> str:
        c = re.sub(r"^(?:أنا|اسمي|الاسم|معكم|حياك\s*الله\s*أنا|أنا\s*المهندس|المهندس|الأخ|أخوك)\s+", "", content).strip()
        m = re.match(r"([^،,.\n]+)", c)
        return m.group(1).strip() if m else c

    @staticmethod
    def _clean_role_answer(content: str) -> str:
        return content.split("،")[0].split(",")[0].strip()

    @staticmethod
    def _clean_entity_type_answer(content: str) -> str:
        c = content.lower()
        if "شركة" in c:
            return "شركة"
        if "إلكتروني" in c or "اونلاين" in c or "أونلاين" in c:
            return "متجر إلكتروني"
        if "محل" in c or "متجر" in c or "معرض" in c:
            return "متجر فعلي"
        if "خدمات" in c or "مزود" in c:
            return "مزود خدمات"
        return content.strip()

    @staticmethod
    def _clean_country_field_answer(content: str) -> tuple[str, str]:
        c = content.strip()
        country = "اليمن"
        if any(w in c.lower() for w in ("السعودية", "saudi", "ksa", "الرياض", "جدة")):
            country = "المملكة العربية السعودية"
        elif any(w in c.lower() for w in ("الإمارات", "دبي", "أبوظبي", "uae")):
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
    def _derive_profile_tags(answers: dict[str, Any]) -> tuple[list[str], list[str]]:
        """
        Derives profile tags, separating stated tags from inferred tags.
        Only stated tags are used for topic planning.
        """
        stated = set()
        inferred = set()
        c = answers.get("country", "")
        f = answers.get("field_of_activity", "")
        e = answers.get("entity_type", "")
        combined = f"{c} {f} {e}".lower()

        # Stated Country
        if "اليمن" in combined or "yemen" in combined:
            stated.add("Yemen")
        if "السعودية" in combined or "saudi" in combined:
            stated.add("Saudi Arabia")

        # Stated Entity Type
        if any(w in combined for w in ("متجر", "محل", "shop", "store")):
            stated.add("shop")
        if any(w in combined for w in ("شركة", "company")):
            stated.add("company")

        # Stated Domain
        if any(w in combined for w in ("عسل", "honey", "مناحل", "نحل")):
            stated.add("honey")
            stated.add("natural_products")
        if any(w in combined for w in ("برمج", "software", "أنظمة", "تقني", "شبكات")):
            stated.add("software")
            stated.add("development")
            stated.add("it")
        if any(w in combined for w in ("مطعم", "restaurant", "أغذية", "وجبات")):
            stated.add("restaurant")
            stated.add("food")

        # Inferred by association (only if NOT stated)
        if "honey" in stated and not any(w in combined for w in ("توصيل", "شحن")):
            inferred.add("delivery")
        if "shop" in stated and "تجزئة" not in combined:
            inferred.add("retail")
        if "software" in stated and "شركات" not in combined:
            inferred.add("b2b")

        return sorted(list(stated)) or ["general_business"], sorted(list(inferred))

    def _persist_profile_facts(self, tenant_id: UUID, answers: dict[str, Any]) -> None:
        """Stores Stage 1 profile answers into FactService ledger with topic 'profile.*'."""
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
