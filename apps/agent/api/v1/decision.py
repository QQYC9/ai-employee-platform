from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_db
from packages.models.domain import User
from packages.services.decision_engine import DecisionEngine


router = APIRouter(
    prefix="/decision",
    tags=["decision"],
)


class DecisionCheckRequest(BaseModel):
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    agent_id: UUID | None = None


@router.post("/check")
def check_decision(
    payload: DecisionCheckRequest,
    current_user: User = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    engine = DecisionEngine(db)

    result = engine.decide(
        tenant_id=current_user.tenant_id,
        action=payload.action,
        resource=payload.resource,
        agent_id=payload.agent_id,
    )

    return {
        "decision": result.decision,
        "reason": result.reason,
        "requires_approval": result.requires_approval,
        "approval_for": result.approval_for,
    }
