from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import roles_of
from app.core.security import CurrentUser, current_user, get_db
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
