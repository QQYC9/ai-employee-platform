from __future__ import annotations

from fastapi import Depends

from packages.auth.dependencies import get_current_user
from packages.models.domain import User
from packages.tenants.context import tenant_context


def get_tenant_context(
    current_user: User = Depends(get_current_user),
):
    """
    Activate the authenticated user's tenant context
    for the duration of the request.
    """
    with tenant_context(current_user.tenant_id):
        yield current_user
