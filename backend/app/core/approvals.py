"""The single place for role and mission-scope checks (D-05, D-16).

Changes need human sign-off (D-29). Agent proposals and playbook gates both go
through this module (decide() arrives in Prompt 9). Roles come only from the
user_role table, never from the token (D-04).

Mission scope:
- ANY_MISSION: the user holds the role at any scope. Used to gate endpoints.
- a mission id: the user holds the role for that mission, or unscoped
  (user_role.mission_id IS NULL, the HQ roles) (D-05).
- None: the subject has no mission (incident.mission_id not yet set), so only
  unscoped holders qualify (D-06).
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Final

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, get_db
from app.modules.people.models import Mission
from app.modules.tenancy.models import Role, UserRole


class _AnyMission(Enum):
    ANY_MISSION = "ANY_MISSION"


ANY_MISSION: Final = _AnyMission.ANY_MISSION
MissionScope = uuid.UUID | None | _AnyMission


def parse_role_codes(role_codes: str | Iterable[str]) -> frozenset[str]:
    """'DUTY_OFFICER|SECURITY_OFFICER' or ['A', 'B|C'] -> {'DUTY_OFFICER', ...}."""
    parts = [role_codes] if isinstance(role_codes, str) else list(role_codes)
    codes = frozenset(c.strip() for part in parts for c in part.split("|") if c.strip())
    if not codes:
        raise ValueError("at least one role code is required")
    return codes


async def user_has_role(
    session: AsyncSession,
    user: CurrentUser | uuid.UUID,
    role_codes: str | Iterable[str],
    mission_id: MissionScope = ANY_MISSION,
) -> bool:
    """True if the user holds one of role_codes within mission_id's scope."""
    user_id = user.id if isinstance(user, CurrentUser) else user
    conditions = [
        UserRole.user_id == user_id,
        Role.code.in_(parse_role_codes(role_codes)),
    ]
    if mission_id is None:
        conditions.append(UserRole.mission_id.is_(None))
    elif mission_id is not ANY_MISSION:
        conditions.append(or_(UserRole.mission_id.is_(None), UserRole.mission_id == mission_id))
    query = select(UserRole.id).join(Role, Role.id == UserRole.role_id).where(*conditions).limit(1)
    return await session.scalar(query) is not None


@dataclass(frozen=True)
class RoleGrant:
    code: str
    mission_id: uuid.UUID | None
    mission_code: str | None


async def roles_of(session: AsyncSession, user_id: uuid.UUID) -> list[RoleGrant]:
    rows = await session.execute(
        select(Role.code, UserRole.mission_id, Mission.code)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(Mission, Mission.id == UserRole.mission_id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.code, Mission.code.nulls_first())
    )
    return [RoleGrant(code=c, mission_id=m, mission_code=mc) for c, m, mc in rows]


def require_roles(
    *role_codes: str, mission_id: MissionScope = ANY_MISSION
) -> Callable[..., Awaitable[CurrentUser]]:
    """FastAPI dependency: 403 unless the caller holds one of role_codes."""
    codes = parse_role_codes(role_codes)

    async def dependency(
        user: Annotated[CurrentUser, Depends(current_user)],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> CurrentUser:
        if not await user_has_role(session, user, codes, mission_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user

    return dependency
