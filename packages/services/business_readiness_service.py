from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import BusinessBrain
from packages.models.tenant import Tenant


@dataclass
class DomainEvaluation:
    domain_key: str
    domain_name: str
    readiness_score: float
    status: str  # "ready", "needs_attention", "blocked"
    missing_fields: list[str] = field(default_factory=list)
    blocking_requirements: list[str] = field(default_factory=list)
    actionable_suggestions: list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_key": self.domain_key,
            "domain_name": self.domain_name,
            "readiness_score": round(self.readiness_score, 1),
            "status": self.status,
            "missing_fields": self.missing_fields,
            "blocking_requirements": self.blocking_requirements,
            "actionable_suggestions": self.actionable_suggestions,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class DiscoveryQuestion:
    id: str
    domain_key: str
    field_path: str
    question_text: str
    importance: str  # "blocking" | "recommended"
    example_format: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "domain_key": self.domain_key,
            "field_path": self.field_path,
            "question_text": self.question_text,
            "importance": self.importance,
            "example_format": self.example_format,
        }


class BusinessReadinessService:
    """
    Evaluates business data completeness and AI employee readiness across specific tasks.
    Pure read-only evaluator: does NOT mutate BusinessBrain or Tenant records.
    Deterministic, rule-based evaluation without LLM hallucination.
    """

    # Domain Display Names in Arabic
    DOMAIN_NAMES = {
        "general_faq": "الرد على الاستفسارات العامة",
        "catalog_presentation": "عرض المنتجات والخدمات والأسعار",
        "order_taking": "استقبال الطلبات",
        "delivery_fulfillment": "التوصيل والشحن",
        "after_sales_support": "الإرجاع والاستبدال وخدمة ما بعد البيع",
    }

    def __init__(self, db: Session):
        self.db = db

    def evaluate_tenant_readiness(self, tenant_id: UUID) -> dict[str, Any]:
        """
        Evaluate readiness for a given tenant strictly from the database.
        Returns a complete evaluation dictionary without mutating the database.
        """
        tenant = self.db.scalar(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.status == "active",
            )
        )
        if tenant is None:
            raise ValueError(f"Active tenant '{tenant_id}' not found")

        brain = self.db.scalar(
            select(BusinessBrain).where(BusinessBrain.tenant_id == tenant_id)
        )

        identity = (brain.identity or {}) if brain else {}
        products = (brain.products or {}) if brain else {}
        services = (brain.services or {}) if brain else {}
        pricing = (brain.pricing or {}) if brain else {}
        policies = (brain.policies or {}) if brain else {}
        operations = (brain.operations or {}) if brain else {}

        # 1. Evaluate individual domains
        faq_eval = self._eval_general_faq(tenant, identity)
        catalog_eval = self._eval_catalog_presentation(products, services, pricing)
        order_eval = self._eval_order_taking(products, services, pricing, policies, operations, identity)
        delivery_eval = self._eval_delivery_fulfillment(policies, operations, identity)
        after_sales_eval = self._eval_after_sales_support(policies, identity)

        domains: dict[str, DomainEvaluation] = {
            "general_faq": faq_eval,
            "catalog_presentation": catalog_eval,
            "order_taking": order_eval,
            "delivery_fulfillment": delivery_eval,
            "after_sales_support": after_sales_eval,
        }

        # 2. Compute aggregate metrics
        domain_dicts = {k: v.to_dict() for k, v in domains.items()}
        overall_score = round(sum(d.readiness_score for d in domains.values()) / len(domains), 1)

        critical_blockers: dict[str, list[str]] = {}
        for k, d in domains.items():
            if d.blocking_requirements:
                critical_blockers[k] = d.blocking_requirements

        has_critical_blockers = len(critical_blockers) > 0

        # Status determined strictly: any blocker prevents overall "ready" status
        if has_critical_blockers:
            overall_status = "not_ready" if overall_score < 50.0 else "partially_ready"
        elif all(d.status in ("ready", "not_applicable") for d in domains.values()):
            overall_status = "ready"
        else:
            overall_status = "partially_ready"

        # 3. Generate structured discovery questions using known profile data
        discovery_questions = self._generate_discovery_questions(domains, identity, pricing)

        # 4. Generate Arabic readiness summary
        if overall_status == "ready":
            summary = "الموظف الذكي جاهز بالكامل للعمل والتفاعل مع العملاء في كافة المجالات."
        elif has_critical_blockers:
            total_blockers = sum(len(b) for b in critical_blockers.values())
            summary = f"النشاط غير مكتمل لبعض المهام الحرجة: يوجد {total_blockers} متطلب تشغيلي حرج يمنع إطلاق الوكيل في تلك المجالات."
        else:
            summary = "النشاط جاهز تشغيليًا بنسبة مقبولة، مع وجود معلومات تكميلية يُنصح باستكمالها لتحسين تجربة العملاء."

        return {
            "tenant_id": str(tenant_id),
            "overall_score": overall_score,
            "overall_status": overall_status,
            "has_critical_blockers": has_critical_blockers,
            "readiness_summary": summary,
            "critical_blockers": critical_blockers,
            "domains": domain_dicts,
            "discovery_questions": [q.to_dict() for q in discovery_questions],
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    # -------------------------------------------------------------------------
    # Domain Evaluators
    # -------------------------------------------------------------------------

    def _eval_general_faq(self, tenant: Tenant, identity: dict[str, Any]) -> DomainEvaluation:
        """Evaluates identity and general FAQ readiness."""
        score = 100.0
        missing: list[str] = []
        blockers: list[str] = []
        suggestions: list[str] = []

        # 1. Commercial Name (Critical)
        comm_name = identity.get("commercial_name") or tenant.name
        if not comm_name or not comm_name.strip():
            score -= 25.0
            missing.append("identity.commercial_name")
            blockers.append("الاسم التجاري للمنشأة غير محدد")
            suggestions.append("أدخل الاسم التجاري المعتمد الذي سيستخدمه الوكيل للتعريف بالمنشأة.")

        # 2. Business Description / Type (Recommended)
        desc = identity.get("description")
        btype = identity.get("business_type")
        if not desc and not btype:
            score -= 20.0
            missing.append("identity.description")
            suggestions.append("أضف وصفًا موجزًا ونوع النشاط لتمكين الوكيل من الإجابة عن طبيعة عمل المنشأة.")

        # 3. Contact Channels (Critical)
        contact = identity.get("contact") or {}
        has_phone = bool(contact.get("phone") or contact.get("whatsapp"))
        has_email = bool(contact.get("email"))
        if not has_phone and not has_email:
            score -= 30.0
            missing.append("identity.contact.phone")
            blockers.append("لا توجد أي وسيلة تواصل رسمية معتمدة (هاتف أو واتساب أو بريد إلكتروني)")
            suggestions.append("أدخل رقم هاتف أو واتساب لتمكين العملاء من التواصل المباشر مع المنشأة.")
        elif not has_phone:
            score -= 10.0
            missing.append("identity.contact.phone")
            suggestions.append("يُفضل إضافة رقم هاتف أو واتساب لتسهيل التواصل الفوري.")

        # 4. Location / Address (Recommended)
        address = identity.get("address") or {}
        if not address.get("city"):
            score -= 15.0
            missing.append("identity.address.city")
            suggestions.append("حدد مدينة المنشأة أو المقر الرئيسي للإجابة عن أسئلة الفروع والموقع.")

        # 5. Operating Hours (Recommended)
        hours = identity.get("operating_hours")
        if not hours:
            score -= 10.0
            missing.append("identity.operating_hours")
            suggestions.append("حدد ساعات وأيام العمل الرسمية حتى يجيب الوكيل بدقة عند سؤال العملاء عن أوقات الدوام.")

        score = max(0.0, min(100.0, score))
        status = "blocked" if blockers else ("ready" if score >= 85.0 else "needs_attention")

        return DomainEvaluation(
            domain_key="general_faq",
            domain_name=self.DOMAIN_NAMES["general_faq"],
            readiness_score=score,
            status=status,
            missing_fields=missing,
            blocking_requirements=blockers,
            actionable_suggestions=suggestions,
        )

    def _eval_catalog_presentation(
        self,
        products: dict[str, Any],
        services: dict[str, Any],
        pricing: dict[str, Any],
    ) -> DomainEvaluation:
        """Evaluates product catalog, services, pricing, and currency readiness."""
        score = 100.0
        missing: list[str] = []
        blockers: list[str] = []
        suggestions: list[str] = []

        total_items = len(products) + len(services)
        if total_items == 0:
            return DomainEvaluation(
                domain_key="catalog_presentation",
                domain_name=self.DOMAIN_NAMES["catalog_presentation"],
                readiness_score=0.0,
                status="blocked",
                missing_fields=["catalog.products"],
                blocking_requirements=["كتالوج المنتجات والخدمات فارغ تمامًا"],
                actionable_suggestions=["أضف منتجاتك أو خدماتك مع الأسعار لتمكين الوكيل من عرضها للعملاء."],
            )

        # Currency validation
        global_currency = pricing.get("currency")
        has_global_currency = bool(global_currency and str(global_currency).strip())

        # Validate products individually
        invalid_price_count = 0
        missing_currency_count = 0
        for slug, prod in products.items():
            if not isinstance(prod, dict):
                continue
            name = prod.get("name") or slug
            price = prod.get("price")
            # Free product check:
            is_free = (
                prod.get("is_free") is True
                or str(prod.get("price_type", "")).lower() == "free"
                or str(prod.get("type", "")).lower() in ("free", "free_sample", "free_consultation")
            )

            # Strict price validation
            try:
                num_price = float(price) if price is not None else None
            except (ValueError, TypeError):
                num_price = None

            if is_free:
                # Legitimate free product, price 0 or None is completely valid
                pass
            elif num_price is None:
                invalid_price_count += 1
                missing.append(f"products.{slug}.price")
                blockers.append(f"المنتج '{name}' ليس له سعر محدد للبيع")
            elif num_price < 0:
                invalid_price_count += 1
                missing.append(f"products.{slug}.price")
                blockers.append(f"المنتج '{name}' سعره سالب وغير صالح للبيع ({price})")
            elif num_price == 0:
                invalid_price_count += 1
                missing.append(f"products.{slug}.price")
                blockers.append(f"المنتج '{name}' سعره غير صالح للبيع (0) ولم يُحدد كمنتج مجاني معتمد (is_free)")

            # Check unit or currency
            item_currency = prod.get("currency") or prod.get("unit")
            if not item_currency and not has_global_currency and not is_free:
                missing_currency_count += 1
                missing.append(f"products.{slug}.currency")
                blockers.append(f"العملة النقدية غير محددة للمنتج '{name}'")

        if invalid_price_count > 0:
            score -= min(40.0, invalid_price_count * 15.0)
            suggestions.append("حدد أسعارًا صالحة وموجبة لجميع المنتجات غير المجانية في الكتالوج.")

        if missing_currency_count > 0 or not has_global_currency:
            if not has_global_currency:
                score -= 20.0
                missing.append("catalog.pricing.currency")
                suggestions.append("حدد العملة النقدية الرسمية للمتجر (مثل: ريال، SAR).")

        # Category completeness (recommended for navigation, penalizes only multi-product catalogs)
        prods_without_cat = [
            s for s, p in products.items() if isinstance(p, dict) and not p.get("category")
        ]
        if prods_without_cat:
            suggestions.append("أضف تصنيفات للمنتجات لتسهيل عرضها وتصفيتها للعملاء.")
            if len(products) > 2:
                score -= 10.0

        score = max(0.0, min(100.0, score))
        status = "blocked" if blockers else ("ready" if score >= 85.0 else "needs_attention")

        return DomainEvaluation(
            domain_key="catalog_presentation",
            domain_name=self.DOMAIN_NAMES["catalog_presentation"],
            readiness_score=score,
            status=status,
            missing_fields=missing,
            blocking_requirements=blockers,
            actionable_suggestions=suggestions,
        )

    def _eval_order_taking(
        self,
        products: dict[str, Any],
        services: dict[str, Any],
        pricing: dict[str, Any],
        policies: dict[str, Any],
        operations: dict[str, Any],
        identity: dict[str, Any],
    ) -> DomainEvaluation:
        """Evaluates whether the agent can accept and process customer orders."""
        score = 100.0
        missing: list[str] = []
        blockers: list[str] = []
        suggestions: list[str] = []

        # 1. At least one valid sellable product or service (either positive price or certified free item)
        sellable_items = []
        has_only_free_items = True
        for items_dict in (products, services):
            for slug, item in items_dict.items():
                if isinstance(item, dict):
                    is_free = (
                        item.get("is_free") is True
                        or str(item.get("price_type", "")).lower() == "free"
                        or str(item.get("type", "")).lower() in ("free", "free_sample", "free_consultation")
                    )
                    if is_free:
                        sellable_items.append(item)
                        continue
                    p = item.get("price")
                    try:
                        num_p = float(p) if p is not None else None
                    except (ValueError, TypeError):
                        num_p = None
                    if num_p is not None and num_p > 0:
                        sellable_items.append(item)
                        has_only_free_items = False

        if not sellable_items:
            score -= 40.0
            missing.append("catalog.products")
            blockers.append("لا يمكن استقبال طلبات لعدم وجود أي منتج أو خدمة معتمدة بسعر صالح للبيع")
            suggestions.append("أضف منتجًا أو خدمة واحدة على الأقل بسعر صالح لتمكين استقبال الطلبات.")

        # 2. Payment methods / settlement mechanism (required for non-free orders)
        payment_policy = policies.get("payment") or operations.get("payment")
        if not payment_policy:
            if not (sellable_items and has_only_free_items):
                score -= 30.0
                missing.append("policies.payment")
                blockers.append("طرق الدفع المقبولة أو آلية سداد الطلبات غير محددة")
                suggestions.append("حدد طرق الدفع المعتمدة (مثل: البطاقات البنكية، المحافظ الرقمية، أو الدفع عند الاستلام).")
        # 3. Contact or ordering channel
        contact = identity.get("contact") or {}
        if not contact.get("phone") and not contact.get("whatsapp") and not contact.get("email"):
            score -= 20.0
            missing.append("identity.contact.phone")
            blockers.append("لا توجد قناة تواصل أو هاتف معتمد لتأكيد ومتابعة الطلبات مع العميل")
            suggestions.append("أدخل هاتفًا أو رقم واتساب لتأكيد الطلبات وإرسال الإشعارات للعميل.")

        # 4. Preparation or fulfillment time (Recommended)
        prep_time = operations.get("prep_time_minutes") or operations.get("fulfillment")
        if not prep_time:
            score -= 10.0
            missing.append("operations.fulfillment")
            suggestions.append("حدد مدة تجهيز الطلبات أو آلية التنفيذ لإبلاغ العميل بالموعد المتوقع.")

        score = max(0.0, min(100.0, score))
        status = "blocked" if blockers else ("ready" if score >= 85.0 else "needs_attention")

        return DomainEvaluation(
            domain_key="order_taking",
            domain_name=self.DOMAIN_NAMES["order_taking"],
            readiness_score=score,
            status=status,
            missing_fields=missing,
            blocking_requirements=blockers,
            actionable_suggestions=suggestions,
        )

    def _eval_delivery_fulfillment(
        self,
        policies: dict[str, Any],
        operations: dict[str, Any],
        identity: dict[str, Any] | None = None,
    ) -> DomainEvaluation:
        """Evaluates delivery policies, shipping fees, coverage areas, and durations."""
        delivery = policies.get("delivery")
        id_dict = identity or {}

        # 1. Distinguish businesses where delivery is not applicable or not offered
        is_delivery_applicable = True
        if isinstance(delivery, dict) and (delivery.get("applicable") is False or delivery.get("offered") is False):
            is_delivery_applicable = False
        elif operations.get("delivery_applicable") is False or operations.get("delivery_offered") is False:
            is_delivery_applicable = False
        elif (
            str(id_dict.get("business_type", "")).lower() in ("services", "digital_services", "consulting", "software", "saas", "digital")
            and not delivery
        ):
            is_delivery_applicable = False

        if not is_delivery_applicable:
            return DomainEvaluation(
                domain_key="delivery_fulfillment",
                domain_name=self.DOMAIN_NAMES["delivery_fulfillment"],
                readiness_score=100.0,
                status="not_applicable",
                missing_fields=[],
                blocking_requirements=[],
                actionable_suggestions=["خدمة التوصيل والشحن غير منطبقة على طبيعة هذا النشاط التجاري."],
            )

        score = 100.0
        missing: list[str] = []
        blockers: list[str] = []
        suggestions: list[str] = []

        if not delivery:
            return DomainEvaluation(
                domain_key="delivery_fulfillment",
                domain_name=self.DOMAIN_NAMES["delivery_fulfillment"],
                readiness_score=0.0,
                status="blocked",
                missing_fields=["policies.delivery"],
                blocking_requirements=["سياسة التوصيل والشحن غير محددة بالكامل"],
                actionable_suggestions=["أضف تفاصيل التوصيل: رسوم الشحن، مناطق التغطية، والمدة المتوقعة."],
            )

        # If delivery is a structured dict
        if isinstance(delivery, dict):
            # Fees validation (Critical)
            has_fee = any(k in delivery for k in ("fees", "domestic_fee", "cost", "price", "rate"))
            if not has_fee:
                score -= 35.0
                missing.append("policies.delivery.fees")
                blockers.append("رسوم وتكلفة التوصيل غير محددة")
                suggestions.append("حدد تكلفة التوصيل (أو حد الشحن المجاني إن وجد).")

            # Coverage areas validation (Critical)
            has_coverage = bool(
                delivery.get("coverage")
                or delivery.get("coverage_areas")
                or delivery.get("areas")
                or delivery.get("cities")
            )
            if not has_coverage:
                score -= 35.0
                missing.append("policies.delivery.coverage")
                blockers.append("مناطق ومدن تغطية التوصيل غير محددة")
                suggestions.append("حدد المدن أو المناطق المشمولة بالشحن والتوصيل.")

            # Estimated delivery time (Recommended)
            has_duration = bool(
                delivery.get("estimated_days")
                or delivery.get("estimated_time")
                or delivery.get("duration")
            )
            if not has_duration:
                score -= 15.0
                missing.append("policies.delivery.estimated_days")
                suggestions.append("حدد المدة المتوقعة للتوصيل (مثال: خلال 1-3 أيام عمل).")
        elif isinstance(delivery, str):
            # Text description: check length and keywords
            text = delivery.strip()
            if len(text) < 10:
                score -= 40.0
                missing.append("policies.delivery")
                blockers.append("نص سياسة التوصيل موجز جدًا وغير كافٍ للتشغيل")
                suggestions.append("وضح رسوم التوصيل والمدن المشمولة تفصيليًا.")

        score = max(0.0, min(100.0, score))
        status = "blocked" if blockers else ("ready" if score >= 85.0 else "needs_attention")

        return DomainEvaluation(
            domain_key="delivery_fulfillment",
            domain_name=self.DOMAIN_NAMES["delivery_fulfillment"],
            readiness_score=score,
            status=status,
            missing_fields=missing,
            blocking_requirements=blockers,
            actionable_suggestions=suggestions,
        )

    def _eval_after_sales_support(
        self,
        policies: dict[str, Any],
        identity: dict[str, Any],
    ) -> DomainEvaluation:
        """Evaluates return policies, refund mechanisms, and after-sales support."""
        score = 100.0
        missing: list[str] = []
        blockers: list[str] = []
        suggestions: list[str] = []

        # 1. Returns Policy
        returns = policies.get("returns")
        has_returns_policy = False
        returns_explicitly_disallowed = False

        if isinstance(returns, dict):
            if returns.get("allowed") is False or returns.get("applicable") is False:
                # Explicit no-returns policy (e.g. food, digital assets, custom work)
                has_returns_policy = True
                returns_explicitly_disallowed = True
            elif returns.get("allowed") is True or returns.get("window_days") or returns.get("days") or returns.get("conditions") or returns.get("policy"):
                has_returns_policy = True
        elif isinstance(returns, str) and len(returns.strip()) >= 5:
            has_returns_policy = True

        if not has_returns_policy:
            score -= 35.0
            missing.append("policies.returns")
            blockers.append("سياسة وشروط الإرجاع غير محددة (سواء بالإتاحة أو بعدم الإمكانية)")
            suggestions.append("حدد سياسة الإرجاع (سواء كانت مسموحة بمدة وشروط، أو غير مسموحة لطبيعة المنتج).")

        # 2. Payment/Refund Methods (Critical if returns are allowed)
        payment = policies.get("payment")
        if not payment and not returns_explicitly_disallowed:
            score -= 25.0
            missing.append("policies.payment")
            blockers.append("طرق استرداد المبالغ والمدفوعات غير محددة")
            suggestions.append("وضح طرق إعادة واسترداد المبالغ عند قبول الإرجاع.")

        # 3. Customer Support Contact (Critical)
        contact = identity.get("contact") or {}
        has_contact = bool(contact.get("phone") or contact.get("email") or contact.get("whatsapp"))
        if not has_contact:
            score -= 25.0
            missing.append("identity.contact.phone")
            blockers.append("لا توجد وسيلة تواصل رسمية معتمدة لخدمة ما بعد البيع وحل المشكلات")
            suggestions.append("أضف هاتفًا أو بريدًا مخصصًا لخدمة العملاء بعد البيع.")

        # 4. Exchange Policy (Recommended)
        exchange = policies.get("exchange")
        if not exchange and not returns_explicitly_disallowed:
            score -= 10.0
            missing.append("policies.exchange")
            suggestions.append("حدد سياسة استبدال المنتجات والمدة المسموحة.")

        # 5. Warranty Information (Recommended)
        warranty = policies.get("warranty")
        if not warranty:
            score -= 5.0
            missing.append("policies.warranty")
            suggestions.append("وضح شروط الضمان للمنتجات المشمولة إن وجدت.")

        score = max(0.0, min(100.0, score))
        status = "blocked" if blockers else ("ready" if score >= 85.0 else "needs_attention")

        return DomainEvaluation(
            domain_key="after_sales_support",
            domain_name=self.DOMAIN_NAMES["after_sales_support"],
            readiness_score=score,
            status=status,
            missing_fields=missing,
            blocking_requirements=blockers,
            actionable_suggestions=suggestions,
        )

    # -------------------------------------------------------------------------
    # Structured Knowledge Discovery Questions
    # -------------------------------------------------------------------------

    def _generate_discovery_questions(
        self,
        domains: dict[str, DomainEvaluation],
        identity: dict[str, Any] | None = None,
        pricing: dict[str, Any] | None = None,
    ) -> list[DiscoveryQuestion]:
        """
        Generates targeted, deterministic discovery questions mapped directly
        to missing fields, prioritized by importance (blocking first).
        Utilizes confirmed tenant information without assuming unverified cities or currencies.
        """
        id_dict = identity or {}
        price_dict = pricing or {}
        known_comm_name = id_dict.get("commercial_name")
        known_city = (id_dict.get("address") or {}).get("city")
        known_currency = price_dict.get("currency")

        comm_name_example = f"مثال: {known_comm_name}" if known_comm_name else "مثال: [الاسم التجاري للمنشأة]"
        city_example = f"مثال: {known_city}" if known_city else "مثال: [المدينة] - [المقر أو الفرع الرئيسي]"
        currency_example = f"مثال: {known_currency}" if known_currency else "مثال: العملة المعتمدة للمبيعات (مثل: SAR, AED, USD, EGP)"
        delivery_fees_example = (
            f"مثال: [تكلفة التوصيل] {known_currency or ''}، أو شحن مجاني للطلبات فوق حد معين".strip()
        )
        delivery_cov_example = "مثال: [قائمة المدن أو مناطق التغطية المشمولة بالتوصيل]"
        payment_example = "مثال: الدفع الإلكتروني (البطاقات البنكية)، المحافظ الرقمية، أو الدفع عند الاستلام"

        # Canonical question registry mapped to field paths
        QUESTION_TEMPLATES: dict[str, dict[str, str]] = {
            "identity.commercial_name": {
                "question": "ما هو الاسم التجاري الرسمي الذي ترغب في أن يحيي به الموظف الذكي عملاءك؟",
                "example": comm_name_example,
            },
            "identity.description": {
                "question": "كيف تصف نشاطك التجاري والخدمات التي تقدمها في جملتين موجزتين؟",
                "example": "مثال: [وصف موجز للمنتجات والخدمات الأساسية التي تقدمها المنشأة لعملائها]",
            },
            "identity.contact.phone": {
                "question": "ما هو رقم الهاتف أو الواتساب المعتمد لخدمة العملاء وتأكيد الطلبات؟",
                "example": "مثال: +[رمز الدولة][رقم الهاتف أو الواتساب المعتمد]",
            },
            "identity.address.city": {
                "question": "في أي مدينة يقع المقر الرئيسي أو فرع نشاطك التجاري؟",
                "example": city_example,
            },
            "identity.operating_hours": {
                "question": "ما هي أوقات وساعات العمل الرسمية لاستقبال العملاء والرد على استفساراتهم؟",
                "example": "مثال: [أيام العمل الأسبوعية وساعات استقبال الطلبات والرد]",
            },
            "catalog.products": {
                "question": "ما هي المنتجات أو الخدمات الرئيسية التي ترغب في توثيقها في كتالوج المنشأة مع أسعارها؟",
                "example": "[{\"name\": \"اسم المنتج/الخدمة\", \"price\": 100}]",
            },
            "catalog.pricing.currency": {
                "question": "ما هي العملة النقدية المعتمدة لأسعار منتجاتك وخدماتك؟",
                "example": currency_example,
            },
            "policies.delivery": {
                "question": "هل تقدم خدمة التوصيل والشحن لعملائك، وما هي تفاصيلها الأساسية؟",
                "example": "مثال: [توضيح ما إذا كان التوصيل متاحًا أو الاستلام من الفرع فقط]",
            },
            "policies.delivery.fees": {
                "question": "كم تبلغ تكلفة ورسوم التوصيل للطلبات، وهل يوجد حد أدنى للشحن المجاني؟",
                "example": delivery_fees_example,
            },
            "policies.delivery.coverage": {
                "question": "ما هي المدن أو المناطق الجغرافية المشمولة بالتوصيل حاليًا؟",
                "example": delivery_cov_example,
            },
            "policies.delivery.estimated_days": {
                "question": "كم المدة الزمنية المتوقعة لوصول الشحنة للعميل بعد إتمام الطلب؟",
                "example": "مثال: [المدة التقريبية بالأيام أو الساعات لوصول الطلب]",
            },
            "policies.payment": {
                "question": "ما هي طرق ووسائل الدفع المعتمدة للشراء من متجرك؟",
                "example": payment_example,
            },
            "policies.returns": {
                "question": "ما هي سياسة وشروط إرجاع المنتجات والمدة المسموحة للعميل بعد الاستلام؟",
                "example": "مثال: [توضيح مدة وشروط الإرجاع، أو توضيح عدم إمكانية الإرجاع لطبيعة المنتج]",
            },
            "policies.exchange": {
                "question": "هل متاح استبدال المنتجات، وما هي المدة والشروط المعتمدة للاستبدال؟",
                "example": "مثال: [شروط ومدة استبدال السلع إن كانت متاحة]",
            },
            "policies.warranty": {
                "question": "هل توفر المنشأة ضمانًا على المنتجات أو الأجهزة، وما هي مدته؟",
                "example": "مثال: [مدة ونطاق الضمان إن كان ساريًا على المنتجات]",
            },
            "operations.fulfillment": {
                "question": "ما هي المدة المطلوبة لتجهيز وإعداد الطلب قبل تسليمه للشحن أو المندوب؟",
                "example": "مثال: [مدة التجهيز المتوقعة بالدقائق أو الساعات]",
            },
        }

        generated: list[DiscoveryQuestion] = []
        seen_fields: set[str] = set()

        # 1. First collect blocking missing fields across domains
        for domain_key, domain in domains.items():
            if domain.blocking_requirements:
                for field_path in domain.missing_fields:
                    # Generic prefix match if specific subfield
                    canonical_key = self._resolve_canonical_key(field_path, QUESTION_TEMPLATES)
                    if canonical_key and canonical_key not in seen_fields:
                        seen_fields.add(canonical_key)
                        tmpl = QUESTION_TEMPLATES[canonical_key]
                        generated.append(
                            DiscoveryQuestion(
                                id=f"dq_{len(generated)+1}",
                                domain_key=domain_key,
                                field_path=canonical_key,
                                question_text=tmpl["question"],
                                importance="blocking",
                                example_format=tmpl["example"],
                            )
                        )

        # 2. Then collect recommended missing fields
        for domain_key, domain in domains.items():
            for field_path in domain.missing_fields:
                canonical_key = self._resolve_canonical_key(field_path, QUESTION_TEMPLATES)
                if canonical_key and canonical_key not in seen_fields:
                    seen_fields.add(canonical_key)
                    tmpl = QUESTION_TEMPLATES[canonical_key]
                    generated.append(
                        DiscoveryQuestion(
                            id=f"dq_{len(generated)+1}",
                            domain_key=domain_key,
                            field_path=canonical_key,
                            question_text=tmpl["question"],
                            importance="recommended",
                            example_format=tmpl["example"],
                        )
                    )

        return generated

    @staticmethod
    def _resolve_canonical_key(field_path: str, templates: dict[str, Any]) -> str | None:
        """Matches a field path or product-specific path to canonical question templates."""
        if field_path in templates:
            return field_path
        if field_path.startswith("products.") and field_path.endswith(".price"):
            return "catalog.products"
        if field_path.startswith("products.") and field_path.endswith(".currency"):
            return "catalog.pricing.currency"
        return None
