import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import roles_of
from app.core.security import CurrentUser, current_user, get_db
from app.modules.agents import proposals
from app.modules.agents.models import AgentProposal
from app.modules.playbooks import service as playbooks
from app.modules.playbooks.schemas import PermissionsOut
from app.modules.tenancy.schemas import MeOut, RoleOut

router = APIRouter(prefix="/api", tags=["tenancy"])


@router.get("/me")
async def me(
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MeOut:
    """The caller and their roles from user_role, never from the token (D-04)."""
    grants = await roles_of(session, user.id)
    return MeOut(
        id=user.id,
        display_name=user.display_name,
        email=user.email,
        roles=[
            RoleOut(code=g.code, mission_id=g.mission_id, mission_code=g.mission_code)
            for g in grants
        ],
    )


@router.get("/me/permissions")
async def my_permissions(
    entity_type: Literal["playbook_run", "agent_proposal"],
    entity_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PermissionsOut:
    """Plan G-07: the actions the caller may take on an entity now, computed by
    approvals.can_decide(), the same code that enforces them."""
    if entity_type == "agent_proposal":
        proposal = await session.get(AgentProposal, entity_id)
        if proposal is None:
            return PermissionsOut(entity_type=entity_type, entity_id=str(entity_id))
        return PermissionsOut(
            entity_type=entity_type,
            entity_id=str(entity_id),
            decide_proposal=await proposals.can_decide(session, user, proposal),
            dismiss_proposal=await proposals.can_dismiss(session, user, proposal),
            undo_proposal=await proposals.can_undo(session, user, proposal),
        )
    return PermissionsOut(
        entity_type=entity_type,
        entity_id=str(entity_id),
        approve_step=await playbooks.approvable_steps(session, user, entity_id),
    )
