from __future__ import annotations

from typing import Any
import re
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Agent, Approval, Conversation, Customer, Message, Task
from packages.tools.base import BaseRealTool
from packages.tools.contract import (
    ToolContract,
    ToolExecutionContext,
    ToolRiskLevel,
)


# --- Customer Search ---
class CustomerSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=100, description="Search term for customer name, email, or phone")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of results to return")


class CustomerSearchTool(BaseRealTool):
    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="customer_search",
            name="Customer Search Tool",
            version="1.0.0",
            description="Searches for customers within the tenant by name, email, or phone number.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=CustomerSearchInput.model_json_schema(),
            output_schema={"type": "array", "items": {"type": "object"}},
            required_permissions=[("read", "customers")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return CustomerSearchInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> list[dict[str, Any]]:
        query_str = f"%{parameters['query'].strip()}%"
        limit = parameters.get("limit", 10)

        stmt = (
            select(Customer)
            .where(
                Customer.tenant_id == context.tenant_id,
                Customer.status != "deleted",
                or_(
                    Customer.name.ilike(query_str),
                    Customer.email.ilike(query_str),
                    Customer.phone.ilike(query_str),
                ),
            )
            .limit(limit)
        )
        customers = self.db.scalars(stmt).all()
        return [
            {
                "id": str(c.id),
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in customers
        ]


# --- Customer Get ---
class CustomerGetInput(BaseModel):
    customer_id: str | None = Field(default=None, description="UUID of customer")
    phone: str | None = Field(default=None, description="Phone number of customer")
    email: str | None = Field(default=None, description="Email address of customer")


class CustomerGetTool(BaseRealTool):
    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="customer_get",
            name="Customer Get Details Tool",
            version="1.0.0",
            description="Retrieves detailed profile information for a customer by ID, phone, or email within the tenant.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=CustomerGetInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "customers")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        parsed = CustomerGetInput(**parameters)
        if not parsed.customer_id and not parsed.phone and not parsed.email:
            raise ValueError("Must provide at least one of 'customer_id', 'phone', or 'email'")
        return parsed.model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        stmt = select(Customer).where(
            Customer.tenant_id == context.tenant_id,
            Customer.status != "deleted",
        )
        if parameters.get("customer_id"):
            try:
                cid = UUID(parameters["customer_id"])
                stmt = stmt.where(Customer.id == cid)
            except ValueError:
                raise ValueError(f"Invalid UUID: '{parameters['customer_id']}'")
        elif parameters.get("phone"):
            stmt = stmt.where(Customer.phone == parameters["phone"].strip())
        elif parameters.get("email"):
            stmt = stmt.where(Customer.email == parameters["email"].strip().lower())

        customer = self.db.scalar(stmt)
        if customer is None:
            raise ValueError("Customer not found")

        return {
            "id": str(customer.id),
            "tenant_id": str(customer.tenant_id),
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "status": customer.status,
            "metadata": customer.metadata_json or {},
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
            "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
        }


# --- Customer Create / Update ---
class CustomerCreateOrUpdateInput(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Full customer name")
    phone: str | None = Field(default=None, max_length=50, description="Customer phone number")
    email: str | None = Field(default=None, max_length=255, description="Customer email address")
    metadata: dict[str, Any] | None = Field(default=None, description="Custom customer metadata")


class CustomerCreateOrUpdateTool(BaseRealTool):
    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="customer_create_or_update",
            name="Customer Create/Update Tool",
            version="1.0.0",
            description="Creates a new customer or updates an existing customer profile with tenant isolation.",
            risk_level=ToolRiskLevel.MEDIUM,
            requires_approval=False,
            input_schema=CustomerCreateOrUpdateInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("write", "customers")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return CustomerCreateOrUpdateInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        name = parameters["name"].strip()
        phone = parameters.get("phone")
        email = parameters.get("email")
        metadata = parameters.get("metadata") or {}

        # Look for existing customer by phone or email
        existing: Customer | None = None
        if phone:
            existing = self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == context.tenant_id,
                    Customer.phone == phone.strip(),
                    Customer.status != "deleted",
                )
            )
        if existing is None and email:
            existing = self.db.scalar(
                select(Customer).where(
                    Customer.tenant_id == context.tenant_id,
                    Customer.email == email.strip().lower(),
                    Customer.status != "deleted",
                )
            )

        if existing is not None:
            existing.name = name
            if phone:
                existing.phone = phone.strip()
            if email:
                existing.email = email.strip().lower()
            if metadata:
                meta = dict(existing.metadata_json or {})
                meta.update(metadata)
                existing.metadata_json = meta
            self.db.flush()
            return {
                "action": "updated",
                "customer_id": str(existing.id),
                "name": existing.name,
                "email": existing.email,
                "phone": existing.phone,
            }

        new_cust = Customer(
            tenant_id=context.tenant_id,
            name=name,
            phone=phone.strip() if phone else None,
            email=email.strip().lower() if email else None,
            status="active",
            metadata_json=metadata,
        )
        self.db.add(new_cust)
        self.db.flush()
        return {
            "action": "created",
            "customer_id": str(new_cust.id),
            "name": new_cust.name,
            "email": new_cust.email,
            "phone": new_cust.phone,
        }


# --- Task Query ---
class TaskQueryInput(BaseModel):
    task_id: str | None = Field(default=None, description="UUID of task")
    status: str | None = Field(default=None, description="Task status filter (e.g. pending, completed, failed)")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum tasks to return")


class TaskQueryTool(BaseRealTool):
    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="task_query",
            name="Task Query Tool",
            version="1.0.0",
            description="Queries tenant tasks and execution statuses.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=TaskQueryInput.model_json_schema(),
            output_schema={"type": "array", "items": {"type": "object"}},
            required_permissions=[("read", "tasks")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return TaskQueryInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> list[dict[str, Any]]:
        stmt = select(Task).where(Task.tenant_id == context.tenant_id)
        if parameters.get("task_id"):
            try:
                tid = UUID(parameters["task_id"])
                stmt = stmt.where(Task.id == tid)
            except ValueError:
                raise ValueError(f"Invalid Task UUID: '{parameters['task_id']}'")
        if parameters.get("status"):
            stmt = stmt.where(Task.status == parameters["status"].strip().lower())

        limit = parameters.get("limit", 10)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit)

        tasks = self.db.scalars(stmt).all()
        return [
            {
                "id": str(t.id),
                "title": t.title,
                "objective": t.objective,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ]


# --- Task Create ---
class TaskCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=255, description="Task title")
    objective: str | None = Field(default=None, description="Detailed task objective or description")
    description: str | None = Field(default=None, description="Detailed task description alias")
    priority: str = Field(default="normal", description="Priority level: low, normal, high, urgent")
    agent_id: str | None = Field(default=None, description="Optional agent UUID to assign")


class TaskCreateTool(BaseRealTool):
    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="task_create",
            name="Task Create Tool",
            version="1.0.0",
            description="Creates an operational task for the digital employee platform within the tenant boundary.",
            risk_level=ToolRiskLevel.MEDIUM,
            requires_approval=False,
            input_schema=TaskCreateInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("write", "tasks")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return TaskCreateInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        agent_uuid = None
        if parameters.get("agent_id"):
            try:
                agent_uuid = UUID(parameters["agent_id"])
            except ValueError:
                raise ValueError(f"Invalid Agent UUID: '{parameters['agent_id']}'")
            agent_exists = self.db.scalar(
                select(Agent).where(
                    Agent.id == agent_uuid,
                    Agent.tenant_id == context.tenant_id,
                )
            )
            if agent_exists is None:
                raise ValueError(f"Agent '{agent_uuid}' not found for tenant")

        objective_text = (
            parameters.get("objective")
            or parameters.get("description")
            or parameters["title"]
        ).strip()

        task = Task(
            tenant_id=context.tenant_id,
            agent_id=agent_uuid,
            title=parameters["title"].strip(),
            objective=objective_text,
            priority=parameters.get("priority", "normal").lower(),
            status="pending",
        )
        self.db.add(task)
        self.db.flush()
        return {
            "task_id": str(task.id),
            "title": task.title,
            "objective": task.objective,
            "status": task.status,
            "priority": task.priority,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }



# --- Business Summary Report ---
class BusinessSummaryInput(BaseModel):
    days: int = Field(default=7, ge=1, le=90, description="Time window in days for report summary")


class BusinessSummaryTool(BaseRealTool):
    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="business_summary",
            name="Business Summary Tool",
            version="1.0.0",
            description="Generates an aggregated operational summary for the tenant (customer counts, active tasks, conversations, approvals).",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=BusinessSummaryInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "reports")],
            default_timeout=10.0,
            max_timeout=30.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return BusinessSummaryInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        tenant_id = context.tenant_id

        # Aggregate counts safely through ORM with tenant isolation
        total_customers = self.db.scalar(
            select(func.count(Customer.id)).where(
                Customer.tenant_id == tenant_id,
                Customer.status != "deleted",
            )
        ) or 0

        active_conversations = self.db.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.tenant_id == tenant_id,
                Conversation.status.in_(["open", "active"]),
            )
        ) or 0


        total_messages = self.db.scalar(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant_id,
            )
        ) or 0

        total_tasks = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_id == tenant_id,
            )
        ) or 0

        completed_tasks = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_id == tenant_id,
                Task.status == "completed",
            )
        ) or 0

        in_progress_tasks = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_id == tenant_id,
                Task.status == "in_progress",
            )
        ) or 0

        pending_only_tasks = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_id == tenant_id,
                Task.status == "pending",
            )
        ) or 0

        pending_tasks = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_id == tenant_id,
                Task.status.in_(["pending", "in_progress", "active"]),
            )
        ) or 0

        pending_approvals = self.db.scalar(
            select(func.count(Approval.id)).where(
                Approval.tenant_id == tenant_id,
                Approval.status == "pending",
            )
        ) or 0

        return {
            "tenant_id": str(tenant_id),
            "window_days": parameters.get("days", 7),
            "metrics": {
                "total_customers": total_customers,
                "active_conversations": active_conversations,
                "total_messages": total_messages,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "in_progress_tasks": in_progress_tasks,
                "pending_only_tasks": pending_only_tasks,
                "pending_tasks": pending_tasks,
                "pending_approvals": pending_approvals,
            },
            "status": "healthy",
        }


