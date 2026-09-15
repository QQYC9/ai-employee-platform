from fastapi import Depends, FastAPI

from apps.agent.api.v1.auth import router as auth_router
from apps.agent.api.v1.tenants import router as tenants_router
from apps.agent.api.v1.agents import router as agents_router
from apps.agent.api.v1.tasks import router as tasks_router
from apps.agent.api.v1.customers import router as customers_router
from apps.agent.api.v1.capabilities import router as capabilities_router
from apps.agent.api.v1.agent_capabilities import (
    router as agent_capabilities_router,
)
from apps.agent.api.v1.tools import router as tools_router
from apps.agent.api.v1.capability_tools import (
    router as capability_tools_router,
)
from apps.agent.api.v1.tool_integrations import (
    router as tool_integrations_router,
)
from apps.agent.api.v1.permissions import (
    router as permissions_router,
)
from apps.agent.api.v1.approvals import (
    router as approvals_router,
)
from apps.agent.api.v1.action_policies import (
    router as action_policies_router,
)
from apps.agent.api.v1.decision import (
    router as decision_router,
)

from packages.auth.context import get_tenant_context
from packages.models.domain import User

app = FastAPI(
    title="AI Employee Platform",
    version="0.1.0",
)

API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(tenants_router, prefix=API_PREFIX)
app.include_router(agents_router, prefix=API_PREFIX)
app.include_router(tasks_router, prefix=API_PREFIX)
app.include_router(customers_router, prefix=API_PREFIX)
app.include_router(capabilities_router, prefix=API_PREFIX)
app.include_router(agent_capabilities_router, prefix=API_PREFIX)
app.include_router(tools_router, prefix=API_PREFIX)
app.include_router(capability_tools_router, prefix=API_PREFIX)
app.include_router(tool_integrations_router, prefix=API_PREFIX)
app.include_router(permissions_router, prefix=API_PREFIX)
app.include_router(approvals_router, prefix=API_PREFIX)
app.include_router(action_policies_router, prefix=API_PREFIX)
app.include_router(decision_router, prefix=API_PREFIX)


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "AI Employee Platform is running",
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/me")
def get_me(
    current_user: User = Depends(get_tenant_context),
):
    return {
        "user_id": str(current_user.id),
        "tenant_id": str(current_user.tenant_id),
        "name": current_user.name,
        "role": current_user.role,
    }
