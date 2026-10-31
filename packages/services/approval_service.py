from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from packages.core.config import settings
from packages.models.domain import Approval, OutboxEvent, Task, User

logger = logging.getLogger(__name__)


# ===========================================================================
# CR-05-01 Exceptions
# ===========================================================================

class ApprovalChallengeError(Exception):
    """Base exception for approval challenge verification errors."""
    pass


class ApprovalExpiredError(ApprovalChallengeError):
    """Raised when the challenge token has passed its TTL."""
    pass


class ApprovalExhaustedError(ApprovalChallengeError):
    """Raised when the maximum verification attempts have been exceeded."""
    pass


class ApprovalCancelledError(ApprovalChallengeError):
    """Raised when attempting to verify a cancelled approval."""
    pass


class ApprovalTokenMismatchError(ApprovalChallengeError):
    """Raised when the submitted challenge token does not match."""
    pass


class ApprovalPayloadMismatchError(ApprovalChallengeError):
    """Raised when runtime payload does not match the approved canonical payload."""
    pass


class FencingOwnershipLostError(Exception):
    """Raised when worker lost ownership of outbox event (claim_generation mismatch)."""
    pass


class ApprovalStateConflictError(Exception):
    """Raised when approval state cannot be updated atomically due to conflict."""
    pass


# ===========================================================================
# ApprovalService Implementation
# ===========================================================================

class ApprovalService:
    VALID_STATUSES = {
        "pending",
        "approved",
        "rejected",
        "cancelled",
        "expired",
        "exhausted",
    }

    VALID_EXECUTION_STATUSES = {
        "not_started",
        "queued",
        "executing",
        "completed",
        "failed",
        "reconciliation_required",
    }

    # CR-05-01 Challenge Alphabet: exactly 29 characters (Base29)
    # Excludes visually ambiguous characters: 0, 1, 8, O, I, L, B
    CHALLENGE_ALPHABET = "2345679ACDEFGHJKMNPQRSTUVWXYZ"
    CHALLENGE_CODE_LENGTH = 6
    CHALLENGE_TTL_MINUTES = 15
    CHALLENGE_MAX_ATTEMPTS = 3
    CHALLENGE_REGEX = re.compile(r"^[2-79AC-HJ-KM-NP-Z]{6}$")

    def __init__(self, db: Session):
        self.db = db

    # -----------------------------------------------------------------------
    # Cryptographic & Payload Utilities
    # -----------------------------------------------------------------------

    @classmethod
    def _resolve_approval_secret(cls, explicit_key: str | None = None) -> bytes:
        key_str = (
            explicit_key
            or getattr(settings, "approval_secret_key", None)
            or getattr(settings, "secret_key", None)
            or os.environ.get("APPROVAL_SECRET_KEY")
            or os.environ.get("SECRET_KEY")
            or "fallback_approval_hmac_secret_key_32b_minimum!"
        )
        return key_str.encode("utf-8")

    @classmethod
    def compute_token_hash(cls, token: str, tenant_id: UUID, secret_key: str | None = None) -> str:
        """Computes HMAC-SHA256 of the uppercase token scoped to tenant_id."""
        clean_token = token.strip().upper()
        key = cls._resolve_approval_secret(secret_key)
        msg = f"{tenant_id}:{clean_token}".encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    @classmethod
    def verify_token(cls, raw_token: str, token_hash: str, tenant_id: UUID, secret_key: str | None = None) -> bool:
        """Constant-time verification of raw challenge token against stored hash."""
        if not raw_token or not token_hash:
            return False
        clean = raw_token.strip().upper()
        if not cls.CHALLENGE_REGEX.match(clean):
            return False
        expected_hash = cls.compute_token_hash(clean, tenant_id, secret_key)
        return hmac.compare_digest(expected_hash, token_hash)

    @classmethod
    def compute_payload_hash(cls, payload: dict[str, Any] | None) -> str:
        """Generates SHA-256 fingerprint of canonical JSON payload."""
        canonical = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def evaluate_retry_eligibility(
        cls,
        first_external_attempt_at: datetime | None,
        provider_retention_window: timedelta | None,
        last_outcome: str,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """
        Evaluates whether an external action can be retried safely under CR-05-01.
        Returns: (can_retry: bool, next_status: str)
        """
        current_now = now or datetime.now(timezone.utc)
        if current_now.tzinfo is None:
            current_now = current_now.replace(tzinfo=timezone.utc)

        if last_outcome == "confirmed_processed":
            return False, "completed"

        if last_outcome != "confirmed_not_processed":
            # outcome_unknown or unconfirmed probe -> halt and reconcile
            return False, "reconciliation_required"

        if first_external_attempt_at is None or provider_retention_window is None:
            return False, "reconciliation_required"

        attempt_time = first_external_attempt_at
        if attempt_time.tzinfo is None:
            attempt_time = attempt_time.replace(tzinfo=timezone.utc)

        # Safety margin: min(15 min, 10% of window)
        safety_margin = min(timedelta(minutes=15), provider_retention_window * 0.1)
        deadline = attempt_time + provider_retention_window - safety_margin

        if current_now >= deadline:
            return False, "reconciliation_required"

        return True, "queued"

    # -----------------------------------------------------------------------
    # Queries & Lookups
    # -----------------------------------------------------------------------

    def list_approvals(
        self,
        tenant_id: UUID,
        status: str | None = None,
        task_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> list[Approval]:
        statement = (
            select(Approval)
            .where(Approval.tenant_id == tenant_id)
            .order_by(Approval.created_at.desc())
        )

        if status is not None:
            status = status.strip().lower()
            if status not in self.VALID_STATUSES:
                raise ValueError("Invalid approval status")
            statement = statement.where(Approval.status == status)

        if task_id is not None:
            statement = statement.where(Approval.task_id == task_id)

        if agent_id is not None:
            statement = statement.where(Approval.requested_by_agent_id == agent_id)

        return list(self.db.scalars(statement).all())

    def get_approval(
        self,
        tenant_id: UUID,
        approval_id: UUID,
    ) -> Approval | None:
        return self.db.scalar(
            select(Approval).where(
                Approval.id == approval_id,
                Approval.tenant_id == tenant_id,
            )
        )

    # -----------------------------------------------------------------------
    # CR-05-01: Challenge Creation & Invalidation
    # -----------------------------------------------------------------------

    def create_approval_challenge(
        self,
        tenant_id: UUID,
        requested_for: str,
        action: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        task_id: UUID | None = None,
        requested_by_agent_id: UUID | None = None,
        expires_in_minutes: int = CHALLENGE_TTL_MINUTES,
    ) -> tuple[Approval, str]:
        """
        Creates an anti-hijack challenge approval record.
        Generates ephemeral 6-char Base29 token, stores HMAC-SHA256 hash in DB,
        and returns (approval, raw_token) in memory only.
        """
        requested_for = requested_for.strip()
        action = action.strip()
        description = description.strip()
        clean_params = dict(parameters or {})

        if not requested_for:
            raise ValueError("Approval requested_for cannot be empty")
        if not action:
            raise ValueError("Approval action cannot be empty")
        if not description:
            raise ValueError("Approval description cannot be empty")

        # Invalidate / Cancel any existing pending approval for this (tenant_id, action)
        existing_pendings = self.db.scalars(
            select(Approval).where(
                Approval.tenant_id == tenant_id,
                Approval.action == action,
                Approval.status == "pending",
            )
        ).all()
        for p in existing_pendings:
            p.status = "cancelled"
            p.decision_reason = "Superseded by new challenge request"

        # Generate cryptographically secure Base29 token
        raw_code = "".join(secrets.choice(self.CHALLENGE_ALPHABET) for _ in range(self.CHALLENGE_CODE_LENGTH))
        token_hash = self.compute_token_hash(raw_code, tenant_id)
        payload_hash = self.compute_payload_hash(clean_params)

        now = datetime.now(timezone.utc)
        calc_expiry = now + timedelta(minutes=expires_in_minutes)
        app_id = uuid4()
        idem_key = f"approval_exec:{app_id}"

        approval = Approval(
            id=app_id,
            tenant_id=tenant_id,
            task_id=task_id,
            requested_by_agent_id=requested_by_agent_id,
            requested_for=requested_for,
            action=action,
            description=description,
            status="pending",
            token=token_hash,  # Stores HMAC-SHA256, NEVER raw code!
            expires_at=calc_expiry,
            failed_attempts=0,
            max_attempts=self.CHALLENGE_MAX_ATTEMPTS,
            payload_hash=payload_hash,
            parameters_json=clean_params,
            execution_status="not_started",
            idempotency_key=idem_key,
        )

        self.db.add(approval)
        self.db.flush()

        logger.info(
            "Created challenge approval %s for tenant %s action %s (TTL: %sm, max_attempts: %s)",
            approval.id, tenant_id, action, expires_in_minutes, self.CHALLENGE_MAX_ATTEMPTS
        )
        return approval, raw_code

    def invalidate_approval_on_mutation(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        reason: str = "Parameters or payload modified",
    ) -> Approval:
        """Immediately revokes pending approval if parameters or payload are mutated."""
        approval = self.db.scalar(
            select(Approval)
            .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
            .with_for_update()
        )
        if not approval:
            raise ValueError("Approval not found")

        if approval.status == "pending":
            approval.status = "cancelled"
            approval.decision_reason = reason
            self.db.flush()

        return approval

    # -----------------------------------------------------------------------
    # CR-05-01: Verification & Atomic Approval
    # -----------------------------------------------------------------------

    def verify_and_approve_challenge(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        submitted_token: str,
        decision_by_user_id: UUID,
        runtime_parameters: dict[str, Any] | None = None,
        reason: str | None = None,
        user_role: str | None = None,
    ) -> Approval:
        """
        Verifies challenge code and payload hash, transitioning approval to 'approved'
        and atomically enqueuing the Outbox execution event in the same transaction.
        """
        approval = self.db.scalar(
            select(Approval)
            .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
            .with_for_update()
        )

        if approval is None:
            # Check for cross-tenant attempt
            cross_tenant = self.db.scalar(select(Approval).where(Approval.id == approval_id))
            if cross_tenant is not None:
                raise PermissionError("Cross-tenant access prohibited: approval belongs to another tenant")
            raise ValueError("Approval not found")

        # Check existing states
        if approval.status == "exhausted":
            raise ApprovalExhaustedError("Approval verification attempts exhausted. Request is revoked.")
        if approval.status == "cancelled":
            raise ApprovalCancelledError("Approval has been cancelled.")
        if approval.status == "approved":
            # Idempotent response: already approved
            return approval
        if approval.status != "pending":
            raise ValueError(f"Cannot verify approval in status '{approval.status}'")

        now = datetime.now(timezone.utc)

        # Check TTL Expiration
        if approval.expires_at is not None:
            exp = approval.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                approval.status = "expired"
                self.db.flush()
                raise ApprovalExpiredError("Approval challenge token has expired.")

        # Check Attempt Exhaustion
        if approval.failed_attempts >= approval.max_attempts:
            approval.status = "exhausted"
            self.db.flush()
            raise ApprovalExhaustedError("Maximum verification attempts exceeded. Approval is revoked.")

        # Role Authorization Check
        if user_role is None:
            user = self.db.scalar(select(User).where(User.id == decision_by_user_id))
            if user is not None:
                user_role = user.role

        if user_role is not None and not self.is_role_authorized(user_role, approval.requested_for):
            raise PermissionError(
                f"User role '{user_role}' is not authorized to approve requests for '{approval.requested_for}'"
            )

        # Verify Token
        stored_hash = approval.token or ""
        clean_submitted = (submitted_token or "").strip().upper()
        is_match = False
        if clean_submitted and stored_hash:
            is_match = self.verify_token(clean_submitted, stored_hash, tenant_id)

        if not is_match:
            approval.failed_attempts += 1
            if approval.failed_attempts >= approval.max_attempts:
                approval.status = "exhausted"
                self.db.flush()
                raise ApprovalExhaustedError(
                    f"Invalid challenge code. Maximum attempts ({approval.max_attempts}) reached. Approval revoked."
                )
            self.db.flush()
            remaining = approval.max_attempts - approval.failed_attempts
            raise ApprovalTokenMismatchError(
                f"Invalid challenge code. {remaining} attempt(s) remaining."
            )

        # Verify Payload Hash Binding
        if runtime_parameters is not None:
            runtime_hash = self.compute_payload_hash(runtime_parameters)
            if approval.payload_hash and runtime_hash != approval.payload_hash:
                approval.status = "cancelled"
                approval.decision_reason = "Payload mismatch detected during approval"
                self.db.flush()
                raise ApprovalPayloadMismatchError(
                    "Action payload does not match the approved parameters. Approval cancelled for safety."
                )

        # Transition Approval State
        approval.status = "approved"
        approval.execution_status = "queued"
        approval.decision_by_user_id = decision_by_user_id
        approval.decided_at = now
        approval.decision_reason = reason or "Verified via challenge code"

        # Atomically Enqueue Outbox Execution Event in the SAME transaction
        outbox_event = OutboxEvent(
            tenant_id=tenant_id,
            approval_id=approval.id,
            event_type="approval_action_execution",
            idempotency_key=approval.idempotency_key or f"approval_exec:{approval.id}",
            payload={
                "approval_id": str(approval.id),
                "action": approval.action,
                "payload_hash": approval.payload_hash,
                "parameters": approval.parameters_json,
            },
            status="pending",
            attempt_count=0,
            max_attempts=5,
            scheduled_at=now,
        )
        self.db.add(outbox_event)
        self.db.flush()

        logger.info(
            "Approved challenge %s for tenant %s. Outbox event %s enqueued atomically.",
            approval.id, tenant_id, outbox_event.id
        )
        return approval

    # -----------------------------------------------------------------------
    # CR-05-01: Atomic Result Update
    # -----------------------------------------------------------------------

    def record_execution_result(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        outbox_event_id: UUID,
        claim_generation: int,
        is_success: bool,
        error_message: str | None = None,
    ) -> None:
        """
        Atomically records execution outcome across outbox_events and approvals.
        Verifies rowcount == 1 on both updates; raises exception on any mismatch
        to force clean rollback and prevent stale worker corruption.
        """
        now = datetime.now(timezone.utc)

        # 1. Update outbox_events with claim_generation condition
        stmt_outbox = (
            update(OutboxEvent)
            .where(
                OutboxEvent.id == outbox_event_id,
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.claim_generation == claim_generation,
            )
            .values(
                status="completed" if is_success else "failed",
                processed_at=now,
                error_message=error_message if not is_success else None,
            )
        )
        res_outbox = self.db.execute(stmt_outbox)

        # 2. Check rowcount == 1
        if res_outbox.rowcount != 1:
            raise FencingOwnershipLostError(
                f"Fencing violation: Worker lost claim on outbox event {outbox_event_id} "
                f"(expected claim_generation {claim_generation}, got rowcount {res_outbox.rowcount})."
            )

        # 3. Update approvals with tenant and executing condition
        stmt_approval = (
            update(Approval)
            .where(
                Approval.id == approval_id,
                Approval.tenant_id == tenant_id,
                Approval.execution_status == "executing",
            )
            .values(
                execution_status="completed" if is_success else "failed",
                decision_reason=error_message if not is_success else None,
            )
        )
        res_approval = self.db.execute(stmt_approval)

        # 4. Check rowcount == 1
        if res_approval.rowcount != 1:
            raise ApprovalStateConflictError(
                f"Approval state conflict: Failed to update execution_status for approval {approval_id} "
                f"(tenant {tenant_id}). Expected rowcount 1, got {res_approval.rowcount}."
            )

        self.db.flush()
        logger.info(
            "Atomically recorded execution result for approval %s (success=%s)",
            approval_id, is_success
        )

    # -----------------------------------------------------------------------
    # Legacy / Compatibility Methods
    # -----------------------------------------------------------------------

    def create_approval(
        self,
        tenant_id: UUID,
        requested_for: str,
        action: str,
        description: str,
        task_id: UUID | None = None,
        requested_by_agent_id: UUID | None = None,
        *,
        token: str | None = None,
        expires_at: datetime | None = None,
        expires_in_hours: int | None = None,
    ) -> Approval:
        requested_for = requested_for.strip()
        action = action.strip()
        description = description.strip()

        if not requested_for:
            raise ValueError("Approval requested_for cannot be empty")
        if not action:
            raise ValueError("Approval action cannot be empty")
        if not description:
            raise ValueError("Approval description cannot be empty")

        meta_prefix = ""
        clean_token = token.strip().upper() if token else None
        if clean_token:
            meta_prefix += f"[TOKEN: {clean_token}] "

        calc_expiry = expires_at
        if calc_expiry is None and expires_in_hours is not None and expires_in_hours > 0:
            calc_expiry = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)

        if calc_expiry:
            if calc_expiry.tzinfo is None:
                calc_expiry = calc_expiry.replace(tzinfo=timezone.utc)
            meta_prefix += f"[EXPIRES: {calc_expiry.isoformat()}] "

        if task_id is not None:
            task = self.db.scalar(select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id))
            if task is None:
                raise ValueError(f"Task '{task_id}' not found for tenant")
            if getattr(task, "status", None) in ("completed", "failed", "cancelled"):
                raise ValueError(f"Cannot create approval for inactive task in status '{task.status}'")

        effective_description = f"{meta_prefix}{description}".strip()
        app_id = uuid4()

        approval = Approval(
            id=app_id,
            tenant_id=tenant_id,
            task_id=task_id,
            requested_by_agent_id=requested_by_agent_id,
            requested_for=requested_for,
            action=action,
            description=effective_description,
            status="pending",
            token=clean_token,
            expires_at=calc_expiry,
            failed_attempts=0,
            max_attempts=self.CHALLENGE_MAX_ATTEMPTS,
            payload_hash=self.compute_payload_hash({}),
            parameters_json={},
            execution_status="not_started",
            idempotency_key=f"approval_exec:{app_id}",
        )

        self.db.add(approval)
        self.db.flush()
        return approval

    @staticmethod
    def get_approval_token(approval: Approval | None) -> str | None:
        if not approval:
            return None
        col_token = getattr(approval, "token", None)
        if col_token:
            return str(col_token).strip()
        if not approval.description:
            return None
        m = re.search(r"\[TOKEN:\s*([A-Za-z0-9_-]+)\]", approval.description)
        return m.group(1).strip() if m else None

    @staticmethod
    def get_approval_expiry(approval: Approval | None) -> datetime | None:
        if not approval:
            return None
        col_expiry = getattr(approval, "expires_at", None)
        if col_expiry is not None:
            return col_expiry
        if not approval.description:
            return None
        m = re.search(r"\[EXPIRES:\s*([^\]]+)\]", approval.description)
        if not m:
            return None
        try:
            return datetime.fromisoformat(m.group(1).strip())
        except Exception:
            return None

    @staticmethod
    def is_approval_expired(approval: Approval | None) -> bool:
        expiry = ApprovalService.get_approval_expiry(approval)
        if expiry is None:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expiry

    def find_pending_approval_by_token(self, tenant_id: UUID, token: str) -> Approval | None:
        if not token:
            return None
        clean_token = token.strip().upper()
        # Direct indexed token search
        indexed_app = self.db.scalar(
            select(Approval).where(
                Approval.tenant_id == tenant_id,
                func.upper(Approval.token) == clean_token,
                Approval.status == "pending",
            )
        )
        if indexed_app is not None:
            return indexed_app

        # Scan for challenge HMAC matching
        pending_list = self.list_approvals(tenant_id, status="pending")
        for app in pending_list:
            if app.token and self.verify_token(clean_token, app.token, tenant_id):
                return app
            app_token = self.get_approval_token(app)
            if app_token and app_token.upper() == clean_token:
                return app
        return None

    @staticmethod
    def is_role_authorized(role: str | None, requested_for: str) -> bool:
        norm_role = (role or "").strip().lower()
        norm_req = (requested_for or "").strip().lower()

        if norm_req in ("owner", "tenant_owner"):
            return norm_role in ("owner", "tenant_owner")
        if norm_role in ("owner", "tenant_owner"):
            return True
        if norm_req in ("superadmin", "platform_admin"):
            return norm_role in ("superadmin", "platform_admin", "owner", "tenant_owner")
        if norm_req in ("tenant_admin", "admin"):
            return norm_role in ("admin", "tenant_admin", "owner", "tenant_owner")
        if norm_req in ("tenant_user", "user", "member", ""):
            return True
        return False

    def approve(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        decision_by_user_id: UUID,
        reason: str | None = None,
        user_role: str | None = None,
        *,
        token: str | None = None,
    ) -> Approval:
        approval = self.db.scalar(
            select(Approval)
            .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
            .with_for_update()
        )

        if approval is None:
            cross_tenant = self.db.scalar(select(Approval).where(Approval.id == approval_id))
            if cross_tenant is not None:
                raise PermissionError("Cross-tenant access prohibited: approval belongs to another tenant")
            raise ValueError("Approval not found")

        if approval.status != "pending":
            raise ValueError("Only pending approvals can be approved")

        if self.is_approval_expired(approval):
            raise ValueError("Approval request has expired")

        expected_token = self.get_approval_token(approval)
        if expected_token:
            clean_submitted = (token or "").strip().upper()
            is_valid = False
            # Check if stored as HMAC or plaintext
            if self.verify_token(clean_submitted, expected_token, tenant_id):
                is_valid = True
            elif clean_submitted == expected_token:
                is_valid = True

            if not is_valid:
                approval.failed_attempts = (approval.failed_attempts or 0) + 1
                if approval.failed_attempts >= (approval.max_attempts or 3):
                    approval.status = "exhausted"
                self.db.flush()
                raise ValueError(f"Approval token mismatch: token is required to authorize this request")

        if user_role is None:
            user = self.db.scalar(select(User).where(User.id == decision_by_user_id))
            if user is not None:
                user_role = user.role

        if user_role is not None and not self.is_role_authorized(user_role, approval.requested_for):
            raise PermissionError(
                f"User role '{user_role}' is not authorized to approve requests for '{approval.requested_for}'"
            )

        if approval.task_id is not None:
            task = self.db.scalar(select(Task).where(Task.id == approval.task_id, Task.tenant_id == tenant_id))
            if task is not None and task.status in ("completed", "failed", "cancelled"):
                raise ValueError(f"Cannot approve request for task in terminal status '{task.status}'")

        now = datetime.now(timezone.utc)
        approval.status = "approved"
        approval.execution_status = "queued"
        approval.decision_by_user_id = decision_by_user_id
        approval.decided_at = now
        clean_reason = reason.strip() if reason is not None else None
        approval.decision_reason = clean_reason

        # Atomic Outbox event creation
        outbox_event = OutboxEvent(
            tenant_id=tenant_id,
            approval_id=approval.id,
            event_type="approval_action_execution",
            idempotency_key=approval.idempotency_key or f"approval_exec:{approval.id}",
            payload={
                "approval_id": str(approval.id),
                "action": approval.action,
                "payload_hash": approval.payload_hash,
                "parameters": approval.parameters_json,
            },
            status="pending",
            attempt_count=0,
            max_attempts=5,
            scheduled_at=now,
        )
        self.db.add(outbox_event)
        self.db.flush()

        return approval

    def reject(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        decision_by_user_id: UUID,
        reason: str | None = None,
        user_role: str | None = None,
    ) -> Approval:
        approval = self.db.scalar(
            select(Approval)
            .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
            .with_for_update()
        )

        if approval is None:
            cross_tenant = self.db.scalar(select(Approval).where(Approval.id == approval_id))
            if cross_tenant is not None:
                raise PermissionError("Cross-tenant access prohibited: approval belongs to another tenant")
            raise ValueError("Approval not found")

        if approval.status != "pending":
            raise ValueError("Only pending approvals can be rejected")

        if user_role is None:
            user = self.db.scalar(select(User).where(User.id == decision_by_user_id))
            if user is not None:
                user_role = user.role

        if user_role is not None and not self.is_role_authorized(user_role, approval.requested_for):
            raise PermissionError(
                f"User role '{user_role}' is not authorized to reject requests for '{approval.requested_for}'"
            )

        approval.status = "rejected"
        approval.execution_status = "not_started"
        approval.decision_by_user_id = decision_by_user_id
        approval.decided_at = datetime.now(timezone.utc)
        approval.decision_reason = reason.strip() if reason is not None else None

        self.db.flush()
        return approval

    def cancel(
        self,
        tenant_id: UUID,
        approval_id: UUID,
        user_id: UUID | None = None,
        user_role: str | None = None,
    ) -> Approval:
        approval = self.db.scalar(
            select(Approval)
            .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
            .with_for_update()
        )

        if approval is None:
            cross_tenant = self.db.scalar(select(Approval).where(Approval.id == approval_id))
            if cross_tenant is not None:
                raise PermissionError("Cross-tenant access prohibited: approval belongs to another tenant")
            raise ValueError("Approval not found")

        if approval.status != "pending":
            raise ValueError("Only pending approvals can be cancelled")

        if user_role is None and user_id is not None:
            user = self.db.scalar(select(User).where(User.id == user_id))
            if user is not None:
                user_role = user.role

        if user_role is not None and user_role not in (
            "owner", "tenant_owner", "admin", "tenant_admin", "superadmin"
        ):
            raise PermissionError("Only administrators or owners can cancel approvals")

        approval.status = "cancelled"
        approval.execution_status = "not_started"
        self.db.flush()
        return approval
