"""People & places services: missions, sites, people and location observations.

Single-row creates are audited per row. Bulk loads (seed data, HR imports) are
audited once per batch with a count (plan G-20). Every function is idempotent:
rows are keyed by id (or a natural key) and existing rows are left alone.
"""

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.people.models import Mission, Person, Site
from app.modules.tenancy.service import SYSTEM, Actor


def _point(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


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
    values: dict[str, Any] = {
        "tenant_id": session.info["tenant_id"],
        "code": code,
        "city": city,
        "country_code": country_code,
        "risk_level": risk_level,
        "location": _point(lat, lon),
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
            details={"code": code, "city": city, "risk_level": risk_level},
        )
        return created
    existing = await session.scalar(select(Mission.id).where(Mission.code == code))
    if existing is None:
        raise RuntimeError(f"mission {code} neither created nor found")
    return existing


@dataclass(frozen=True)
class SiteIn:
    id: uuid.UUID
    mission_id: uuid.UUID
    site_type: str
    name: str
    lat: float
    lon: float
    readiness_score: int | None = None
    last_drill_on: date | None = None


@dataclass(frozen=True)
class PersonIn:
    id: uuid.UUID
    mission_id: uuid.UUID | None
    person_type: str
    full_name: str
    role_title: str | None = None
    email: str | None = None
    preferred_lang: str = "en"
    hr_external_id: str | None = None


@dataclass(frozen=True)
class ObservationIn:
    person_id: uuid.UUID
    source: str
    lat: float
    lon: float
    observed_at: datetime
    place_label: str | None = None
    raw: dict[str, Any] | None = None


async def _bulk_audit(
    session: AsyncSession, actor: Actor, action: str, entity_type: str, count: int
) -> None:
    if count:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action=action,
            entity_type=entity_type,
            details={"count": count},
        )


async def load_sites(session: AsyncSession, sites: list[SiteIn], actor: Actor = SYSTEM) -> int:
    if not sites:
        return 0
    tenant_id = session.info["tenant_id"]
    result = await session.scalars(
        insert(Site)
        .values(
            [
                {
                    "id": s.id,
                    "tenant_id": tenant_id,
                    "mission_id": s.mission_id,
                    "site_type": s.site_type,
                    "name": s.name,
                    "location": _point(s.lat, s.lon),
                    "readiness_score": s.readiness_score,
                    "last_drill_on": s.last_drill_on,
                }
                for s in sites
            ]
        )
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(Site.id)
    )
    count = len(result.all())
    await _bulk_audit(session, actor, "SITE.BULK_LOAD", "site", count)
    return count


async def load_persons(
    session: AsyncSession, persons: list[PersonIn], actor: Actor = SYSTEM, batch: int = 1000
) -> int:
    tenant_id = session.info["tenant_id"]
    count = 0
    for start in range(0, len(persons), batch):
        rows = [{**asdict(p), "tenant_id": tenant_id} for p in persons[start : start + batch]]
        result = await session.scalars(
            insert(Person)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(Person.id)
        )
        count += len(result.all())
    await _bulk_audit(session, actor, "PERSON.BULK_LOAD", "person", count)
    return count


async def add_observations(
    session: AsyncSession, observations: list[ObservationIn], actor: Actor = SYSTEM
) -> int:
    """Insert observations, skipping exact repeats (same person, source and time)."""
    if not observations:
        return 0
    rows = [
        {
            "person_id": str(o.person_id),
            "source": o.source,
            "lat": o.lat,
            "lon": o.lon,
            "observed_at": o.observed_at.isoformat(),
            "place_label": o.place_label,
            "raw": o.raw,
        }
        for o in observations
    ]
    result = await session.execute(
        text(
            """
            INSERT INTO location_observation
                   (tenant_id, person_id, source, location, place_label, observed_at, raw)
            SELECT current_tenant_id(), r.person_id, r.source,
                   ST_SetSRID(ST_MakePoint(r.lon, r.lat), 4326)::geography,
                   r.place_label, r.observed_at, r.raw
              FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(
                     person_id uuid, source text, lat float8, lon float8,
                     observed_at timestamptz, place_label text, raw jsonb)
             WHERE NOT EXISTS (
                     SELECT 1 FROM location_observation o
                      WHERE o.person_id = r.person_id AND o.source = r.source
                        AND o.observed_at = r.observed_at)
            RETURNING id
            """
        ),
        {"rows": json.dumps(rows)},
    )
    count = len(result.all())
    await _bulk_audit(
        session, actor, "LOCATION_OBSERVATION.BULK_LOAD", "location_observation", count
    )
    return count
