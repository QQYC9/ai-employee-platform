from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.context.ranking import ContextRanking
from packages.models.domain import BusinessBrain, Knowledge, Memory


class ContextRetriever:
    def __init__(
        self,
        db: Session,
        ranking: ContextRanking | None = None,
    ):
        self.db = db
        self.ranking = ranking or ContextRanking()

    def get_business_brain(
        self,
        tenant_id: UUID,
    ) -> BusinessBrain | None:
        statement = select(BusinessBrain).where(
            BusinessBrain.tenant_id == tenant_id,
        )

        return self.db.scalar(statement)

    def get_memories(
        self,
        tenant_id: UUID,
        agent_id: UUID | None = None,
        customer_id: UUID | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        if limit <= 0:
            return []

        now = datetime.now(timezone.utc)

        statement = select(Memory).where(
            Memory.tenant_id == tenant_id,
            Memory.status == "active",
            or_(
                Memory.expires_at.is_(None),
                Memory.expires_at > now,
            ),
        )

        if agent_id is not None:
            statement = statement.where(
                (Memory.agent_id == agent_id)
                | (Memory.agent_id.is_(None))
            )

        if customer_id is not None:
            # Enforce customer privacy: only retrieve memories specific to this customer
            # or general tenant memories that are not tied to any customer
            statement = statement.where(
                or_(
                    Memory.metadata_json["customer_id"].as_string() == str(customer_id),
                    Memory.metadata_json.is_(None),
                    ~Memory.metadata_json.has_key("customer_id"),
                )
            )
        else:
            # When customer_id is None, strictly exclude customer-specific memories
            # Only general tenant memories (unassociated with any specific customer) are returned
            statement = statement.where(
                or_(
                    Memory.metadata_json.is_(None),
                    ~Memory.metadata_json.has_key("customer_id"),
                )
            )

        # Retrieve candidates before ranking so that the database does
        # not discard potentially relevant memories using a fixed limit.
        candidates = list(self.db.scalars(statement).all())

        # Defense-in-depth: Python-level customer privacy isolation
        def _get_cust_id(m: Any) -> Any:
            meta = getattr(m, "metadata_json", None) or getattr(m, "metadata", None) or {}
            if isinstance(meta, dict):
                return meta.get("customer_id")
            return None

        if customer_id is not None:
            str_customer_id = str(customer_id)
            candidates = [
                m for m in candidates
                if not _get_cust_id(m)
                or str(_get_cust_id(m)).strip() in ("", str_customer_id)
            ]
        else:
            candidates = [
                m for m in candidates
                if not _get_cust_id(m)
                or str(_get_cust_id(m)).strip() == ""
            ]

        return self.ranking.rank_memories(
            candidates,
            limit=limit,
            query=query,
        )

    def get_knowledge(
        self,
        tenant_id: UUID,
        query: str | None = None,
        customer_id: UUID | None = None,
        limit: int = 20,
    ) -> list[Knowledge]:
        if limit <= 0:
            return []

        statement = select(Knowledge).where(
            Knowledge.tenant_id == tenant_id,
            Knowledge.status == "active",
        )

        if customer_id is not None:
            # Enforce customer privacy: only retrieve knowledge specific to this customer
            # or general tenant knowledge that is not tied to any customer
            try:
                statement = statement.where(
                    or_(
                        Knowledge.metadata_json["customer_id"].as_string() == str(customer_id),
                        Knowledge.metadata_json.is_(None),
                        ~Knowledge.metadata_json.has_key("customer_id"),
                    )
                )
            except Exception:
                pass
        else:
            # When customer_id is None, strictly exclude customer-specific knowledge
            # Only general tenant knowledge (unassociated with any specific customer) is returned
            try:
                statement = statement.where(
                    or_(
                        Knowledge.metadata_json.is_(None),
                        ~Knowledge.metadata_json.has_key("customer_id"),
                    )
                )
            except Exception:
                pass

        candidates = list(self.db.scalars(statement).all())

        # Defense-in-depth: Python-level customer privacy isolation
        def _get_cust_id(k: Any) -> Any:
            meta = getattr(k, "metadata_json", None) or getattr(k, "metadata", None) or {}
            if isinstance(meta, dict):
                return meta.get("customer_id")
            return None

        if customer_id is not None:
            str_customer_id = str(customer_id)
            candidates = [
                k for k in candidates
                if not _get_cust_id(k)
                or str(_get_cust_id(k)).strip() in ("", str_customer_id)
            ]
        else:
            candidates = [
                k for k in candidates
                if not _get_cust_id(k)
                or str(_get_cust_id(k)).strip() == ""
            ]

        return self.ranking.rank_knowledge(
            candidates,
            limit=limit,
            query=query,
        )
