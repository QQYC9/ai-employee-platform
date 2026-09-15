from fastapi import APIRouter

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


router = APIRouter(
    prefix="/api/v1",
)


router.include_router(auth_router)
router.include_router(tenants_router)
router.include_router(agents_router)
router.include_router(tasks_router)
router.include_router(customers_router)
router.include_router(capabilities_router)
router.include_router(agent_capabilities_router)
router.include_router(tools_router)
