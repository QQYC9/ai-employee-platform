from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from packages.tools.base import BaseRealTool
from packages.tools.business_tools import (
    BusinessSummaryTool,
    CustomerCreateOrUpdateTool,
    CustomerGetTool,
    CustomerSearchTool,
    TaskCreateTool,
    TaskQueryTool,
)
from packages.tools.contract import (
    ToolContract,
    ToolExecutionContext,
)
from packages.tools.document_tool import DocumentGeneratorTool
from packages.tools.executor import ToolExecutor
from packages.tools.http_tool import HttpRequestTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central repository and binding mechanism for all real platform tools.
    Connects tool definitions and handlers to ToolExecutor, API routers, and AI Agents.
    """

    def __init__(self):
        self._tools: dict[str, BaseRealTool] = {}

    def register(self, tool: BaseRealTool) -> None:
        slug = tool.contract.slug.strip().lower()
        self._tools[slug] = tool

    def get(self, slug: str) -> BaseRealTool | None:
        return self._tools.get(slug.strip().lower())

    def list_contracts(self) -> list[ToolContract]:
        return [tool.contract for tool in self._tools.values()]

    def bind_to_executor(
        self,
        executor: ToolExecutor,
        tenant_id: UUID | None = None,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> None:
        """
        Binds all registered tools to a ToolExecutor instance.
        Wraps tool execution to handle context extraction, parameter validation,
        and idempotency flags.
        """
        for slug, tool in self._tools.items():
            handler = self._create_executor_handler(tool, default_tenant_id=tenant_id, default_agent_id=agent_id, default_task_id=task_id)
            setattr(handler, "supports_idempotency", tool.contract.supports_idempotency)
            executor.register_handler(slug, handler)

    def _create_executor_handler(
        self,
        tool: BaseRealTool,
        default_tenant_id: UUID | None = None,
        default_agent_id: UUID | None = None,
        default_task_id: UUID | None = None,
    ) -> Callable[..., Any]:
        def handler(**kwargs: Any) -> Any:
            # Extract or resolve execution context
            ctx = kwargs.pop("_context", None)
            if ctx is not None and isinstance(ctx, ToolExecutionContext):
                if default_tenant_id is not None and ctx.tenant_id != default_tenant_id:
                    raise PermissionError("Cross-tenant execution prohibited")
            else:
                untrusted_t_id = kwargs.pop("tenant_id", None)
                t_id = default_tenant_id or untrusted_t_id
                a_id = kwargs.pop("agent_id", None) or default_agent_id
                tsk_id = kwargs.pop("task_id", None) or default_task_id
                if t_id is None:
                    # Fallback UUID for safety in unit tests without tenant context
                    from uuid import uuid4
                    t_id = uuid4()
                elif isinstance(t_id, str):
                    t_id = UUID(t_id)

                ctx = ToolExecutionContext(
                    tenant_id=t_id,
                    agent_id=UUID(a_id) if isinstance(a_id, str) else a_id,
                    task_id=UUID(tsk_id) if isinstance(tsk_id, str) else tsk_id,
                )

            result = tool.execute(ctx, **kwargs)
            if not result.success:
                raise ValueError(f"Tool '{tool.contract.slug}' failed: {result.error}")
            return result.data

        return handler


def create_default_registry(db: Session) -> ToolRegistry:
    """
    Creates and populates the standard ToolRegistry with all Phase 15 real tools.
    """
    registry = ToolRegistry()
    registry.register(HttpRequestTool())
    registry.register(CustomerSearchTool(db))
    registry.register(CustomerGetTool(db))
    registry.register(CustomerCreateOrUpdateTool(db))
    registry.register(TaskQueryTool(db))
    registry.register(TaskCreateTool(db))
    registry.register(BusinessSummaryTool(db))
    registry.register(DocumentGeneratorTool(db))
    return registry
