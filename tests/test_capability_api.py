from uuid import uuid4

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Capability, User
from packages.models.tenant import Tenant


client = TestClient(app)


def create_test_user(
    tenant_name: str,
) -> tuple[Tenant, User]:
    db = SessionLocal()

    tenant = Tenant(
        name=tenant_name,
        slug=f"{tenant_name.lower()}-{uuid4().hex[:8]}",
        status="active",
    )

    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Test User",
        email=f"{uuid4().hex}@example.com",
        role="owner",
        status="active",
    )

    db.add(user)
    db.commit()

    db.refresh(tenant)
    db.refresh(user)

    db.close()

    return tenant, user


def test_create_capability():
    _, user = create_test_user("Capability Create")

    response = client.post(
        "/api/v1/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
        json={
            "name": "Marketing",
            "slug": "marketing",
            "description": "Marketing capability",
            "config": {
                "version": 1,
            },
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "Marketing"
    assert data["slug"] == "marketing"
    assert data["scope"] == "tenant"
    assert data["is_active"] is True


def test_list_capabilities_is_tenant_scoped():
    tenant_one, user_one = create_test_user(
        "Capability Tenant One"
    )

    tenant_two, _ = create_test_user(
        "Capability Tenant Two"
    )

    db = SessionLocal()

    capability_one = Capability(
        tenant_id=tenant_one.id,
        name="Sales One",
        slug="sales-one",
        description="Tenant one capability",
        config={},
        is_active=True,
    )

    capability_two = Capability(
        tenant_id=tenant_two.id,
        name="Sales Two",
        slug="sales-two",
        description="Tenant two capability",
        config={},
        is_active=True,
    )

    db.add_all(
        [
            capability_one,
            capability_two,
        ]
    )

    db.commit()
    db.close()

    response = client.get(
        "/api/v1/capabilities",
        headers={
            "X-User-ID": str(user_one.id),
        },
    )

    assert response.status_code == 200

    data = response.json()

    slugs = {
        capability["slug"]
        for capability in data
    }

    assert "sales-one" in slugs
    assert "sales-two" not in slugs


def test_global_capability_is_visible_to_tenant():
    _, user = create_test_user(
        "Capability Global Visibility"
    )

    db = SessionLocal()

    global_capability = Capability(
        tenant_id=None,
        name="Research",
        slug=f"research-{uuid4().hex[:8]}",
        description="Global research capability",
        config={},
        is_active=True,
    )

    db.add(global_capability)
    db.commit()
    db.refresh(global_capability)

    slug = global_capability.slug

    db.close()

    response = client.get(
        "/api/v1/capabilities",
        headers={
            "X-User-ID": str(user.id),
        },
    )

    assert response.status_code == 200

    data = response.json()

    matching = [
        capability
        for capability in data
        if capability["slug"] == slug
    ]

    assert len(matching) == 1
    assert matching[0]["scope"] == "global"
    assert matching[0]["is_active"] is True


def test_capability_requires_authentication():
    response = client.get(
        "/api/v1/capabilities"
    )

    assert response.status_code == 401
