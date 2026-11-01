"""Fleet & Assets (FLT-01..07, D-41; docs/plan-pilot-flt.md).

- The register is seeded (`ensure_assets`); only position, fuel and status change (PC-33).
- Blocked (the driver's SOS), in an impact zone and assigned to an evacuation are worked out
  on every read and not stored, so they clear by themselves (§3, §58 Q3). A vehicle within
  150 m of one of its mission's sites is at site, not in a zone (G-1).
- Status and maintenance are changed by a Security Officer, Duty Officer or the mission's Head
  of Mission, checked through app/core/approvals.py (§58 Q4, D-29).
- Positions come from simulated telematics and the workshop is simulated (D-19); a vehicle
  crossing an ACTIVE incident's zone writes a FLEET entry on its timeline (FLT-05, G-4).
- A driver's name only within the evacuation name scope (G-8). Every change is audited.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.evacuations import service as evacuations
from app.modules.fleet import schemas
from app.modules.fleet.models import FleetAsset, FleetMaintenance
from app.modules.intel.models import IncidentEvent
from app.modules.people.models import Mission
from app.modules.tenancy.service import SYSTEM, Actor

ACTORS = "SECURITY_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION"  # §58 Q4, for the asset's mission
AT_SITE_M = 150  # G-1
ALERT_DAYS = 14  # §58 Q6
TELEMATICS = Actor(type="SYSTEM", id="telematics (simulated)")
WORKSHOP = Actor(type="SYSTEM", id="workshop (simulated)")
STATUSES = ("AVAILABLE", "IN_USE", "MAINTENANCE")
NEEDED_TYPES = ("DIPLOMAT", "DELEGATE", "DEPENDANT")  # the mission part (§4, §53 Q3 of EV)
TRANSPORT = "SECURE_TRANSPORT"


class FleetError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Outcome:
    events: list[Event] = field(default_factory=list)


def fleet_event(asset: FleetAsset, change: str, incidents: list[str] | None = None) -> Event:
    """Ids, the code and what changed (realtime carries no names)."""
    return Event(
        type="FLEET_UPDATED",
        tenant_id=asset.tenant_id,
        payload={
            "asset_id": str(asset.id),
            "code": asset.code,
            "mission_id": str(asset.mission_id),
            "change": change,
            "incident_ids": incidents or [],
        },
        source="fleet",
    )


async def _audit(
    session: AsyncSession, actor: Actor, action: str, asset: FleetAsset, details: Any
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=f"FLEET.{action}",
        entity_type="fleet_asset",
        entity_id=asset.code,
        details=details,
    )


def _user(user: CurrentUser) -> Actor:
    return Actor(type="USER", id=str(user.id))


# --- the derived states (FLT-02, §3) ---------------------------------------------------------

# One row per asset. At site: within AT_SITE_M of one of its mission's sites (G-1). Blocked: the
# driver's latest answer in an ACTIVE incident's check-in is NEED_HELP (G-2). In zone: inside an
# ACTIVE incident's impact zone and not at site. Assigned: the mission has an ACTIVE evacuation.
_ASSETS = text(
    """
    SELECT a.id, a.code, a.kind, a.type_label, a.armoured, a.seats, a.mission_id,
           m.code AS mission_code, m.city, a.location_label,
           ST_Y(a.location::geometry) AS lat, ST_X(a.location::geometry) AS lon,
           a.fuel_pct, a.position_at, a.status, a.status_reason, a.driver_id, a.source,
           p.full_name AS driver_full_name, s.at_site,
           CASE WHEN a.kind = 'VEHICLE' THEN (
             SELECT CASE WHEN l.status = 'NEED_HELP' THEN i.reference END
               FROM v_checkin_latest l
               JOIN notification_campaign c ON c.id = l.campaign_id
               JOIN incident i ON i.id = c.incident_id
              WHERE l.person_id = a.driver_id AND c.campaign_type = 'CHECKIN'
                AND i.status = 'ACTIVE'
              ORDER BY l.responded_at DESC LIMIT 1) END AS blocked_incident,
           CASE WHEN a.kind = 'VEHICLE' AND NOT s.at_site THEN (
             SELECT i.reference FROM incident i
              WHERE i.status = 'ACTIVE' AND i.location IS NOT NULL
                AND ST_DWithin(a.location, i.location, i.impact_radius_m)
              ORDER BY i.opened_at, i.reference LIMIT 1) END AS zone_incident,
           CASE WHEN a.kind = 'VEHICLE' THEN (
             SELECT e.reference FROM evacuation e
              WHERE e.mission_id = a.mission_id AND e.status = 'ACTIVE' LIMIT 1) END
             AS evacuation_reference
      FROM fleet_asset a
      JOIN mission m ON m.id = a.mission_id
      LEFT JOIN person p ON p.id = a.driver_id
      CROSS JOIN LATERAL (
        SELECT EXISTS (SELECT 1 FROM site st
                        WHERE st.mission_id = a.mission_id
                          AND ST_DWithin(st.location, a.location, :at_site_m)) AS at_site) s
     WHERE (CAST(:mission_id AS uuid) IS NULL OR a.mission_id = CAST(:mission_id AS uuid))
       AND (CAST(:asset_id AS uuid) IS NULL OR a.id = CAST(:asset_id AS uuid))
     ORDER BY m.code, a.kind DESC, a.code
    """
)


def _states(row: Any) -> tuple[schemas.StateOut, list[schemas.StateOut], bool]:
    """The first state that applies, every derived one, and whether it is available (§3)."""
    tags: list[schemas.StateOut] = []
    if row.status == "MAINTENANCE":
        tags.append(schemas.StateOut(code="MAINTENANCE"))
    if row.blocked_incident:
        tags.append(schemas.StateOut(code="BLOCKED", reference=row.blocked_incident))
    if row.zone_incident:
        tags.append(schemas.StateOut(code="IN_ZONE", reference=row.zone_incident))
    available = not tags
    if available and row.evacuation_reference:
        tags.append(schemas.StateOut(code="ASSIGNED", reference=row.evacuation_reference))
    state = tags[0] if tags else schemas.StateOut(code=row.status)
    return state, tags, available and row.kind == "VEHICLE"


async def list_assets(
    session: AsyncSession,
    user: CurrentUser,
    mission_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
) -> list[schemas.AssetOut]:
    scope = await evacuations.name_scope(session, user)
    rows = await session.execute(
        _ASSETS, {"mission_id": mission_id, "asset_id": asset_id, "at_site_m": AT_SITE_M}
    )
    out = []
    for row in rows:
        state, tags, available = _states(row)
        out.append(
            schemas.AssetOut(
                id=row.id,
                code=row.code,
                kind=row.kind,
                type_label=row.type_label,
                armoured=row.armoured,
                seats=row.seats,
                mission_id=row.mission_id,
                mission_code=row.mission_code,
                city=row.city,
                location_label=row.location_label,
                lat=row.lat,
                lon=row.lon,
                at_site=row.at_site,
                fuel_pct=row.fuel_pct,
                position_at=row.position_at,
                status=row.status,
                status_reason=row.status_reason,
                state=state,
                tags=tags,
                available=available,
                driver_assigned=row.driver_id is not None,
                driver_name=(
                    row.driver_full_name
                    if row.driver_id and evacuations.sees_names(scope, row.mission_id)
                    else None
                ),
                source=row.source,
            )
        )
    return out


# --- capacity (FLT-03, §4) ---------------------------------------------------------------------


async def _needed(session: AsyncSession, mission_id: uuid.UUID) -> tuple[int, str, str | None]:
    """The mission part of an ACTIVE evacuation's manifest, else the mission's people."""
    live = await session.execute(
        text(
            "SELECT e.reference, count(x.id) FILTER (WHERE x.category <> 'CITIZEN') AS n "
            "FROM evacuation e LEFT JOIN evacuation_manifest x ON x.evacuation_id = e.id "
            "WHERE e.mission_id = :m AND e.status = 'ACTIVE' GROUP BY e.reference"
        ),
        {"m": mission_id},
    )
    row = live.first()
    if row is not None:
        return int(row.n), "EVACUATION", str(row.reference)
    people = await session.scalar(
        text(
            "SELECT count(*) FROM person WHERE mission_id = :m AND is_active "
            "AND person_type = ANY(:types)"
        ),
        {"m": mission_id, "types": list(NEEDED_TYPES)},
    )
    return int(people or 0), "PEOPLE", None


async def _suggest(session: AsyncSession, country: str) -> schemas.SuggestionOut | None:
    row = (
        await session.execute(
            text(
                "SELECT id, name, sla_minutes FROM partner WHERE is_active "
                "AND :service = ANY(services) AND :country = ANY(coverage) "
                "ORDER BY sla_minutes, name LIMIT 1"
            ),
            {"service": TRANSPORT, "country": country},
        )
    ).first()
    if row is None:
        return None
    return schemas.SuggestionOut(
        partner_id=row.id, partner_name=row.name, sla_minutes=row.sla_minutes
    )


async def mission_fleet(
    session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID
) -> schemas.MissionFleetOut:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise FleetError(404, "Mission not found")
    assets = await list_assets(session, user, mission_id)
    vehicles = [a for a in assets if a.kind == "VEHICLE"]
    seats = sum(a.seats or 0 for a in vehicles if a.available)
    needed, needed_from, reference = await _needed(session, mission_id)
    shortfall = max(0, needed - seats)
    generator = next((a for a in assets if a.code.startswith("GEN-")), None)
    return schemas.MissionFleetOut(
        mission_id=mission.id,
        mission_code=mission.code,
        city=mission.city,
        country_code=mission.country_code,
        vehicles=len(vehicles),
        available=sum(1 for a in vehicles if a.available),
        generator_fuel_pct=generator.fuel_pct if generator else None,
        capacity=schemas.CapacityOut(
            seats_available=seats,
            seats_needed=needed,
            needed_from=needed_from,
            evacuation_reference=reference,
            shortfall=shortfall,
            suggestion=await _suggest(session, mission.country_code) if shortfall else None,
        ),
    )


async def summary(session: AsyncSession, today: date) -> schemas.SummaryOut:
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE kind = 'VEHICLE') AS vehicles, "
                "count(*) FILTER (WHERE kind = 'VEHICLE' AND armoured) AS armoured, "
                "round(avg(fuel_pct))::int AS fuel FROM fleet_asset"
            )
        )
    ).one()
    due = await session.scalar(
        text("SELECT count(*) FROM fleet_maintenance WHERE done_at IS NULL AND due_on <= :until"),
        {"until": today + timedelta(days=ALERT_DAYS)},
    )
    return schemas.SummaryOut(
        vehicles=row.vehicles,
        armoured=row.armoured,
        average_fuel_pct=row.fuel,
        maintenance_due=int(due or 0),
    )


# --- maintenance and status (FLT-04, §5) ----------------------------------------------------


async def maintenance(
    session: AsyncSession, today: date, mission_id: uuid.UUID | None = None
) -> list[schemas.MaintenanceOut]:
    query = (
        select(FleetMaintenance, FleetAsset.code, FleetAsset.mission_id, Mission.code)
        .join(FleetAsset, FleetAsset.id == FleetMaintenance.asset_id)
        .join(Mission, Mission.id == FleetAsset.mission_id)
        .order_by(FleetMaintenance.due_on, FleetAsset.code)
    )
    if mission_id is not None:
        query = query.where(FleetAsset.mission_id == mission_id)
    until = today + timedelta(days=ALERT_DAYS)
    return [
        schemas.MaintenanceOut(
            id=m.id,
            asset_id=m.asset_id,
            asset_code=code,
            mission_id=mission,
            mission_code=mission_code,
            task=m.task,
            due_on=m.due_on,
            done_at=m.done_at,
            done_by_type=m.done_by_type,
            alert=m.done_at is None and m.due_on <= until,
            overdue=m.done_at is None and m.due_on < today,
        )
        for m, code, mission, mission_code in (await session.execute(query)).all()
    ]


async def may_act(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID) -> bool:
    return await approvals.user_has_role(session, user, ACTORS, mission_id)


async def _require(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID) -> None:
    if not await may_act(session, user, mission_id):
        raise FleetError(
            403,
            "Changing fleet status or maintenance needs SECURITY_OFFICER, DUTY_OFFICER or "
            "HEAD_OF_MISSION for this mission",
        )


async def _mission_of(session: AsyncSession, asset_id: uuid.UUID) -> uuid.UUID:
    mission_id = await session.scalar(
        select(FleetAsset.mission_id).where(FleetAsset.id == asset_id)
    )
    if mission_id is None:
        raise FleetError(404, "Asset not found")
    return mission_id


async def _locked(session: AsyncSession, asset_id: uuid.UUID) -> FleetAsset:
    asset = await session.scalar(
        select(FleetAsset).where(FleetAsset.id == asset_id).with_for_update()
    )
    if asset is None:
        raise FleetError(404, "Asset not found")
    return asset


async def set_status(
    session: AsyncSession,
    user: CurrentUser,
    asset_id: uuid.UUID,
    status: str,
    reason: str | None,
) -> Outcome:
    # The role first, so a refused caller never holds the row lock (review of Prompt 73, L3);
    # the mission is frozen (PC-33), so the check holds after the lock.
    await _require(session, user, await _mission_of(session, asset_id))
    asset = await _locked(session, asset_id)
    if status not in STATUSES:
        raise FleetError(422, "Status is AVAILABLE, IN_USE or MAINTENANCE")
    if status == "MAINTENANCE" and not reason:
        raise FleetError(422, "Maintenance needs a reason")
    if status != "MAINTENANCE" and reason:
        raise FleetError(422, "A reason only for maintenance")
    if status == "IN_USE" and asset.kind != "VEHICLE":
        raise FleetError(422, "Only a vehicle is in use")
    if (status, reason) == (asset.status, asset.status_reason):
        raise FleetError(409, f"{asset.code} is already {status.lower().replace('_', ' ')}")
    before = asset.status
    asset.status = status
    asset.status_reason = reason if status == "MAINTENANCE" else None
    await session.flush()
    await _audit(
        session,
        _user(user),
        "STATUS",
        asset,
        {"from": before, "to": status, "reason": asset.status_reason},
    )
    return Outcome([fleet_event(asset, "status")])


async def _done(
    session: AsyncSession, item: FleetMaintenance, asset: FleetAsset, by_type: str, actor: Actor
) -> None:
    item.done_by_type = by_type
    item.done_by = actor.id
    await session.flush()
    await _audit(
        session,
        actor,
        "MAINTENANCE_DONE",
        asset,
        {"item": str(item.id), "task": item.task, "due_on": item.due_on.isoformat()},
    )


async def complete(session: AsyncSession, user: CurrentUser, item_id: uuid.UUID) -> Outcome:
    asset_id = await session.scalar(
        select(FleetMaintenance.asset_id).where(FleetMaintenance.id == item_id)
    )
    if asset_id is None:
        raise FleetError(404, "Maintenance item not found")
    await _require(session, user, await _mission_of(session, asset_id))  # before the lock (L3)
    item = await session.scalar(
        select(FleetMaintenance).where(FleetMaintenance.id == item_id).with_for_update()
    )
    if item is None:
        raise FleetError(404, "Maintenance item not found")
    asset = await session.get_one(FleetAsset, asset_id)
    if item.done_at is not None:
        raise FleetError(409, f"{item.task} on {asset.code} is already done")
    # Done by the caller, never on someone's behalf (review of Prompt 72, L4). The status
    # stays: a person sets it separately (G-7).
    await _done(session, item, asset, "USER", _user(user))
    return Outcome([fleet_event(asset, "maintenance")])


@dataclass(frozen=True)
class Permissions:
    set_status: bool = False
    complete: bool = False


async def permissions(
    session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID
) -> Permissions:
    """For the screen (GET /api/me/permissions?entity_type=fleet), the endpoints' check."""
    if await session.get(Mission, mission_id) is None:
        return Permissions()
    allowed = await may_act(session, user, mission_id)
    return Permissions(set_status=allowed, complete=allowed)


