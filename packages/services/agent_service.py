from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Agent


class AgentService:
    """
    Business logic for Digital Employee operations.

    All tenant ownership checks are explicit and mandatory.
    """

    def __init__(self, db: Session):
        self.db = db

    def list_agents(self, tenant_id: UUID) -> list[Agent]:
        """Return all active agents belonging to the tenant."""
        statement = (
            select(Agent)
            .where(
                Agent.tenant_id == tenant_id,
                Agent.status != "deleted",
            )
            .order_by(Agent.created_at)
        )

        return list(self.db.scalars(statement).all())

    def get_agent(
        self,
        tenant_id: UUID,
        agent_id: UUID,
    ) -> Agent | None:
        """Return an agent only when it belongs to the tenant."""
        return self.db.scalar(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
                Agent.status != "deleted",
            )
        )

    def create_agent(
        self,
        tenant_id: UUID,
        name: str,
        agent_type: str = "main",
    ) -> Agent:
        """Create a Digital Employee for the tenant."""
        name = name.strip()

        if not name:
            raise ValueError("Agent name cannot be empty")

        agent_type = agent_type.strip()

        if not agent_type:
            raise ValueError("Agent type cannot be empty")

        agent = Agent(
            tenant_id=tenant_id,
            name=name,
            agent_type=agent_type,
            status="active",
            system_config={},
        )

        self.db.add(agent)
        self.db.flush()

        return agent

    def update_agent(
        self,
        tenant_id: UUID,
        agent_id: UUID,
        name: str | None = None,
        status: str | None = None,
    ) -> Agent:
        """Update an agent belonging to the tenant."""
        agent = self.get_agent(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        if agent is None:
            raise ValueError("Agent not found")

        if name is not None:
            name = name.strip()

            if not name:
                raise ValueError("Agent name cannot be empty")

            agent.name = name

        if status is not None:
            allowed_statuses = {
                "active",
                "paused",
                "disabled",
            }

            if status not in allowed_statuses:
                raise ValueError("Invalid agent status")

            agent.status = status

        self.db.flush()

        return agent
