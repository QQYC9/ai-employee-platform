from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import (
    Agent,
    BusinessBrain,
    CapabilityVersion,
    Channel,
    Fact,
    Integration,
    Permission,
    Tool,
)
from packages.models.tenant import Tenant
from packages.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class CoreIdentity:
    """Layer A: Core Identity of the AI Digital Employee."""
    name: str
    company_name: str
    role_title: str
    is_ai: bool = True
    nature_description: str = "موظف رقمي ذكي يعمل بتقنيات الذكاء الاصطناعي (AI Digital Employee)"
    autonomy_limits: str = (
        "يعمل وفق سياسات المنصة وحدود الصلاحيات الممنوحة. "
        "لا يملك صلاحية اتخاذ قرارات مالية مباشرة أو تعديلات جذرية في النظام دون موافقة الإدارة البشرية."
    )
    transparency_rule: str = (
        "عند سؤاله إن كان بشرياً أم ذكاء اصطناعياً، يجيب بصدق ووضوح بأنه موظف رقمي يعمل بالذكاء الاصطناعي."
    )


@dataclass
class GeneralCapabilities:
    """Layer B: General capabilities the platform supports overall."""
    skills: list[str] = field(default_factory=lambda: [
        "التواصل وخدمة العملاء: الرد على الاستفسارات، تقديم شروحات المنتجات، ومتابعة المحادثات عبر القنوات.",
        "التسويق الاستشاري وإعداد المحتوى: صياغة النصوص الترويجية، اقتراح الأفكار التسويقية، ومواءمة العروض مع احتياج العميل.",
        "دعم المبيعات وتأهيل العملاء: استكشاف متطلبات العميل، مطابقة الحلول المناسبة، وتسجيل بيانات واهتمامات المهتمين.",
        "تنظيم المعلومات وتحليل البيانات: استرجاع تفاصيل المنتجات والأسعار والسياسات، واستعراض ملخصات النشاط.",
        "إعداد التقارير والمستندات: تلخيص المحادثات، إعداد التقارير المهنية، وصياغة مقترحات الأعمال.",
        "دعم العمليات الإدارية: إدارة وتتبع المهام وفق توجيهات المالك وصلاحيات النظام.",
    ])
    scope_clarification: str = (
        "القدرات العامة تمثل إمكانات النظام، وتفعيلها العملي يرتبط بالأدوات والتكاملات والصلاحيات المتاحة في البيئة الحالية."
    )


@dataclass
class ActivatedCapabilities:
    """Layer C: Actual active capabilities derived from verified system sources."""
    active_channels: list[str] = field(default_factory=list)
    directly_executable: list[str] = field(default_factory=list)
    planning_and_content: list[str] = field(default_factory=list)
    requires_setup_or_approval: list[str] = field(default_factory=list)
    unsupported_currently: list[str] = field(default_factory=list)
    raw_tools: list[str] = field(default_factory=list)


@dataclass
class EnterpriseContext:
    """Layer D: Enterprise context scoped strictly to current tenant."""
    tenant_id: UUID
    company_name: str
    industry: str | None = None
    target_audience: str | None = None
    products_and_services: list[str] = field(default_factory=list)
    confirmed_facts: list[str] = field(default_factory=list)
    value_proposition: str = ""


@dataclass
class DigitalEmployeeProfile:
    """Full 4-layer profile for a Digital Employee."""
    tenant_id: UUID
    agent_id: UUID | None
    core: CoreIdentity
    general: GeneralCapabilities
    activated: ActivatedCapabilities
    enterprise: EnterpriseContext


