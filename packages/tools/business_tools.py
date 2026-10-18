from __future__ import annotations

from typing import Any
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
                "pending_tasks": pending_tasks,
                "pending_approvals": pending_approvals,
            },
            "status": "healthy",
        }
