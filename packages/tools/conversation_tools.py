from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Conversation, Customer, Message
from packages.tools.base import BaseRealTool
from packages.tools.contract import (
    ToolContract,
    ToolExecutionContext,
    ToolRiskLevel,
)


# --- 1. Conversation Search ---
class ConversationSearchInput(BaseModel):
    query: str | None = Field(default=None, description="Search term for customer name, phone, subject, or message content")
    status: str | None = Field(default=None, description="Conversation status filter (e.g. 'open', 'escalated', 'closed', 'resolved')")
    needs_human: bool | None = Field(default=None, description="Filter for conversations escalated to a human agent")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of results to return")


class ConversationSearchTool(BaseRealTool):
    """Searches tenant conversations with customer details and escalation status."""

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="conversation_search",
            name="Conversation Search Tool",
            version="1.0.0",
            description="Searches for conversations within the tenant by status, customer name, query, or escalation flag.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=ConversationSearchInput.model_json_schema(),
            output_schema={"type": "array", "items": {"type": "object"}},
            required_permissions=[("read", "conversations")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ConversationSearchInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> list[dict[str, Any]]:
        limit = parameters.get("limit", 10)
        status = parameters.get("status")
        needs_human = parameters.get("needs_human")
        query = parameters.get("query")

        stmt = select(Conversation).where(Conversation.tenant_id == context.tenant_id)

        if status and status.lower() != "any":
            stmt = stmt.where(Conversation.status == status.lower())

        if needs_human is True:
            stmt = stmt.where(
                or_(
                    Conversation.status == "escalated",
                    Conversation.metadata_json["needs_human"].as_boolean() == True,
                    Conversation.metadata_json["escalated_at"].is_not(None),
                )
            )

        if query and query.strip():
            clean_q = f"%{query.strip()}%"
            # Match customer name or subject
            customer_match = select(Customer.id).where(
                Customer.tenant_id == context.tenant_id,
                or_(
                    Customer.name.ilike(clean_q),
                    Customer.phone.ilike(clean_q),
                    Customer.email.ilike(clean_q),
                ),
            )
            stmt = stmt.where(
                or_(
                    Conversation.subject.ilike(clean_q),
                    Conversation.customer_id.in_(customer_match),
                )
            )

        stmt = stmt.order_by(desc(Conversation.last_message_at), desc(Conversation.started_at)).limit(limit)
        conversations = self.db.scalars(stmt).all()

        results = []
        for conv in conversations:
            customer = None
            if conv.customer_id:
                customer = self.db.scalar(
                    select(Customer).where(Customer.id == conv.customer_id, Customer.tenant_id == context.tenant_id)
                )

            meta = conv.metadata_json or {}
            is_escalated = conv.status == "escalated" or meta.get("needs_human") is True or meta.get("escalation_reason") is not None

            results.append({
                "conversation_id": str(conv.id),
                "customer_id": str(conv.customer_id) if conv.customer_id else None,
                "customer_name": customer.name if customer else (meta.get("customer_name") or "عميل"),
                "customer_phone": customer.phone if customer else meta.get("customer_phone"),
                "status": conv.status,
                "is_escalated": is_escalated,
                "escalation_reason": meta.get("escalation_reason"),
                "escalated_at": meta.get("escalated_at"),
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
                "subject": conv.subject,
            })

        return results


# --- 2. Conversation Get Messages ---
class ConversationGetMessagesInput(BaseModel):
    conversation_id: str = Field(description="UUID of the conversation")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of messages to fetch")


class ConversationGetMessagesTool(BaseRealTool):
    """Retrieves full chronological message log of a conversation with strict tenant isolation."""

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="conversation_get_messages",
            name="Conversation Get Messages Tool",
            version="1.0.0",
            description="Fetches chronological message log for a specific conversation within the tenant.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=ConversationGetMessagesInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "conversations"), ("read", "messages")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ConversationGetMessagesInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        raw_id = parameters["conversation_id"].strip()
        try:
            conv_id = UUID(raw_id)
        except ValueError:
            raise ValueError(f"Invalid conversation_id UUID format: '{raw_id}'")

        # Verify conversation belongs to tenant
        conv = self.db.scalar(
            select(Conversation).where(Conversation.id == conv_id, Conversation.tenant_id == context.tenant_id)
        )
        if conv is None:
            raise ValueError(f"Conversation '{raw_id}' not found for tenant")

        limit = parameters.get("limit", 20)
        messages = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conv_id, Message.tenant_id == context.tenant_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        ).all()

        return {
            "conversation_id": str(conv.id),
            "status": conv.status,
            "subject": conv.subject,
            "message_count": len(messages),
            "messages": [
                {
                    "message_id": str(m.id),
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }


# --- 3. Conversation Summarize ---
class ConversationSummarizeInput(BaseModel):
    conversation_id: str | None = Field(default=None, description="UUID of the conversation to summarize (optional)")
    query: str | None = Field(default=None, description="Optional search query or description to locate conversation (e.g. 'محادثة العميل الذي طلب موظف بشري')")


class ConversationSummarizeTool(BaseRealTool):
    """
    Summarizes a customer conversation, highlighting customer needs,
    agent responses, and escalation reasons if human assistance was requested.
    """

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="conversation_summarize",
            name="Conversation Summarize Tool",
            version="1.0.0",
            description="Summarizes real conversation exchanges, customer questions, agent answers, and escalation status.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=ConversationSummarizeInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "conversations"), ("read", "messages")],
            default_timeout=5.0,
            max_timeout=20.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ConversationSummarizeInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        raw_id = parameters.get("conversation_id")
        query = (parameters.get("query") or "").strip().lower()

        target_conv: Conversation | None = None

        if raw_id and raw_id.strip():
            try:
                cid = UUID(raw_id.strip())
                target_conv = self.db.scalar(
                    select(Conversation).where(Conversation.id == cid, Conversation.tenant_id == context.tenant_id)
                )
            except ValueError:
                pass

        # If not resolved by ID, resolve by query or find most recent escalated conversation
        if target_conv is None:
            is_escalation_query = any(k in query for k in ("بشري", "موظف", "تصعيد", "إنسان", "خدمة عملاء", "human", "escalat"))

            stmt = select(Conversation).where(
                Conversation.tenant_id == context.tenant_id,
                Conversation.customer_id.is_not(None),  # Strictly filter customer conversations, excluding owner chats
            )

            if is_escalation_query or not query:
                # Prioritize escalated conversations
                stmt = stmt.where(
                    or_(
                        Conversation.status == "escalated",
                        Conversation.metadata_json["needs_human"].as_boolean() == True,
                        Conversation.metadata_json["escalation_reason"].is_not(None),
                    )
                )

            stmt = stmt.order_by(desc(Conversation.last_message_at), desc(Conversation.started_at))
            target_conv = self.db.scalar(stmt)

        # Fallback to any recent customer conversation if none escalated
        if target_conv is None:
            stmt = (
                select(Conversation)
                .where(
                    Conversation.tenant_id == context.tenant_id,
                    Conversation.customer_id.is_not(None),  # Strictly customer conversations
                )
                .order_by(desc(Conversation.last_message_at), desc(Conversation.started_at))
            )
            target_conv = self.db.scalar(stmt)

        if target_conv is None:
            return {
                "found": False,
                "summary": "لم يتم العثور على أي محادثات عملاء مسجلة للمنشأة لتلخيصها.",
                "conversation_id": None,
            }

        # Fetch customer details
        customer_name = "عميل"
        customer_phone = None
        if target_conv.customer_id:
            customer = self.db.scalar(
                select(Customer).where(Customer.id == target_conv.customer_id, Customer.tenant_id == context.tenant_id)
            )
            if customer:
                customer_name = customer.name
                customer_phone = customer.phone

        # Fetch messages
        messages = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == target_conv.id, Message.tenant_id == context.tenant_id)
            .order_by(Message.created_at.asc())
        ).all()

        meta = target_conv.metadata_json or {}
        is_escalated = target_conv.status == "escalated" or meta.get("needs_human") is True or meta.get("escalation_reason") is not None
        reason = meta.get("escalation_reason", "طلب التحدث إلى موظف بشري" if is_escalated else "محادثة استفسار عام")

        # Build chronological dialogue excerpt
        dialogue_lines = []
        customer_requests = []
        for m in messages:
            content = (m.content or "").strip()
            sender = "العميل" if m.sender_type == "customer" else ("الموظف الذكي" if m.sender_type == "agent" else m.sender_type)
            dialogue_lines.append(f"{sender}: {content}")
            if m.sender_type == "customer":
                customer_requests.append(content)

        summary_text = (
            f"👤 محادثة العميل: {customer_name}" + (f" ({customer_phone})" if customer_phone else "") + "\n"
            f"📌 الحالة: {'🚨 تم التصعيد لموظف بشري' if is_escalated else target_conv.status}\n"
            f"❓ سبب التصعيد / الاستفسار: {reason}\n"
            f"💬 عدد الرسائل: {len(messages)}\n"
        )
        if customer_requests:
            summary_text += f"📝 ملخص استفسار العميل: \"{customer_requests[-1]}\"\n"
        if dialogue_lines:
            summary_text += "📜 مقتطف من المحادثة:\n" + "\n".join(dialogue_lines[-4:])

        return {
            "found": True,
            "conversation_id": str(target_conv.id),
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "status": target_conv.status,
            "is_escalated": is_escalated,
            "escalation_reason": reason,
            "message_count": len(messages),
            "summary": summary_text,
            "latest_customer_message": customer_requests[-1] if customer_requests else None,
        }


