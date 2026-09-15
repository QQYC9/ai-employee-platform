from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Capability, CapabilityTool, Tool


class CapabilityToolService:
    def __init__(self, db: Session):
        self.db = db

    def list_tools(
        self,
        tenant_id: UUID,
        capability_id: UUID,
    ) -> list[Tool]:
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

        statement = (
            select(Tool)
            .join(
                CapabilityTool,
                CapabilityTool.tool_id == Tool.id,
            )
            .where(
                CapabilityTool.tenant_id == tenant_id,
                CapabilityTool.capability_id == capability_id,
                Tool.is_active.is_(True),
                or_(
                    Tool.tenant_id.is_(None),
                    Tool.tenant_id == tenant_id,
                ),
            )
            .order_by(Tool.name)
        )

        return list(
            self.db.scalars(statement).all()
        )

    def attach_tool(
        self,
        tenant_id: UUID,
        capability_id: UUID,
        tool_id: UUID,
        config: dict | None = None,
    ) -> CapabilityTool:
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

        tool = self.db.scalar(
            select(Tool).where(
                Tool.id == tool_id,
                Tool.is_active.is_(True),
                or_(
                    Tool.tenant_id.is_(None),
                    Tool.tenant_id == tenant_id,
                ),
            )
        )

        if tool is None:
            raise ValueError("Tool not found")

        existing = self.db.scalar(
            select(CapabilityTool).where(
                CapabilityTool.tenant_id == tenant_id,
                CapabilityTool.capability_id == capability_id,
                CapabilityTool.tool_id == tool_id,
            )
        )

        if existing is not None:
            raise ValueError(
                "Tool is already attached to this capability"
            )

        assignment = CapabilityTool(
            tenant_id=tenant_id,
            capability_id=capability_id,
            tool_id=tool_id,
            config=config or {},
        )

        self.db.add(assignment)
        self.db.flush()

        return assignment

    def detach_tool(
        self,
        tenant_id: UUID,
        capability_id: UUID,
        tool_id: UUID,
    ) -> None:
        assignment = self.db.scalar(
            select(CapabilityTool).where(
                CapabilityTool.tenant_id == tenant_id,
                CapabilityTool.capability_id == capability_id,
                CapabilityTool.tool_id == tool_id,
            )
        )

        if assignment is None:
            raise ValueError(
                "Tool assignment not found"
            )

        self.db.delete(assignment)
        self.db.flush()
