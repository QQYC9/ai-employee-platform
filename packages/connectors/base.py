from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class InboundMessage:
    """
    Standardized internal representation of an incoming message from any channel.
    """
    channel_type: str
    channel_id: UUID
    tenant_id: UUID
    external_message_id: str
    sender_id: str
    sender_name: str | None = None
    recipient_id: str | None = None
    content: str = ""
    content_type: str = "text"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundDeliveryResult:
    """
    Standard delivery confirmation returned after dispatching an outbound message.
    """
    success: bool
    channel_type: str
    recipient_id: str
    external_message_id: str | None = None
    status: str = "sent"
    error: str | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "channel_type": self.channel_type,
            "recipient_id": self.recipient_id,
            "external_message_id": self.external_message_id,
            "status": self.status,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }


@dataclass
class ConnectionTestResult:
    """
    Diagnostic result returned after probing channel connectivity.
    """
    connected: bool
    status: str
    latency_ms: float = 0.0
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "details": self.details,
        }


class BaseConnector(ABC):
    """
    Unified abstract interface for external communication channels.
    Provides isolation between transport-specific protocols and platform domain logic.
    """

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Normalized channel type identifier (e.g. 'whatsapp', 'telegram', 'email')."""
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Verify incoming webhook request authenticity and challenge.
        Returns: (is_valid, challenge_response_or_error)
        """
        raise NotImplementedError

    @abstractmethod
    def parse_inbound(
        self,
        payload: dict[str, Any] | bytes,
        headers: dict[str, str] | None = None,
    ) -> list[InboundMessage]:
        """
        Extract normalized InboundMessage items from the raw provider payload.
        """
        raise NotImplementedError

    @abstractmethod
    def send_message(
        self,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        """
        Dispatch a message to the external messaging platform.
        """
        raise NotImplementedError

    @abstractmethod
    def test_connection(self) -> ConnectionTestResult:
        """
        Probe external provider API/server to verify credentials and connectivity.
        """
        raise NotImplementedError
