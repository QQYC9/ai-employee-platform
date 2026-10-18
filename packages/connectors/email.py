from __future__ import annotations

from datetime import datetime, timezone
import email
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
import logging
import re
import smtplib
import time
from typing import Any
from uuid import UUID

from packages.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    InboundMessage,
    OutboundDeliveryResult,
)

logger = logging.getLogger(__name__)


def _decode_mime_header(header_value: str | None) -> str:
    if not header_value:
        return ""
    decoded_fragments = []
    for fragment, encoding in decode_header(header_value):
        if isinstance(fragment, bytes):
            decoded_fragments.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded_fragments.append(str(fragment))
    return "".join(decoded_fragments)


class EmailConnector(BaseConnector):
    """
    Production-grade Email connector supporting SMTP dispatch and MIME inbound parsing.
    Includes STARTTLS, authentication, recipient email validation, and connection diagnostics.
    """

    EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

    def __init__(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        from_name: str | None = None,
        use_tls: bool = True,
        use_ssl: bool = False,
    ):
        self.tenant_id = tenant_id
        self.channel_id = channel_id
        self.smtp_host = str(smtp_host).strip()
        self.smtp_port = int(smtp_port)
        self.smtp_user = str(smtp_user).strip() if smtp_user else None
        self.smtp_password = str(smtp_password).strip() if smtp_password else None
        self.from_address = (from_address or smtp_user or "").strip()
        self.from_name = str(from_name).strip() if from_name else None
        self.use_tls = use_tls
        self.use_ssl = use_ssl

    @property
    def channel_type(self) -> str:
        return "email"

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str | None]:
        """
        Email webhooks (e.g. from SendGrid, Postmark, or Mailgun inbound parsers).
        Verifies content presence.
        """
        if not body:
            return False, "Empty email webhook body"
        return True, None

    def parse_inbound(
        self,
        payload: dict[str, Any] | bytes,
        headers: dict[str, str] | None = None,
    ) -> list[InboundMessage]:
        """
        Parses raw RFC 822 / MIME email or JSON inbound payload into InboundMessage.
        """
        if isinstance(payload, bytes):
            # Parse raw RFC822 email message
            msg = email.message_from_bytes(payload)
            msg_id = msg.get("Message-ID") or f"email-{int(time.time())}"
            from_hdr = _decode_mime_header(msg.get("From"))
            subject = _decode_mime_header(msg.get("Subject"))

            # Extract sender address
            sender_email = from_hdr
            match = re.search(r"<([^>]+)>", from_hdr)
            if match:
                sender_email = match.group(1).strip()
            sender_name = from_hdr.split("<")[0].strip("\"' ") if "<" in from_hdr else None

            # Extract body text
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        payload_bytes = part.get_payload(decode=True)
                        if payload_bytes:
                            body_text = payload_bytes.decode(part.get_content_charset() or "utf-8", errors="replace")
                            break
            else:
                payload_bytes = msg.get_payload(decode=True)
                if payload_bytes:
                    body_text = payload_bytes.decode(msg.get_content_charset() or "utf-8", errors="replace")

            combined_content = f"Subject: {subject}\n\n{body_text}".strip() if subject else body_text

            return [
                InboundMessage(
                    channel_type=self.channel_type,
                    channel_id=self.channel_id,
                    tenant_id=self.tenant_id,
                    external_message_id=str(msg_id),
                    sender_id=sender_email,
                    sender_name=sender_name,
                    recipient_id=self.from_address,
                    content=combined_content,
                    content_type="email",
                    timestamp=datetime.now(timezone.utc),
                    raw_payload={"from": from_hdr, "subject": subject},
                )
            ]
        elif isinstance(payload, dict):
            # Structured JSON inbound webhook
            msg_id = str(payload.get("message_id") or payload.get("id") or f"email-{int(time.time())}")
            sender = str(payload.get("from") or payload.get("sender") or "")
            subject = str(payload.get("subject") or "")
            body_text = str(payload.get("text") or payload.get("body") or payload.get("content") or "")
            combined_content = f"Subject: {subject}\n\n{body_text}".strip() if subject else body_text

            return [
                InboundMessage(
                    channel_type=self.channel_type,
                    channel_id=self.channel_id,
                    tenant_id=self.tenant_id,
                    external_message_id=msg_id,
                    sender_id=sender,
                    recipient_id=self.from_address,
                    content=combined_content,
                    content_type="email",
                    timestamp=datetime.now(timezone.utc),
                    raw_payload=payload,
                )
            ]
        return []

    def send_message(
        self,
        recipient: str,
        content: str,
        **kwargs: Any,
    ) -> OutboundDeliveryResult:
        """
        Sends an email using standard SMTP.
        """
        clean_recipient = str(recipient).strip()
        if not self.EMAIL_REGEX.match(clean_recipient):
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=clean_recipient,
                status="failed",
                error=f"Invalid recipient email address format: '{clean_recipient}'",
            )

        subject = kwargs.get("subject") or "Notification from Digital Employee"
        msg = MIMEMultipart()
        msg["From"] = f"{self.from_name} <{self.from_address}>" if self.from_name else self.from_address
        msg["To"] = clean_recipient
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg_id = make_msgid(domain=self.from_address.split("@")[-1] if "@" in self.from_address else "platform.local")
        msg["Message-ID"] = msg_id

        # Attach text content
        msg.attach(MIMEText(content, "plain", "utf-8"))

        start_time = time.perf_counter()
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=15.0)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15.0)
                if self.use_tls:
                    server.starttls()

            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            server.send_message(msg)
            server.quit()
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            return OutboundDeliveryResult(
                success=True,
                channel_type=self.channel_type,
                recipient_id=clean_recipient,
                external_message_id=str(msg_id),
                status="sent",
                latency_ms=duration_ms,
                metadata={"smtp_host": self.smtp_host, "subject": subject},
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return OutboundDeliveryResult(
                success=False,
                channel_type=self.channel_type,
                recipient_id=clean_recipient,
                status="failed",
                error=f"SMTP dispatch failed: {str(exc)}",
                latency_ms=duration_ms,
            )

    def test_connection(self) -> ConnectionTestResult:
        """
        Tests SMTP server connection, EHLO, and optional credentials.
        """
        start_time = time.perf_counter()
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=10.0)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10.0)
                if self.use_tls:
                    server.starttls()

            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            server.quit()
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

            return ConnectionTestResult(
                connected=True,
                status="connected",
                latency_ms=duration_ms,
                details={
                    "smtp_host": self.smtp_host,
                    "smtp_port": self.smtp_port,
                    "tls_enabled": self.use_tls or self.use_ssl,
                },
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ConnectionTestResult(
                connected=False,
                status="failed",
                latency_ms=duration_ms,
                error=f"SMTP connection test failed: {str(exc)}",
            )
