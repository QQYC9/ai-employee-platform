from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from uuid import UUID

import httpx

from packages.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    InboundMessage,
    OutboundDeliveryResult,
)

logger = logging.getLogger(__name__)


class FacebookMessengerConnector(BaseConnector):
    """
    Production connector for Meta Facebook Messenger Platform (Graph API v19.0).
    Supports Webhook verification, HMAC-SHA256 signature checking, connection probing,
    and message dispatch to Facebook Page recipients.
    """

    GRAPH_API_VERSION = "v19.0"
    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        page_id: str,
        access_token: str,
        webhook_verify_token: str | None = None,
        app_secret: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.tenant_id = tenant_id
        self.channel_id = channel_id
        self.page_id = str(page_id).strip()
        self.access_token = str(access_token).strip()
        self.webhook_verify_token = str(webhook_verify_token).strip() if webhook_verify_token else None
        self.app_secret = str(app_secret).strip() if app_secret else None
        self._client = http_client

    @property
    def channel_type(self) -> str:
        return "facebook"

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        params = params or {}
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")

        if mode == "subscribe" and token and challenge:
            if not self.webhook_verify_token:
                return False, "No webhook verify token configured for Facebook channel"
            if hmac.compare_digest(token, self.webhook_verify_token):
                return True, challenge
            return False, "Verify token mismatch"

        if self.app_secret:
            sig_header = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
            if not sig_header:
                return False, "Missing X-Hub-Signature-256 header"
            expected_sig = "sha256=" + hmac.new(
                self.app_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected_sig):
                return False, "Invalid HMAC-SHA256 signature"

        return True, None

    def parse_inbound(
        self,
        payload: dict[str, Any] | bytes,
        headers: dict[str, str] | None = None,
    ) -> list[InboundMessage]:
        if isinstance(payload, bytes):
            try:
                data = json.loads(payload.decode("utf-8"))
            except Exception as exc:
                logger.error("Failed to parse Facebook inbound JSON: %s", exc)
                return []
        else:
            data = payload or {}

        messages: list[InboundMessage] = []
        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                msg = messaging.get("message")
                if not msg or msg.get("is_echo"):
                    continue

                text = msg.get("text", "")
                sender_id = messaging.get("sender", {}).get("id")
                recipient_id = messaging.get("recipient", {}).get("id")
                msg_id = msg.get("mid") or f"fb-{int(time.time() * 1000)}"

                if sender_id and (text or msg.get("attachments")):
                    messages.append(
                        InboundMessage(
                            channel_type=self.channel_type,
                            channel_id=self.channel_id,
                            tenant_id=self.tenant_id,
                            external_message_id=msg_id,
                            sender_id=sender_id,
                            recipient_id=recipient_id,
                            content=text or "[Attachment]",
                            content_type="text" if text else "media",
                            raw_payload=messaging,
                        )
                    )
        return messages

    def send_message(
        self,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/me/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "recipient": {"id": recipient.strip()},
            "message": {"text": content},
            "messaging_type": kwargs.get("messaging_type", "RESPONSE"),
        }

        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.post(url, headers=headers, json=payload)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code in (200, 201):
                data = resp.json()
                return OutboundDeliveryResult(
                    success=True,
                    channel_type=self.channel_type,
                    recipient_id=recipient,
                    external_message_id=data.get("message_id"),
                    status="sent",
                    latency_ms=duration_ms,
                    metadata=data,
                )
            error_data = resp.json().get("error", {}) if resp.text else {}
            error_msg = error_data.get("message", resp.text)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=recipient,
                status="failed",
                error=f"Facebook API error ({resp.status_code}): {error_msg}",
                latency_ms=duration_ms,
                metadata=error_data,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=recipient,
                status="failed",
                error=f"Network exception: {str(exc)}",
                latency_ms=duration_ms,
            )
        finally:
            if should_close:
                client.close()

    def test_connection(self) -> ConnectionTestResult:
        target_id = self.page_id or "me"
        url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{target_id}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.get(url, headers=headers)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code == 200:
                data = resp.json()
                return ConnectionTestResult(
                    connected=True,
                    status="connected",
                    latency_ms=duration_ms,
                    details={
                        "page_id": data.get("id", self.page_id),
                        "page_name": data.get("name"),
                    },
                )
            error_data = resp.json().get("error", {}) if resp.text else {}
            error_msg = error_data.get("message", resp.text)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Meta Graph API error ({resp.status_code}): {error_msg}",
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Connection failure: {str(exc)}",
            )
        finally:
            if should_close:
                client.close()


