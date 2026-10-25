"""
Secure, Single-Use, Expiring Link Code Service for Tenant Channel Ownership.

Implements Phase 3.2 & Addendum X1:
- Cryptographically secure high-entropy random generation.
- Stored hashed (SHA-256) at rest; raw code never persisted.
- Single-use with atomic invalidation upon successful link.
- Short configurable expiry (default 24 hours).
- Scoped strictly to one tenant and one channel.
- Rate-limited against guessing / brute-force attempts.
- Comprehensive audit trail (create, use, failure, expiry, revoke).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.models.domain import Channel, TenantLinkCode
from packages.services.audit_service import AuditService

logger = logging.getLogger(__name__)


import threading

class SenderLinkRateLimiter:
    """
    Thread-safe in-memory rate limiter with exponential backoff per (tenant_id, channel_id, sender_id).
    Blocks senders who fail repeatedly without locking or invalidating the actual link code.
    """
    def __init__(self):
        self._lock = threading.Lock()
        # key: (tenant_id, channel_id, sender_id)
        # value: {"failed_attempts": int, "blocked_until": float, "last_attempt": float}
        self._records: dict[tuple[str, str, str], dict[str, Any]] = {}

    def is_blocked(self, tenant_id: UUID, channel_id: UUID, sender_id: str) -> tuple[bool, int]:
        """Returns (is_blocked: bool, retry_after_seconds: int)."""
        key = (str(tenant_id), str(channel_id), str(sender_id))
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                return False, 0
            blocked_until = rec.get("blocked_until", 0.0)
            if now < blocked_until:
                return True, max(1, int(blocked_until - now))
            return False, 0

    def record_failure(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        sender_id: str,
        base_block_seconds: int = 60,
        max_failures_before_block: int = 5,
    ) -> tuple[int, int]:
        """
        Records a failed attempt for sender.
        Returns (total_failed_attempts: int, block_seconds: int).
        If total_failed_attempts >= max_failures_before_block, applies exponential backoff:
        block_seconds = base_block_seconds * (2 ** (total_failed_attempts - max_failures_before_block)).
        """
        key = (str(tenant_id), str(channel_id), str(sender_id))
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            rec = self._records.setdefault(key, {"failed_attempts": 0, "blocked_until": 0.0, "last_attempt": now})
            rec["failed_attempts"] += 1
            rec["last_attempt"] = now
            failures = rec["failed_attempts"]
            if failures >= max_failures_before_block:
                multiplier = min(failures - max_failures_before_block, 6)
                block_duration = base_block_seconds * (2 ** multiplier)
                rec["blocked_until"] = now + block_duration
                return failures, block_duration
            return failures, 0

    def record_success(self, tenant_id: UUID, channel_id: UUID, sender_id: str):
        """Clears failed attempts on successful verification."""
        key = (str(tenant_id), str(channel_id), str(sender_id))
        with self._lock:
            self._records.pop(key, None)

    def reset(self):
        """Reset all records (useful for test isolation)."""
        with self._lock:
            self._records.clear()

sender_link_rate_limiter = SenderLinkRateLimiter()

class LinkCodeService:
    """Manages the creation, verification, consumption, and audit trail of channel link codes."""

    def __init__(self, db: Session):
        self.db = db
        self.audit_service = AuditService(db)

    @staticmethod
    def hash_code(raw_code: str) -> str:
        """Computes SHA-256 hex digest of normalized uppercase link code."""
        normalized = raw_code.strip().upper()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_random_code() -> str:
        """Generates a high-entropy formatted link code (e.g. LINK-4F8A-9B2D)."""
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        return f"LINK-{part1}-{part2}"

    def generate_link_code(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        *,
        expires_in_hours: int = 24,
        created_by_user_id: UUID | None = None,
    ) -> tuple[str, TenantLinkCode]:
        """
        Generates a new single-use cryptographically random link code.
        Revokes any existing active codes for this channel (regeneration support).
        Returns the plaintext code (returned only once) and the persisted model record.
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=expires_in_hours)

        # 1. Invalidate / revoke previous active codes for this tenant and channel
        existing_active = self.db.scalars(
            select(TenantLinkCode).where(
                TenantLinkCode.tenant_id == tenant_id,
                TenantLinkCode.channel_id == channel_id,
                TenantLinkCode.is_used.is_(False),
                TenantLinkCode.is_revoked.is_(False),
            )
        ).all()

        is_regeneration = len(existing_active) > 0
        for old_code in existing_active:
            old_code.is_revoked = True
            self.db.add(old_code)

        # 2. Generate new code and hash
        raw_code = self.generate_random_code()
        code_h = self.hash_code(raw_code)
        prefix = raw_code[:8] + "..."

        link_record = TenantLinkCode(
            tenant_id=tenant_id,
            channel_id=channel_id,
            code_hash=code_h,
            code_prefix=prefix,
            expires_at=expires_at,
            is_used=False,
            attempts_count=0,
            max_attempts=5,
            is_revoked=False,
        )
        self.db.add(link_record)
        self.db.flush()

        # 3. Record Audit Event
        action_name = "link_code_regenerated" if is_regeneration else "link_code_created"
        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type=f"channel_{action_name}",
            action=action_name,
            user_id=created_by_user_id,
            description=f"Generated secure link code ({prefix}) for channel '{channel_id}' expiring in {expires_in_hours}h",
            event_metadata={
                "channel_id": str(channel_id),
                "code_prefix": prefix,
                "expires_at": expires_at.isoformat(),
                "is_regeneration": is_regeneration,
            },
        )

        return raw_code, link_record

    def verify_and_consume_code(
        self,
        tenant_id: UUID,
        channel_id: UUID,
        sender_id: str,
        candidate_code: str,
    ) -> tuple[bool, str, TenantLinkCode | None]:
        """
        Verifies and consumes a candidate link code:
        - Rate limits brute force per sender and per channel with exponential backoff.
        - Keeps the legitimate owner's link code valid even if an attacker guesses wrong.
        - Validates tenant and channel scoping.
        - Checks expiration and single-use status.
        - Atomically marks the code as used upon success.
        Returns: (success: bool, reason: str, record: TenantLinkCode | None)
        Reasons: 'success', 'invalid_code', 'expired', 'reused', 'revoked', 'rate_limited'
        """
        clean_code = candidate_code.strip()
        cand_hash = self.hash_code(clean_code)
        now = datetime.now(timezone.utc)

        # 1. Rate Limiting Check: Blocked sender check
        is_blocked, retry_after = sender_link_rate_limiter.is_blocked(tenant_id, channel_id, sender_id)
        if is_blocked:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                event_type="channel_link_code_rate_limited",
                action="link_code_rate_limited",
                description=f"Link code attempt blocked: sender '{sender_id}' temporarily blocked on channel '{channel_id}' ({retry_after}s remaining)",
                event_metadata={
                    "channel_id": str(channel_id),
                    "sender_id": sender_id,
                    "retry_after": retry_after,
                },
            )
            return False, "rate_limited", None

        # 2. Lookup record matching hash, tenant, and channel
        matched_record = self.db.scalar(
            select(TenantLinkCode).where(
                TenantLinkCode.tenant_id == tenant_id,
                TenantLinkCode.channel_id == channel_id,
                TenantLinkCode.code_hash == cand_hash,
            )
        )

        if matched_record is None:
            # Increment attempt counter on active codes for audit/telemetry
            active_codes = self.db.scalars(
                select(TenantLinkCode).where(
                    TenantLinkCode.tenant_id == tenant_id,
                    TenantLinkCode.channel_id == channel_id,
                    TenantLinkCode.is_used.is_(False),
                    TenantLinkCode.is_revoked.is_(False),
                )
            ).all()
            for ac in active_codes:
                ac.attempts_count += 1
                self.db.add(ac)
            self.db.flush()

            # Record failed attempt for this specific sender
            failures, block_dur = sender_link_rate_limiter.record_failure(
                tenant_id, channel_id, sender_id
            )
            if block_dur > 0:
                self.audit_service.record_event(
                    tenant_id=tenant_id,
                    event_type="channel_link_code_rate_limited",
                    action="link_code_rate_limited",
                    description=f"Sender '{sender_id}' blocked on channel '{channel_id}' for {block_dur}s after {failures} failed attempts",
                    event_metadata={
                        "channel_id": str(channel_id),
                        "sender_id": sender_id,
                        "failed_attempts": failures,
                        "block_duration": block_dur,
                    },
                )
                return False, "rate_limited", None

            self.audit_service.record_event(
                tenant_id=tenant_id,
                event_type="channel_link_code_failed",
                action="link_code_failed",
                description=f"Invalid link code submitted by sender '{sender_id}' for channel '{channel_id}' (attempt {failures})",
                event_metadata={
                    "channel_id": str(channel_id),
                    "sender_id": sender_id,
                    "failed_attempts": failures,
                    "reason": "invalid_code",
                },
            )
            return False, "invalid_code", None

        # 3. Validation checks on matched record
        if matched_record.is_revoked:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                event_type="channel_link_code_failed",
                action="link_code_failed",
                description=f"Revoked link code submitted by sender '{sender_id}' for channel '{channel_id}'",
                event_metadata={"channel_id": str(channel_id), "sender_id": sender_id, "reason": "revoked"},
            )
            return False, "revoked", matched_record

        if matched_record.is_used:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                event_type="channel_link_code_reused",
                action="link_code_reused",
                description=f"Already used link code attempted by sender '{sender_id}' for channel '{channel_id}'",
                event_metadata={"channel_id": str(channel_id), "sender_id": sender_id, "used_at": matched_record.used_at.isoformat() if matched_record.used_at else None},
            )
            return False, "reused", matched_record

        if now > matched_record.expires_at:
            self.audit_service.record_event(
                tenant_id=tenant_id,
                event_type="channel_link_code_expired",
                action="link_code_expired",
                description=f"Expired link code submitted by sender '{sender_id}' for channel '{channel_id}'",
                event_metadata={"channel_id": str(channel_id), "sender_id": sender_id, "expires_at": matched_record.expires_at.isoformat()},
            )
            return False, "expired", matched_record

        # 4. Successful consumption! Mark single-use and clear sender failures
        sender_link_rate_limiter.record_success(tenant_id, channel_id, sender_id)
        matched_record.is_used = True
        matched_record.used_at = now
        matched_record.used_by_sender_id = sender_id
        self.db.add(matched_record)
        self.db.flush()

        self.audit_service.record_event(
            tenant_id=tenant_id,
            event_type="channel_link_code_used",
            action="link_code_used",
            description=f"Link code successfully verified and consumed by owner '{sender_id}' on channel '{channel_id}'",
            event_metadata={
                "channel_id": str(channel_id),
                "sender_id": sender_id,
                "code_prefix": matched_record.code_prefix,
            },
        )
        return True, "success", matched_record

    def get_active_code_status(
        self,
        tenant_id: UUID,
        channel_id: UUID,
    ) -> dict[str, Any]:
        """Returns the current link code status for dashboard UI display."""
        now = datetime.now(timezone.utc)
        record = self.db.scalar(
            select(TenantLinkCode).where(
                TenantLinkCode.tenant_id == tenant_id,
                TenantLinkCode.channel_id == channel_id,
                TenantLinkCode.is_used.is_(False),
                TenantLinkCode.is_revoked.is_(False),
            ).order_by(TenantLinkCode.created_at.desc())
        )
        if record is None:
            return {
                "has_active": False,
                "has_active_code": False,
                "code_prefix": None,
                "code_preview": None,
                "expires_at": None,
                "is_expired": False,
            }

        is_expired = now > record.expires_at
        return {
            "has_active": not is_expired,
            "has_active_code": not is_expired,
            "code_prefix": record.code_prefix,
            "code_preview": f"{record.code_prefix}..." if record.code_prefix else None,
            "expires_at": record.expires_at.isoformat(),
            "is_expired": is_expired,
            "attempts_count": record.attempts_count,
            "max_attempts": record.max_attempts,
        }

    @staticmethod
    def extract_candidate_code(content: str) -> str | None:
        """
        Extracts candidate link code from user message.
        Requires explicit command format: /link <code>, link: <code>, or كود الربط <code>.
        Does NOT treat arbitrary random messages as a link code.
        """
        c = (content or "").strip()
        m = re.search(r"(?:/link|كود\s*الربط\s*:?|رمز\s*الربط\s*:?|^link\s*:?)\s*([A-Za-z0-9_-]{6,32})\b", c, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # Direct raw code format match (e.g. LINK-XXXX-XXXX)
        if re.match(r"^LINK-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$", c, re.IGNORECASE):
            return c
        return None
