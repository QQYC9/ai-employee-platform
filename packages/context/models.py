from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class TaskContext:
    task_id: UUID
    agent_id: UUID | None
    objective: str
    title: str
    priority: str
    status: str


@dataclass(frozen=True)
class AgentContext:
    tenant_id: UUID
    task: TaskContext

    business: dict[str, Any] = field(default_factory=dict)
    customer: dict[str, Any] | None = None
    conversation: dict[str, Any] | None = None

    memories: list[dict[str, Any]] = field(default_factory=list)
    knowledge: list[dict[str, Any]] = field(default_factory=list)

    capabilities: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    policies: list[dict[str, Any]] = field(default_factory=list)

    metadata: dict[str, Any] = field(default_factory=dict)
