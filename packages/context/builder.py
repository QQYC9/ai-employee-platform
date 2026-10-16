from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.context.models import AgentContext, TaskContext
from packages.context.retriever import ContextRetriever


class ContextBuilder:
    """Build a tenant-scoped context for a digital employee task."""

    def __init__(self, retriever: ContextRetriever):
        self.retriever = retriever

    def build(
        self,
        tenant_id: UUID,
        task: TaskContext,
        memory_limit: int = 20,
        knowledge_limit: int = 20,
        knowledge_query: str | None = None,
        customer_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> AgentContext:
        if memory_limit < 0:
            raise ValueError("memory_limit cannot be negative")

        if knowledge_limit < 0:
            raise ValueError("knowledge_limit cannot be negative")

        business_brain = self.retriever.get_business_brain(
            tenant_id=tenant_id,
        )

        import inspect
        sig = inspect.signature(self.retriever.get_memories)
        mem_kwargs: dict[str, Any] = {"limit": memory_limit}
        if "agent_id" in sig.parameters:
            mem_kwargs["agent_id"] = task.agent_id
        if "customer_id" in sig.parameters and customer_id is not None:
            mem_kwargs["customer_id"] = customer_id
        if "query" in sig.parameters and task.objective:
            mem_kwargs["query"] = task.objective

        memories = self.retriever.get_memories(
            tenant_id=tenant_id,
            **mem_kwargs,
        )

        knowledge = self.retriever.get_knowledge(
            tenant_id=tenant_id,
            query=knowledge_query or task.objective,
            limit=knowledge_limit,
        )

        business: dict[str, Any] = {}

        if business_brain is not None:
            business = {
                "identity": business_brain.identity,
                "products": business_brain.products,
                "services": business_brain.services,
                "pricing": business_brain.pricing,
                "brand": business_brain.brand,
                "customers": business_brain.customers,
                "competitors": business_brain.competitors,
                "marketing": business_brain.marketing,
                "sales": business_brain.sales,
                "operations": business_brain.operations,
                "policies": business_brain.policies,
                "people": business_brain.people,
                "goals": business_brain.goals,
                "strategy": business_brain.strategy,
                "preferences": business_brain.preferences,
                "performance": business_brain.performance,
                "lessons": business_brain.lessons,
                "version": business_brain.version,
            }

        # Resolve customer profile if available and requested
        customer_data: dict[str, Any] | None = None
        if customer_id is not None and hasattr(self.retriever, "db") and self.retriever.db is not None:
            try:
                from packages.services.customer_service import CustomerService
                c_svc = CustomerService(self.retriever.db)
                cust = c_svc.get_customer(tenant_id, customer_id)
                if cust is not None:
                    customer_data = {
                        "id": str(cust.id),
                        "name": cust.name,
                        "email": cust.email,
                        "phone": cust.phone,
                        "customer_type": cust.customer_type,
                        "profile": cust.profile or {},
                    }
            except Exception:
                customer_data = None

        # Resolve conversation context if available and requested
        conversation_data: dict[str, Any] | None = None
        if conversation_id is not None and hasattr(self.retriever, "db") and self.retriever.db is not None:
            try:
                from packages.services.conversation_service import ConversationService
                conv_svc = ConversationService(self.retriever.db)
                conv = conv_svc.get_conversation(tenant_id, conversation_id)
                if conv is not None:
                    conversation_data = {
                        "id": str(conv.id),
                        "subject": conv.subject,
                        "status": conv.status,
                        "metadata": conv.metadata_json or {},
                    }
            except Exception:
                conversation_data = None

        return AgentContext(
            tenant_id=tenant_id,
            task=task,
            business=business,
            customer=customer_data,
            conversation=conversation_data,
            memories=[
                self._memory_to_dict(memory)
                for memory in memories
            ],
            knowledge=[
                self._knowledge_to_dict(item)
                for item in knowledge
            ],
            metadata={
                "memory_count": len(memories),
                "knowledge_count": len(knowledge),
                "is_untrusted_data": True,
            },
        )

    @staticmethod
    def _memory_to_dict(memory: Any) -> dict[str, Any]:
        return {
            "id": str(memory.id),
            "agent_id": (
                str(memory.agent_id)
                if memory.agent_id is not None
                else None
            ),
            "user_id": (
                str(memory.user_id)
                if memory.user_id is not None
                else None
            ),
            "memory_type": memory.memory_type,
            "content": memory.content,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "metadata": getattr(memory, "metadata_json", getattr(memory, "metadata", {})),
            "expires_at": (
                memory.expires_at.isoformat()
                if getattr(memory, "expires_at", None) is not None
                else None
            ),
            "is_untrusted_data": True,
        }

    @staticmethod
    def _knowledge_to_dict(item: Any) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "title": item.title,
            "content": item.content,
            "knowledge_type": item.knowledge_type,
            "metadata": item.metadata_json,
            "version": item.version,
        }