class AgentIdentityService:
    """
    Shared, multi-tenant service for Digital Employee identity awareness,
    capability discovery, consultative self-marketing, and dialogue grounding.
    """

    CHANNEL_TYPE_LABELS = {
        "telegram": "تيليجرام (محادثات فورية)",
        "whatsapp": "واتساب للأعمال",
        "email": "البريد الإلكتروني",
        "webchat": "المحادثة المباشرة على الموقع الإلكتروني",
        "api": "واجهة برمجة التطبيقات (API)",
        "webhook": "تكاملات Webhook المؤتمتة",
        "slack": "سلاك (Slack)",
        "sms": "الرسائل النصية القصيرة (SMS)",
    }

    TOOL_CAPABILITY_MAP = {
        "customer_search": "البحث في سجلات العملاء واسترجاع ملفاتهم",
        "customer_get": "استعراض تفاصيل ملف العميل وتفضيلاته",
        "customer_create_or_update": "تسجيل عميل جديد أو تحديث بيانات العميل",
        "task_create": "إنشاء مهام عمل جديدة وتعيين أولوياتها",
        "task_query": "الاستعلام عن المهام ومتابعة حالة تنفيذها",
        "document_generator": "توليد المستندات والتقارير التنفيذية",
        "generate_document": "توليد المستندات والتقارير التنفيذية",
        "business_summary": "استعراض ملخص المنشأة والنشاط التجاري",
        "product_list": "استعراض قائمة المنتجات والخدمات المعتمدة",
        "product_add_or_update": "إضافة أو تعديل منتج في النظام",
        "conversation_search": "البحث في أرشيف المحادثات السابقة",
        "conversation_summarize": "تلخيص محادثة قائمة واستخراج النقاط المهمة",
        "conversation_summarize_all": "إعداد تقرير مجمع لعدة محادثات",
        "conversation_escalation_status": "متابعة حالة تصعيد المحادثة إلى الإدارة",
        "http_request": "التواصل مع خدمات خارجية عبر بروتوكول HTTP",
    }

    def __init__(self, db: Session, tool_registry: ToolRegistry | None = None):
        self.db = db
        self.tool_registry = tool_registry
        self._profile_cache: dict[tuple[UUID, UUID | None], DigitalEmployeeProfile] = {}

    def clear_cache(self) -> None:
        """Clears local profile cache for tests or after updates."""
        self._profile_cache.clear()

    def get_profile(
        self,
        tenant_id: UUID,
        agent_id: UUID | None = None,
        refresh: bool = False,
    ) -> DigitalEmployeeProfile:
        """
        Dynamically extracts and constructs the 4-layer profile for a Digital Employee
        scoped strictly to the specified tenant.
        Uses scoped memoization within the service instance to prevent redundant DB queries.
        """
        cache_key = (tenant_id, agent_id)
        if not refresh and cache_key in self._profile_cache:
            return self._profile_cache[cache_key]

        tenant = self.db.scalar(select(Tenant).where(Tenant.id == tenant_id))

        # 1. Resolve Agent
        agent = None
        if agent_id is not None:
            agent = self.db.scalar(
                select(Agent).where(
                    Agent.id == agent_id,
                    Agent.tenant_id == tenant_id,
                    Agent.status != "deleted",
                )
            )
        else:
            agent = self.db.scalar(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.status != "deleted",
                ).order_by(Agent.agent_type == "main", Agent.created_at)
            )

        # 2. Resolve Company Name & Confirmed Facts
        confirmed_company_name = None
        confirmed_facts_list: list[str] = []
        product_names_list: list[str] = []

        try:
            from packages.services.fact_service import FactService
            fact_svc = FactService(self.db)
            db_facts = fact_svc.get_relevant_facts(tenant_id=tenant_id, limit=30)
            for f in db_facts:
                if f.topic in ("company.identity", "company.name") or f.subject in (
                    "اسم الشركة", "الاسم التجاري", "اسم المنشأة", "اسم المتجر", "هوية المنشأة"
                ):
                    if isinstance(f.value, dict):
                        confirmed_company_name = f.value.get("name") or f.value.get("identity")
                    elif isinstance(f.value, str):
                        confirmed_company_name = f.value.strip('"')

                if f.topic.startswith("product.") or f.topic == "products":
                    product_names_list.append(f.subject.strip())
                elif not f.topic.endswith(".benchmarks") and not f.topic.endswith(".roadmap"):
                    confirmed_facts_list.append(f"{f.subject}: {f.topic}")
        except Exception as exc:
            logger.debug("AgentIdentityService: FactService query skipped: %s", exc)

        biz_brain = self.db.scalar(select(BusinessBrain).where(BusinessBrain.tenant_id == tenant_id))
        biz_identity = (biz_brain.identity if biz_brain else {}) or {}

        effective_company_name = (
            confirmed_company_name
            or (tenant.name if tenant else None)
            or biz_identity.get("name")
            or "منشأتنا"
        )

        # 3. Resolve Employee Name
        emp_name = (
            (getattr(tenant, "employee_name", None) or "").strip()
            or (agent.name if agent else "").strip()
            or "الموظف الرقمي الذكي"
        )

        core = CoreIdentity(
            name=emp_name,
            company_name=effective_company_name,
            role_title=f"الموظف الرقمي وممثل خدمة العملاء والعمليات لمنشأة '{effective_company_name}'",
            is_ai=True,
        )

        general = GeneralCapabilities()

        # 4. Resolve Active Channels
        active_channels = []
        channels = self.db.scalars(
            select(Channel).where(
                Channel.tenant_id == tenant_id,
                Channel.status == "active",
            )
        ).all()
        for ch in channels:
            ctype = (ch.channel_type or "").strip().lower()
            label = self.CHANNEL_TYPE_LABELS.get(ctype, ctype)
            if label not in active_channels:
                active_channels.append(label)

        # 5. Resolve Tools, Permissions & Execution Readiness
        from packages.services.permission_service import PermissionService
        perm_svc = PermissionService(self.db)
        tenant_perms = perm_svc.list_permissions(tenant_id, agent_id=agent.id if agent else None)
        has_custom_permissions = len(tenant_perms) > 0

        # Active integrations for this tenant
        active_integrations = self.db.scalars(
            select(Integration).where(
                Integration.status == "active",
                or_(Integration.tenant_id.is_(None), Integration.tenant_id == tenant_id),
            )
        ).all()
        active_integration_providers = {i.provider.strip().lower() for i in active_integrations if i.provider}

        registered_tool_slugs: set[str] = set()
        contracts_by_slug: dict[str, Any] = {}
        if self.tool_registry is not None:
            for contract in self.tool_registry.list_contracts():
                s = contract.slug.strip().lower()
                registered_tool_slugs.add(s)
                contracts_by_slug[s] = contract

        # Also query DB tools for this tenant
        db_tools = self.db.scalars(
            select(Tool).where(
                Tool.is_active.is_(True),
                or_(Tool.tenant_id.is_(None), Tool.tenant_id == tenant_id),
            )
        ).all()
        for t in db_tools:
            registered_tool_slugs.add(t.slug.strip().lower())

        # Query dynamic capabilities
        cap_versions = self.db.scalars(
            select(CapabilityVersion).where(
                CapabilityVersion.tenant_id == tenant_id,
                CapabilityVersion.status == "active",
            )
        ).all()
        for cv in cap_versions:
            registered_tool_slugs.add(cv.slug.strip().lower())

        directly_executable = []
        requires_setup_or_approval = [
            "إطلاق الحملات التسويقية الجماعية المباشرة (يتطلب موافقة المالك)",
            "إجراء المعاملات المالية المباشرة وتعديل الفواتير (يتطلب صلاحية وموافقة الإدارة)",
            "الربط مع بوابات دفع أو أنظمة خارجية جديدة (يتطلب تكامل مفاتيح API)",
        ]

        for slug in sorted(registered_tool_slugs):
            if slug not in self.TOOL_CAPABILITY_MAP:
                continue
            desc = self.TOOL_CAPABILITY_MAP[slug]
            contract = contracts_by_slug.get(slug)
            req_perms = contract.required_permissions if contract else []

            # 1. Permission check: If tenant has defined permissions, verify all required are allowed
            if has_custom_permissions and req_perms:
                all_allowed = True
                for act, res in req_perms:
                    if not perm_svc.is_allowed(tenant_id, action=act, resource=res, agent_id=agent.id if agent else None):
                        all_allowed = False
                        break
                if not all_allowed:
                    # Tool is registered but not authorized for this tenant
                    continue

            # 2. Integration / External execution readiness check
            if slug == "http_request":
                has_http = any(
                    p in active_integration_providers for p in ("http", "api", "rest", "webhook", "custom_api")
                )
                if not has_http:
                    requires_setup_or_approval.append(f"{desc} (يتطلب ربط وتفعيل تكامل API خارجي)")
                    continue

            # 3. Sensitive operations requiring explicit human approval
            if slug in ("product_add_or_update",):
                requires_setup_or_approval.append(f"{desc} (يتطلب موافقة الإدارة)")
                continue

            if desc not in directly_executable:
                directly_executable.append(desc)

        if not directly_executable:
            # Fallback for standard baseline tools when registry empty
            directly_executable.append("التواصل وخدمة العملاء والإجابة عن الاستفسارات المعتمدة")

        planning_and_content = [
            "المساعدة في صياغة الخطط التسويقية واقتراح الأفكار الترويجية",
            "صياغة المراسلات المهنية وعروض الأسعار الاستشارية",
            "تحليل وتأهيل احتياجات العملاء ومواءمتها مع الحلول المعتمدة",
            "تلخيص وتنسيق المعلومات والبيانات المتاحة",
        ]

        unsupported_currently = [
            "إجراء مكالمات هاتفية صوتية مباشرة (غير مدعوم حالياً)",
            "تصميم وتوليد الصور أو الرسوميات (غير مدعوم حالياً)",
            "حجز المواعيد عبر تقويم خارجي (غير مفعّل لعدم توفر أداة التقويم حالياً)",
            "منح فترات تجريبية مجانية غير معتمدة في سياسات المنشأة",
        ]

        activated = ActivatedCapabilities(
            active_channels=active_channels,
            directly_executable=directly_executable,
            planning_and_content=planning_and_content,
            requires_setup_or_approval=requires_setup_or_approval,
            unsupported_currently=unsupported_currently,
            raw_tools=list(registered_tool_slugs),
        )

        # 6. Enterprise Context
        industry = biz_identity.get("industry")
        target_audience = (biz_brain.customers.get("target_audience") if biz_brain and biz_brain.customers else None)
        products_combined = list(dict.fromkeys(product_names_list))
        if not products_combined and biz_brain and biz_brain.products:
            products_combined = list(biz_brain.products.keys())

        value_prop = (
            f"تقديم دعم رقمي متكامل على مدار الساعة لخدمة عملاء '{effective_company_name}'، "
            "والإجابة الدقيقة عن المنتجات والخدمات بالحقائق المؤكدة، وتأهيل العملاء المحتملين، "
            "وتنظيم المهام والمستندات، مما يخفف العبء الإداري ويرفع كفاءة الأعمال."
        )

        enterprise = EnterpriseContext(
            tenant_id=tenant_id,
            company_name=effective_company_name,
            industry=industry,
            target_audience=target_audience,
            products_and_services=products_combined,
            confirmed_facts=confirmed_facts_list[:8],
            value_proposition=value_prop,
        )

        profile = DigitalEmployeeProfile(
            tenant_id=tenant_id,
            agent_id=agent.id if agent else None,
            core=core,
            general=general,
            activated=activated,
            enterprise=enterprise,
        )
        self._profile_cache[cache_key] = profile
        return profile

    @classmethod
    def detect_identity_or_capability_intent(cls, message_content: str | None) -> dict[str, Any] | None:
        """
        Detects if the customer's query is about the agent's identity,
        capabilities, business value, marketing skills, hiring, or unconfigured features.
        """
        if not message_content:
            return None
        text = message_content.strip().lower()

        # 1. Identity (Human vs AI, who are you?)
        identity_pats = [
            r"هل\s*أنت\s*(?:بشري|إنسان|آدمي|شخص\s*حقيقي|ذكاء\s*اصطناعي|روبوت|بوت|آلة)",
            r"أنت\s*(?:بشري|إنسان|آدمي|شخص\s*حقيقي)\s*(?:ولا|أم|أو)\s*(?:ذكاء|روبوت|بوت)",
            r"أنت\s*(?:إنسان|آدمي|شخص\s*حقيقي|ذكاء\s*اصطناعي|بوت|روبوت)",
            r"من\s*أنت(?:م)?\b",
            r"عرف(?:ني)?\s*بـ?نفسك",
            r"ايش\s*أنت|شو\s*أنت|ما\s*أنت\b",
            r"\b(are\s*you\s*human|are\s*you\s*ai|who\s*are\s*you)\b",
        ]
        for pat in identity_pats:
            if re.search(pat, text, re.IGNORECASE):
                return {"intent": "identity", "pattern": pat}

        # 2. Unconfigured / Unsupported Capabilities (Check before general capability/marketing)
        unconfigured_pats = [
            r"(?:مكالم[اإ]ت(?:\s*هاتفي[ةه])?|اتصال(?:\s*هاتفي)?|تتصل|مكالمة|مكالمات)",
            r"(?:تصميم\s*صور|توليد\s*صور|رسم|تصاميم|فيديو)",
            r"(?:حجز\s*موعد|ربط\s*تقويم|تقويم\s*خارجي)",
        ]
        for pat in unconfigured_pats:
            if re.search(pat, text, re.IGNORECASE):
                return {"intent": "unconfigured", "pattern": pat}

        # 3. Hiring / Employing a Digital Employee
        hire_pats = [
            r"(?:توظيف|أوظف|نوظف|أحصل\s*على|نحصل\s*على)\s*(?:موظف\s*رقمي|موظف\s*ذكاء|موظف\s*مثلك|بوت\s*مثلك)",
            r"كيف\s*(?:أحصل|نوظف|نحصل)\s*على\s*موظف\s*(?:رقمي|ذكاء|مثلك)",
            r"\b(hire\s*an\s*ai|employ\s*an\s*ai|get\s*a\s*digital\s*employee)\b",
        ]
        for pat in hire_pats:
            if re.search(pat, text, re.IGNORECASE):
                return {"intent": "hire_agent", "pattern": pat}

        # 4. Marketing & Sales Capabilities
        marketing_pats = [
            r"(?:تسويق|خطة\s*تسويق|خطة\s*تسويقية|حمل[اإ]ت\s*تسويقي|حملة\s*إعلاني|ترويج)",
            r"(?:تأهيل\s*العملاء|دعم\s*المبيعات|محتوى\s*تسويقي|محتوى\s*ترويجي)",
        ]
        for pat in marketing_pats:
            if re.search(pat, text, re.IGNORECASE):
                return {"intent": "marketing", "pattern": pat}

        # 5. Business Value (How do you help our company?)
        business_value_pats = [
            r"(?:كيف\s*(?:ستفيد|تفيد|تساعد|تنفع|تخدم))",
            r"(?:ما\s*(?:هي\s*)?(?:الفائد[ةه]|القيم[ةه]|الجدوى|الميز[ةه]))",
            r"(?:ليش\s*(?:نوظفك|نستخدمك|نعتمد\s*عليك))",
            r"\b(how\s*can\s*you\s*help|how\s*do\s*you\s*benefit)\s*(our\s*company|us)\b",
        ]
        for pat in business_value_pats:
            if re.search(pat, text, re.IGNORECASE):
                return {"intent": "business_value", "pattern": pat}

        # 6. General / Actual Capabilities (What can you do?)
        capabilities_pats = [
            r"ماذا\s*(?:تستطيع|يمكنك|تقدر)\s*(?:أن\s*تفعل|عمله|تسوي|تقديمه)",
            r"ايش\s*(?:تقدر\s*تسوي|مهاراتك|خدماتك|إمكانياتك|قدراتك|بتسوي)",
            r"ما\s*(?:هي\s*)?(?:مهاراتك|قدراتك|إمكانياتك|خدماتك|وظيفتك|طبيعة\s*عملك|دورك)\b",
            r"(?:ايش|شو|ما)\s*(?:شغلتك|وظيفتك|عملك|دورك)\b",
            r"ماذا\s*تعرف|ايش\s*تعرف|شو\s*تعرف\b",
            r"\b(what\s*can\s*you\s*do|what\s*are\s*your\s*capabilities|what\s*are\s*your\s*skills|what\s*is\s*your\s*role|what\s*is\s*your\s*job)\b",
        ]
        for pat in capabilities_pats:
            if re.search(pat, text, re.IGNORECASE):
                return {"intent": "capabilities", "pattern": pat}

        return None

    def format_prompt_section(
        self,
        profile: DigitalEmployeeProfile,
        customer_query: str | None = None,
    ) -> str:
        """
        Formats a compact, high-signal prompt section providing verified identity
        and capability boundaries to the conversational agent.
        """
        lines = [
            "### DIGITAL EMPLOYEE IDENTITY & CAPABILITIES (Verified Ground Truth)",
            f"- الهوية والاسم: أنت {profile.core.name}، {profile.core.role_title}.",
            f"- الطبيعة الذكية: {profile.core.nature_description}.",
            f"- الصدق والشفافية: {profile.core.transparency_rule}",
            f"- حدود الاستقلالية: {profile.core.autonomy_limits}",
            f"- القنوات المفعّلة للمنشأة: {', '.join(profile.activated.active_channels) if profile.activated.active_channels else 'القناة الحالية'}.",
            f"- القدرات المتاحة للتنفيذ المباشر: {'; '.join(profile.activated.directly_executable)}.",
            f"- المساعدة الاستشارية والتخطيط: {'; '.join(profile.activated.planning_and_content)}.",
            f"- ما يتطلب إعداداً أو موافقة: {'; '.join(profile.activated.requires_setup_or_approval)}.",
            f"- غير مدعوم حالياً: {'; '.join(profile.activated.unsupported_currently)}.",
            f"- القيمة العملية للمنشأة: {profile.enterprise.value_proposition}",
        ]
        return "\n".join(lines)

    def get_corpus_text(self, profile: DigitalEmployeeProfile) -> str:
        """
        Returns a text string containing all verified identity terms, active tools,
        channels, and skills to be included in Guardrail's verified corpus_chunks.
        """
        tokens = [
            profile.core.name.lower(),
            profile.core.company_name.lower(),
            "موظف رقمي",
            "ذكاء اصطناعي",
            "خدمة العملاء",
            "استفسارات",
            "محادثات",
            "المهام",
            "إدارة المهام",
            "إنشاء المهام",
            "متابعة المهام",
            "العملاء",
            "بيانات العملاء",
            "المستندات",
            "التقارير",
            "إعداد التقارير",
            "التسويق",
            "خطط تسويقية",
            "محتوى تسويقي",
            "تأهيل العملاء",
            "دعم المبيعات",
        ]
        tokens.extend(ch.lower() for ch in profile.activated.active_channels)
        tokens.extend(t.lower() for t in profile.activated.directly_executable)
        tokens.extend(p.lower() for p in profile.activated.planning_and_content)
        tokens.extend(prod.lower() for prod in profile.enterprise.products_and_services)
        return " ".join(tokens)

    def synthesize_identity_reply(
        self,
        profile: DigitalEmployeeProfile,
        customer_query: str,
        continuity: dict[str, Any] | None = None,
    ) -> str:
        """
        Synthesizes a tailored, consultative Arabic response answering identity,
        capability, business value, or marketing questions based strictly on verified facts.
        """
        intent_info = self.detect_identity_or_capability_intent(customer_query) or {"intent": "capabilities"}
        intent = intent_info.get("intent")

        is_new = (continuity or {}).get("is_new_conversation", True)
        has_prior_greeting = (continuity or {}).get("has_prior_greeting", False)
        prefix_greeting = "مرحبًا بك! " if (is_new and not has_prior_greeting) else ""

        emp_name = profile.core.name
        company = profile.core.company_name

        if intent == "identity":
            return (
                f"{prefix_greeting}أنا {emp_name}، موظف رقمي أعمل بتقنيات الذكاء الاصطناعي لتمثيل منشأة {company}. "
                "أساعد عملاءنا في الإجابة الدقيقة عن المنتجات والخدمات المعتمدة، ومتابعة الاستفسارات، "
                "ودعم العمليات باحترافية وسرعة على مدار الساعة. كيف يمكنني خدمتك اليوم؟"
            )

        if intent == "business_value":
            prod_summary = f" مثل ({', '.join(profile.enterprise.products_and_services[:3])})" if profile.enterprise.products_and_services else ""
            return (
                f"{prefix_greeting}أقدم لمنشأة {company} قيمة مهنية متعددة الجوانب:\n"
                f"1. التواجد المستمر والرد الفوري على العملاء عبر القنوات المعتمدة بالمعلومات الموثقة{prod_summary}.\n"
                "2. تأهيل العملاء المهتمين وتحديد احتياجاتهم بدقة لتسهيل إتمام عمليات البيع.\n"
                "3. تنظيم المهام واستخراج الملخصات والتقارير التنفيذية مما يوفر وقت الفريق البشري.\n"
                "4. العمل ضمن حدود الصلاحيات المعتمدة مع تحويل القرارات الحساسة إلى الإدارة لاتخاذ القرار المناسب.\n"
                "هل ترغب في معرفة كيفية تطبيق هذه المزايا على احتياج محدد لديك؟"
            )

        if intent == "marketing":
            return (
                f"{prefix_greeting}في الجانب التسويقي، أستطيع المساعدة الفورية في:\n"
                "1. صياغة الخطط والأفكار التسويقية المناسبة لنشاطكم وجمهوركم المستهدف.\n"
                "2. إعداد النصوص الترويجية ومحتوى الرسائل الإعلانية المقنعة.\n"
                "3. تأهيل العملاء المحتملين ومواءمة العروض مع متطلبات كل عميل.\n"
                "أما بالنسبة لإطلاق الحملات الجماعية أو الترويجية المؤتمتة، فيتم تنفيذها عبر أدوات المنصة بتنسيق وموافقة الإدارة المسبقة. "
                "ما هو الهدف التسويقي الذي ترغب بالتركيز عليه حالياً؟"
            )

        if intent == "unconfigured":
            # Phone calls / image generation / external booking
            q_lower = customer_query.lower()
            unsupported_item = "هذه الخدمة"
            if "اتصال" in q_lower or "مكالم" in q_lower or "هاتف" in q_lower:
                unsupported_item = "إجراء المكالمات الهاتفية الصوتية المباشرة"
            elif "صور" in q_lower or "تصميم" in q_lower or "رسم" in q_lower:
                unsupported_item = "تصميم وتوليد الصور أو الرسوميات"
            elif "موعد" in q_lower or "تقويم" in q_lower:
                unsupported_item = "حجز المواعيد عبر التقويم الخارجي"

            return (
                f"{prefix_greeting}{unsupported_item} غير متاحة أو غير مفعّلة في النظام حالياً. "
                f"أنا متخصص في تقديم الدعم المكتوب، وتوضيح المنتجات والخدمات لمنشأة {company}، "
                "وإدارة المهام ومتابعة الاستفسارات عبر القنوات المعتمدة. "
                "يسعدني مساعدتك في أي استفسار آخر ضمن خدماتنا المتاحة."
            )

        if intent == "hire_agent":
            return (
                f"{prefix_greeting}نعم، تدعم منصتنا تمكين الشركات ورواد الأعمال من توظيف موظفين رقميين ذكيين "
                "مخصصين لنشاطهم التجاري، للرد على العملاء عبر القنوات (تيليجرام، واتساب، الويب)، "
                "وتنظيم العمليات والمهام وفق الصلاحيات الممنوحة. "
                "يمكنك تزويدي ببيانات التواصل لنرتب لك تفاصيل إعداد موظف رقمي يناسب مشروعك."
            )

        # Default: Capabilities
        exec_skills = profile.activated.directly_executable[:3]
        exec_str = "، و".join(exec_skills)
        return (
            f"{prefix_greeting}بصفتي موظفاً رقمياً لمنشأة {company}، أستطيع مساعدتك في:\n"
            f"1. {exec_str}.\n"
            "2. المساعدة في إعداد المحتوى، والخطط التسويقية، وتنظيم متطلبات العمل.\n"
            "3. توضيح كافة الميزات والخدمات المعتمدة وفوائدها العملية لاحتياجاتك.\n"
            "أعمل دائماً وفق الحقائق المعتمدة والصلاحيات المحددة، وأصعّد أي قرار مالي أو إداري حساس إلى المسؤولين. "
            "ما الذي تحتاج مساعدتي فيه تحديداً؟"
        )
