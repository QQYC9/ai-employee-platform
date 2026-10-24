from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.core.database import SessionLocal
from packages.models.domain import BusinessBrain, User
from packages.models.tenant import Tenant
from packages.services.business_brain_service import BusinessBrainService
from packages.services.business_readiness_service import BusinessReadinessService

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures and Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def create_tenant_and_user(db, name: str, role: str = "tenant_owner") -> tuple[Tenant, User, str]:
    slug = f"tenant-{uuid4().hex[:8]}"
    tenant = Tenant(name=name, slug=slug, status="active")
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name=f"User {role}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        role=role,
        status="active",
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        role=role,
    )
    return tenant, user, token


def _cleanup_tenant(db, tenant_id):
    try:
        t = db.get(Tenant, tenant_id)
        if t is not None:
            db.delete(t)
            db.commit()
    except Exception:
        db.rollback()


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_1_new_business_empty_data_evaluation(db):
    """
    Test Phase 4B: A new business with empty profile evaluates to not_ready,
    flags critical blockers across tasks, and generates targeted discovery questions.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر جديد فارغ", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["tenant_id"] == str(tenant.id)
        assert data["has_critical_blockers"] is True
        assert data["overall_status"] == "not_ready"
        assert data["overall_score"] < 50.0

        domains = data["domains"]
        assert "catalog_presentation" in domains
        assert domains["catalog_presentation"]["status"] == "blocked"
        assert "كتالوج المنتجات والخدمات فارغ تمامًا" in domains["catalog_presentation"]["blocking_requirements"]

        assert "delivery_fulfillment" in domains
        assert domains["delivery_fulfillment"]["status"] == "blocked"

        assert "order_taking" in domains
        assert domains["order_taking"]["status"] == "blocked"

        # Check structured discovery questions
        questions = data["discovery_questions"]
        assert len(questions) > 0
        blocking_questions = [q for q in questions if q["importance"] == "blocking"]
        assert len(blocking_questions) > 0

        # Check field mappings in questions
        field_paths = [q["field_path"] for q in questions]
        assert "catalog.products" in field_paths
        assert "policies.delivery" in field_paths

    finally:
        _cleanup_tenant(db, tenant.id)


def test_2_partially_complete_business(db):
    """
    Test Phase 4B: Partially complete business (has identity and catalog, but lacks delivery/returns).
    Accurately isolates what is ready vs what needs attention.
    """
    tenant, owner, token = create_tenant_and_user(db, name="مؤسسة التقنية الجزئية", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "مؤسسة التقنية الجزئية",
                "description": "حلول برمجية وتطوير سحابي",
                "contact": {"phone": "+966509998877", "email": "tech@partial.sa"},
                "address": {"city": "الرياض"},
                "operating_hours": "من الأحد إلى الخميس 9 صباحًا إلى 6 مساءً",
                "products": [
                    {"name": "اشتراك استضافة سنوي", "price": 450.0, "unit": "ريال", "slug": "hosting_yearly"},
                ],
                "pricing": {"currency": "SAR"},
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        domains = data["domains"]
        # General FAQ and catalog presentation should be ready
        assert domains["general_faq"]["status"] == "ready"
        assert domains["general_faq"]["readiness_score"] >= 85.0

        assert domains["catalog_presentation"]["status"] == "ready"
        assert len(domains["catalog_presentation"]["blocking_requirements"]) == 0

        # Delivery and after sales still blocked because no policies were provided
        assert domains["delivery_fulfillment"]["status"] == "blocked"
        assert domains["after_sales_support"]["status"] == "blocked"

        # Overall cannot be ready while blockers exist
        assert data["overall_status"] in ("partially_ready", "not_ready")
        assert data["has_critical_blockers"] is True

    finally:
        _cleanup_tenant(db, tenant.id)


def test_3_independent_domain_evaluation(db):
    """
    Test Phase 4B: Independent domain evaluation.
    Completing catalog does not require delivery; digital businesses or in-store
    businesses can have catalog ready while delivery is evaluated independently.
    """
    tenant, owner, token = create_tenant_and_user(db, name="استوديو التصميم", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "متجر الأناقة للحقائب",
                "business_type": "retail",
                "description": "متجر لبيع الحقائب والإكسسوارات الجلدية",
                "contact": {"phone": "+966555123456", "email": "info@bags.sa"},
                "address": {"city": "الرياض"},
                "operating_hours": "يوميًا من 9 صباحًا إلى 6 مساءً",
                "products": [
                    {"name": "حقيبة جلدية فاخرة", "price": 350.0, "unit": "ريال", "slug": "leather_bag"},
                ],
                "pricing": {"currency": "SAR"},
                "policies": {
                    "payment": {"methods": ["Mada", "Bank Transfer"]},
                    "returns": {"policy": "الاسترجاع متاح خلال 7 أيام"},
                },
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200
        data = res.json()

        # Catalog presentation and FAQ should be ready
        assert data["domains"]["general_faq"]["status"] == "ready"
        assert data["domains"]["catalog_presentation"]["status"] == "ready"

        # Delivery is blocked because no shipping policy was defined
        assert data["domains"]["delivery_fulfillment"]["status"] == "blocked"
        assert "policies.delivery" in data["domains"]["delivery_fulfillment"]["missing_fields"]

        # Crucial: Delivery block does NOT degrade catalog_presentation score!
        assert data["domains"]["catalog_presentation"]["readiness_score"] == 100.0

    finally:
        _cleanup_tenant(db, tenant.id)


def test_4_product_without_price_or_currency_is_blocked(db):
    """
    Test Phase 4B: A product with zero, negative, or missing price, or missing currency
    strictly blocks catalog_presentation and order_taking with detailed diagnostic.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر الأسعار الناقصة", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        # Adding products with invalid price and missing global currency
        brain_svc.update_brain(
            tenant_id=tenant.id,
            products={
                "valid_item": {"name": "منتج صحيح", "price": 50.0, "unit": "ريال"},
                "zero_price_item": {"name": "منتج مجاني غير محدد", "price": 0.0},
                "negative_price_item": {"name": "منتج بسعر سالب", "price": -15.0},
            },
            pricing={},  # No global currency
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200
        data = res.json()

        catalog_domain = data["domains"]["catalog_presentation"]
        assert catalog_domain["status"] == "blocked"
        blockers = catalog_domain["blocking_requirements"]
        assert any("غير صالح للبيع (0.0)" in b or "غير صالح للبيع (0)" in b for b in blockers)
        assert any("غير صالح للبيع (-15.0)" in b or "غير صالح للبيع (-15)" in b for b in blockers)
        assert any("العملة النقدية غير محددة" in b for b in blockers)

    finally:
        _cleanup_tenant(db, tenant.id)


def test_5_missing_delivery_fees_or_coverage_is_blocked(db):
    """
    Test Phase 4B: Having a delivery policy that omits either fees or coverage areas
    strictly flags blocking requirements and prevents the delivery task from being ready.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر الشحن الناقص", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        # Delivery policy with estimated time but missing fees and coverage
        brain_svc.update_policies(
            tenant_id=tenant.id,
            policies={
                "delivery": {
                    "estimated_days": "2-4 أيام عمل",
                    # No fees, no coverage!
                }
            },
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200
        data = res.json()

        delivery_domain = data["domains"]["delivery_fulfillment"]
        assert delivery_domain["status"] == "blocked"
        assert "policies.delivery.fees" in delivery_domain["missing_fields"]
        assert "policies.delivery.coverage" in delivery_domain["missing_fields"]
        assert "رسوم وتكلفة التوصيل غير محددة" in delivery_domain["blocking_requirements"]
        assert "مناطق ومدن تغطية التوصيل غير محددة" in delivery_domain["blocking_requirements"]

    finally:
        _cleanup_tenant(db, tenant.id)


def test_6_fully_ready_business_evaluation(db):
    """
    Test Phase 4B: A fully populated business profile achieves overall_status = 'ready',
    zero critical blockers, and no blocking discovery questions.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر النخبة المتكامل", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "متجر النخبة المتكامل",
                "legal_name": "شركة النخبة للحلول التجارية",
                "business_type": "ecommerce",
                "description": "متجر يقدم أحدث المنتجات الذكية مع شحن فوري لكافة مناطق المملكة",
                "contact": {
                    "phone": "+966501112233",
                    "whatsapp": "+966501112233",
                    "email": "support@al-nokhba.sa",
                },
                "address": {
                    "city": "الرياض",
                    "district": "الملقا",
                    "country": "المملكة العربية السعودية",
                },
                "operating_hours": "يوميًا من 9 صباحًا إلى 11 مساءً",
                "products": [
                    {"name": "سماعة بلوتوث ذكية", "price": 199.0, "unit": "ريال", "category": "إلكترونيات", "slug": "smart_headphone"},
                ],
                "pricing": {"currency": "SAR", "vat_percentage": 15, "vat_included": True},
                "policies": {
                    "delivery": {
                        "fees": 20,
                        "coverage": ["الرياض", "جدة", "الدمام", "مكة المكرمة"],
                        "estimated_days": "1-3 أيام عمل",
                    },
                    "returns": {
                        "allowed": True,
                        "window_days": 14,
                        "conditions": "غير مستخدم وفي عبوته الأصلية",
                    },
                    "exchange": {
                        "allowed": True,
                        "window_days": 14,
                    },
                    "payment": {
                        "methods": ["Mada", "Apple Pay", "Visa"],
                    },
                    "warranty": "سنتان ضمان الوكيل المعتمد",
                },
                "operations": {
                    "prep_time_minutes": 20,
                    "fulfillment": "express_dispatch",
                },
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        assert data["overall_status"] == "ready"
        assert data["has_critical_blockers"] is False
        assert data["overall_score"] >= 90.0
        assert len(data["critical_blockers"]) == 0

        for domain_key, domain in data["domains"].items():
            assert domain["status"] == "ready", f"Domain {domain_key} is not ready: {domain}"
            assert len(domain["blocking_requirements"]) == 0

        # No blocking discovery questions
        blocking_questions = [q for q in data["discovery_questions"] if q["importance"] == "blocking"]
        assert len(blocking_questions) == 0

    finally:
        _cleanup_tenant(db, tenant.id)


def test_7_cross_tenant_isolation_in_readiness(db):
    """
    Test Phase 4B: Strict cross-tenant isolation in readiness evaluations.
    Tenant A (complete) and Tenant B (empty) evaluate strictly within their own silos.
    """
    tenant_a, owner_a, token_a = create_tenant_and_user(db, name="مستأجر أ الجاهز", role="tenant_owner")
    tenant_b, owner_b, token_b = create_tenant_and_user(db, name="مستأجر ب الفارغ", role="tenant_owner")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    try:
        # Populate Tenant A only
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant_a.id,
            profile_data={
                "commercial_name": "مستأجر أ الجاهز",
                "description": "نشاط متكامل",
                "contact": {"phone": "+966500000001", "email": "a@tenant.sa"},
                "address": {"city": "الرياض"},
                "products": [{"name": "منتج أ", "price": 100.0, "unit": "ريال", "slug": "item_a"}],
                "pricing": {"currency": "SAR"},
                "policies": {
                    "delivery": {"fees": 15, "coverage": "الرياض"},
                    "returns": {"days": 7},
                    "payment": {"methods": ["Mada"]},
                },
            },
        )
        db.commit()

        # Query Tenant A
        res_a = client.get("/api/v1/tenants/me/readiness", headers=headers_a)
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["tenant_id"] == str(tenant_a.id)
        assert data_a["overall_score"] >= 85.0
        assert len(data_a["critical_blockers"]) == 0

        # Query Tenant B (must be strictly empty and not affected by Tenant A)
        res_b = client.get("/api/v1/tenants/me/readiness", headers=headers_b)
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["tenant_id"] == str(tenant_b.id)
        assert data_b["overall_status"] == "not_ready"
        assert data_b["has_critical_blockers"] is True
        assert "catalog_presentation" in data_b["critical_blockers"]

    finally:
        _cleanup_tenant(db, tenant_a.id)
        _cleanup_tenant(db, tenant_b.id)


