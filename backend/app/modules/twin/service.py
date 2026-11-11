"""Site Twin (TWN-01..05, D-43; docs/plan-pilot-twn.md).

- The plan, routes, sensors and readiness items are seeded (`ensure_plan`); only presence,
  sensor status and readiness ticks change (PC-39..42).
- Every role reads the twin; a staff name only within the caller's people scope
  (`evacuations.name_scope()`); guards and visitors are labels, never names (§68 Q3).
- Presence is shown here only; nothing is written to location observations, so People &
  Sites, exposure and the check-in never change (D-43).
- Presence and sensors move only through the simulated feeds (the scenario player's
  SITE_PRESENCE and SITE_SENSOR events; review of Prompt 84, L5). A sensor fault or recovery at
  a site inside an ACTIVE incident's zone writes a SITE entry on its timeline (§4).
- Shelter-in-place and the evacuation route are worked out on every read (§5, G-4, G-5).
- A readiness item is ticked by the caller only, a Security Officer or the mission's Head of
  Mission, checked through app/core/approvals.py (D-29; review of Prompt 84, M2). Audited.
- SITE_UPDATED carries ids and counts only (G-8).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.evacuations import service as evacuations
from app.modules.exercises import queries as exercise_queries
from app.modules.fleet import service as fleet
from app.modules.fleet.models import FleetAsset
from app.modules.intel.models import IncidentEvent
from app.modules.people.models import Mission, Person, Site
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import SYSTEM, Actor
from app.modules.twin import schemas
from app.modules.twin.models import (
    SitePresence,
    SiteReadinessItem,
    SiteRoute,
    SiteSensor,
    SiteZone,
)

TICKERS = "SECURITY_OFFICER|HEAD_OF_MISSION"  # §68 Q7, for the site's mission
ACCESS = Actor(type="SYSTEM", id="access control (simulated)")
BUILDING = Actor(type="SYSTEM", id="building systems (simulated)")
ONLINE = ("OK", "DEGRADED")  # G-2
DOWN = ("FAULT", "OFFLINE")
ACCESS_POINTS = ("GATE", "BADGE_READER")
SYSTEMS = (("GEN", "Generator"), ("SAT", "Satellite comms"))  # from Fleet (§68 Q5)
DEFAULT_ROUTE = "B"  # G-5
STAFF_TYPES = ("DIPLOMAT", "LOCAL_STAFF", "CONTRACTOR")  # the PC-41 guard


class TwinError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Outcome:
    site_id: uuid.UUID
    events: list[Event] = field(default_factory=list)


async def _audit(
    session: AsyncSession, actor: Actor, action: str, site: Site, details: dict[str, Any]
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=f"SITE.{action}",
        entity_type="site",
        entity_id=str(site.id),
        details=details,
    )


def _user(user: CurrentUser) -> Actor:
    return Actor(type="USER", id=str(user.id))


# --- reading the twin (TWN-01..05) --------------------------------------------------------------


async def list_sites(session: AsyncSession) -> list[schemas.SiteSummaryOut]:
    """The sites that have a floor plan (TWN-01)."""
    rows = await session.execute(
        select(Site, Mission)
        .join(Mission, Mission.id == Site.mission_id)
        .where(select(SiteZone.id).where(SiteZone.site_id == Site.id).exists())
        .order_by(Mission.code, Site.site_type)
    )
    return [_summary(site, mission) for site, mission in rows.all()]


def _summary(site: Site, mission: Mission) -> schemas.SiteSummaryOut:
    return schemas.SiteSummaryOut(
        id=site.id,
        name=site.name,
        site_type=site.site_type,
        mission_id=mission.id,
        mission_code=mission.code,
        city=mission.city,
    )


# The shelter alert of a playbook run for an ACTIVE incident of the site's mission (G-4): a DONE
# step whose configuration carries a citizen advisory template (PB-07 step 4, PB-06, PB-01).
_SHELTER = text(
    """
    SELECT i.id, i.reference FROM incident i
      JOIN playbook_run r ON r.incident_id = i.id
      JOIN playbook_run_step rs ON rs.run_id = r.id AND rs.status = 'DONE'
      JOIN playbook_step ps ON ps.id = rs.step_id
     WHERE i.status = 'ACTIVE' AND i.mission_id = :mission
       AND ps.action_config ? 'citizen_advisory_template'
     ORDER BY i.opened_at, i.reference LIMIT 1
    """
)

_EVACUATION = text(
    "SELECT e.reference, p.route_label FROM evacuation e "
    "JOIN evacuation_plan p ON p.id = e.plan_id "
    "WHERE e.mission_id = :mission AND e.status = 'ACTIVE' "
    "ORDER BY e.activated_at, e.reference LIMIT 1"
)


async def _route(
    session: AsyncSession, site: Site, zones: dict[uuid.UUID, SiteZone]
) -> schemas.RouteOut | None:
    evacuation = (await session.execute(_EVACUATION, {"mission": site.mission_id})).first()
    if evacuation is None:
        return None
    routes = list(
        await session.scalars(
            select(SiteRoute).where(SiteRoute.site_id == site.id).order_by(SiteRoute.code)
        )
    )
    # The plan names the route ("Route B"); either label may be the longer (review of
    # Prompt 85, L5).
    named = evacuation.route_label.strip()
    route = next(
        (r for r in routes if r.label.startswith(named) or named.startswith(f"Route {r.code}")),
        next((r for r in routes if r.code == DEFAULT_ROUTE), routes[0] if routes else None),
    )
    if route is None:
        return None
    return schemas.RouteOut(
        code=route.code,
        label=route.label,
        path=[[int(x), int(y)] for x, y in route.path],
        exit_zone_code=zones[route.exit_zone_id].code,
        evacuation_reference=evacuation.reference,
    )


async def _systems(
    session: AsyncSession, user: CurrentUser, mission: Mission
) -> list[schemas.SystemOut]:
    """The generator and satellite comms with their live Fleet state (§4, §68 Q5)."""
    out = []
    for prefix, label in SYSTEMS:
        code = f"{prefix}-{mission.code}"
        asset_id = await session.scalar(select(FleetAsset.id).where(FleetAsset.code == code))
        if asset_id is None:
            continue
        for asset in await fleet.list_assets(session, user, asset_id=asset_id):
            out.append(
                schemas.SystemOut(
                    code=code, label=label, state=asset.state.code, fuel_pct=asset.fuel_pct
                )
            )
    return out


MOUNT_COLUMNS = ("mount_x", "mount_y", "heading_deg", "fov_deg", "range_u")  # PC-53


def _mount(s: SiteSensor) -> schemas.MountOut | None:
    if (
        s.mount_x is None
        or s.mount_y is None
        or s.heading_deg is None
        or s.fov_deg is None
        or s.range_u is None
    ):
        return None  # not a camera: the database keeps all five or none
    return schemas.MountOut(
        x=s.mount_x, y=s.mount_y, heading_deg=s.heading_deg, fov_deg=s.fov_deg, range_u=s.range_u
    )


def _counts(
    zones: list[SiteZone], occupants: list[SitePresence], sensors: list[SiteSensor]
) -> schemas.CountsOut:
    safe = next((z for z in zones if z.kind == "SAFE_ROOM"), None)
    return schemas.CountsOut(
        on_site=len(occupants),
        staff=sum(1 for o in occupants if o.kind == "STAFF"),
        guards=sum(1 for o in occupants if o.kind == "GUARD"),
        visitors=sum(1 for o in occupants if o.kind == "VISITOR"),
        safe_room=sum(1 for o in occupants if safe is not None and o.zone_id == safe.id),
        safe_room_capacity=safe.capacity if safe else None,
        sensors_online=sum(1 for s in sensors if s.status in ONLINE),
        sensors=len(sensors),
        faults=sum(1 for s in sensors if s.status not in ONLINE),
    )


async def _readiness(
    session: AsyncSession, site: Site, sensors: list[SiteSensor], names: bool
) -> schemas.ReadinessOut:
    rows = await session.execute(
        select(SiteReadinessItem, AppUser.display_name)
        .outerjoin(AppUser, AppUser.id == SiteReadinessItem.done_by)
        .where(SiteReadinessItem.site_id == site.id)
        .order_by(SiteReadinessItem.created_at, SiteReadinessItem.label)
        .execution_options(populate_existing=True)  # done_at, written by the database (L2)
    )
    items = [
        schemas.ReadinessItemOut(
            id=item.id,
            label=item.label,
            done=item.done_by is not None,
            # A person's name only within the people scope (review of Prompt 85, M1).
            done_by_name=name if names else None,
            done_at=item.done_at,
        )
        for item, name in rows.all()
    ]
    down = [s for s in sensors if s.kind in ACCESS_POINTS and s.status in DOWN]
    items.append(
        schemas.ReadinessItemOut(
            id=None,
            label="All access points monitored",
            done=not down,
            done_by_name=None,
            done_at=None,
            derived=True,
            detail=", ".join(f"{s.label}: {s.detail or s.status.lower()}" for s in down) or None,
        )
    )
    # The embassy's readiness is its mission's latest exercise (EXR-07; plan-pilot-exr §5).
    drill = (
        (await exercise_queries.readiness(session)).get(site.mission_id)
        if site.site_type == "EMBASSY"
        else None
    )
    if drill is None:
        return schemas.ReadinessOut(
            score=site.readiness_score, last_drill_on=site.last_drill_on, items=items
        )
    return schemas.ReadinessOut(
        score=drill.score, last_drill_on=drill.drilled_on, source=drill.source, items=items
    )


async def twin(session: AsyncSession, user: CurrentUser, site_id: uuid.UUID) -> schemas.TwinOut:
    site = await session.get(Site, site_id)
    if site is None:
        raise TwinError(404, "Site not found")
    zones = list(
        await session.scalars(
            select(SiteZone).where(SiteZone.site_id == site.id).order_by(SiteZone.y, SiteZone.x)
        )
    )
    if not zones:
        raise TwinError(404, "No floor plan yet")
    mission = await session.get_one(Mission, site.mission_id)
    by_id = {z.id: z for z in zones}
    rows = await session.execute(
        select(SitePresence, Person.full_name)
        .outerjoin(Person, Person.id == SitePresence.person_id)
        .where(SitePresence.site_id == site.id)
        # Never by name: the order must not hint at hidden names (review of Prompt 85, L6).
        .order_by(SitePresence.kind.desc(), SitePresence.label, SitePresence.since, SitePresence.id)
    )
    presence = list(rows.all())
    names = evacuations.sees_names(await evacuations.name_scope(session, user), site.mission_id)
    occupants = [
        schemas.OccupantOut(
            id=p.id,
            kind=p.kind,
            zone_code=by_id[p.zone_id].code,
            name=full_name if names and p.kind == "STAFF" else None,
            label=p.label,
            since=p.since,
        )
        for p, full_name in presence
    ]
    present = [p for p, _ in presence]
    sensors = list(
        await session.scalars(
            select(SiteSensor).where(SiteSensor.site_id == site.id).order_by(SiteSensor.code)
        )
    )
    counts = {z.id: 0 for z in zones}
    for p in present:
        counts[p.zone_id] += 1
    shelter = (await session.execute(_SHELTER, {"mission": site.mission_id})).first()
    return schemas.TwinOut(
        site=_summary(site, mission),
        zones=[
            schemas.ZoneOut(
                id=z.id,
                code=z.code,
                name=z.name,
                kind=z.kind,
                x=z.x,
                y=z.y,
                w=z.w,
                h=z.h,
                capacity=z.capacity,
                count=counts[z.id],
            )
            for z in zones
        ],
        occupants=occupants,
        sensors=[
            schemas.SensorOut(
                code=s.code,
                kind=s.kind,
                label=s.label,
                zone_code=by_id[s.zone_id].code if s.zone_id else None,
                status=s.status,
                detail=s.detail,
                status_at=s.status_at,
                online=s.status in ONLINE,
                mount=_mount(s),
            )
            for s in sensors
        ],
        systems=await _systems(session, user, mission),
        counts=_counts(zones, present, sensors),
        shelter=(
            schemas.ShelterOut(incident_id=shelter.id, incident_reference=shelter.reference)
            if shelter
            else None
        ),
        route=await _route(session, site, by_id),
        readiness=await _readiness(session, site, sensors, names),
    )


# --- realtime (G-8) -----------------------------------------------------------------------------


async def sheltering(session: AsyncSession, mission_id: uuid.UUID) -> str | None:
    """The ACTIVE incident whose shelter alert covers the mission's sites, if any (G-4); for
    the Executive Overview's drivers (plan-pilot-exe G-7)."""
    row = (await session.execute(_SHELTER, {"mission": mission_id})).first()
    return str(row.reference) if row else None


