"""People & places services. Prompt 3 needs missions for mission-scoped roles;
sites, people and location confidence follow in Prompt 4."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.people.models import Mission
from app.modules.tenancy.service import SYSTEM, Actor


async def ensure_mission(
    session: AsyncSession,
    *,
    code: str,
    city: str,
    country_code: str,
    lat: float,
    lon: float,
    risk_level: str = "LOW",
    mission_id: uuid.UUID | None = None,
    actor: Actor = SYSTEM,
) -> uuid.UUID:
    """Create the mission if its code is new; return its id. Audited on create."""
    tenant_id = session.info["tenant_id"]
    values = {
        "tenant_id": tenant_id,
        "code": code,
        "city": city,
        "country_code": country_code,
        "risk_level": risk_level,
        "location": f"SRID=4326;POINT({lon} {lat})",
    }
    if mission_id is not None:
        values["id"] = mission_id
    created: uuid.UUID | None = await session.scalar(
        insert(Mission)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(Mission.id)
    )
    if created is not None:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="MISSION.CREATE",
            entity_type="mission",
            entity_id=str(created),
            details={"code": code, "city": city},
        )
        return created
    existing = await session.scalar(select(Mission.id).where(Mission.code == code))
    if existing is None:
        raise RuntimeError(f"mission {code} neither created nor found")
    return existing