# --- Arabic Product Parser Helper ---
def parse_arabic_products(text: str) -> list[dict[str, Any]]:
    """
    Robust Arabic product parser capable of parsing single-line and multi-line catalogs.
    Extracts name, weight/spec, price, and currency/unit with unique slugs.
    """
    results: list[dict[str, Any]] = []
    lines = text.strip().split("\n")

    catalog_regex = re.compile(
        r"^(?:[\d\-\*\•\.\)]+\s*)?"
        r"(?:أضف\s*منتج\s*(?:جديد\s*)?(?:اسمه\s*)?|تحديث\s*سعر\s*(?:منتج)?|تعديل\s*سعر\s*(?:منتج)?|سعر\s*)?"
        r"(.+?)"
        r"\s*(?:—|-|–|:|=|بسعر|سعره|سعر|بـ|مقابل|يصبح|أصبح|اصبح|صار|إلى|الى|هو)\s*"
        r"(\d+(?:[.,]\d+)?)"
        r"\s*(ريال|سعودي|دولار|درهم|جنيه|ر\.س|SAR|USD)?",
        re.IGNORECASE,
    )

    for line in lines:
        line_clean = line.strip().rstrip(".").strip()
        if not line_clean or line_clean.startswith(("#", "//")):
            continue
        if re.search(r"^(?:اسم\s*المتجر|المتجر|قائمة\s*المنتجات|المنتجات)\s*[:—\-]?", line_clean):
            continue

        m = catalog_regex.search(line_clean)
        if m:
            raw_name = m.group(1).strip()
            raw_name = re.sub(r"^[\d\.\-\)\*]+\s*", "", raw_name).strip()
            if len(raw_name) < 2 or raw_name.lower() in ("اسم المتجر", "قائمة المنتجات", "المنتجات"):
                continue

            price_str = m.group(2).replace(",", ".")
            try:
                price = float(price_str)
            except ValueError:
                continue

            unit = (m.group(3) or "ريال").strip()
            slug = re.sub(r"[^\w]+", "_", raw_name.strip()).strip("_").lower()
            if not slug:
                slug = f"prod_{len(results)+1}"

            results.append({
                "slug": slug,
                "name": raw_name,
                "price": price,
                "unit": unit,
                "currency": unit,
            })

    return results


