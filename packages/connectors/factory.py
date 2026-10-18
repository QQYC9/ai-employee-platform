from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from packages.connectors.base import BaseConnector
from packages.connectors.email import EmailConnector
from packages.connectors.telegram import TelegramConnector
from packages.connectors.whatsapp import WhatsAppCloudConnector
from packages.core.crypto import SecretsEncryptionService
from packages.models.domain import Channel

logger = logging.getLogger(__name__)


class ConnectorFactory:
    """
    Factory resolving and instantiating secure channel connectors.
    Decrypts stored secrets using AES-256-GCM before connector initialization.
    """

    def __init__(self, crypto: SecretsEncryptionService | None = None):
        self.crypto = crypto or SecretsEncryptionService()

    def _decrypt_value(self, val: Any) -> str:
        if not val or not isinstance(val, str):
            return ""
        if val.startswith(SecretsEncryptionService.PREFIX):
            try:
                return self.crypto.decrypt(val)
            except Exception as exc:
                logger.error("Failed to decrypt connector secret: %s", exc)
                return ""
        return val

    def create_connector(self, channel: Channel) -> BaseConnector:
        """
        Instantiates the appropriate connector from a Channel ORM entity.
        """
        c_type = (channel.channel_type or "").strip().lower()
        config = dict(channel.config or {})

        if c_type == "whatsapp":
            phone_number_id = config.get("phone_number_id") or ""
            raw_token = config.get("access_token") or config.get("token") or ""
            access_token = self._decrypt_value(raw_token)
            raw_verify = config.get("webhook_verify_token") or config.get("verify_token")
            webhook_verify_token = self._decrypt_value(raw_verify) if raw_verify else None
            raw_secret = config.get("app_secret") or config.get("client_secret")
            app_secret = self._decrypt_value(raw_secret) if raw_secret else None

            return WhatsAppCloudConnector(
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                phone_number_id=phone_number_id,
                access_token=access_token,
                webhook_verify_token=webhook_verify_token,
                app_secret=app_secret,
            )

        elif c_type == "telegram":
            raw_token = config.get("bot_token") or config.get("token") or ""
            bot_token = self._decrypt_value(raw_token)
            raw_secret = config.get("secret_token")
            secret_token = self._decrypt_value(raw_secret) if raw_secret else None

            return TelegramConnector(
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                bot_token=bot_token,
                secret_token=secret_token,
            )

        elif c_type == "email":
            smtp_host = config.get("smtp_host") or "localhost"
            smtp_port = int(config.get("smtp_port") or 587)
            smtp_user = config.get("smtp_user") or config.get("username")
            raw_pass = config.get("smtp_password") or config.get("password")
            smtp_password = self._decrypt_value(raw_pass) if raw_pass else None
            from_addr = config.get("from_address") or smtp_user
            from_name = config.get("from_name")
            use_tls = config.get("use_tls", True)
            use_ssl = config.get("use_ssl", False)

            return EmailConnector(
                tenant_id=channel.tenant_id,
                channel_id=channel.id,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
                from_address=from_addr,
                from_name=from_name,
                use_tls=use_tls,
                use_ssl=use_ssl,
            )

        raise ValueError(f"No connector available for channel type '{channel.channel_type}'")