class InstagramConnector(BaseConnector):
    """
    Production connector for Meta Instagram Messaging API (Graph API v19.0).
    Connects to Instagram Professional Account via Meta Graph API.
    """

    GRAPH_API_VERSION = "v19.0"
    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        instagram_account_id: str,
        access_token: str,
        webhook_verify_token: str | None = None,
        app_secret: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.tenant_id = tenant_id
        self.channel_id = channel_id
        self.instagram_account_id = str(instagram_account_id).strip()
        self.access_token = str(access_token).strip()
        self.webhook_verify_token = str(webhook_verify_token).strip() if webhook_verify_token else None
        self.app_secret = str(app_secret).strip() if app_secret else None
        self._client = http_client

    @property
    def channel_type(self) -> str:
        return "instagram"

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        params = params or {}
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")

        if mode == "subscribe" and token and challenge:
            if not self.webhook_verify_token:
                return False, "No webhook verify token configured for Instagram channel"
            if hmac.compare_digest(token, self.webhook_verify_token):
                return True, challenge
            return False, "Verify token mismatch"

        if self.app_secret:
            sig_header = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256")
            if not sig_header:
                return False, "Missing X-Hub-Signature-256 header"
            expected_sig = "sha256=" + hmac.new(
                self.app_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected_sig):
                return False, "Invalid HMAC-SHA256 signature"

        return True, None

    def parse_inbound(
        self,
        payload: dict[str, Any] | bytes,
        headers: dict[str, str] | None = None,
    ) -> list[InboundMessage]:
        if isinstance(payload, bytes):
            try:
                data = json.loads(payload.decode("utf-8"))
            except Exception as exc:
                logger.error("Failed to parse Instagram inbound JSON: %s", exc)
                return []
        else:
            data = payload or {}

        messages: list[InboundMessage] = []
        for entry in data.get("entry", []):
            for messaging in entry.get("messaging", []):
                msg = messaging.get("message")
                if not msg or msg.get("is_echo"):
                    continue

                text = msg.get("text", "")
                sender_id = messaging.get("sender", {}).get("id")
                recipient_id = messaging.get("recipient", {}).get("id")
                msg_id = msg.get("mid") or f"ig-{int(time.time() * 1000)}"

                if sender_id and (text or msg.get("attachments")):
                    messages.append(
                        InboundMessage(
                            channel_type=self.channel_type,
                            channel_id=self.channel_id,
                            tenant_id=self.tenant_id,
                            external_message_id=msg_id,
                            sender_id=sender_id,
                            recipient_id=recipient_id,
                            content=text or "[Media]",
                            content_type="text" if text else "media",
                            raw_payload=messaging,
                        )
                    )
        return messages

    def send_message(
        self,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/me/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "recipient": {"id": recipient.strip()},
            "message": {"text": content},
        }

        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.post(url, headers=headers, json=payload)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code in (200, 201):
                data = resp.json()
                return OutboundDeliveryResult(
                    success=True,
                    channel_type=self.channel_type,
                    recipient_id=recipient,
                    external_message_id=data.get("message_id"),
                    status="sent",
                    latency_ms=duration_ms,
                    metadata=data,
                )
            error_data = resp.json().get("error", {}) if resp.text else {}
            error_msg = error_data.get("message", resp.text)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=recipient,
                status="failed",
                error=f"Instagram API error ({resp.status_code}): {error_msg}",
                latency_ms=duration_ms,
                metadata=error_data,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=recipient,
                status="failed",
                error=f"Network exception: {str(exc)}",
                latency_ms=duration_ms,
            )
        finally:
            if should_close:
                client.close()

    def test_connection(self) -> ConnectionTestResult:
        target_id = self.instagram_account_id or "me"
        url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{target_id}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
        }

        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.get(url, headers=headers)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code == 200:
                data = resp.json()
                return ConnectionTestResult(
                    connected=True,
                    status="connected",
                    latency_ms=duration_ms,
                    details={
                        "account_id": data.get("id", self.instagram_account_id),
                        "username": data.get("username"),
                    },
                )
            error_data = resp.json().get("error", {}) if resp.text else {}
            error_msg = error_data.get("message", resp.text)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Instagram API error ({resp.status_code}): {error_msg}",
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Connection failure: {str(exc)}",
            )
        finally:
            if should_close:
                client.close()
