from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID


_current_tenant_id: ContextVar[UUID | None] = ContextVar(
    "current_tenant_id",
    default=None,
)


def set_current_tenant(tenant_id: UUID) -> None:
    """Set the tenant for the current execution context."""
    _current_tenant_id.set(tenant_id)


def get_current_tenant_id() -> UUID:
    """Return the current tenant ID or raise if none is set."""
    tenant_id = _current_tenant_id.get()

    if tenant_id is None:
        raise RuntimeError("No tenant context is active")

    return tenant_id


def clear_current_tenant() -> None:
    """Clear the tenant from the current execution context."""
    _current_tenant_id.set(None)


@contextmanager
def tenant_context(tenant_id: UUID):
    """Temporarily activate a tenant context."""
    _current_tenant_id.set(tenant_id)

    try:
        yield
    finally:
        _current_tenant_id.set(None)


def require_tenant(tenant_id: UUID) -> None:
    """Verify that an operation belongs to the active tenant."""
    current_tenant_id = get_current_tenant_id()

    if current_tenant_id != tenant_id:
        raise PermissionError("Tenant access denied")
