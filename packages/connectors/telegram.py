from __future__ import annotations

from datetime import datetime, timezone
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


class TelegramConnector(BaseConnector):
    """
    Production connector for Telegram Bot API.
    Supports webhook secret token verification, message parsing, and outgoing dispatch.
    """

    BASE_URL = "https://api.telegram.org"

    def __init__(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        bot_token: str,
        secret_token: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.tenant_id = tenant_id
        self.channel_id = channel_id
        self.bot_token = str(bot_token).strip()
        self.secret_token = str(secret_token).strip() if secret_token else None
        self._client = http_client

    @property
    def channel_type(self) -> str:
        return "telegram"

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Verifies the secret token sent by Telegram in the X-Telegram-Bot-Api-Secret-Token header.
        """
        if not self.secret_token:
            # If no secret token is configured, allow
            return True, None

        provided_token = (
            headers.get("x-telegram-bot-api-secret-token")
            or headers.get("X-Telegram-Bot-Api-Secret-Token")
            or ""
        ).strip()

        if not provided_token:
            logger.warning("Telegram webhook rejected: missing secret token header")
            return False, "Missing X-Telegram-Bot-Api-Secret-Token header"

        if not hmac.compare_digest(provided_token, self.secret_token):
            logger.warning("Telegram webhook rejected: secret token mismatch")
            return False, "Invalid secret token"

        return True, None

    def parse_inbound(
        self,
        payload: dict[str, Any] | bytes,
        headers: dict[str, str] | None = None,
    ) -> list[InboundMessage]:
        """
        Parses Telegram Update object into normalized InboundMessage list.
        """
        if isinstance(payload, bytes):
            try:
                data = json.loads(payload.decode("utf-8"))
            except Exception:
                return []
        else:
            data = payload or {}

        # Extract message, edited_message, or channel_post
        msg_obj = data.get("message") or data.get("edited_message") or data.get("channel_post")
        if not msg_obj or not isinstance(msg_obj, dict):
            return []

        message_id = str(msg_obj.get("message_id"))
        chat = msg_obj.get("chat", {})
        chat_id = str(chat.get("id"))
        from_user = msg_obj.get("from", {})
        sender_id = str(from_user.get("id") or chat_id)
        sender_name = from_user.get("first_name") or from_user.get("username") or chat.get("title")

        content = msg_obj.get("text") or msg_obj.get("caption") or ""
        msg_type = "text"
        if not content:
            if "photo" in msg_obj:
                content = "[Photo]"
                msg_type = "photo"
            elif "document" in msg_obj:
                doc_name = msg_obj.get("document", {}).get("file_name", "Document")
                content = f"[Document: {doc_name}]"
                msg_type = "document"
            elif "voice" in msg_obj:
                content = "[Voice message]"
                msg_type = "voice"

        date_unix = msg_obj.get("date")
        ts = datetime.now(timezone.utc)
        if date_unix:
            try:
                ts = datetime.fromtimestamp(int(date_unix), tz=timezone.utc)
            except Exception:
                pass

        return [
            InboundMessage(
                channel_type=self.channel_type,
                channel_id=self.channel_id,
                tenant_id=self.tenant_id,
                external_message_id=message_id,
                sender_id=sender_id,
                sender_name=sender_name,
                recipient_id=chat_id,
                content=content,
                content_type=msg_type,
                timestamp=ts,
                raw_payload=msg_obj,
            )
        ]

    def send_message(
        self,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        """
        Dispatches a message using Telegram Bot API sendMessage.
        """
        url = f"{self.BASE_URL}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": str(recipient).strip(),
            "text": content,
        }
        parse_mode = kwargs.get("parse_mode")
        if parse_mode:
            payload["parse_mode"] = parse_mode

        client = self._client or httpx.Client(timeout=15.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.post(url, json=payload)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code == 200:
                data = resp.json()
                msg_id = str(data.get("result", {}).get("message_id"))
                return OutboundDeliveryResult(
                    success=True,
                    channel_type=self.channel_type,
                    recipient_id=str(recipient),
                    external_message_id=msg_id,
                    status="sent",
                    latency_ms=duration_ms,
                    metadata={"provider": "telegram"},
                )

            err_text = resp.text
            try:
                err_json = resp.json()
                err_text = err_json.get("description", err_text)
            except Exception:
                pass

            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=str(recipient),
                status="failed",
                error=f"Telegram API error ({resp.status_code}): {err_text}",
                latency_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=str(recipient),
                status="failed",
                error=f"Connection failure: {str(exc)}",
                latency_ms=duration_ms,
            )
        finally:
            if should_close:
                client.close()

    def test_connection(self) -> ConnectionTestResult:
        """
        Tests Bot API credentials via getMe.
        """
        url = f"{self.BASE_URL}/bot{self.bot_token}/getMe"
        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            resp = client.get(url)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code == 200:
                data = resp.json()
                bot_info = data.get("result", {})
                return ConnectionTestResult(
                    connected=True,
                    status="connected",
                    latency_ms=duration_ms,
                    details={
                        "bot_id": bot_info.get("id"),
                        "username": bot_info.get("username"),
                        "first_name": bot_info.get("first_name"),
                        "can_join_groups": bot_info.get("can_join_groups"),
                    },
                )

            err_msg = resp.text
            try:
                err_json = resp.json()
                err_msg = err_json.get("description", err_msg)
            except Exception:
                pass

            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Telegram Bot API ({resp.status_code}): {err_msg}",
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
