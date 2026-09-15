import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from packages.tenants.context import (
    get_current_tenant_id,
    require_tenant,
    tenant_context,
)


def test_tenant_context_allows_same_tenant():
    tenant_id = uuid4()

    with tenant_context(tenant_id):
        assert get_current_tenant_id() == tenant_id
        require_tenant(tenant_id)


def test_tenant_context_denies_cross_tenant():
    tenant_a = uuid4()
    tenant_b = uuid4()

    with tenant_context(tenant_a):
        with pytest.raises(PermissionError, match="Tenant access denied"):
            require_tenant(tenant_b)


def test_tenant_context_is_cleaned_up():
    tenant_id = uuid4()

    with tenant_context(tenant_id):
        assert get_current_tenant_id() == tenant_id

    with pytest.raises(RuntimeError, match="No tenant context is active"):
        get_current_tenant_id()
