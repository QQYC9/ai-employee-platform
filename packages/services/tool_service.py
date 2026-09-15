from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.models.domain import Tool


class ToolService:
    def __init__(self, db: Session):
        self.db = db

    def list_tools(
        self,
        tenant_id: UUID,
    ) -> list[Tool]:
        statement = (
            select(Tool)
            .where(
                Tool.is_active.is_(True),
                or_(
                    Tool.tenant_id.is_(None),
                    Tool.tenant_id == tenant_id,
                ),
            )
            .order_by(Tool.name)
        )

        return list(self.db.scalars(statement).all())

    def get_tool(
        self,
        tenant_id: UUID,
        tool_id: UUID,
    ) -> Tool | None:
        statement = (
            select(Tool)
            .where(
                Tool.id == tool_id,
                Tool.is_active.is_(True),
                or_(
                    Tool.tenant_id.is_(None),
                    Tool.tenant_id == tenant_id,
                ),
            )
        )

        return self.db.scalar(statement)

    def create_tool(
        self,
        tenant_id: UUID,
        name: str,
        slug: str,
        tool_type: str,
        description: str | None = None,
        config: dict | None = None,
    ) -> Tool:
        name = name.strip()
        slug = slug.strip().lower()
        tool_type = tool_type.strip()

        if not name:
            raise ValueError("Tool name cannot be empty")

        if not slug:
            raise ValueError("Tool slug cannot be empty")

        if not tool_type:
            raise ValueError("Tool type cannot be empty")

        existing = self.db.scalar(
            select(Tool).where(
                Tool.tenant_id == tenant_id,
                Tool.slug == slug,
            )
        )

        if existing is not None:
            raise ValueError(
                "A tool with this slug already exists"
            )

        tool = Tool(
            tenant_id=tenant_id,
            name=name,
            slug=slug,
            description=description,
            tool_type=tool_type,
            config=config or {},
            is_active=True,
        )

        self.db.add(tool)
        self.db.flush()

        return tool

    def update_tool(
        self,
        tenant_id: UUID,
        tool_id: UUID,
        name: str | None = None,
        description: str | None = None,
        tool_type: str | None = None,
        config: dict | None = None,
        is_active: bool | None = None,
    ) -> Tool:
        tool = self.db.scalar(
            select(Tool).where(
                Tool.id == tool_id,
                Tool.tenant_id == tenant_id,
            )
        )

        if tool is None:
            raise ValueError("Tool not found")

        if name is not None:
            name = name.strip()

            if not name:
                raise ValueError(
                    "Tool name cannot be empty"
                )

            tool.name = name

        if description is not None:
            tool.description = description

        if tool_type is not None:
            tool_type = tool_type.strip()

            if not tool_type:
                raise ValueError(
                    "Tool type cannot be empty"
                )

            tool.tool_type = tool_type

        if config is not None:
            tool.config = config

        if is_active is not None:
            tool.is_active = is_active

        self.db.flush()

        return tool