# --- Product Add Or Update Tool ---
class ProductAddOrUpdateInput(BaseModel):
    products: list[dict[str, Any]] | None = Field(default=None, description="Structured list of products to add or update")
    raw_text: str | None = Field(default=None, description="Raw Arabic text containing product catalog lines")
    replace_all: bool = Field(default=False, description="If True, replaces existing products; if False, merges/updates")


class ProductAddOrUpdateTool(BaseRealTool):
    """
    Adds or updates products in the tenant BusinessBrain (SSOT) and synchronizes with Knowledge.
    Provides verifiable proof of persistence in the database.
    """

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="product_add_or_update",
            name="Product Add or Update Tool",
            version="1.0.0",
            description="Adds or updates single or batch products in tenant BusinessBrain and Knowledge base with strict verification.",
            risk_level=ToolRiskLevel.LOW,
            requires_approval=False,
            input_schema=ProductAddOrUpdateInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("write", "products")],
            default_timeout=10.0,
            max_timeout=30.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ProductAddOrUpdateInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        from packages.services.business_brain_service import BusinessBrainService
        from packages.services.knowledge_service import KnowledgeService

        raw_text = parameters.get("raw_text")
        parsed_items: list[dict[str, Any]] = []

        if parameters.get("products"):
            parsed_items.extend(parameters["products"])

        if raw_text and raw_text.strip():
            extracted = parse_arabic_products(raw_text)
            parsed_items.extend(extracted)

        if not parsed_items:
            raise ValueError("No valid products provided in structured list or extracted from text.")

        # Build clean products dictionary with validation
        products_dict: dict[str, dict[str, Any]] = {}
        for item in parsed_items:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            try:
                price = float(item.get("price", 0))
            except (ValueError, TypeError):
                continue
            if price <= 0:
                continue

            unit = item.get("unit") or item.get("currency") or "ريال"
            slug = item.get("slug") or re.sub(r"[^\w]+", "_", name).strip("_").lower()
            if not slug:
                slug = f"prod_{len(products_dict)+1}"

            products_dict[slug] = {
                "name": name,
                "price": price,
                "unit": unit,
                "currency": unit,
                "category": item.get("category", "منتجات"),
            }

        if not products_dict:
            raise ValueError("All provided product entries were invalid (missing name or non-positive price).")

        replace_all = parameters.get("replace_all", False)
        brain_svc = BusinessBrainService(self.db)
        replace_sections = ["products"] if replace_all else None

        # 1. Update BusinessBrain (SSOT)
        brain_svc.update_brain(
            tenant_id=context.tenant_id,
            products=products_dict,
            replace_sections=replace_sections,
        )

        # 2. Sync Knowledge Base for RAG
        knowledge_svc = KnowledgeService(self.db)
        for slug, prod in products_dict.items():
            knowledge_svc.create_knowledge(
                tenant_id=context.tenant_id,
                title=f"منتج: {prod['name']}",
                content=f"المنتج المعتمد: {prod['name']}، السعر: {prod['price']} {prod['unit']}.",
                knowledge_type="products",
                metadata_json={
                    "source": "owner_conversation" if getattr(context, "conversation_id", None) else "product_tool",
                    "slug": slug,
                    "verified": True,
                },
            )

        self.db.flush()

        # 3. Direct SSOT verification from database
        updated_brain = brain_svc.get_brain(context.tenant_id)
        saved_products = updated_brain.products if updated_brain and updated_brain.products else {}

        verified_saved = []
        for slug, expected in products_dict.items():
            if slug in saved_products and float(saved_products[slug].get("price", 0)) == expected["price"]:
                verified_saved.append({
                    "slug": slug,
                    "name": saved_products[slug].get("name", expected["name"]),
                    "price": saved_products[slug].get("price"),
                    "unit": saved_products[slug].get("unit", expected["unit"]),
                })

        return {
            "success": True,
            "tenant_id": str(context.tenant_id),
            "total_requested": len(products_dict),
            "total_saved": len(verified_saved),
            "action": "replace_all" if replace_all else "merge",
            "saved_products": verified_saved,
            "message": f"تم حفظ وتوثيق {len(verified_saved)} منتج بنجاح في قاعدة البيانات المعتمدة.",
        }


