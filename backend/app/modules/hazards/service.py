"""Natural hazard events and climate exposure for the screen (HZ-03, HZ-04, HZ-08..10;
plan-pilot-hz §8). Hazard events are incidents of the hazard categories; their details
come from the newest signal (forecast.py). Counts only, never names, for every role."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.hazards import clock, forecast
from app.modules.hazards.models import MissionClimateRisk
from app.modules.hazards.schemas import (
    ArmedOut,
    ClimateOut,
    ExposureOut,
    HazardOut,
    HazardsOut,
)
from app.modules.intel import exposure, hazards
from app.modules.intel.models import Incident, IncidentEvent, IncidentSignal, IntelSource, RawSignal
from app.modules.intel.normalise import severity_rank
from app.modules.people.models import Mission
from app.modules.playbooks.models import Playbook, PlaybookRun
from app.modules.tenancy.service import SYSTEM, Actor

SHOWN = ("ACTIVE", "MONITORING")
# The simulated sources of the module (§43 Q1): xWeather, the seismic network, the
# air-quality network and the illustrative climate model.
SOURCES = 4
FORECAST_CHANGED = timedelta(hours=1)

_NEAREST = text(
    """
    SELECT m.code, m.city, ST_Distance(m.location, i.location)::int AS distance_m
      FROM incident i, mission m
     WHERE i.id = :incident_id AND m.tenant_id = i.tenant_id
     ORDER BY m.location <-> i.location, m.code
     LIMIT 1
    """
)
_HOMES = text(
    """
    SELECT count(*) FROM incident_exposure e
      JOIN person_location_current l ON l.person_id = e.subject_id
     WHERE e.incident_id = :incident_id AND e.subject_type = 'PERSON'
       AND l.place_label ILIKE 'Home%'
    """
)


def _hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


async def _armed(
    session: AsyncSession, incident: Incident, landfall: datetime | None, now: datetime
) -> ArmedOut | None:
    """The incident's newest armed run (one with a start time), whatever its state."""
    row = (
        await session.execute(
            select(PlaybookRun, Playbook.code)
            .join(Playbook, Playbook.id == PlaybookRun.playbook_id)
            .where(PlaybookRun.incident_id == incident.id, PlaybookRun.scheduled_for.is_not(None))
            .order_by(PlaybookRun.started_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    run, code = row
    data = await session.scalar(
        select(IncidentEvent.data)
        .where(
            IncidentEvent.incident_id == incident.id,
            IncidentEvent.data["run_id"].astext == str(run.id),
            IncidentEvent.data.has_key("armed_for_landfall_at"),
        )
        .order_by(IncidentEvent.id)
        .limit(1)
    )
    armed_for = datetime.fromisoformat(str(data["armed_for_landfall_at"])) if data else None
    changed = (
        landfall is not None
        and armed_for is not None
        and abs(landfall - armed_for) >= FORECAST_CHANGED
    )
    scheduled = run.scheduled_for
    return ArmedOut(
        run_id=run.id,
        playbook_code=code,
        status=run.status,
        scheduled_for=scheduled,
        starts_in_h=max(0.0, _hours(scheduled - now))
        if run.status == "SCHEDULED" and scheduled
        else None,
        forecast_changed=changed,
    )


async def _event(session: AsyncSession, incident: Incident, now: datetime) -> HazardOut:
    latest = await forecast.latest(session, incident)
    nearest = (await session.execute(_NEAREST, {"incident_id": incident.id})).one_or_none()
    counts = await exposure.exposure_counts(session, incident.id)
    homes = int(await session.scalar(_HOMES, {"incident_id": incident.id}) or 0)
    sources = await session.scalars(
        select(IntelSource.name)
        .join(RawSignal, RawSignal.source_id == IntelSource.id)
        .join(IncidentSignal, IncidentSignal.signal_id == RawSignal.id)
        .where(IncidentSignal.incident_id == incident.id)
        .distinct()
        .order_by(IntelSource.name)
    )
    lat, lon = (
        await session.execute(
            select(
                func.ST_Y(func.geometry(Incident.location)),
                func.ST_X(func.geometry(Incident.location)),
            ).where(Incident.id == incident.id)
        )
    ).one()
    landfall = latest.landfall_at if latest else None
    distance = nearest.distance_m if nearest else None
    return HazardOut(
        incident_id=incident.id,
        reference=incident.reference,
        title=incident.title,
        category=incident.category,
        severity=incident.severity,
        status=incident.status,
        place_label=incident.place_label,
        lat=lat,
        lon=lon,
        impact_radius_m=incident.impact_radius_m,
        opened_at=incident.opened_at,
        updated_at=incident.last_signal_at,
        hazard=latest.hazard if latest else {},
        landfall_at=landfall,
        landfall_in_h=max(0.0, _hours(landfall - now)) if landfall else None,
        nearest_mission_code=nearest.code if nearest else None,
        nearest_mission_city=nearest.city if nearest else None,
        nearest_mission_m=distance,
        within_range=distance is not None and distance <= hazards.NO_MISSION_WITHIN_M,
        exposed=counts.people > 0 or counts.sites > 0,
        exposure=ExposureOut(
            staff=counts.staff,
            people=counts.people,
            homes=homes,
            mission_sites=counts.mission_sites,
        ),
        sources=list(sources),
        armed=await _armed(session, incident, landfall, now),
    )


async def list_hazards(session: AsyncSession, now: datetime | None = None) -> HazardsOut:
    clock_now = await clock.hazard_now(session, now)
    incidents = list(
        await session.scalars(
            select(Incident).where(
                Incident.category.in_(hazards.HAZARD_CATEGORIES), Incident.status.in_(SHOWN)
            )
        )
    )
    incidents.sort(key=lambda i: (-severity_rank(i.severity), -i.last_signal_at.timestamp()))
    return HazardsOut(
        events=[await _event(session, i, clock_now.now) for i in incidents],
        clock_now=clock_now.now,
        demo_advance_h=clock_now.demo_advance_h,
        sources=SOURCES,
    )


async def list_climate(session: AsyncSession) -> list[ClimateOut]:
    """HZ-08: sorted by the 2050 score, highest first."""
    rows = await session.execute(
        select(MissionClimateRisk, Mission.code, Mission.city)
        .join(Mission, Mission.id == MissionClimateRisk.mission_id)
        .order_by(MissionClimateRisk.score_2050.desc(), Mission.code)
    )
    return [
        ClimateOut(
            mission_id=r.mission_id,
            mission_code=code,
            city=city,
            hazards=list(r.hazards),
            score_today=r.score_today,
            score_2050=r.score_2050,
            scenario=r.scenario,
            source=r.source,
        )
        for r, code, city in rows
    ]


async def ensure_climate(
    session: AsyncSession, rows: list[dict[str, Any]], actor: Actor = SYSTEM
) -> int:
    """Seed the illustrative scores (PC-25: INSERT only, as nexira_api). Rows whose
    mission already has a score are left alone. Audited once with the count."""
    tenant_id: uuid.UUID = session.info["tenant_id"]
    existing = set(await session.scalars(select(MissionClimateRisk.mission_id)))
    new = [r for r in rows if r["mission_id"] not in existing]
    session.add_all(MissionClimateRisk(tenant_id=tenant_id, **r) for r in new)
    await session.flush()
    if new:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="CLIMATE_RISK.SEED",
            entity_type="mission_climate_risk",
            details={"missions": len(new)},
        )
    return len(new)
