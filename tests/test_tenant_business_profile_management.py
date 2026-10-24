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
from packages.models.domain import AuditEvent, BusinessBrain, User
from packages.models.tenant import Tenant
from packages.services.business_brain_service import BusinessBrainService

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


def test_business_profile_initial_and_full_update(db):
    """
    Test Phase 4A: Business profile retrieval, comprehensive update,
    and verification of commercial name synchronization with Tenant.name.
    """
    tenant, owner, token = create_tenant_and_user(db, name="مطحنة الأفق القديمة", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # 1. Initial Profile Retrieval
        res_get = client.get("/api/v1/tenants/me/profile", headers=headers)
        assert res_get.status_code == 200, res_get.text
        data = res_get.json()
        assert data["tenant_id"] == str(tenant.id)
        assert data["commercial_name"] == "مطحنة الأفق القديمة"
        assert data["products"] == {}
        assert data["policies"] == {}
        assert data["version"] == 1

        # 2. Comprehensive Profile Update
        payload = {
            "commercial_name": "محمصة الأفق الفاخرة",
            "legal_name": "شركة الأفق للتجارة ذ.م.م",
            "business_type": "specialty_coffee",
            "description": "محمصة ومورد لحبوب القهوة المختصة وأدوات الباريستا",
            "contact": {
                "phone": "+966501234567",
                "email": "contact@alofuq.sa",
                "whatsapp": "+966501234567",
                "website": "https://alofuq.sa",
            },
            "address": {
                "country": "المملكة العربية السعودية",
                "city": "الرياض",
                "district": "العليا",
                "street": "طريق الملك فهد",
                "postal_code": "12214",
            },
            "operating_hours": {
                "weekdays": "7:00 AM - 11:00 PM",
                "friday": "1:00 PM - 11:30 PM",
            },
            "products": [
                {
                    "name": "بن إثيوبي قوجي",
                    "price": 68.0,
                    "unit": "ريال",
                    "category": "حبوب قهوة",
                    "slug": "ethiopian_guji_250g",
                },
                {
                    "name": "مطحنة تيمور C2",
                    "price": 195.0,
                    "unit": "ريال",
                    "category": "أدوات",
                    "slug": "timemore_c2",
                },
            ],
            "services": [
                {"name": "معايرة مكائن الإسبريسو", "price": 150.0},
            ],
            "pricing": {
                "currency": "SAR",
                "vat_percentage": 15,
                "vat_included": True,
            },
            "policies": {
                "delivery": {
                    "fees": 20,
                    "free_shipping_threshold": 200,
                    "estimated_days": "1-3 أيام عمل",
                    "coverage": ["الرياض", "جدة", "الدمام"],
                },
                "returns": {
                    "allowed": True,
                    "window_days": 7,
                    "condition": "غير مفتوح وفي التغليف الأصلي",
                },
                "exchange": {
                    "allowed": True,
                    "window_days": 14,
                },
                "payment": {
                    "methods": ["Mada", "Apple Pay", "Visa", "Tabby"],
                },
            },
            "operations": {
                "fulfillment": "internal_dispatch",
                "prep_time_minutes": 30,
            },
        }

        res_put = client.put("/api/v1/tenants/me/profile", headers=headers, json=payload)
        assert res_put.status_code == 200, res_put.text
        updated = res_put.json()

        assert updated["commercial_name"] == "محمصة الأفق الفاخرة"
        assert updated["legal_name"] == "شركة الأفق للتجارة ذ.م.م"
        assert updated["business_type"] == "specialty_coffee"
        assert updated["contact"]["phone"] == "+966501234567"
        assert updated["address"]["city"] == "الرياض"
        assert updated["operating_hours"]["weekdays"] == "7:00 AM - 11:00 PM"
        assert "ethiopian_guji_250g" in updated["products"]
        assert updated["products"]["ethiopian_guji_250g"]["price"] == 68.0
        assert updated["policies"]["delivery"]["fees"] == 20
        assert updated["policies"]["payment"]["methods"] == ["Mada", "Apple Pay", "Visa", "Tabby"]
        assert updated["version"] >= 2

        # 3. Verify Database Synchronization with Tenant.name
        db.expire_all()
        reloaded_tenant = db.get(Tenant, tenant.id)
        assert reloaded_tenant.name == "محمصة الأفق الفاخرة"

        # 4. Verify Audit Event Generated
        audit = db.query(AuditEvent).filter(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "business_profile_updated",
        ).first()
        assert audit is not None
        assert "identity" in audit.event_metadata["sections_updated"]
        assert "policies" in audit.event_metadata["sections_updated"]

    finally:
        _cleanup_tenant(db, tenant.id)


def test_dedicated_catalog_api(db):
    """
    Test dedicated /api/v1/tenants/me/catalog GET and PUT endpoints.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر المنتجات التجريبي", role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Initial catalog
        res_get = client.get("/api/v1/tenants/me/catalog", headers=headers)
        assert res_get.status_code == 200
        assert res_get.json()["products"] == {}

        # Update catalog with products, services, and pricing
        cat_payload = {
            "products": [
                {"name": "عطر فاخر 100 مل", "price": 320.0, "slug": "perfume_100ml"},
                {"name": "معطر جو مسك", "price": 45.0, "slug": "air_freshener_musk"},
            ],
            "services": [
                {"name": "تغليف هدايا ملكي", "price": 25.0, "slug": "gift_wrapping"},
            ],
            "pricing": {
                "currency": "SAR",
                "vat_included": True,
            },
            "replace_all": False,
        }
        res_put = client.put("/api/v1/tenants/me/catalog", headers=headers, json=cat_payload)
        assert res_put.status_code == 200, res_put.text
        cat_data = res_put.json()

        assert "perfume_100ml" in cat_data["products"]
        assert cat_data["products"]["perfume_100ml"]["price"] == 320.0
        assert "gift_wrapping" in cat_data["services"]
        assert cat_data["pricing"]["currency"] == "SAR"

        # Read back catalog
        res_verify = client.get("/api/v1/tenants/me/catalog", headers=headers)
        assert res_verify.status_code == 200
        assert "air_freshener_musk" in res_verify.json()["products"]

    finally:
        _cleanup_tenant(db, tenant.id)


def test_dedicated_policies_api(db):
    """
    Test dedicated /api/v1/tenants/me/policies GET and PUT endpoints.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر السياسات", role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        policy_payload = {
            "delivery": {
                "domestic_fee": 25,
                "free_delivery_min": 250,
                "courier": "SMSA",
            },
            "returns": {
                "return_window_days": 14,
                "requires_invoice": True,
            },
            "exchange": {
                "exchange_window_days": 14,
            },
            "payment": {
                "methods": ["Mada", "Apple Pay", "Cash on Delivery"],
                "cod_fee": 15,
            },
            "warranty": "سنتان ضمان الوكيل لجميع الأجهزة الإلكترونية",
            "terms": "تطبق الشروط والأحكام الخاصة بالمملكة العربية السعودية",
            "replace_all": False,
        }
        res_put = client.put("/api/v1/tenants/me/policies", headers=headers, json=policy_payload)
        assert res_put.status_code == 200, res_put.text
        data = res_put.json()

        assert data["policies"]["delivery"]["courier"] == "SMSA"
        assert data["policies"]["returns"]["return_window_days"] == 14
        assert data["policies"]["warranty"] == "سنتان ضمان الوكيل لجميع الأجهزة الإلكترونية"

        # Read back policies
        res_get = client.get("/api/v1/tenants/me/policies", headers=headers)
        assert res_get.status_code == 200
        assert res_get.json()["policies"]["payment"]["cod_fee"] == 15

    finally:
        _cleanup_tenant(db, tenant.id)


