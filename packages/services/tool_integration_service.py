from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Integration, Tool, ToolIntegration


class ToolIntegrationService:
    def __init__(self, db: Session):
        self.db = db

    def list_integrations(
        self,
        tenant_id: UUID,
        tool_id: UUID,
    ) -> list[Integration]:
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

        statement = (
            select(Integration)
            .join(
                ToolIntegration,
                ToolIntegration.integration_id == Integration.id,
            )
            .where(
                ToolIntegration.tenant_id == tenant_id,
                ToolIntegration.tool_id == tool_id,
                or_(
                    Integration.tenant_id.is_(None),
                    Integration.tenant_id == tenant_id,
                ),
            )
            .order_by(Integration.name)
        )

        return list(
            self.db.scalars(statement).all()
        )

    def attach_integration(
        self,
        tenant_id: UUID,
        tool_id: UUID,
        integration_id: UUID,
        config: dict | None = None,
    ) -> ToolIntegration:
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

        integration = self.db.scalar(
            select(Integration).where(
                Integration.id == integration_id,
                or_(
                    Integration.tenant_id.is_(None),
                    Integration.tenant_id == tenant_id,
                ),
            )
        )

        if integration is None:
            raise ValueError("Integration not found")

        existing = self.db.scalar(
            select(ToolIntegration).where(
                ToolIntegration.tenant_id == tenant_id,
                ToolIntegration.tool_id == tool_id,
                ToolIntegration.integration_id == integration_id,
            )
        )

        if existing is not None:
            raise ValueError(
                "Integration is already attached to this tool"
            )

        assignment = ToolIntegration(
            tenant_id=tenant_id,
            tool_id=tool_id,
            integration_id=integration_id,
            config=config or {},
        )

        self.db.add(assignment)
        self.db.flush()

        return assignment

    def detach_integration(
        self,
        tenant_id: UUID,
        tool_id: UUID,
        integration_id: UUID,
    ) -> None:
        assignment = self.db.scalar(
            select(ToolIntegration).where(
                ToolIntegration.tenant_id == tenant_id,
                ToolIntegration.tool_id == tool_id,
                ToolIntegration.integration_id == integration_id,
            )
        )

        if assignment is None:
            raise ValueError(
                "Integration assignment not found"
            )

        self.db.delete(assignment)
        self.db.flush()
