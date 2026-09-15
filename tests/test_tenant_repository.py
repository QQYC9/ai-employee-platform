import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import Customer
from packages.tenants.context import tenant_context
from packages.tenants.repository import TenantRepository


def test_tenant_repository_isolates_customers():
    db = SessionLocal()

    try:
        tenant_a = Tenant(
            name="Repository Test A",
            slug=f"repository-test-a-{uuid4().hex[:8]}",
        )

        tenant_b = Tenant(
            name="Repository Test B",
            slug=f"repository-test-b-{uuid4().hex[:8]}",
        )

        db.add_all([tenant_a, tenant_b])
        db.flush()

        customer_a = Customer(
            tenant_id=tenant_a.id,
            name="Customer A",
            email=f"a-{uuid4().hex[:8]}@example.com",
            status="active",
        )

        customer_b = Customer(
            tenant_id=tenant_b.id,
            name="Customer B",
            email=f"b-{uuid4().hex[:8]}@example.com",
            status="active",
        )

        db.add_all([customer_a, customer_b])
        db.flush()

        repository = TenantRepository(db, Customer)

        with tenant_context(tenant_a.id):
            customers = repository.list()

            assert len(customers) == 1
            assert customers[0].id == customer_a.id
            assert repository.get(customer_a.id) is not None
            assert repository.get(customer_b.id) is None

        with tenant_context(tenant_b.id):
            customers = repository.list()

            assert len(customers) == 1
            assert customers[0].id == customer_b.id
            assert repository.get(customer_b.id) is not None
            assert repository.get(customer_a.id) is None

    finally:
        db.rollback()
        db.close()
