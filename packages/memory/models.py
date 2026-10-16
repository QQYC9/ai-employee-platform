from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID


class MemoryType:
    CUSTOMER_PREFERENCE: Final[str] = "customer_preference"
    DECISION: Final[str] = "decision"
    TASK_LEARNING: Final[str] = "task_learning"
    OPERATING_FACT: Final[str] = "operating_fact"
    GENERAL: Final[str] = "general"

    ALL: Final[set[str]] = {
        CUSTOMER_PREFERENCE,
        DECISION,
        TASK_LEARNING,
        OPERATING_FACT,
        GENERAL,
    }


class MemoryStatus:
    CANDIDATE: Final[str] = "candidate"
    ACTIVE: Final[str] = "active"
    DEPRECATED: Final[str] = "deprecated"
    INVALIDATED: Final[str] = "invalidated"
    EXPIRED: Final[str] = "expired"

    ALL: Final[set[str]] = {
        CANDIDATE,
        ACTIVE,
        DEPRECATED,
        INVALIDATED,
        EXPIRED,
    }


class MemoryScope:
    TENANT: Final[str] = "tenant"
    CUSTOMER: Final[str] = "customer"
    CONVERSATION: Final[str] = "conversation"
    AGENT: Final[str] = "agent"


@dataclass
class MemoryCandidate:
    """Represents a potential memory extracted from conversation or task outcomes."""

    content: str
    memory_type: str = MemoryType.GENERAL
    importance: int = 50
    confidence: int = 50
    customer_id: UUID | None = None
    conversation_id: UUID | None = None
    task_id: UUID | None = None
    agent_id: UUID | None = None
    source: str = "unspecified"
    source_id: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class MemoryExtractionResult:
    """Outcome of extracting memory candidates from messages or task outputs."""

    candidates: list[MemoryCandidate]
    extracted_count: int
    source_type: str
    details: dict[str, Any] = field(default_factory=dict)