# --- 4. Conversation Escalation Status ---
class ConversationEscalationStatusInput(BaseModel):
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of escalated conversations to retrieve")


class ConversationEscalationStatusTool(BaseRealTool):
    """Lists customer conversations currently awaiting human assistance."""

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="conversation_escalation_status",
            name="Conversation Escalation Status Tool",
            version="1.0.0",
            description="Lists all customer conversations escalated to a human agent and awaiting action.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=ConversationEscalationStatusInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "conversations")],
            default_timeout=5.0,
            max_timeout=15.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ConversationEscalationStatusInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        limit = parameters.get("limit", 5)
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == context.tenant_id,
                or_(
                    Conversation.status == "escalated",
                    Conversation.metadata_json["needs_human"].as_boolean() == True,
                    Conversation.metadata_json["escalation_reason"].is_not(None),
                ),
            )
            .order_by(desc(Conversation.last_message_at), desc(Conversation.started_at))
            .limit(limit)
        )
        escalated_convs = self.db.scalars(stmt).all()

        items = []
        for conv in escalated_convs:
            customer = None
            if conv.customer_id:
                customer = self.db.scalar(
                    select(Customer).where(Customer.id == conv.customer_id, Customer.tenant_id == context.tenant_id)
                )
            meta = conv.metadata_json or {}
            items.append({
                "conversation_id": str(conv.id),
                "customer_name": customer.name if customer else (meta.get("customer_name") or "عميل"),
                "customer_phone": customer.phone if customer else meta.get("customer_phone"),
                "escalated_at": meta.get("escalated_at"),
                "reason": meta.get("escalation_reason", "طلب التحدث إلى موظف بشري"),
            })

        return {
            "total_pending_escalations": len(items),
            "escalations": items,
        }


