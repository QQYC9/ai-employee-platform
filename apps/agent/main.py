from fastapi import Depends, FastAPI

from apps.agent.api.v1.auth import router as auth_router
from apps.agent.api.v1.tenants import router as tenants_router
from apps.agent.api.v1.agents import router as agents_router
from apps.agent.api.v1.tasks import router as tasks_router
from apps.agent.api.v1.customers import router as customers_router
from apps.agent.api.v1.channels import router as channels_router
from apps.agent.api.v1.conversations import router as conversations_router
from apps.agent.api.v1.memory import router as memory_router
from apps.agent.api.v1.knowledge import router as knowledge_router
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
from apps.agent.api.v1.audit import (
    router as audit_router,
)
from apps.agent.api.v1.ai_providers import (
    router as ai_providers_router,
)
from apps.agent.api.v1.webhooks import (
    router as webhooks_router,
)
from apps.agent.api.v1.proactive_workflows import (
    router as proactive_workflows_router,
)
from apps.agent.api.v1.documents import (
    router as documents_router,
)
from apps.agent.api.v1.admin import (
    router as admin_router,
)
from apps.agent.api.v1.admin_integrations import (
    router as admin_integrations_router,
)
from apps.agent.api.v1.self_development import (
    router as self_development_router,
)
from apps.agent.api.v1.traces import (
    router as traces_router,
)
from apps.agent.api.v1.campaigns import (
    router as campaigns_router,
)



from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import User
from sqlalchemy.orm import Session
from apps.agent.api.v1.tenants import (
    BusinessBrainUpdateRequest,
    get_my_business_brain,
    update_my_business_brain,
)

from contextlib import asynccontextmanager
import logging
import threading
from packages.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify production security configuration at startup
    if settings.environment.lower() in ("production", "prod", "staging"):
        if (
            not settings.jwt_secret_key
            or settings.jwt_secret_key.startswith("dev-")
            or len(settings.jwt_secret_key) < 32
        ):
            raise RuntimeError(
                f"Application startup aborted: Insecure JWT_SECRET_KEY in production environment ({settings.environment})"
            )

    worker = None
    worker_thread = None

    if settings.enable_embedded_worker:
        from packages.services.outbox_worker import OutboxWorker
        worker = OutboxWorker(
            poll_interval_seconds=settings.outbox_worker_poll_interval,
            batch_size=settings.outbox_worker_batch_size,
            lock_timeout_seconds=settings.outbox_worker_lock_timeout,
        )
        worker_thread = threading.Thread(
            target=worker.run,
            name="outbox-embedded-worker",
            daemon=True,
        )
        worker_thread.start()
        logger.info("Embedded outbox worker started in background thread")

    yield

    if worker is not None:
        logger.info("Stopping embedded outbox worker...")
        worker.stop()
        if worker_thread is not None:
            worker_thread.join(timeout=5.0)
        logger.info("Embedded outbox worker stopped")


app = FastAPI(
    title="AI Employee Platform",
    version="0.1.0",
    lifespan=lifespan,
)


API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(tenants_router, prefix=API_PREFIX)
app.include_router(agents_router, prefix=API_PREFIX)
app.include_router(tasks_router, prefix=API_PREFIX)
app.include_router(customers_router, prefix=API_PREFIX)
app.include_router(channels_router, prefix=API_PREFIX)
app.include_router(conversations_router, prefix=API_PREFIX)
app.include_router(memory_router, prefix=API_PREFIX)
app.include_router(knowledge_router, prefix=API_PREFIX)
app.include_router(capabilities_router, prefix=API_PREFIX)
app.include_router(agent_capabilities_router, prefix=API_PREFIX)
app.include_router(tools_router, prefix=API_PREFIX)
app.include_router(capability_tools_router, prefix=API_PREFIX)
app.include_router(tool_integrations_router, prefix=API_PREFIX)
app.include_router(permissions_router, prefix=API_PREFIX)
app.include_router(approvals_router, prefix=API_PREFIX)
app.include_router(action_policies_router, prefix=API_PREFIX)
app.include_router(decision_router, prefix=API_PREFIX)
app.include_router(audit_router, prefix=API_PREFIX)
app.include_router(ai_providers_router, prefix=API_PREFIX)
app.include_router(webhooks_router, prefix=API_PREFIX)
app.include_router(proactive_workflows_router, prefix=API_PREFIX)
app.include_router(documents_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(admin_integrations_router, prefix=API_PREFIX)
app.include_router(self_development_router, prefix=API_PREFIX)
app.include_router(traces_router, prefix=API_PREFIX)
app.include_router(campaigns_router, prefix=API_PREFIX)




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


@app.get("/api/v1/me/brain")
def get_me_brain(
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    return get_my_business_brain(current_user=current_user, db=db)


@app.patch("/api/v1/me/brain")
def patch_me_brain(
    payload: BusinessBrainUpdateRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    return update_my_business_brain(payload=payload, current_user=current_user, db=db)