def test_8_read_only_guarantee_no_mutations(db):
    """
    Test Phase 4B: Verification that evaluating readiness is strictly read-only.
    Does not update timestamps, does not increment BusinessBrain.version,
    and does not mutate any records in the database.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر الفحص للقراءة فقط", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain = brain_svc.create_brain_if_not_exists(tenant.id)
        db.commit()

        initial_version = brain.version
        initial_tenant_name = tenant.name

        # Call readiness endpoint 3 consecutive times
        for _ in range(3):
            res = client.get("/api/v1/tenants/me/readiness", headers=headers)
            assert res.status_code == 200

        # Reload from database and verify no mutations occurred
        db.expire_all()
        reloaded_brain = brain_svc.get_brain(tenant.id)
        reloaded_tenant = db.get(Tenant, tenant.id)

        assert reloaded_brain.version == initial_version
        assert reloaded_tenant.name == initial_tenant_name

    finally:
        _cleanup_tenant(db, tenant.id)


def test_9_auth_and_rbac(db):
    """
    Test Phase 4B:
    - Unauthenticated request is rejected with 401.
    - Tenant member can view readiness report (read-only insight).
    """
    # 1. Unauthenticated request
    res_unauth = client.get("/api/v1/tenants/me/readiness")
    assert res_unauth.status_code == 401

    # 2. Tenant member viewing readiness
    tenant, member, token = create_tenant_and_user(db, name="متجر العضو", role="tenant_member")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        res_member = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res_member.status_code == 200
        assert res_member.json()["tenant_id"] == str(tenant.id)
    finally:
        _cleanup_tenant(db, tenant.id)


def test_10_non_applicable_delivery_for_services(db):
    """
    Test Phase 4B Review: When delivery is not applicable (e.g. digital services or explicitly disabled),
    delivery_fulfillment is marked 'not_applicable' and does NOT block overall business readiness.
    """
    tenant, owner, token = create_tenant_and_user(db, name="مؤسسة استشارات برمجية", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "مؤسسة استشارات برمجية",
                "business_type": "services",
                "description": "استشارات هندسة برمجيات سحابية",
                "contact": {"phone": "+966555999111", "email": "consult@cloud.sa"},
                "address": {"city": "الرياض"},
                "operating_hours": "يوميًا 9 صباحًا إلى 5 مساءً",
                "services": [
                    {"name": "جلسة مراجعة معمارية", "price": 1500.0, "slug": "arch_review"},
                ],
                "pricing": {"currency": "SAR"},
                "policies": {
                    "payment": {"methods": ["Mada", "Bank Transfer"]},
                    "delivery": {"applicable": False, "reason": "خدمات رقمية سحابية بحتة لا تتطلب شحنًا"},
                    "returns": {"allowed": False, "policy": "الاستشارات المؤداة غير قابلة للإرجاع"},
                },
                "operations": {
                    "delivery_applicable": False,
                },
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        # Delivery domain should be not_applicable with 0 blockers
        delivery_domain = data["domains"]["delivery_fulfillment"]
        assert delivery_domain["status"] == "not_applicable"
        assert len(delivery_domain["blocking_requirements"]) == 0
        assert delivery_domain["readiness_score"] == 100.0

        # Entire business should be overall 'ready' despite having no courier or shipping fees
        assert data["overall_status"] == "ready"
        assert data["has_critical_blockers"] is False

    finally:
        _cleanup_tenant(db, tenant.id)


def test_11_explicit_no_returns_policy_is_valid(db):
    """
    Test Phase 4B Review: A business that explicitly defines a 'no-returns' policy
    (e.g. perishable goods, fresh food, customized items) is considered to have a valid,
    complete returns policy and is NOT blocked.
    """
    tenant, owner, token = create_tenant_and_user(db, name="مخبوزات ومأكولات طازجة", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "مخبوزات ومأكولات طازجة",
                "business_type": "food",
                "description": "حلويات ومخبوزات طازجة يوميًا",
                "contact": {"phone": "+966551234888", "email": "orders@bakery.sa"},
                "address": {"city": "جدة"},
                "operating_hours": "يوميًا من 7 صباحًا حتى 11 مساءً",
                "products": [
                    {"name": "كعكة فراولة طازجة", "price": 120.0, "unit": "ريال", "slug": "strawberry_cake"},
                ],
                "pricing": {"currency": "SAR"},
                "policies": {
                    "delivery": {
                        "fees": 15,
                        "coverage": ["جدة"],
                        "estimated_days": "خلال ساعتين",
                    },
                    "payment": {"methods": ["Mada", "Apple Pay"]},
                    "returns": {
                        "allowed": False,
                        "conditions": "نظرًا لطبيعة المواد الغذائية الطازجة، لا يمكن إرجاع المنتجات بعد استلامها",
                    },
                },
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        after_sales = data["domains"]["after_sales_support"]
        assert after_sales["status"] == "ready"
        assert len(after_sales["blocking_requirements"]) == 0
        assert "policies.returns" not in after_sales["missing_fields"]

    finally:
        _cleanup_tenant(db, tenant.id)


def test_12_legitimate_free_product_allowed(db):
    """
    Test Phase 4B Review: Explicitly free items (e.g. is_free: True, free consultation, sample)
    with price 0 are accepted and not rejected as invalid prices.
    """
    tenant, owner, token = create_tenant_and_user(db, name="مركز الاستشارات المجانية", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "مركز الاستشارات المجانية",
                "business_type": "consulting",
                "contact": {"phone": "+966558888999"},
                "products": [
                    {
                        "name": "جلسة تشخيص أولية مجانية",
                        "price": 0.0,
                        "is_free": True,
                        "slug": "free_diagnostic_session",
                    },
                ],
                "pricing": {"currency": "SAR"},
                "operations": {"delivery_applicable": False},
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        catalog_domain = data["domains"]["catalog_presentation"]
        assert catalog_domain["status"] == "ready"
        assert len(catalog_domain["blocking_requirements"]) == 0
        assert "products.free_diagnostic_session.price" not in catalog_domain["missing_fields"]

    finally:
        _cleanup_tenant(db, tenant.id)


def test_13_neutral_discovery_questions_leverage_tenant_data(db):
    """
    Test Phase 4B Review: Discovery questions do not assume Riyadh, Saudi Arabia, or SAR
    when a business operates elsewhere, and leverage known data without inventing facts.
    """
    tenant, owner, token = create_tenant_and_user(db, name="مؤسسة النيل للتجارة", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        brain_svc = BusinessBrainService(db)
        # Egyptian business with EGP currency and Cairo city
        brain_svc.update_profile(
            tenant_id=tenant.id,
            profile_data={
                "commercial_name": "مؤسسة النيل للتجارة",
                "address": {"city": "القاهرة"},
                "pricing": {"currency": "EGP"},
            },
            user_id=owner.id,
        )
        db.commit()

        res = client.get("/api/v1/tenants/me/readiness", headers=headers)
        assert res.status_code == 200, res.text
        data = res.json()

        questions = data["discovery_questions"]
        assert len(questions) > 0

        # Verify known city and currency are utilized in examples instead of hardcoded Riyadh/SAR
        for q in questions:
            example = q["example_format"]
            # Must not invent unverified assumptions
            if q["field_path"] == "identity.address.city":
                assert "القاهرة" in example
                assert "الرياض" not in example
            if q["field_path"] == "catalog.pricing.currency":
                assert "EGP" in example
                assert "ريال سعودي" not in example

    finally:
        _cleanup_tenant(db, tenant.id)