# --- Product List Tool ---
class ProductListInput(BaseModel):
    category: str | None = Field(default=None, description="Optional category filter")
    query: str | None = Field(default=None, description="Optional search keyword for product name or slug")


class ProductListTool(BaseRealTool):
    """
    Retrieves the official verified catalog of products from the tenant BusinessBrain (SSOT).
    Guarantees consistency between storage and agent retrieval.
    """

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="product_list",
            name="Product List Tool",
            version="1.0.0",
            description="Retrieves the official verified catalog of products from the tenant BusinessBrain (SSOT).",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=ProductListInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "products")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ProductListInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        from packages.services.business_brain_service import BusinessBrainService

        brain = BusinessBrainService(self.db).get_brain(context.tenant_id)
        if not brain or not brain.products:
            return {
                "tenant_id": str(context.tenant_id),
                "total_count": 0,
                "products": [],
                "catalog_text": "لا توجد أي منتجات مسجلة في قاعدة بيانات المنشأة حالياً.",
            }

        query = (parameters.get("query") or "").strip().lower()
        items = []
        for slug, data in brain.products.items():
            if not isinstance(data, dict):
                continue
            name = data.get("name") or data.get("title") or slug
            price = data.get("price", 0)
            unit = data.get("unit") or data.get("currency") or "ريال"
            cat = data.get("category", "")

            if query and query not in name.lower() and query not in slug.lower():
                continue

            items.append({
                "slug": slug,
                "name": name,
                "price": price,
                "unit": unit,
                "category": cat,
            })

        catalog_lines = [f"{i+1}. {p['name']} — {p['price']:g} {p['unit']}" for i, p in enumerate(items)]
        catalog_text = "📦 **قائمة المنتجات المعتمدة:**\n" + "\n".join(catalog_lines)

        return {
            "tenant_id": str(context.tenant_id),
            "total_count": len(items),
            "products": items,
            "catalog_text": catalog_text,
        }

