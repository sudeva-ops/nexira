"""Tenancy services: roles, users and role grants. Every change is audited.

Called by the seeder and (later) by admin endpoints. Idempotent: running them
twice changes nothing and writes no second audit row.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import ActorType
from app.modules.tenancy.models import AppUser, Role, UserRole

# Phase 1 roles (PRD section 2; Prompt 3).
ROLES: dict[str, str] = {
    "ADMIN": "Administrator",
    "DUTY_OFFICER": "Duty Officer",
    "SECURITY_OFFICER": "Security Officer",
    "HEAD_OF_MISSION": "Head of Mission",
    "HQ_CRISIS_DIRECTOR": "HQ Crisis Director",
    "TRAVEL_DESK": "Travel Desk",
    "CONSULAR_OFFICER": "Consular Officer",
    "VIEWER": "Viewer",
}


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str | None


SYSTEM = Actor(type="SYSTEM", id="seed")


def _tenant(session: AsyncSession) -> uuid.UUID:
    tenant_id: uuid.UUID | None = session.info.get("tenant_id")
    if tenant_id is None:
        raise RuntimeError("tenancy services need a tenant-scoped session (D-02)")
    return tenant_id


async def ensure_roles(session: AsyncSession, actor: Actor = SYSTEM) -> dict[str, uuid.UUID]:
    """Create any missing Phase 1 roles; return code -> role id."""
    tenant_id = _tenant(session)
    created = await session.scalars(
        insert(Role)
        .values([{"tenant_id": tenant_id, "code": c, "name": n} for c, n in ROLES.items()])
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(Role.code)
    )
    new_codes = sorted(created.all())
    if new_codes:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="ROLE.CREATE",
            entity_type="role",
            details={"codes": new_codes},
        )
    rows = await session.execute(select(Role.code, Role.id))
    return {code: role_id for code, role_id in rows}


async def ensure_user(
    session: AsyncSession,
    *,
    external_id: str,
    email: str,
    display_name: str,
    actor: Actor = SYSTEM,
) -> uuid.UUID:
    """Create the app_user for an OIDC subject if it does not exist yet."""
    tenant_id = _tenant(session)
    created_id: uuid.UUID | None = await session.scalar(
        insert(AppUser)
        .values(
            tenant_id=tenant_id, external_id=external_id, email=email, display_name=display_name
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "external_id"])
        .returning(AppUser.id)
    )
    if created_id is not None:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="USER.CREATE",
            entity_type="app_user",
            entity_id=str(created_id),
            details={"external_id": external_id, "email": email},
        )
        return created_id
    user_id = await session.scalar(select(AppUser.id).where(AppUser.external_id == external_id))
    if user_id is None:  # the email belongs to another subject in this tenant
        raise ValueError(f"cannot create user {external_id!r}: email {email!r} is taken")
    return user_id


async def grant_role(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    mission_id: uuid.UUID | None,
    actor: Actor = SYSTEM,
) -> bool:
    """Grant a role (optionally mission-scoped, D-05). Returns False if already held."""
    tenant_id = _tenant(session)
    grant_id = await session.scalar(
        insert(UserRole)
        .values(tenant_id=tenant_id, user_id=user_id, role_id=role_id, mission_id=mission_id)
        .on_conflict_do_nothing()
        .returning(UserRole.id)
    )
    if grant_id is None:
        return False
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="ROLE.GRANT",
        entity_type="user_role",
        entity_id=str(grant_id),
        details={
            "user_id": str(user_id),
            "role_id": str(role_id),
            "mission_id": str(mission_id) if mission_id else None,
        },
    )
    return True


async def ensure_reference_counter(
    session: AsyncSession, *, prefix: str, with_year: bool, last_value: int, actor: Actor = SYSTEM
) -> bool:
    """Start a reference series (D-18), e.g. INC for the current UTC year at 1041 so the
    next incident is INC-<year>-1042. An existing counter is never reset."""
    created = await session.scalar(
        text(
            """
            INSERT INTO reference_counter (tenant_id, prefix, year, last_value)
            VALUES (current_tenant_id(), :prefix,
                    CASE WHEN :with_year
                         THEN extract(year FROM now() AT TIME ZONE 'UTC')::smallint
                         ELSE 0 END,
                    :last_value)
            ON CONFLICT DO NOTHING
            RETURNING year
            """
        ),
        {"prefix": prefix, "with_year": with_year, "last_value": last_value},
    )
    if created is None:
        return False
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="REFERENCE_COUNTER.CREATE",
        entity_type="reference_counter",
        entity_id=f"{prefix}:{created}",
        details={"last_value": last_value},
    )
    return True
