"""The single place for role and mission-scope checks (D-05, D-16).

Changes need human sign-off (D-29). Agent proposals and playbook gates both go
through decide() / can_decide() here. Roles come only from the user_role table,
never from the token (D-04).

decide() checks, in this order, and refuses with the first failure:
1. 409 the step is already decided;
2. 409 the step is not open for a decision yet (earlier steps not approved, or
   the run or proposal has not reached it);
3. 403 the user already decided another step of the same subject (D-16: one
   person never fills two steps, even holding both roles);
4. 403 the user lacks the role ('|' alternatives) within the mission scope.
For agent proposals the database adds a backstop (the distinct-approver index and
the order triggers on proposal_approval); app/core/errors.py turns those into 409.
Playbook gates have no such constraint yet (proposed as PC-06): for them this
check, made with the run row locked, is the only enforcement.

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


@dataclass(frozen=True)
class Gate:
    """One approval step, as the caller found it with its rows locked.

    The caller builds it from its own tables (playbook_run_step now, and
    proposal_approval in Prompt 12); every rule is applied here.
    """

    subject: str  # for messages, e.g. "PB-07 step 7"
    required_role: str  # one approval step; may list alternatives with '|' (D-16)
    mission_id: uuid.UUID | None  # incident.mission_id; None = unscoped holders only (D-06)
    decided: bool
    open: bool  # reached, and every earlier step approved
    deciders_of_other_steps: frozenset[uuid.UUID]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    status_code: int  # 200, 403 or 409
    reason: str


class ApprovalDeniedError(Exception):
    def __init__(self, verdict: Verdict) -> None:
        super().__init__(verdict.reason)
        self.verdict = verdict


async def can_decide(session: AsyncSession, user: CurrentUser | uuid.UUID, gate: Gate) -> Verdict:
    """Whether user may decide gate now. Also used to show or hide actions (plan G-07)."""
    user_id = user.id if isinstance(user, CurrentUser) else user
    if gate.decided:
        return Verdict(False, status.HTTP_409_CONFLICT, f"{gate.subject} is already decided")
    if not gate.open:
        return Verdict(
            False, status.HTTP_409_CONFLICT, f"{gate.subject} is not awaiting a decision"
        )
    if user_id in gate.deciders_of_other_steps:
        return Verdict(
            False,
            status.HTTP_403_FORBIDDEN,
            "The same person cannot decide two steps (D-16)",
        )
    if not await user_has_role(session, user_id, gate.required_role, gate.mission_id):
        scope = "this mission" if gate.mission_id else "HQ (no mission set)"
        return Verdict(
            False,
            status.HTTP_403_FORBIDDEN,
            f"{gate.subject} needs {gate.required_role.replace('|', ' or ')} for {scope}",
        )
    return Verdict(True, status.HTTP_200_OK, "allowed")


async def decide(session: AsyncSession, user: CurrentUser | uuid.UUID, gate: Gate) -> None:
    """Raise ApprovalDeniedError unless user may decide gate now. The caller records
    the decision in the same transaction, with its rows still locked."""
    verdict = await can_decide(session, user, gate)
    if not verdict.allowed:
        raise ApprovalDeniedError(verdict)


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
