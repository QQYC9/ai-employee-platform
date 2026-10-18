from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID


class ToolRiskLevel(str, Enum):
    """Risk classification for tools to enforce safety and approval policies."""
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ToolContract:
    """
    Standard contract defining tool specifications, safety boundaries, and capabilities.
    """
    slug: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    requires_approval: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    required_permissions: list[tuple[str, str]] = field(default_factory=list)
    default_timeout: float = 10.0
    max_timeout: float = 30.0
    supports_idempotency: bool = False
    rate_limit_per_minute: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "required_permissions": [
                {"action": action, "resource": resource}
                for action, resource in self.required_permissions
            ],
            "default_timeout": self.default_timeout,
            "max_timeout": self.max_timeout,
            "supports_idempotency": self.supports_idempotency,
            "rate_limit_per_minute": self.rate_limit_per_minute,
        }


@dataclass(frozen=True)
class ToolExecutionContext:
    """
    Runtime execution context identifying the tenant, actor, and workflow boundary.
    """
    tenant_id: UUID
    agent_id: UUID | None = None
    task_id: UUID | None = None
    conversation_id: UUID | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StandardToolResult:
    """
    Normalized result structure returned by all real tools.
    """
    success: bool
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "error_code": self.error_code,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }
