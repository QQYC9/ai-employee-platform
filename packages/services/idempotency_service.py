from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.models.domain import IdempotencyRecord


class ConcurrencyConflictError(Exception):
    """Raised when an operation with the same idempotency key is already running."""
    pass


class ReconciliationRequiredError(Exception):
    """Raised when an operation cannot be automatically verified after an interruption."""
    pass


class IdempotencyTamperingError(Exception):
    """Raised when an idempotency key is reused with different parameters or action."""
    pass


class IdempotencyService:
    """
    Manages persistent idempotency records in PostgreSQL.
    Provides row-level concurrency control, duplicate prevention,
    and post-crash reconciliation guarantees.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_record(
        self,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        try:
            return self.db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.tenant_id == tenant_id,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
        except Exception:
            return None

    def acquire_or_check(
        self,
        *,
        tenant_id: UUID,
        idempotency_key: str,
        action: str,
        resource: str | None = None,
        tool_id: UUID | None = None,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
    ) -> tuple[str, Any | None]:
        """
        Acquire lock for execution or return existing status/result.

        Returns tuple: (status, result_or_output)
          - ("acquired", None): lock acquired, caller may proceed with execution
          - ("completed", result): already completed, cached result returned

        Raises:
          - ConcurrencyConflictError: operation is already running in parallel
          - ReconciliationRequiredError: execution was interrupted and needs manual resolution
          - IdempotencyTamperingError: parameters or action mismatch
        """
        params_hash = hashlib.sha256(
            json.dumps(parameters or {}, sort_keys=True).encode()
        ).hexdigest()

        try:
            statement = select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )

            try:
                record = self.db.scalar(statement.with_for_update())
            except Exception:
                record = self.db.scalar(statement)

            if record is not None:
                # Guard against tampering
                if record.action != action:
                    raise IdempotencyTamperingError(
                        f"Idempotency key '{idempotency_key}' reused with different action: "
                        f"original='{record.action}', new='{action}'"
                    )
                if record.parameters_hash and record.parameters_hash != params_hash:
                    raise IdempotencyTamperingError(
                        f"Idempotency key '{idempotency_key}' reused with altered parameters."
                    )

                if record.status == "completed":
                    return ("completed", record.result)

                if record.status == "reconciliation_required":
                    raise ReconciliationRequiredError(
                        f"Operation with idempotency key '{idempotency_key}' requires manual reconciliation."
                    )

                if record.status == "in_progress":
                    now = datetime.now(timezone.utc)
                    locked_at = record.locked_at
                    if locked_at is not None and locked_at.tzinfo is None:
                        locked_at = locked_at.replace(tzinfo=timezone.utc)

                    elapsed = (now - locked_at).total_seconds() if locked_at else 0
                    if elapsed < timeout_seconds:
                        raise ConcurrencyConflictError(
                            f"Operation with idempotency key '{idempotency_key}' is currently in progress."
                        )

                    # Lock timed out: mark reconciliation required to prevent silent duplicates
                    record.status = "reconciliation_required"
                    record.error = f"Lock timed out after {elapsed:.0f} seconds without completion."
                    self.db.flush()
                    raise ReconciliationRequiredError(
                        f"Operation with idempotency key '{idempotency_key}' timed out in progress. Manual reconciliation required."
                    )

                if record.status == "failed":
                    record.status = "in_progress"
                    record.locked_at = datetime.now(timezone.utc)
                    self.db.flush()
                    return ("acquired", None)

            # Record does not exist: create in_progress
            new_record = IdempotencyRecord(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                tool_id=tool_id,
                action=action,
                resource=resource,
                parameters_hash=params_hash,
                status="in_progress",
                locked_at=datetime.now(timezone.utc),
            )
            self.db.add(new_record)
            self.db.flush()
            return ("acquired", None)

        except IntegrityError:
            self.db.rollback()
            raise ConcurrencyConflictError(
                f"Concurrent request in progress for idempotency key '{idempotency_key}'."
            )

    def complete(
        self,
        tenant_id: UUID,
        idempotency_key: str,
        result: Any,
    ) -> IdempotencyRecord | None:
        try:
            record = self.db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.tenant_id == tenant_id,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if record is not None:
                record.status = "completed"
                record.result = result
                record.error = None
                self.db.flush()
            return record
        except Exception:
            return None

    def fail(
        self,
        tenant_id: UUID,
        idempotency_key: str,
        error: str,
    ) -> IdempotencyRecord | None:
        try:
            record = self.db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.tenant_id == tenant_id,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if record is not None:
                record.status = "failed"
                record.error = error
                self.db.flush()
            return record
        except Exception:
            return None

    def mark_reconciliation_required(
        self,
        tenant_id: UUID,
        idempotency_key: str,
        error: str,
    ) -> IdempotencyRecord | None:
        try:
            record = self.db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.tenant_id == tenant_id,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if record is not None:
                record.status = "reconciliation_required"
                record.error = error
                self.db.flush()
            return record
        except Exception:
            return None
