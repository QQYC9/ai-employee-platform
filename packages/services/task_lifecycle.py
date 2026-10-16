from __future__ import annotations

from typing import Final


class TaskStatus:
    """Canonical task lifecycle statuses."""

    PENDING: Final[str] = "pending"
    PLANNING: Final[str] = "planning"
    PLANNED: Final[str] = "planned"
    RUNNING: Final[str] = "running"
    WAITING_APPROVAL: Final[str] = "waiting_approval"
    COMPLETED: Final[str] = "completed"
    FAILED: Final[str] = "failed"
    CANCELLED: Final[str] = "cancelled"

    ALL: Final[set[str]] = {
        PENDING,
        PLANNING,
        PLANNED,
        RUNNING,
        WAITING_APPROVAL,
        COMPLETED,
        FAILED,
        CANCELLED,
    }

    TERMINAL: Final[set[str]] = {
        COMPLETED,
        FAILED,
        CANCELLED,
    }


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal lifecycle state transition is attempted."""

    def __init__(self, from_status: str, to_status: str, message: str | None = None):
        self.from_status = from_status
        self.to_status = to_status
        msg = message or f"Illegal state transition from '{from_status}' to '{to_status}'"
        super().__init__(msg)


# Allowed forward state transitions in normal execution
VALID_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.PENDING: {
        TaskStatus.PLANNING,
        TaskStatus.PLANNED,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PLANNING: {
        TaskStatus.PLANNED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PLANNED: {
        TaskStatus.PLANNING,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_APPROVAL: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),  # Terminal: completed tasks cannot transition
    TaskStatus.FAILED: {
        # Terminal: only reachable via explicit recovery operation
        TaskStatus.PLANNING,
        TaskStatus.PLANNED,
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CANCELLED: set(),  # Terminal: cancelled tasks cannot transition
}


def can_transition(
    from_status: str,
    to_status: str,
    *,
    is_recovery: bool = False,
) -> bool:
    """
    Check if a state transition is permissible under the lifecycle rules.
    Terminal states cannot transition unless explicit recovery is requested.
    """
    norm_from = (from_status or "").strip().lower()
    norm_to = (to_status or "").strip().lower()

    if norm_from == norm_to:
        return True

    if norm_from == TaskStatus.FAILED and not is_recovery:
        return False

    allowed = VALID_TRANSITIONS.get(norm_from, set())
    return norm_to in allowed


def validate_transition(
    from_status: str,
    to_status: str,
    *,
    is_recovery: bool = False,
    task_id: str | None = None,
) -> None:
    """
    Validate that transitioning from from_status to to_status is allowed.
    Raises InvalidStateTransitionError if the transition is prohibited.
    """
    norm_from = (from_status or "").strip().lower()
    norm_to = (to_status or "").strip().lower()

    if not can_transition(norm_from, norm_to, is_recovery=is_recovery):
        prefix = f"Task '{task_id}': " if task_id else ""
        if norm_from in TaskStatus.TERMINAL:
            if norm_from == TaskStatus.FAILED and not is_recovery:
                raise InvalidStateTransitionError(
                    norm_from,
                    norm_to,
                    f"{prefix}Cannot transition failed task to '{norm_to}' without an explicit recovery operation",
                )
            raise InvalidStateTransitionError(
                norm_from,
                norm_to,
                f"{prefix}Cannot transition terminal task from '{norm_from}' to '{norm_to}'",
            )
        raise InvalidStateTransitionError(
            norm_from,
            norm_to,
            f"{prefix}Invalid task lifecycle transition: cannot transition from '{norm_from}' to '{norm_to}'",
        )
