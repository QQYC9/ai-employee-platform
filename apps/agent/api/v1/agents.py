from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from packages.auth.dependencies import get_current_user, get_db
from packages.models.domain import User
from packages.services.agent_service import AgentService
from packages.tenants.context import tenant_context


router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)


class AgentResponse(BaseModel):
    id: str
    name: str
    agent_type: str
    status: str


class AgentCreateRequest(BaseModel):
    name: str
    agent_type: str = "main"


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None


def serialize_agent(agent):
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        agent_type=agent.agent_type,
        status=agent.status,
    )


@router.get("/status")
def agents_status():
    return {
        "status": "ok",
        "service": "agents",
    }


@router.get("", response_model=list[AgentResponse])
def list_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentService(db)

        agents = service.list_agents(
            tenant_id=current_user.tenant_id,
        )

        return [
            serialize_agent(agent)
            for agent in agents
        ]


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentService(db)

        agent = service.get_agent(
            tenant_id=current_user.tenant_id,
            agent_id=agent_id,
        )

        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            )

        return serialize_agent(agent)


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_agent(
    payload: AgentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentService(db)

        try:
            agent = service.create_agent(
                tenant_id=current_user.tenant_id,
                name=payload.name,
                agent_type=payload.agent_type,
            )

            db.commit()

        except ValueError as exc:
            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        return serialize_agent(agent)


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
)
def update_agent(
    agent_id: UUID,
    payload: AgentUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with tenant_context(current_user.tenant_id):
        service = AgentService(db)

        try:
            agent = service.update_agent(
                tenant_id=current_user.tenant_id,
                agent_id=agent_id,
                name=payload.name,
                status=payload.status,
            )

            db.commit()

        except ValueError as exc:
            db.rollback()

            if str(exc) == "Agent not found":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

        return serialize_agent(agent)
