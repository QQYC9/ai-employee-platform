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

        # Extract callback_query if present
        cb_query = data.get("callback_query")
        if cb_query and isinstance(cb_query, dict):
            msg_obj = cb_query.get("message") or {}
            chat = msg_obj.get("chat", {})
            chat_id = str(chat.get("id"))
            from_user = cb_query.get("from", {})
            sender_id = str(from_user.get("id") or chat_id)
            sender_name = from_user.get("first_name") or from_user.get("username")
            query_id = str(cb_query.get("id"))
            data_val = str(cb_query.get("data") or "")
            return [
                InboundMessage(
                    channel_type=self.channel_type,
                    channel_id=self.channel_id,
                    tenant_id=self.tenant_id,
                    external_message_id=f"cb_{query_id}",
                    sender_id=sender_id,
                    sender_name=sender_name,
                    recipient_id=chat_id,
                    content=data_val,
                    content_type="callback_query",
                    timestamp=datetime.now(timezone.utc),
                    raw_payload=cb_query,
                )
            ]

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
        # Telegram character limit is 4096 characters per message
        chunk_size = 4000
        chunks = [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)] if len(content) > chunk_size else [content]

        client = self._client or httpx.Client(timeout=15.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            last_msg_id = None
            for chunk in chunks:
                payload = {
                    "chat_id": str(recipient).strip(),
                    "text": chunk,
                }
                parse_mode = kwargs.get("parse_mode")
                if parse_mode:
                    payload["parse_mode"] = parse_mode

                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
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

                data = resp.json()
                last_msg_id = str(data.get("result", {}).get("message_id"))

            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return OutboundDeliveryResult(
                success=True,
                channel_type=self.channel_type,
                recipient_id=str(recipient),
                external_message_id=last_msg_id,
                status="sent",
                latency_ms=duration_ms,
                metadata={"provider": "telegram", "chunks_sent": len(chunks)},
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

    def set_webhook(
        self,
        webhook_url: str,
        secret_token: str | None = None,
        drop_pending_updates: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Registers a webhook endpoint with Telegram Bot API via setWebhook.
        Returns: (success: bool, description_or_error: str | None)
        """
        clean_url = str(webhook_url).strip()
        if not clean_url:
            return False, "Webhook URL cannot be empty"
        if not (clean_url.startswith("https://") or clean_url.startswith("http://")):
            return False, "Webhook URL must start with https:// (or http:// in dev)"

        url = f"{self.BASE_URL}/bot{self.bot_token}/setWebhook"
        payload: dict[str, Any] = {
            "url": clean_url,
            "drop_pending_updates": drop_pending_updates,
        }
        effective_secret = (secret_token or self.secret_token or "").strip()
        if effective_secret:
            payload["secret_token"] = effective_secret

        client = self._client or httpx.Client(timeout=15.0)
        should_close = self._client is None
        try:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return True, data.get("description", "Webhook registered successfully")
                return False, data.get("description", "Failed to register webhook")

            err_msg = resp.text
            try:
                err_msg = resp.json().get("description", err_msg)
            except Exception:
                pass
            return False, f"Telegram API error ({resp.status_code}): {err_msg}"
        except Exception as exc:
            return False, f"Connection error: {str(exc)}"
        finally:
            if should_close:
                client.close()

    def get_webhook_info(self) -> dict[str, Any]:
        """
        Queries current webhook status from Telegram Bot API via getWebhookInfo.
        """
        url = f"{self.BASE_URL}/bot{self.bot_token}/getWebhookInfo"
        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result", {})
            err_msg = resp.text
            try:
                err_msg = resp.json().get("description", err_msg)
            except Exception:
                pass
            return {"error": f"Telegram API error ({resp.status_code}): {err_msg}"}
        except Exception as exc:
            return {"error": str(exc)}
        finally:
            if should_close:
                client.close()

    def test_connection(self, expected_webhook_url: str | None = None) -> ConnectionTestResult:
        """
        Tests Bot API credentials via getMe AND verifies webhook registration via getWebhookInfo.
        Shows specifically which of the two failed.
        """
        url = f"{self.BASE_URL}/bot{self.bot_token}/getMe"
        client = self._client or httpx.Client(timeout=10.0)
        should_close = self._client is None
        start_time = time.perf_counter()

        try:
            # 1. Probe credentials via getMe
            resp = client.get(url)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            if resp.status_code != 200:
                err_msg = resp.text
                try:
                    err_msg = resp.json().get("description", err_msg)
                except Exception:
                    pass
                return ConnectionTestResult(
                    connected=False,
                    status="failed",
                    latency_ms=duration_ms,
                    error=f"Token verification failed (getMe error {resp.status_code}): {err_msg}",
                    details={
                        "token_verified": False,
                        "webhook_verified": False,
                        "failure_stage": "token_verification",
                    },
                )

            bot_info = resp.json().get("result", {})

            # 2. Probe webhook registration via getWebhookInfo
            wh_url = f"{self.BASE_URL}/bot{self.bot_token}/getWebhookInfo"
            wh_resp = client.get(wh_url)
            wh_info = wh_resp.json().get("result", {}) if wh_resp.status_code == 200 else {}
            current_wh_url = wh_info.get("url", "")
            pending_updates = wh_info.get("pending_update_count", 0)
            last_error = wh_info.get("last_error_message")

            webhook_details = {
                "bot_id": bot_info.get("id"),
                "username": bot_info.get("username"),
                "first_name": bot_info.get("first_name"),
                "can_join_groups": bot_info.get("can_join_groups"),
                "token_verified": True,
                "webhook_verified": False,
                "current_webhook_url": current_wh_url,
                "expected_webhook_url": expected_webhook_url,
                "pending_update_count": pending_updates,
                "last_error_message": last_error,
            }

            if not current_wh_url:
                return ConnectionTestResult(
                    connected=False,
                    status="failed",
                    latency_ms=duration_ms,
                    error="Webhook verification failed: No webhook registered at Telegram (URL is empty). Click 'Re-register webhook'.",
                    details={**webhook_details, "failure_stage": "webhook_verification"},
                )

            if expected_webhook_url and current_wh_url.strip() != expected_webhook_url.strip():
                return ConnectionTestResult(
                    connected=False,
                    status="failed",
                    latency_ms=duration_ms,
                    error=f"Webhook verification failed: Telegram URL ('{current_wh_url}') does not match expected URL ('{expected_webhook_url}'). Click 'Re-register webhook'.",
                    details={**webhook_details, "failure_stage": "webhook_verification"},
                )

            if last_error:
                return ConnectionTestResult(
                    connected=False,
                    status="failed",
                    latency_ms=duration_ms,
                    error=f"Webhook verification failed: Telegram reports webhook error: {last_error}",
                    details={**webhook_details, "failure_stage": "webhook_verification"},
                )

            webhook_details["webhook_verified"] = True
            return ConnectionTestResult(
                connected=True,
                status="connected",
                latency_ms=duration_ms,
                details=webhook_details,
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"Connection test error: {str(exc)}",
                details={"token_verified": False, "webhook_verified": False, "failure_stage": "network_error"},
            )
        finally:
            if should_close:
                client.close()