def test_rbac_member_cannot_modify_business_profile(db):
    """
    Test server-side RBAC:
    - Member can READ business profile (GET 200).
    - Member CANNOT modify profile, catalog, or policies (PUT 403 Forbidden).
    """
    tenant, member, token = create_tenant_and_user(db, name="متجر الصلاحيات", role="tenant_member")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Read profile as member: Allowed
        res_get = client.get("/api/v1/tenants/me/profile", headers=headers)
        assert res_get.status_code == 200

        # Attempt to modify profile as member: Denied with 403
        res_put_profile = client.put(
            "/api/v1/tenants/me/profile",
            headers=headers,
            json={"commercial_name": "اسم غير مصرح به"},
        )
        assert res_put_profile.status_code == 403
        assert "lacks administrator privileges" in res_put_profile.json()["detail"]

        # Attempt to modify catalog as member: Denied with 403
        res_put_catalog = client.put(
            "/api/v1/tenants/me/catalog",
            headers=headers,
            json={"products": [{"name": "منتج احتيالي", "price": 1}]},
        )
        assert res_put_catalog.status_code == 403

        # Attempt to modify policies as member: Denied with 403
        res_put_policies = client.put(
            "/api/v1/tenants/me/policies",
            headers=headers,
            json={"delivery": "شحن مجاني للجميع بدون شروط"},
        )
        assert res_put_policies.status_code == 403

    finally:
        _cleanup_tenant(db, tenant.id)


