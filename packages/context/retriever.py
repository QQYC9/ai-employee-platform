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

        # Retrieve candidates before ranking so that the database does
        # not discard potentially relevant memories using a fixed limit.
        candidates = list(self.db.scalars(statement).all())

        return self.ranking.rank_memories(
            candidates,
            limit=limit,
        )

    def get_knowledge(
        self,
        tenant_id: UUID,
        query: str | None = None,
        limit: int = 20,
    ) -> list[Knowledge]:
        if limit <= 0:
            return []

        statement = select(Knowledge).where(
            Knowledge.tenant_id == tenant_id,
            Knowledge.status == "active",
        )

        if query:
            query = query.strip()

            if query:
                pattern = f"%{query}%"

                statement = statement.where(
                    or_(
                        Knowledge.title.ilike(pattern),
                        Knowledge.content.ilike(pattern),
                    )
                )

        statement = statement.order_by(
            Knowledge.updated_at.desc(),
        ).limit(limit)

        return list(self.db.scalars(statement).all())