async def site_event(session: AsyncSession, site: Site, change: str) -> Event:
    """Ids and counts only, never names (G-8)."""
    zones = list(await session.scalars(select(SiteZone).where(SiteZone.site_id == site.id)))
    present = list(
        await session.scalars(select(SitePresence).where(SitePresence.site_id == site.id))
    )
    sensors = list(await session.scalars(select(SiteSensor).where(SiteSensor.site_id == site.id)))
    counts = _counts(zones, present, sensors)
    return Event(
        type="SITE_UPDATED",
        tenant_id=site.tenant_id,
        payload={
            "site_id": str(site.id),
            "mission_id": str(site.mission_id),
            "change": change,
            "on_site": counts.on_site,
            "safe_room": counts.safe_room,
            "sensors_online": counts.sensors_online,
        },
        source="twin",
    )


# --- readiness (TWN-05; G-6, G-7; review of Prompt 84, M2) -------------------------------------


async def may_tick(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID) -> bool:
    return await approvals.user_has_role(session, user, TICKERS, mission_id)


async def tick(session: AsyncSession, user: CurrentUser, item_id: uuid.UUID) -> Outcome:
    site_id = await session.scalar(
        select(SiteReadinessItem.site_id).where(SiteReadinessItem.id == item_id)
    )
    if site_id is None:
        raise TwinError(404, "Readiness item not found")
    site = await session.get_one(Site, site_id)
    # The role first, so a refused caller never holds the row lock (as Fleet, review of
    # Prompt 73, L3); a site's mission does not change.
    if not await may_tick(session, user, site.mission_id):
        raise TwinError(
            403, "Ticking readiness needs SECURITY_OFFICER or HEAD_OF_MISSION for this mission"
        )
    item = await session.scalar(
        select(SiteReadinessItem)
        .where(SiteReadinessItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise TwinError(404, "Readiness item not found")
    if item.done_by is not None:
        raise TwinError(409, f"{item.label} is already done")
    item.done_by = user.id  # the caller, never on someone's behalf (M2)
    await session.flush()
    await _audit(session, _user(user), "READINESS_DONE", site, {"item": str(item.id)})
    return Outcome(site.id, [await site_event(session, site, "readiness")])


@dataclass(frozen=True)
class Permissions:
    tick_readiness: bool = False


async def permissions(session: AsyncSession, user: CurrentUser, site_id: uuid.UUID) -> Permissions:
    """For the screen (GET /api/me/permissions?entity_type=site), the endpoint's check."""
    site = await session.get(Site, site_id)
    if site is None:
        return Permissions()
    return Permissions(tick_readiness=await may_tick(session, user, site.mission_id))


# --- the simulated feeds (TWN-02, TWN-03; §3, §4) -----------------------------------------------


async def site_by_key(session: AsyncSession, key: str) -> Site | None:
    """ "NBO:EMBASSY": the mission's site of that type."""
    code, _, site_type = key.partition(":")
    return await session.scalar(
        select(Site)
        .join(Mission, Mission.id == Site.mission_id)
        .where(Mission.code == code, Site.site_type == site_type)
        .order_by(Site.created_at, Site.id)
        .limit(1)
    )


async def _zone(session: AsyncSession, site: Site, code: str) -> SiteZone | None:
    zone: SiteZone | None = await session.scalar(
        select(SiteZone).where(SiteZone.site_id == site.id, SiteZone.code == code)
    )
    return zone


def _occupant(occupant: str) -> tuple[str, uuid.UUID | None, str | None]:
    """A person's id (staff), or a label "Guard n" / "Visitor n"."""
    try:
        return "STAFF", uuid.UUID(occupant), None
    except ValueError:
        return occupant.split(" ", 1)[0].upper(), None, occupant


async def presence(
    session: AsyncSession, site_key: str, occupant: str, zone_code: str | None
) -> Outcome | None:
    """An arrival, a move or (zone None) a departure. None if nothing applies: an unknown
    site, zone or occupant, or no change."""
    site = await site_by_key(session, site_key)
    if site is None:
        return None
    kind, person_id, label = _occupant(occupant)
    if kind not in ("STAFF", "GUARD", "VISITOR"):
        return None
    zone = await _zone(session, site, zone_code) if zone_code else None
    if zone_code and zone is None:
        return None
    match = (
        SitePresence.person_id == person_id
        if person_id
        else (SitePresence.site_id == site.id) & (SitePresence.label == label)
    )
    row = await session.scalar(
        select(SitePresence)
        .where(match)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    before = None
    if row is not None:
        if row.site_id != site.id:
            return None  # at another site: it leaves there first (one place at a time)
        before = (await session.get_one(SiteZone, row.zone_id)).code
    if zone is None:
        if row is None:
            return None
        await session.delete(row)
    elif row is None:
        # An arrival: staff are active personnel of the site's mission (the PC-41 guard);
        # anyone else is not applied. Moves and departures are always applied, so a person
        # deactivated while on site can still leave (review of Prompt 85, L3).
        if person_id is not None and not await _staff(session, site, person_id):
            return None
        try:
            async with session.begin_nested():
                session.add(
                    SitePresence(
                        tenant_id=site.tenant_id,
                        site_id=site.id,
                        zone_id=zone.id,
                        kind=kind,
                        person_id=person_id,
                        label=label,
                    )
                )
        except IntegrityError:
            return None  # a concurrent event added them first (review of Prompt 85, L4)
    elif row.zone_id == zone.id:
        return None
    else:
        row.zone_id = zone.id
    await session.flush()
    details: dict[str, Any] = {"kind": kind, "from": before, "to": zone.code if zone else None}
    if person_id:
        details["person_id"] = str(person_id)  # never the name
    else:
        details["label"] = label
    await _audit(session, ACCESS, "PRESENCE", site, details)
    return Outcome(site.id, [await site_event(session, site, "presence")])


async def _staff(session: AsyncSession, site: Site, person_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(Person.id).where(
            Person.id == person_id,
            Person.mission_id == site.mission_id,
            Person.is_active,
            Person.person_type.in_(STAFF_TYPES),
        )
    )
    return found is not None


_ZONES = text(
    """
    SELECT i.id, i.reference FROM site s, incident i
     WHERE s.id = :site AND i.status = 'ACTIVE' AND i.location IS NOT NULL
       AND ST_DWithin(s.location, i.location, i.impact_radius_m)
     ORDER BY i.reference
    """
)


async def sensor(
    session: AsyncSession, site_key: str, code: str, status: str, detail: str | None
) -> Outcome | None:
    """A simulated status change. A change into or out of FAULT or OFFLINE at a site inside an
    ACTIVE incident's zone writes a SITE timeline entry (§4). None if nothing applies."""
    site = await site_by_key(session, site_key)
    if site is None:
        return None
    row = await session.scalar(
        select(SiteSensor)
        .where(SiteSensor.site_id == site.id, SiteSensor.code == code)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or (row.status, row.detail) == (status, detail):
        return None
    before = row.status
    row.status = status
    row.detail = detail
    await session.flush()
    incidents: list[str] = []
    if (before in DOWN) != (status in DOWN):
        for incident in await session.execute(_ZONES, {"site": site.id}):
            incidents.append(str(incident.id))
            session.add(
                IncidentEvent(
                    tenant_id=site.tenant_id,
                    incident_id=incident.id,
                    event_type="SITE",  # free text, as Fleet's FLEET (FLT G-10)
                    summary=f"{site.name} · {row.label}: {status}"
                    + (f" ({detail})" if detail else "")
                    + ".",
                    actor_type=BUILDING.type,
                    actor_id=BUILDING.id,
                    data={"site_id": str(site.id), "sensor": row.code, "status": status},
                )
            )
    await _audit(
        session,
        BUILDING,
        "SENSOR",
        site,
        {"sensor": row.code, "from": before, "to": status, "incidents": incidents},
    )
    await session.flush()
    event = await site_event(session, site, "sensor")
    event.payload["incident_ids"] = incidents
    return Outcome(site.id, [event])


# --- the seed (TWN-01, §2) ----------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneIn:
    code: str
    name: str
    kind: str
    x: int
    y: int
    w: int
    h: int
    capacity: int | None = None


@dataclass(frozen=True)
class RouteIn:
    code: str
    label: str
    path: tuple[tuple[int, int], ...]
    exit_zone: str


# (x, y, heading, field of view, range) in plan units (PC-53).
Mount = tuple[int, int, int, int, int]


@dataclass(frozen=True)
class SensorIn:
    code: str
    kind: str
    label: str
    zone: str | None
    detail: str | None = None
    mount: Mount | None = None  # CCTV only


@dataclass(frozen=True)
class OccupantIn:
    zone: str
    person_id: uuid.UUID | None = None  # staff
    label: str | None = None  # guards and visitors


@dataclass(frozen=True)
class PlanIn:
    site_id: uuid.UUID
    zones: tuple[ZoneIn, ...]
    routes: tuple[RouteIn, ...]
    sensors: tuple[SensorIn, ...]
    items: tuple[tuple[str, uuid.UUID | None], ...]  # (label, done by)
    occupants: tuple[OccupantIn, ...]


async def ensure_plan(session: AsyncSession, plan: PlanIn, actor: Actor = SYSTEM) -> bool:
    """Seed a site's plan, routes, sensors, readiness items and presence once (TWN-01). A
    site that already has a plan is never changed. Audited once, by counts."""
    if await session.scalar(select(SiteZone.id).where(SiteZone.site_id == plan.site_id).limit(1)):
        return False
    site = await session.get_one(Site, plan.site_id)
    zones = {}
    for z in plan.zones:
        zone = SiteZone(
            tenant_id=site.tenant_id,
            site_id=site.id,
            code=z.code,
            name=z.name,
            kind=z.kind,
            x=z.x,
            y=z.y,
            w=z.w,
            h=z.h,
            capacity=z.capacity,
        )
        session.add(zone)
        zones[z.code] = zone
    await session.flush()
    for r in plan.routes:
        session.add(
            SiteRoute(
                tenant_id=site.tenant_id,
                site_id=site.id,
                code=r.code,
                label=r.label,
                path=[list(p) for p in r.path],
                exit_zone_id=zones[r.exit_zone].id,
            )
        )
    for s in plan.sensors:
        session.add(
            SiteSensor(
                tenant_id=site.tenant_id,
                site_id=site.id,
                zone_id=zones[s.zone].id if s.zone else None,
                code=s.code,
                kind=s.kind,
                label=s.label,
                detail=s.detail,
                **(dict(zip(MOUNT_COLUMNS, s.mount, strict=True)) if s.mount else {}),
            )
        )
    for label, done_by in plan.items:
        session.add(
            SiteReadinessItem(
                tenant_id=site.tenant_id, site_id=site.id, label=label, done_by=done_by
            )
        )
    for o in plan.occupants:
        session.add(
            SitePresence(
                tenant_id=site.tenant_id,
                site_id=site.id,
                zone_id=zones[o.zone].id,
                kind=_occupant(str(o.person_id) if o.person_id else o.label or "")[0],
                person_id=o.person_id,
                label=o.label,
            )
        )
    await session.flush()
    await _audit(
        session,
        actor,
        "SEED",
        site,
        {
            "zones": len(plan.zones),
            "routes": len(plan.routes),
            "sensors": len(plan.sensors),
            "items": len(plan.items),
            "occupants": len(plan.occupants),
        },
    )
    return True


# --- recent movements (TWN-14, D-53; plan-pilot-twa §3, G-5) ------------------------------------

MOVEMENTS = 20
# Read from the record of presence moves: audit.py only inserts, and the app may read its rows.
# Only the kind and the zones' codes leave this query; never a person id or a label.
_MOVES = text(
    """
    SELECT occurred_at, details->>'kind' AS kind, details->>'from' AS from_code,
           details->>'to' AS to_code
      FROM audit_log
     WHERE entity_type = 'site' AND entity_id = :site AND action = 'SITE.PRESENCE'
     ORDER BY occurred_at DESC, chain_seq DESC
     LIMIT :limit
    """
)
_TODAY = text(
    """
    SELECT count(*) FILTER (WHERE details->>'from' IS NULL) AS arrivals,
           count(*) FILTER (WHERE details->>'to' IS NULL) AS departures
      FROM audit_log
     WHERE entity_type = 'site' AND entity_id = :site AND action = 'SITE.PRESENCE'
       AND occurred_at >= :since
    """
)


async def movements(
    session: AsyncSession, site_id: uuid.UUID, since: datetime
) -> schemas.MovementsOut:
    site = await session.get(Site, site_id)
    if site is None:
        raise TwinError(404, "Site not found")
    zones = list(await session.scalars(select(SiteZone).where(SiteZone.site_id == site.id)))
    if not zones:
        raise TwinError(404, "No floor plan yet")
    name = {z.code: z.name for z in zones}
    params = {"site": str(site.id), "limit": MOVEMENTS, "since": since}
    moves = [
        schemas.MovementOut(
            at=m.occurred_at,
            kind=m.kind,
            from_zone=name.get(m.from_code) if m.from_code else None,
            to_zone=name.get(m.to_code) if m.to_code else None,
        )
        for m in await session.execute(_MOVES, params)
    ]
    today = (await session.execute(_TODAY, params)).one()
    waiting_zones = [z.id for z in zones if z.kind in ("LOBBY", "CONSULAR")]
    waiting = await session.scalar(
        select(func.count())
        .select_from(SitePresence)
        .where(
            SitePresence.site_id == site.id,
            SitePresence.kind == "VISITOR",
            SitePresence.zone_id.in_(waiting_zones),
        )
    )
    return schemas.MovementsOut(
        movements=moves,
        arrivals_today=today.arrivals,
        departures_today=today.departures,
        visitors_waiting=waiting or 0,
    )