def test_cross_tenant_isolation(db):
    """
    Test strict multi-tenant isolation:
    - Tenant A and Tenant B configure different profiles.
    - Neither can view or overwrite the other's profile, catalog, or policies.
    """
    tenant_a, owner_a, token_a = create_tenant_and_user(db, name="مؤسسة التقنية أ", role="tenant_owner")
    tenant_b, owner_b, token_b = create_tenant_and_user(db, name="شركة الأغذية ب", role="tenant_owner")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    try:
        # 1. Tenant A updates profile
        client.put(
            "/api/v1/tenants/me/profile",
            headers=headers_a,
            json={
                "commercial_name": "حلول التقنية المتطورة",
                "description": "استشارات وأنظمة سحابية",
                "products": [{"name": "نظام ERP", "price": 15000, "slug": "erp_system"}],
                "policies": {"delivery": "تسليم إلكتروني فوري"},
            },
        )

        # 2. Tenant B updates profile
        client.put(
            "/api/v1/tenants/me/profile",
            headers=headers_b,
            json={
                "commercial_name": "مزارع الريف الطازجة",
                "description": "خضار وفواكه عضوية",
                "products": [{"name": "صندوق تمر سكري", "price": 45, "slug": "sukari_dates"}],
                "policies": {"delivery": "توصيل مبرد خلال 24 ساعة"},
            },
        )

        # 3. Read as Tenant A: strictly Tenant A's data
        res_a = client.get("/api/v1/tenants/me/profile", headers=headers_a)
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["tenant_id"] == str(tenant_a.id)
        assert data_a["commercial_name"] == "حلول التقنية المتطورة"
        assert "erp_system" in data_a["products"]
        assert "sukari_dates" not in data_a["products"]
        assert data_a["policies"]["delivery"] == "تسليم إلكتروني فوري"

        # 4. Read as Tenant B: strictly Tenant B's data
        res_b = client.get("/api/v1/tenants/me/profile", headers=headers_b)
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["tenant_id"] == str(tenant_b.id)
        assert data_b["commercial_name"] == "مزارع الريف الطازجة"
        assert "sukari_dates" in data_b["products"]
        assert "erp_system" not in data_b["products"]
        assert data_b["policies"]["delivery"] == "توصيل مبرد خلال 24 ساعة"

    finally:
        _cleanup_tenant(db, tenant_a.id)
        _cleanup_tenant(db, tenant_b.id)


def test_secret_detection_in_profile_update(db):
    """
    Test security guard: Storing sensitive credentials (API keys, private keys, passwords)
    in the business profile is immediately detected and rejected with 400 Bad Request.
    """
    tenant, owner, token = create_tenant_and_user(db, name="متجر الحماية", role="tenant_owner")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Attempt to insert raw OpenAI API key in description
        payload_secret = {
            "description": "Key is sk-proj-1234567890abcdef1234567890abcdef1234",
        }
        res = client.put("/api/v1/tenants/me/profile", headers=headers, json=payload_secret)
        assert res.status_code == 400
        assert "restricted credential or secret" in res.json()["detail"].lower()

        # Attempt to insert sensitive password assignment in contact
        payload_pwd = {
            "contact": {"admin_password": "supersecretpassword123"},
        }
        res_pwd = client.put("/api/v1/tenants/me/profile", headers=headers, json=payload_pwd)
        assert res_pwd.status_code == 400

    finally:
        _cleanup_tenant(db, tenant.id)


def test_unauthenticated_request_rejected():
    """
    Test that endpoints strictly reject unauthenticated calls with 401 Unauthorized.
    """
    res_profile = client.get("/api/v1/tenants/me/profile")
    assert res_profile.status_code == 401

    res_put = client.put("/api/v1/tenants/me/profile", json={"commercial_name": "Hack"})
    assert res_put.status_code == 401

    res_cat = client.get("/api/v1/tenants/me/catalog")
    assert res_cat.status_code == 401

    res_pol = client.get("/api/v1/tenants/me/policies")
    assert res_pol.status_code == 401


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def _cleanup_tenant(db, tenant_id):
    try:
        t = db.get(Tenant, tenant_id)
        if t is not None:
            db.delete(t)
            db.commit()
    except Exception:
        db.rollback()