# --- 5. Conversation Summarize All Customer Conversations ---
class ConversationSummarizeAllInput(BaseModel):
    status: str | None = Field(default=None, description="Optional status filter (e.g. 'open', 'escalated', 'closed')")
    needs_human_only: bool = Field(default=False, description="Filter only conversations requiring human assistance")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum number of customer conversations to include")


class ConversationSummarizeAllTool(BaseRealTool):
    """
    Summarizes all customer conversations for the tenant.
    Strictly excludes internal owner management conversations (customer_id is None).
    """

    def __init__(self, db: Session):
        self.db = db

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="conversation_summarize_all",
            name="Conversation Summarize All Tool",
            version="1.0.0",
            description="Aggregates and summarizes all customer conversations for the tenant, excluding internal owner chats.",
            risk_level=ToolRiskLevel.READ_ONLY,
            requires_approval=False,
            input_schema=ConversationSummarizeAllInput.model_json_schema(),
            output_schema={"type": "object"},
            required_permissions=[("read", "conversations"), ("read", "messages")],
            default_timeout=10.0,
            max_timeout=30.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return ConversationSummarizeAllInput(**parameters).model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        status = parameters.get("status")
        needs_human_only = parameters.get("needs_human_only", False)
        limit = parameters.get("limit", 50)

        # STRICT customer_id.is_not(None) filter to isolate customer conversations
        stmt = (
            select(Conversation)
            .where(
                Conversation.tenant_id == context.tenant_id,
                Conversation.customer_id.is_not(None),
            )
        )
        if status and status.lower() != "any":
            stmt = stmt.where(Conversation.status == status.lower())

        if needs_human_only:
            stmt = stmt.where(
                or_(
                    Conversation.status == "escalated",
                    Conversation.metadata_json["needs_human"].as_boolean() == True,
                    Conversation.metadata_json["escalation_reason"].is_not(None),
                )
            )

        stmt = stmt.order_by(desc(Conversation.last_message_at), desc(Conversation.started_at)).limit(limit)
        conversations = self.db.scalars(stmt).all()

        if not conversations:
            return {
                "tenant_id": str(context.tenant_id),
                "total_conversations": 0,
                "conversations": [],
                "summary": "لم يتم العثور على أي محادثات مع الزبائن حتى الآن في المنشأة.",
            }

        summaries = []
        for conv in conversations:
            customer = self.db.scalar(
                select(Customer).where(Customer.id == conv.customer_id, Customer.tenant_id == context.tenant_id)
            )
            customer_name = customer.name if customer else "عميل غير مسجل"
            customer_phone = customer.phone if customer else "غير متوفر"

            # Get last messages
            messages = self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.tenant_id == context.tenant_id)
                .order_by(Message.created_at.desc())
                .limit(5)
            ).all()

            last_inquiry = "استفسار عام"
            for m in messages:
                if m.sender_type == "customer" and m.content:
                    last_inquiry = m.content.strip()
                    break

            meta = conv.metadata_json or {}
            is_escalated = conv.status == "escalated" or meta.get("needs_human") is True or meta.get("escalation_reason") is not None
            escalation_reason = meta.get("escalation_reason")

            summaries.append({
                "conversation_id": str(conv.id),
                "customer_id": str(conv.customer_id),
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "status": conv.status,
                "is_escalated": is_escalated,
                "escalation_reason": escalation_reason,
                "last_inquiry": last_inquiry,
                "message_count": len(messages),
                "last_activity": conv.last_message_at.isoformat() if conv.last_message_at else None,
            })

        lines = [f"📊 **تقرير شامل لجميع محادثات العملاء ({len(summaries)} محادثة):**\n"]
        for idx, item in enumerate(summaries, 1):
            esc_badge = " [🚨 تصعيد لموظف بشري]" if item["is_escalated"] else ""
            lines.append(
                f"{idx}. **العميل:** {item['customer_name']} ({item['customer_phone']}){esc_badge}\n"
                f"   - **الحالة:** {item['status']}\n"
                f"   - **آخر استفسار:** \"{item['last_inquiry']}\"\n"
                + (f"   - **سبب التصعيد:** {item['escalation_reason']}\n" if item["escalation_reason"] else "")
            )

        return {
            "tenant_id": str(context.tenant_id),
            "total_conversations": len(summaries),
            "conversations": summaries,
            "summary": "\n".join(lines),
        }

