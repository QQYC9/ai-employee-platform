from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_db
from packages.models.domain import Channel, Conversation, Customer, Message, OutboxEvent
from packages.services.conversation_service import ConversationService
from packages.services.customer_service import CustomerService
from packages.services.outbox_service import OutboxService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class InboundWebhookPayload(BaseModel):
    content: str
    customer_id: UUID | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    conversation_id: UUID | None = None
    external_id: str | None = None
    external_conversation_id: str | None = None
    idempotency_key: str | None = None
    sender_type: str = "customer"
    message_type: str = "text"
    metadata_json: dict[str, Any] | None = None


def verify_webhook_signature(
    channel_config: dict[str, Any],
    raw_body: bytes,
    headers: dict[str, str],
) -> bool:
    """
    Verify webhook cryptographic signature if configured for the channel.
    Supports HMAC-SHA256 signature verification.
    Fails closed if signature is required but secret is missing, empty, or signature does not match.
    """
    require_signature = (
        channel_config.get("require_signature") is True
        or channel_config.get("signature_required") is True
        or bool(channel_config.get("signature_header"))
        or bool(channel_config.get("webhook_secret"))
        or bool(channel_config.get("secret"))
    )

    if not require_signature:
        # Channel does not require signature authentication
        return True

    secret = (
        channel_config.get("webhook_secret")
        or channel_config.get("secret")
    )
    if not secret:
        # Signature is required by channel configuration, but no secret is provisioned -> FAIL CLOSED
        logger.warning("Webhook signature verification failed closed: channel requires signature but no secret is configured")
        return False

    secret_str = str(secret).strip()
    if not secret_str:
        logger.warning("Webhook signature verification failed closed: secret is empty string")
        return False

    sig_header_name = str(channel_config.get("signature_header") or "x-webhook-signature").lower().strip()
    provided_signature = headers.get(sig_header_name) or headers.get("x-hub-signature-256") or headers.get("x-signature")

    if not provided_signature:
        logger.warning("Webhook signature verification failed closed: missing signature header '%s'", sig_header_name)
        return False

    clean_sig = provided_signature.strip()
    if clean_sig.startswith("sha256="):
        clean_sig = clean_sig[7:]

    expected_signature = hmac.new(
        secret_str.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(clean_sig.lower(), expected_signature.lower())



@router.post("/channels/{channel_id}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_channel_message(
    channel_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Generic webhook ingestion endpoint for inbound communication channels.

    Guarantees:
      1. Validates channel association and active status.
      2. Verifies cryptographic HMAC-SHA256 signature if secret is configured.
      3. Rejects non-customer messages to prevent feedback loops.
      4. Idempotently deduplicates inbound events via persistent outbox key.
      5. Atomically persists customer message and outbox event in the same transaction.
      6. Returns HTTP 202 Accepted without waiting for asynchronous AI agent reply.
    """
    # 1. Fetch channel and validate status
    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.status != "deleted",
        )
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    if channel.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Channel is not active (current status: '{channel.status}')",
        )

    tenant_id = channel.tenant_id

    # 2. Signature verification
    raw_body = await request.body()
    headers_dict = {k.lower(): v for k, v in request.headers.items()}
    if not verify_webhook_signature(channel.config or {}, raw_body, headers_dict):
        logger.warning(
            "Rejected webhook for channel %s: invalid or missing signature",
            channel_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook signature",
        )

    # 3. Parse JSON payload safely
    try:
        body_json = json.loads(raw_body.decode("utf-8") or "{}")
        payload = InboundWebhookPayload(**body_json)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid webhook JSON payload: {str(exc)}",
        )

    # 4. Loop prevention: Only customer/user messages can be ingested
    clean_sender = (payload.sender_type or "customer").strip().lower()
    if clean_sender not in ("customer", "user"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only inbound customer messages are accepted (rejected sender_type: '{clean_sender}')",
        )

    if not payload.content and not payload.metadata_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incoming message must have non-empty content or metadata",
        )

    # 5. Determine stable idempotency key
    idempotency_key = (
        payload.idempotency_key
        or payload.external_id
        or f"webhook-{channel_id}-{hashlib.sha256(raw_body).hexdigest()[:24]}"
    ).strip()

    outbox_service = OutboxService(db)
    conversation_service = ConversationService(db)
    customer_service = CustomerService(db)

    # 6. Idempotency check: if outbox event already exists for tenant, return accepted existing
    existing_event = outbox_service.get_event_by_idempotency_key(tenant_id, idempotency_key)
    if existing_event is not None:
        return {
            "status": "already_accepted",
            "message": "Duplicate event acknowledged",
            "outbox_event_id": str(existing_event.id),
            "message_id": str(existing_event.message_id),
            "conversation_id": str(existing_event.conversation_id),
            "idempotency_key": idempotency_key,
        }

    # 7. Customer resolution
    customer_id = payload.customer_id
    if customer_id is not None:
        cust = db.scalar(
            select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == tenant_id,
                Customer.status != "deleted",
            )
        )
        if cust is None:
            raise HTTPException(
                status_code=400,
                detail=f"Customer '{customer_id}' does not belong to this tenant",
            )
        if cust.status == "blocked":
            raise HTTPException(
                status_code=403,
                detail=f"Customer '{customer_id}' is blocked from interaction",
            )
    elif payload.customer_email:
        # Find or create customer by email
        cust = db.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.email == payload.customer_email.strip().lower(),
                Customer.status != "deleted",
            )
        )
        if cust is None:
            cust = customer_service.create_customer(
                tenant_id=tenant_id,
                name=payload.customer_name or payload.customer_email.split("@")[0],
                email=payload.customer_email.strip().lower(),
            )
        customer_id = cust.id

    # 8. Conversation resolution
    conv: Conversation | None = None
    if payload.conversation_id is not None:
        conv = conversation_service.get_conversation(tenant_id, payload.conversation_id)
        if conv is None:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation '{payload.conversation_id}' not found for tenant",
            )
    elif payload.external_conversation_id:
        conv = db.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.channel_id == channel_id,
                Conversation.external_id == payload.external_conversation_id.strip(),
            )
        )

    if conv is None:
        # Start new conversation
        conv = conversation_service.start_conversation(
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel_id=channel_id,
            subject=f"Inbound from {channel.name}",
            external_id=payload.external_conversation_id,
        )

    # 9. Atomic message and outbox persistence in the same transaction
    try:
        msg = conversation_service.send_message(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            sender_type="customer",
            content=payload.content,
            customer_id=customer_id,
            message_type=payload.message_type,
            external_id=payload.external_id,
            metadata_json=payload.metadata_json,
        )

        event = outbox_service.create_event(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            message_id=msg.id,
            idempotency_key=idempotency_key,
            event_type="process_incoming_message",
            payload={
                "channel_id": str(channel_id),
                "channel_type": channel.channel_type,
                "external_id": payload.external_id,
            },
        )

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Failed to persist incoming message and outbox event: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to persist incoming message and outbox event",
        )

    return {
        "status": "accepted",
        "tenant_id": str(tenant_id),
        "channel_id": str(channel.id),
        "conversation_id": str(conv.id),
        "message_id": str(msg.id),
        "outbox_event_id": str(event.id),
        "idempotency_key": idempotency_key,
    }
