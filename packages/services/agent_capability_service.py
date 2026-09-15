from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Agent, AgentCapability, Capability


class AgentCapabilityService:
    def __init__(self, db: Session):
        self.db = db

    def list_capabilities(
        self,
        tenant_id: UUID,
        agent_id: UUID,
    ) -> list[Capability]:
        agent = self.db.scalar(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
                Agent.status != "deleted",
            )
        )

        if agent is None:
            raise ValueError("Agent not found")

        statement = (
            select(Capability)
            .join(
                AgentCapability,
                AgentCapability.capability_id == Capability.id,
            )
            .where(
                AgentCapability.tenant_id == tenant_id,
                AgentCapability.agent_id == agent_id,
                Capability.is_active.is_(True),
                or_(
                    Capability.tenant_id.is_(None),
                    Capability.tenant_id == tenant_id,
                ),
            )
            .order_by(Capability.name)
        )

        return list(self.db.scalars(statement).all())

    def attach_capability(
        self,
        tenant_id: UUID,
        agent_id: UUID,
        capability_id: UUID,
        config: dict | None = None,
    ) -> AgentCapability:
        agent = self.db.scalar(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
                Agent.status != "deleted",
            )
        )

        if agent is None:
            raise ValueError("Agent not found")

        capability = self.db.scalar(
            select(Capability).where(
                Capability.id == capability_id,
                Capability.is_active.is_(True),
                or_(
                    Capability.tenant_id.is_(None),
                    Capability.tenant_id == tenant_id,
                ),
            )
        )

        if capability is None:
            raise ValueError("Capability not found")

        existing = self.db.scalar(
            select(AgentCapability).where(
                AgentCapability.tenant_id == tenant_id,
                AgentCapability.agent_id == agent_id,
                AgentCapability.capability_id == capability_id,
            )
        )

        if existing is not None:
            raise ValueError(
                "Capability is already attached to this agent"
            )

        assignment = AgentCapability(
            tenant_id=tenant_id,
            agent_id=agent_id,
            capability_id=capability_id,
            config=config or {},
        )

        self.db.add(assignment)
        self.db.flush()

        return assignment

    def detach_capability(
        self,
        tenant_id: UUID,
        agent_id: UUID,
        capability_id: UUID,
    ) -> None:
        assignment = self.db.scalar(
            select(AgentCapability).where(
                AgentCapability.tenant_id == tenant_id,
                AgentCapability.agent_id == agent_id,
                AgentCapability.capability_id == capability_id,
            )
        )

        if assignment is None:
            raise ValueError(
                "Capability assignment not found"
            )

        self.db.delete(assignment)
        self.db.flush()