# --- telematics and the workshop (FLT-05, §6) -----------------------------------------------

_ZONES = text(
    """
    SELECT i.id, i.reference FROM fleet_asset a, incident i
     WHERE a.id = :asset AND a.kind = 'VEHICLE' AND i.status = 'ACTIVE'
       AND i.location IS NOT NULL
       AND ST_DWithin(a.location, i.location, i.impact_radius_m)
       AND NOT EXISTS (SELECT 1 FROM site st WHERE st.mission_id = a.mission_id
                         AND ST_DWithin(st.location, a.location, :at_site_m))
     ORDER BY i.reference
    """
)


async def _zones(session: AsyncSession, asset_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = await session.execute(_ZONES, {"asset": asset_id, "at_site_m": AT_SITE_M})
    return {r.id: r.reference for r in rows}


async def position(
    session: AsyncSession,
    code: str,
    lat: float,
    lon: float,
    label: str,
    fuel_pct: int,
) -> Outcome | None:
    """A simulated telematics position. None if there is no such asset. A crossing of an
    ACTIVE incident's zone writes a FLEET timeline entry (G-4); only crossings do."""
    asset_id = await session.scalar(select(FleetAsset.id).where(FleetAsset.code == code))
    if asset_id is None:
        return None
    asset = await _locked(session, asset_id)
    before = await _zones(session, asset.id)
    await session.execute(
        text(
            "UPDATE fleet_asset SET location = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
            "::geography, location_label = :label, fuel_pct = :fuel WHERE id = :id"
        ),
        {"lon": lon, "lat": lat, "label": label, "fuel": fuel_pct, "id": asset.id},
    )
    await session.refresh(asset)  # the database writes position_at
    after = await _zones(session, asset.id)
    crossings = [(i, before[i], "left") for i in before if i not in after] + [
        (i, after[i], "entered") for i in after if i not in before
    ]
    for incident_id, reference, way in crossings:
        session.add(
            IncidentEvent(
                tenant_id=asset.tenant_id,
                incident_id=incident_id,
                event_type="FLEET",  # G-10: event_type is free text
                summary=f"{asset.code} {way} the impact zone of {reference} · {label}.",
                actor_type=TELEMATICS.type,
                actor_id=TELEMATICS.id,
                data={"asset_id": str(asset.id), "code": asset.code, "crossing": way},
            )
        )
    await _audit(
        session,
        TELEMATICS,
        "POSITION",
        asset,
        {
            "label": label,
            "fuel_pct": fuel_pct,
            "crossings": [{"incident": r, "crossing": w} for _, r, w in crossings],
        },
    )  # G-5
    await session.flush()
    return Outcome([fleet_event(asset, "position", [str(i) for i, _, _ in crossings])])


async def workshop_done(session: AsyncSession, code: str, task: str, today: date) -> Outcome | None:
    """The simulated workshop (G-7): the open item done and, if the vehicle was in maintenance
    and has no other overdue item, AVAILABLE again (review of Prompt 73, M1). None if there is
    no such asset or open item."""
    asset_id = await session.scalar(select(FleetAsset.id).where(FleetAsset.code == code))
    if asset_id is None:
        return None
    asset = await _locked(session, asset_id)
    item = await session.scalar(
        select(FleetMaintenance)
        .where(
            FleetMaintenance.asset_id == asset.id,
            FleetMaintenance.task == task,
            FleetMaintenance.done_at.is_(None),
        )
        .with_for_update()
    )
    if item is None:
        return None
    await _done(session, item, asset, "WORKSHOP", WORKSHOP)
    overdue = await session.scalar(
        select(FleetMaintenance.id)
        .where(
            FleetMaintenance.asset_id == asset.id,
            FleetMaintenance.done_at.is_(None),
            FleetMaintenance.due_on < today,
        )
        .limit(1)
    )
    if asset.status == "MAINTENANCE" and overdue is None:
        asset.status = "AVAILABLE"
        asset.status_reason = None
        await session.flush()
        await _audit(session, WORKSHOP, "STATUS", asset, {"from": "MAINTENANCE", "to": "AVAILABLE"})
    return Outcome([fleet_event(asset, "maintenance")])


# --- the seed (FLT-01, §2) ------------------------------------------------------------------


@dataclass(frozen=True)
class ItemIn:
    task: str
    due_in_days: int  # from the seed date; negative is overdue


@dataclass(frozen=True)
class AssetIn:
    mission_id: uuid.UUID
    code: str
    kind: str
    type_label: str
    lat: float
    lon: float
    location_label: str
    fuel_pct: int
    armoured: bool = False
    seats: int | None = None
    driver_id: uuid.UUID | None = None
    status: str = "AVAILABLE"
    status_reason: str | None = None
    items: tuple[ItemIn, ...] = ()


async def ensure_assets(
    session: AsyncSession, assets: list[AssetIn], today: date, actor: Actor = SYSTEM
) -> int:
    """Seed the assets not yet in the register, with their maintenance items (FLT-01).
    Existing assets are never changed (PC-33). Audited once."""
    has = set(await session.scalars(select(FleetAsset.code)))
    new = [a for a in assets if a.code not in has]
    for a in new:
        asset_id = await session.scalar(
            text(
                "INSERT INTO fleet_asset (tenant_id, mission_id, code, kind, type_label, armoured, "
                "seats, driver_id, location, location_label, fuel_pct, status, status_reason) "
                "VALUES (current_tenant_id(), :mission_id, :code, :kind, :type_label, :armoured, "
                ":seats, :driver_id, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
                ":location_label, :fuel_pct, :status, :status_reason) RETURNING id"
            ),
            {
                "mission_id": a.mission_id,
                "code": a.code,
                "kind": a.kind,
                "type_label": a.type_label,
                "armoured": a.armoured,
                "seats": a.seats,
                "driver_id": a.driver_id,
                "lon": a.lon,
                "lat": a.lat,
                "location_label": a.location_label,
                "fuel_pct": a.fuel_pct,
                "status": a.status,
                "status_reason": a.status_reason,
            },
        )
        for item in a.items:
            session.add(
                FleetMaintenance(
                    tenant_id=session.info["tenant_id"],
                    asset_id=asset_id,
                    task=item.task,
                    due_on=today + timedelta(days=item.due_in_days),
                )
            )
    await session.flush()
    if new:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="FLEET.SEED",
            entity_type="fleet_asset",
            details={"assets": len(new), "items": sum(len(a.items) for a in new)},
        )
    return len(new)
