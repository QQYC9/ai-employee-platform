from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Customer
from packages.services.audit_service import AuditService


class CustomerService:
    """
    Business logic for Customer operations.

    All operations are explicitly tenant-scoped.
    """

    ALLOWED_STATUSES = {"active", "inactive", "blocked", "deleted"}
    ALLOWED_TYPES = {"individual", "business", "vip", "lead"}

    def __init__(self, db: Session, audit_service: AuditService | None = None):
        self.db = db
        self.audit_service = audit_service or AuditService(db)

    def create_customer(
        self,
        tenant_id: UUID,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        customer_type: str = "individual",
        profile: dict | None = None,
        metadata_json: dict | None = None,
    ) -> Customer:
        """Create a new tenant-scoped customer record."""
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Customer name cannot be empty")

        clean_email = email.strip().lower() if email and email.strip() else None
        clean_phone = phone.strip() if phone and phone.strip() else None

        clean_type = (customer_type or "individual").strip().lower()
        if clean_type not in self.ALLOWED_TYPES:
            raise ValueError(f"Invalid customer type: {customer_type}")

        # Check unique email within tenant if email provided
        if clean_email:
            existing = self.find_by_email(tenant_id, clean_email)
            if existing:
                raise ValueError(f"A customer with email '{clean_email}' already exists in this tenant")

        customer = Customer(
            tenant_id=tenant_id,
            name=clean_name,
            email=clean_email,
            phone=clean_phone,
            status="active",
            customer_type=clean_type,
            profile=profile or {},
            metadata_json=metadata_json or {},
        )

        self.db.add(customer)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="customer_created",
            action="create_customer",
            description=f"Created customer '{customer.name}'",
            event_metadata={
                "customer_id": str(customer.id),
                "email": customer.email,
                "customer_type": customer.customer_type,
            },
        )

        return customer

    def get_customer(
        self,
        tenant_id: UUID,
        customer_id: UUID,
    ) -> Customer | None:
        """Retrieve a customer belonging to the tenant."""
        return self.db.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
                Customer.status != "deleted",
            )
        )

    def find_by_email(
        self,
        tenant_id: UUID,
        email: str,
    ) -> Customer | None:
        """Find an active/non-deleted customer by email within the tenant."""
        clean_email = email.strip().lower()
        return self.db.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.email == clean_email,
                Customer.status != "deleted",
            )
        )

    def find_by_phone(
        self,
        tenant_id: UUID,
        phone: str,
    ) -> Customer | None:
        """Find an active/non-deleted customer by phone within the tenant."""
        clean_phone = phone.strip()
        return self.db.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.phone == clean_phone,
                Customer.status != "deleted",
            )
        )

    def list_customers(
        self,
        tenant_id: UUID,
        *,
        status: str | None = None,
        customer_type: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Customer]:
        """List customers scoped to the tenant with optional filters and pagination."""
        if limit < 1:
            raise ValueError("Limit must be greater than zero")
        if limit > 200:
            limit = 200

        stmt = select(Customer).where(Customer.tenant_id == tenant_id)

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in self.ALLOWED_STATUSES:
                raise ValueError(f"Invalid customer status filter: {status}")
            stmt = stmt.where(Customer.status == clean_status)
        else:
            stmt = stmt.where(Customer.status != "deleted")

        if customer_type is not None:
            clean_type = customer_type.strip().lower()
            stmt = stmt.where(Customer.customer_type == clean_type)

        if search is not None and search.strip():
            term = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    Customer.name.ilike(term),
                    Customer.email.ilike(term),
                    Customer.phone.ilike(term),
                )
            )

        stmt = stmt.order_by(Customer.created_at.desc()).offset(offset).limit(limit)
        return list(self.db.scalars(stmt).all())

    def update_customer(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        status: str | None = None,
        customer_type: str | None = None,
        profile: dict | None = None,
        metadata_json: dict | None = None,
    ) -> Customer:
        """Update an existing customer record belonging to the tenant."""
        customer = self.get_customer(tenant_id, customer_id)
        if customer is None:
            raise ValueError(f"Customer '{customer_id}' not found")

        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("Customer name cannot be empty")
            customer.name = clean_name

        if email is not None:
            clean_email = email.strip().lower() if email.strip() else None
            if clean_email and clean_email != customer.email:
                existing = self.find_by_email(tenant_id, clean_email)
                if existing and existing.id != customer.id:
                    raise ValueError(f"Customer with email '{clean_email}' already exists")
            customer.email = clean_email

        if phone is not None:
            customer.phone = phone.strip() if phone.strip() else None

        if status is not None:
            clean_status = status.strip().lower()
            if clean_status not in self.ALLOWED_STATUSES:
                raise ValueError(f"Invalid customer status: {status}")
            customer.status = clean_status

        if customer_type is not None:
            clean_type = customer_type.strip().lower()
            if clean_type not in self.ALLOWED_TYPES:
                raise ValueError(f"Invalid customer type: {customer_type}")
            customer.customer_type = clean_type

        if profile is not None:
            updated_profile = dict(customer.profile or {})
            updated_profile.update(profile)
            customer.profile = updated_profile

        if metadata_json is not None:
            updated_meta = dict(customer.metadata_json or {})
            updated_meta.update(metadata_json)
            customer.metadata_json = updated_meta

        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="customer_updated",
            action="update_customer",
            description=f"Updated customer '{customer.name}'",
            event_metadata={
                "customer_id": str(customer.id),
                "status": customer.status,
            },
        )

        return customer

    def delete_customer(
        self,
        tenant_id: UUID,
        customer_id: UUID,
    ) -> Customer:
        """Soft-delete customer by marking status as 'deleted'."""
        customer = self.get_customer(tenant_id, customer_id)
        if customer is None:
            raise ValueError(f"Customer '{customer_id}' not found")

        customer.status = "deleted"
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="customer_deleted",
            action="delete_customer",
            description=f"Deleted customer '{customer.name}'",
            event_metadata={"customer_id": str(customer.id)},
        )

        return customer
