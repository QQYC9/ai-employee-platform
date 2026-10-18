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


class WhatsAppCloudConnector(BaseConnector):
    """
    Production connector for Meta WhatsApp Business Platform Cloud API (Graph API v19.0).
    Enforces webhook verification, HMAC-SHA256 signature validation, and message dispatch.
    """

    GRAPH_API_VERSION = "v19.0"
    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        phone_number_id: str,
        access_token: str,
        webhook_verify_token: str | None = None,
        app_secret: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.tenant_id = tenant_id
        self.channel_id = channel_id
        self.phone_number_id = str(phone_number_id).strip()
        self.access_token = str(access_token).strip()
        self.webhook_verify_token = str(webhook_verify_token).strip() if webhook_verify_token else None
        self.app_secret = str(app_secret).strip() if app_secret else None
        self._client = http_client

    @property
    def channel_type(self) -> str:
        return "whatsapp"

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Verifies either GET subscription challenge or POST HMAC-SHA256 signature.
        """
        params = params or {}

        # 1. GET Challenge verification
        hub_mode = params.get("hub.mode") or params.get("hub_mode")
        if hub_mode == "subscribe":
            verify_token = params.get("hub.verify_token") or params.get("hub_verify_token")
            challenge = params.get("hub.challenge") or params.get("hub_challenge")
            if not self.webhook_verify_token:
                logger.warning("WhatsApp webhook verification failed: no verify token configured")
                return False, "Verify token not configured"
            if verify_token == self.webhook_verify_token:
                return True, challenge
            return False, "Verify token mismatch"

        # 2. POST HMAC-SHA256 signature verification
        if self.app_secret:
            sig_header = (
                headers.get("x-hub-signature-256")
                or headers.get("X-Hub-Signature-256")
                or ""
            ).strip()

            if not sig_header:
                logger.warning("WhatsApp webhook failed: missing X-Hub-Signature-256 header")
                return False, "Missing signature header"

            if sig_header.startswith("sha256="):
                sig_header = sig_header[7:]

            expected_sig = hmac.new(
                self.app_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(sig_header.lower(), expected_sig.lower()):
                logger.warning("WhatsApp webhook signature mismatch")
                return False, "Signature mismatch"

        return True, None

    def parse_inbound(
        self,
        payload: dict[str, Any] | bytes,
        headers: dict[str, str] | None = None,
    ) -> list[InboundMessage]:
        """
        Parses incoming Meta WhatsApp Cloud API webhook notifications.
        """
        if isinstance(payload, bytes):
            try:
                data = json.loads(payload.decode("utf-8"))
            except Exception:
                return []
        else:
            data = payload or {}

        messages: list[InboundMessage] = []
        entries = data.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {
                    c.get("wa_id"): c.get("profile", {}).get("name")
                    for c in value.get("contacts", [])
                }
                raw_msgs = value.get("messages", [])
                for msg in raw_msgs:
                    msg_id = msg.get("id")
                    from_id = msg.get("from")
                    msg_type = msg.get("type", "text")
                    timestamp_raw = msg.get("timestamp")

                    content = ""
                    if msg_type == "text":
                        content = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        int_type = interactive.get("type")
                        if int_type == "button_reply":
                            content = interactive.get("button_reply", {}).get("title", "")
                        elif int_type == "list_reply":
                            content = interactive.get("list_reply", {}).get("title", "")
                    elif msg_type in ("image", "document", "audio", "video"):
                        content = f"[{msg_type.upper()} attachment: {msg.get(msg_type, {}).get('filename') or msg_id}]"

                    ts = datetime.now(timezone.utc)
                    if timestamp_raw:
                        try:
                            ts = datetime.fromtimestamp(int(timestamp_raw), tz=timezone.utc)
                        except Exception:
                            pass

                    if msg_id and from_id:
                        messages.append(
                            InboundMessage(
                                channel_type=self.channel_type,
                                channel_id=self.channel_id,
                                tenant_id=self.tenant_id,
                                external_message_id=msg_id,
                                sender_id=str(from_id),
                                sender_name=contacts.get(from_id),
                                recipient_id=self.phone_number_id,
                                content=content,
                                content_type=msg_type,
                                timestamp=ts,
                                raw_payload=msg,
                            )
                        )
        return messages

    def send_message(
        self,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        """
        Sends an outbound text or template message via Meta Graph API.
        """
        clean_recipient = str(recipient).strip().replace("+", "").replace("-", "").replace(" ", "")
        url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": content,
            },
        }

        client = self._client or httpx.Client(timeout=15.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.post(url, headers=headers, json=payload)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code in (200, 201):
                data = resp.json()
                msg_id = None
                messages_data = data.get("messages", [])
                if messages_data and isinstance(messages_data, list):
                    msg_id = messages_data[0].get("id")

                return OutboundDeliveryResult(
                    success=True,
                    channel_type=self.channel_type,
                    recipient_id=clean_recipient,
                    external_message_id=msg_id,
                    status="sent",
                    latency_ms=duration_ms,
                    metadata={"provider": "meta", "status_code": resp.status_code},
                )

            error_detail = resp.text
            try:
                err_json = resp.json()
                error_detail = err_json.get("error", {}).get("message", error_detail)
            except Exception:
                pass

            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=clean_recipient,
                status="failed",
                error=f"WhatsApp API error ({resp.status_code}): {error_detail}",
                latency_ms=duration_ms,
                metadata={"provider": "meta", "status_code": resp.status_code},
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=clean_recipient,
                status="failed",
                error=f"Connection failure: {str(exc)}",
                latency_ms=duration_ms,
            )
        finally:
            if should_close:
                client.close()

    def test_connection(self) -> ConnectionTestResult:
        """
        Tests Meta Graph API connectivity and verifies phone number status.
        """
        url = f"{self.BASE_URL}/{self.GRAPH_API_VERSION}/{self.phone_number_id}"
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
                        "verified_name": data.get("verified_name"),
                        "display_phone_number": data.get("display_phone_number"),
                        "quality_rating": data.get("quality_rating"),
                    },
                )

            error_msg = resp.text
            try:
                err_json = resp.json()
                error_msg = err_json.get("error", {}).get("message", error_msg)
            except Exception:
                pass

            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"WhatsApp Graph API ({resp.status_code}): {error_msg}",
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Connection test error: {str(exc)}",
            )
        finally:
            if should_close:
                client.close()
