"""Supply Chain & Third-Party Risk (SUP-01..06, D-44; docs/plan-pilot-sup.md).

- The register and routes are seeded (`ensure_register`); only their reported status changes,
  through the simulated logistics feed and supplier notices (PC-43, PC-44; §3).
- ROUTE BLOCKED, ALTERNATE, the zone tag and "impacted" are worked out on every read and not
  stored, so they clear by themselves (§3, §4, §73 Q2). A reported change at a mission with an
  ACTIVE incident writes a SUPPLY entry on its timeline; only changes do (§4).
- A mitigation is recorded by a Security Officer, Duty Officer or the mission's Head of Mission,
  checked through app/core/approvals.py (§5, §73 Q4, D-29). Nothing is sent to the supplier.
- The names of who acted only within the evacuation name scope (§6). Every change is audited.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.documents import service as documents
from app.modules.evacuations import service as evacuations
from app.modules.fleet.service import ACTORS
from app.modules.intel.models import IncidentEvent
from app.modules.people.models import Mission
from app.modules.supply import schemas
from app.modules.supply.models import LogisticsRoute, Supplier, SupplyMitigation
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import SYSTEM, Actor

FUEL_TANK_HOURS = 100  # an illustrative full-tank endurance (§4, §73 Q6)
LOGISTICS = Actor(type="SYSTEM", id="logistics feed (simulated)")
NOTICES = Actor(type="SYSTEM", id="supplier notice (simulated)")
SUPPLIER_STATUSES = ("NORMAL", "WATCH", "DELAYED", "AT_RISK")
ROUTE_STATUSES = ("OPEN", "RESTRICTED", "DELAYED", "BLOCKED")
# The shown order, worst first (§3).
SEVERITY = {"ROUTE_BLOCKED": 4, "AT_RISK": 3, "DELAYED": 2, "WATCH": 1, "NORMAL": 0}
IMPACTING = frozenset({"ROUTE_BLOCKED", "AT_RISK", "DELAYED"})


class SupplyError(Exception):
    """The request cannot be done: status_code 403, 404 or 409."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Outcome:
    events: list[Event] = field(default_factory=list)


def supply_event(
    tenant_id: uuid.UUID,
    change: str,
    *,
    supplier_id: uuid.UUID | None = None,
    route_id: uuid.UUID | None = None,
    status: str | None = None,
) -> Event:
    """Ids and statuses only; realtime carries no names (G-8)."""
    return Event(
        type="SUPPLY_UPDATED",
        tenant_id=tenant_id,
        payload={
            "supplier_id": str(supplier_id) if supplier_id else None,
            "route_id": str(route_id) if route_id else None,
            "change": change,
            "status": status,
        },
        source="supply",
    )


async def _audit(
    session: AsyncSession,
    actor: Actor,
    action: str,
    entity: str,
    code: str,
    details: dict[str, Any],
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=f"SUPPLY.{action}",
        entity_type=entity,
        entity_id=code,
        details=details,
    )


def _user(user: CurrentUser) -> Actor:
    return Actor(type="USER", id=str(user.id))


def shown_label(status: str) -> str:
    return status.replace("_", " ")


# --- the picture, worked out on read (§3, §4) ---------------------------------------------------


@dataclass(frozen=True)
class _Incident:
    id: uuid.UUID
    reference: str


_ACTIVE = text(
    """
    SELECT DISTINCT ON (mission_id) mission_id, id, reference FROM incident
     WHERE status = 'ACTIVE' AND mission_id IS NOT NULL
     ORDER BY mission_id, created_at DESC, reference DESC
    """
)  # the most recent ACTIVE incident per mission (G-5)

_ROUTES = text(
    """
    SELECT r.id, r.code, r.label, r.kind, r.mission_id, m.code AS mission_code, r.supplier_id,
           s.code AS supplier_code, a.code AS alternate_of_code, a.status AS primary_status,
           r.status, r.detail, r.status_at,
           ARRAY(SELECT i.reference FROM incident i
                  WHERE i.status = 'ACTIVE'
                    AND ST_DWithin(r.path, i.location, i.impact_radius_m)
                  ORDER BY i.reference) AS zone_incidents
      FROM logistics_route r
      JOIN mission m ON m.id = r.mission_id
      LEFT JOIN supplier s ON s.id = r.supplier_id
      LEFT JOIN logistics_route a ON a.id = r.alternate_of_id
     ORDER BY m.code, r.code
    """
)


@dataclass
class _Picture:
    """Everything a read needs, loaded once."""

    suppliers: list[Supplier]
    missions: dict[uuid.UUID, Mission]
    routes: list[schemas.RouteOut]
    active: dict[uuid.UUID, _Incident]  # by mission
    fuel: dict[uuid.UUID, int]  # GEN-<mission> fuel by mission
    mitigations: list[SupplyMitigation]
    references: dict[uuid.UUID, str]  # the mitigations' incidents, ACTIVE or not
    names: dict[uuid.UUID, str]
    scope: documents.Scope | None
    today: date

    def routes_of(self, supplier_id: uuid.UUID) -> list[schemas.RouteOut]:
        return [r for r in self.routes if r.supplier_id == supplier_id]


async def _picture(session: AsyncSession, user: CurrentUser, today: date) -> _Picture:
    # populate_existing: the current rows, never a copy loaded earlier in the session (M1).
    fresh = {"populate_existing": True}
    suppliers = list(
        await session.scalars(select(Supplier).order_by(Supplier.code).execution_options(**fresh))
    )
    missions = {m.id: m for m in await session.scalars(select(Mission))}
    routes = [
        schemas.RouteOut(
            id=r.id,
            code=r.code,
            label=r.label,
            kind=r.kind,
            mission_id=r.mission_id,
            mission_code=r.mission_code,
            supplier_id=r.supplier_id,
            supplier_code=r.supplier_code,
            alternate_of_code=r.alternate_of_code,
            status=r.status,
            shown=(
                "ALTERNATE" if r.status == "OPEN" and r.primary_status == "BLOCKED" else r.status
            ),
            detail=r.detail,
            status_at=r.status_at,
            zone_incidents=list(r.zone_incidents),
        )
        for r in await session.execute(_ROUTES)
    ]
    active = {r.mission_id: _Incident(r.id, r.reference) for r in await session.execute(_ACTIVE)}
    fuel = {
        r.mission_id: int(r.fuel_pct)
        for r in await session.execute(
            text(
                "SELECT a.mission_id, a.fuel_pct FROM fleet_asset a JOIN mission m "
                "ON m.id = a.mission_id WHERE a.code = 'GEN-' || m.code"
            )
        )
    }
    mitigations = list(
        await session.scalars(
            select(SupplyMitigation)
            .order_by(SupplyMitigation.activated_at.desc())
            .execution_options(**fresh)
        )
    )
    people = {m.activated_by for m in mitigations} | {
        m.stood_down_by for m in mitigations if m.stood_down_by
    }
    names: dict[uuid.UUID, str] = {}
    if people:
        users = await session.scalars(select(AppUser).where(AppUser.id.in_(people)))
        names = {u.id: u.display_name for u in users}
    incidents = [m.incident_id for m in mitigations if m.incident_id]
    references: dict[uuid.UUID, str] = {}
    if incidents:
        rows = await session.execute(
            text("SELECT id, reference FROM incident WHERE id = ANY(:ids)"), {"ids": incidents}
        )
        references = {r.id: r.reference for r in rows}
    return _Picture(
        suppliers=suppliers,
        missions=missions,
        routes=routes,
        active=active,
        fuel=fuel,
        mitigations=mitigations,
        references=references,
        names=names,
        scope=await evacuations.name_scope(session, user),
        today=today,
    )


def _shown(supplier: Supplier, routes: list[schemas.RouteOut]) -> tuple[str, str | None]:
    """The worst of the reported status and ROUTE BLOCKED, with its detail (§3)."""
    blocked = [r for r in routes if r.status == "BLOCKED"]
    if blocked and SEVERITY["ROUTE_BLOCKED"] > SEVERITY[supplier.status]:
        return "ROUTE_BLOCKED", blocked[0].detail
    return supplier.status, supplier.status_detail


def _mitigation_out(
    picture: _Picture, m: SupplyMitigation, supplier: Supplier
) -> schemas.MitigationOut:
    by_id = {s.id: s for s in picture.suppliers}
    backup = by_id.get(m.backup_supplier_id) if m.backup_supplier_id else None
    route = next((r for r in picture.routes if r.id == m.route_id), None)
    sees = supplier.mission_id is not None and evacuations.sees_names(
        picture.scope, supplier.mission_id
    )
    incident = picture.references.get(m.incident_id) if m.incident_id else None
    return schemas.MitigationOut(
        id=m.id,
        supplier_id=m.supplier_id,
        supplier_code=supplier.code,
        incident_id=m.incident_id,
        incident_reference=incident,
        backup=schemas.SupplierRef(id=backup.id, code=backup.code, name=backup.name)
        if backup
        else None,
        route_code=route.code if route else None,
        route_label=route.label if route else None,
        note=m.note,
        activated_at=m.activated_at,
        activated_by_name=picture.names.get(m.activated_by) if sees else None,
        stood_down_at=m.stood_down_at,
        stood_down_by_name=(
            picture.names.get(m.stood_down_by) if sees and m.stood_down_by else None
        ),
        active=m.stood_down_at is None,
    )


def _supplier_out(picture: _Picture, s: Supplier) -> schemas.SupplierOut:
    routes = picture.routes_of(s.id)
    shown, detail = _shown(s, routes)
    incident = picture.active.get(s.mission_id) if s.mission_id else None
    impacted = incident is not None and shown in IMPACTING
    backup = next((b for b in picture.suppliers if b.id == s.backup_supplier_id), None)
    mission = picture.missions.get(s.mission_id) if s.mission_id else None
    fuel = (
        picture.fuel.get(s.mission_id)
        if s.mission_id and any(r.kind == "FUEL" for r in routes)
        else None
    )
    active = next(
        (m for m in picture.mitigations if m.supplier_id == s.id and m.stood_down_at is None),
        None,
    )
    return schemas.SupplierOut(
        id=s.id,
        code=s.code,
        name=s.name,
        service=s.service,
        mission_id=s.mission_id,
        mission_code=mission.code if mission else None,
        city=mission.city if mission else None,
        tier=s.tier,
        status=s.status,
        status_detail=s.status_detail,
        status_at=s.status_at,
        shown=shown,
        detail=detail,
        impacted=impacted,
        incident_id=incident.id if impacted and incident else None,
        incident_reference=incident.reference if impacted and incident else None,
        backup=schemas.SupplierRef(id=backup.id, code=backup.code, name=backup.name)
        if backup
        else None,
        in_bcp=s.in_bcp,
        vetting_valid_until=s.vetting_valid_until,
        vetting_current=s.vetting_valid_until >= picture.today,
        performance_score=s.performance_score,
        fuel_stock_hours=round(fuel * FUEL_TANK_HOURS / 100) if fuel is not None else None,
        mitigation=_mitigation_out(picture, active, s) if active else None,
        source=s.source,
    )


async def list_suppliers(
    session: AsyncSession, user: CurrentUser, today: date, mission_id: uuid.UUID | None = None
) -> list[schemas.SupplierOut]:
    picture = await _picture(session, user, today)
    return [
        _supplier_out(picture, s)
        for s in picture.suppliers
        if mission_id is None or s.mission_id == mission_id
    ]


async def supplier_detail(
    session: AsyncSession, user: CurrentUser, today: date, supplier_id: uuid.UUID
) -> schemas.SupplierDetailOut:
    picture = await _picture(session, user, today)
    supplier = next((s for s in picture.suppliers if s.id == supplier_id), None)
    if supplier is None:
        raise SupplyError(404, "Supplier not found")
    out = _supplier_out(picture, supplier)
    return schemas.SupplierDetailOut(
        **out.model_dump(),
        # The mission's routes, and any a Global supplier runs (review of Prompt 91, L3).
        routes=[
            r
            for r in picture.routes
            if (supplier.mission_id is not None and r.mission_id == supplier.mission_id)
            or r.supplier_id == supplier.id
        ],
        mitigations=[
            _mitigation_out(picture, m, supplier)
            for m in picture.mitigations
            if m.supplier_id == supplier.id
        ],
    )


async def list_routes(
    session: AsyncSession, user: CurrentUser, today: date, mission_id: uuid.UUID | None = None
) -> list[schemas.RouteOut]:
    picture = await _picture(session, user, today)
    return [r for r in picture.routes if mission_id is None or r.mission_id == mission_id]


async def summary(session: AsyncSession, user: CurrentUser, today: date) -> schemas.SummaryOut:
    picture = await _picture(session, user, today)
    suppliers = [_supplier_out(picture, s) for s in picture.suppliers]
    impacted = [s for s in suppliers if s.impacted]
    by_incident: dict[uuid.UUID, list[schemas.SupplierOut]] = defaultdict(list)
    for s in impacted:
        if s.incident_id is not None:
            by_incident[s.incident_id].append(s)
    banners = [
        schemas.BannerOut(
            incident_id=incident_id,
            incident_reference=found[0].incident_reference or "",
            mission_code=found[0].mission_code or "",
            suppliers=[
                schemas.ImpactedOut(code=s.code, name=s.name, shown=s.shown, detail=s.detail)
                for s in found
            ],
        )
        for incident_id, found in by_incident.items()
    ]
    return schemas.SummaryOut(
        suppliers=len(suppliers),
        missions=len({s.mission_id for s in suppliers if s.mission_id}),
        tier1=sum(1 for s in suppliers if s.tier == 1),
        impacted=len(impacted),
        impacted_missions=sorted({s.mission_code for s in impacted if s.mission_code}),
        routes=len(picture.routes),
        banners=sorted(banners, key=lambda b: b.incident_reference),
    )


# --- mitigation (SUP-04, §5) ----------------------------------------------------------------


async def may_act(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID | None) -> bool:
    """For a Global supplier, only a grant without a mission (it is never impacted anyway)."""
    return await approvals.user_has_role(session, user, ACTORS, mission_id)


async def _require(session: AsyncSession, user: CurrentUser, supplier: Supplier) -> None:
    if not await may_act(session, user, supplier.mission_id):
        raise SupplyError(
            403,
            "Recording a mitigation needs SECURITY_OFFICER, DUTY_OFFICER or HEAD_OF_MISSION "
            "for this mission",
        )


async def _timeline(
    session: AsyncSession,
    incident_id: uuid.UUID,
    actor: Actor,
    summary_text: str,
    data: dict[str, Any],
) -> None:
    session.add(
        IncidentEvent(
            tenant_id=session.info["tenant_id"],
            incident_id=incident_id,
            event_type="SUPPLY",  # free text, as FLEET and SITE
            summary=summary_text,
            actor_type=actor.type,
            actor_id=actor.id,
            data=data,
        )
    )


async def activate(
    session: AsyncSession,
    user: CurrentUser,
    today: date,
    supplier_id: uuid.UUID,
    note: str | None,
) -> tuple[Outcome, uuid.UUID]:
    found = await session.get(Supplier, supplier_id)
    if found is None:
        raise SupplyError(404, "Supplier not found")
    # The role first, so a refused caller never holds the row lock; the mission is frozen
    # (PC-43), so the check holds after the lock.
    await _require(session, user, found)
    supplier = await session.scalar(
        select(Supplier)
        .where(Supplier.id == supplier_id)
        # Re-read under the lock, not the copy loaded before it, so a status a feed changed
        # meanwhile counts (review of Prompt 91, M1). NO KEY UPDATE: references to the
        # supplier (a backup, a mitigation) are not blocked (L6).
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    assert supplier is not None
    picture = await _picture(session, user, today)
    out = _supplier_out(picture, supplier)
    if not out.impacted:
        raise SupplyError(409, f"{supplier.code} is not impacted by an ACTIVE incident")
    if out.mitigation is not None:
        raise SupplyError(409, f"{supplier.code} already has an active mitigation")
    routes = picture.routes_of(supplier.id)
    blocked = {r.code for r in routes if r.status == "BLOCKED"}
    alternate = next(
        (
            r
            for r in picture.routes
            if r.alternate_of_code in blocked
            and r.mission_id == supplier.mission_id
            and r.status == "OPEN"
        ),
        None,
    )
    text_note = (note or "").strip() or None
    mitigation = SupplyMitigation(
        tenant_id=supplier.tenant_id,
        supplier_id=supplier.id,
        incident_id=out.incident_id,
        backup_supplier_id=supplier.backup_supplier_id,
        route_id=alternate.id if alternate else None,
        note=text_note,
        activated_by=user.id,
    )
    session.add(mitigation)
    await session.flush()
    await session.refresh(mitigation)  # the database writes activated_at
    parts = [f"{out.city} · {supplier.name}: mitigation activated"]
    if out.backup is not None:
        parts.append(f"backup {out.backup.name} on standby")
    if alternate is not None:
        parts.append(f"{alternate.label} in use")
    details = {
        "mitigation": str(mitigation.id),
        "incident": out.incident_reference,
        "backup": out.backup.code if out.backup else None,
        "route": alternate.code if alternate else None,
        "note": text_note,
    }
    await _audit(session, _user(user), "MITIGATION_ACTIVATED", "supplier", supplier.code, details)
    if out.incident_id is not None:
        await _timeline(
            session,
            out.incident_id,
            _user(user),
            " · ".join(parts) + ".",
            {"supplier": supplier.code, "mitigation": str(mitigation.id)},
        )
    await session.flush()
    event = supply_event(supplier.tenant_id, "mitigation", supplier_id=supplier.id)
    return Outcome([event]), mitigation.id


async def stand_down(
    session: AsyncSession, user: CurrentUser, mitigation_id: uuid.UUID
) -> tuple[Outcome, uuid.UUID]:
    found = await session.get(SupplyMitigation, mitigation_id)
    if found is None:
        raise SupplyError(404, "Mitigation not found")
    supplier = await session.get_one(Supplier, found.supplier_id)
    await _require(session, user, supplier)  # before the lock
    mitigation = await session.scalar(
        select(SupplyMitigation)
        .where(SupplyMitigation.id == mitigation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert mitigation is not None
    if mitigation.stood_down_at is not None:
        raise SupplyError(409, f"The mitigation for {supplier.code} is already stood down")
    mitigation.stood_down_by = user.id
    await session.flush()
    await session.refresh(mitigation)  # the database writes stood_down_at
    await _audit(
        session,
        _user(user),
        "MITIGATION_STOOD_DOWN",
        "supplier",
        supplier.code,
        {"mitigation": str(mitigation.id)},
    )
    if mitigation.incident_id is not None:
        still = await session.scalar(
            text("SELECT status = 'ACTIVE' FROM incident WHERE id = :i"),
            {"i": mitigation.incident_id},
        )
        if still:
            # An incident is only recorded for a supplier with a mission (PC-45 guard).
            mission = await session.get_one(Mission, supplier.mission_id)
            await _timeline(
                session,
                mitigation.incident_id,
                _user(user),
                f"{mission.city} · {supplier.name}: mitigation stood down.",
                {"supplier": supplier.code, "mitigation": str(mitigation.id)},
            )
    await session.flush()
    event = supply_event(supplier.tenant_id, "mitigation", supplier_id=supplier.id)
    return Outcome([event]), supplier.id


@dataclass(frozen=True)
class Permissions:
    activate_mitigation: bool = False
    stand_down_mitigation: bool = False


async def permissions(
    session: AsyncSession, user: CurrentUser, today: date, supplier_id: uuid.UUID | None
) -> Permissions:
    """For the screen (GET /api/me/permissions?entity_type=supplier), the endpoints' checks."""
    supplier = await session.get(Supplier, supplier_id) if supplier_id else None
    if supplier is None or not await may_act(session, user, supplier.mission_id):
        return Permissions()
    out = _supplier_out(await _picture(session, user, today), supplier)
    return Permissions(
        activate_mitigation=out.impacted and out.mitigation is None,
        stand_down_mitigation=out.mitigation is not None,
    )


# --- the simulated feeds (§3) ----------------------------------------------------------------


async def _active_at(session: AsyncSession, mission_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            text(
                "SELECT id FROM incident WHERE status = 'ACTIVE' AND mission_id = :m "
                "ORDER BY reference"
            ),
            {"m": mission_id},
        )
    )


def _said(status: str, detail: str | None) -> str:
    return shown_label(status) + (f" ({detail})" if detail else "")


async def route_status(
    session: AsyncSession, code: str, status: str, detail: str | None
) -> Outcome | None:
    """A simulated logistics report. None if there is no such route. A change of status at a
    mission with an ACTIVE incident writes a SUPPLY timeline entry; a report of the same
    status and detail changes nothing (G-6)."""
    route = await session.scalar(
        select(LogisticsRoute).where(LogisticsRoute.code == code).with_for_update(key_share=True)
    )
    if route is None or status not in ROUTE_STATUSES:
        return None
    if (route.status, route.detail) == (status, detail):
        return Outcome()
    before = route.status
    route.status = status
    route.detail = detail
    await session.flush()
    await _audit(
        session,
        LOGISTICS,
        "ROUTE_STATUS",
        "logistics_route",
        route.code,
        {"from": before, "to": status, "detail": detail},
    )
    if before != status:
        mission = await session.get_one(Mission, route.mission_id)
        for incident_id in await _active_at(session, route.mission_id):
            await _timeline(
                session,
                incident_id,
                LOGISTICS,
                f"{mission.city} · {route.label}: {_said(status, detail)}.",
                {"route": route.code, "status": status},
            )
    await session.flush()
    return Outcome([supply_event(route.tenant_id, "route", route_id=route.id, status=status)])


async def supplier_status(
    session: AsyncSession, code: str, status: str, detail: str | None
) -> Outcome | None:
    """A simulated supplier notice; as route_status."""
    supplier = await session.scalar(
        select(Supplier).where(Supplier.code == code).with_for_update(key_share=True)
    )
    if supplier is None or status not in SUPPLIER_STATUSES:
        return None
    if (supplier.status, supplier.status_detail) == (status, detail):
        return Outcome()
    before = supplier.status
    supplier.status = status
    supplier.status_detail = detail
    await session.flush()
    await _audit(
        session,
        NOTICES,
        "SUPPLIER_STATUS",
        "supplier",
        supplier.code,
        {"from": before, "to": status, "detail": detail},
    )
    if before != status and supplier.mission_id is not None:
        mission = await session.get_one(Mission, supplier.mission_id)
        for incident_id in await _active_at(session, supplier.mission_id):
            await _timeline(
                session,
                incident_id,
                NOTICES,
                f"{mission.city} · {supplier.name}: {_said(status, detail)}.",
                {"supplier": supplier.code, "status": status},
            )
    await session.flush()
    return Outcome(
        [supply_event(supplier.tenant_id, "supplier", supplier_id=supplier.id, status=status)]
    )


# --- the seed (SUP-01, §2, §3) ----------------------------------------------------------------


@dataclass(frozen=True)
class SupplierIn:
    code: str
    name: str
    service: str
    mission_id: uuid.UUID | None
    tier: int
    vetting_valid_until: date
    backup_code: str | None = None
    in_bcp: bool = False
    performance_score: int | None = None
    status: str = "NORMAL"
    status_detail: str | None = None


@dataclass(frozen=True)
class RouteIn:
    code: str
    mission_id: uuid.UUID
    label: str
    kind: str
    points: tuple[tuple[float, float], ...]  # (lat, lon)
    supplier_code: str | None = None
    alternate_of_code: str | None = None


def _wkt(points: tuple[tuple[float, float], ...]) -> str:
    return "LINESTRING(" + ", ".join(f"{float(lon)!r} {float(lat)!r}" for lat, lon in points) + ")"


async def ensure_register(
    session: AsyncSession,
    suppliers: list[SupplierIn],
    routes: list[RouteIn],
    actor: Actor = SYSTEM,
) -> tuple[int, int]:
    """Seed the suppliers and routes not yet there (SUP-01). Existing rows are never changed
    (PC-43, PC-44). A backup or a primary route is inserted before what refers to it, since
    both are frozen once set. Audited once."""
    ids: dict[str, uuid.UUID] = {s.code: s.id for s in await session.scalars(select(Supplier))}
    pending = [s for s in suppliers if s.code not in ids]
    added_suppliers = 0
    while pending:
        ready = [s for s in pending if s.backup_code is None or s.backup_code in ids]
        if not ready:
            raise ValueError(f"unknown or circular backups: {[s.code for s in pending]}")
        for s in ready:
            row = Supplier(
                tenant_id=session.info["tenant_id"],
                code=s.code,
                name=s.name,
                service=s.service,
                mission_id=s.mission_id,
                tier=s.tier,
                backup_supplier_id=ids[s.backup_code] if s.backup_code else None,
                in_bcp=s.in_bcp,
                vetting_valid_until=s.vetting_valid_until,
                performance_score=s.performance_score,
                status=s.status,
                status_detail=s.status_detail,
            )
            session.add(row)
            await session.flush()
            ids[s.code] = row.id
            added_suppliers += 1
        pending = [s for s in pending if s.code not in ids]
    route_ids: dict[str, uuid.UUID] = {
        r.code: r.id for r in await session.scalars(select(LogisticsRoute))
    }
    waiting = [r for r in routes if r.code not in route_ids]
    added_routes = 0
    while waiting:
        ready_routes = [
            r for r in waiting if r.alternate_of_code is None or r.alternate_of_code in route_ids
        ]
        if not ready_routes:
            raise ValueError(f"unknown or circular alternates: {[r.code for r in waiting]}")
        for r in ready_routes:
            route_id = await session.scalar(
                text(
                    "INSERT INTO logistics_route (tenant_id, mission_id, code, label, kind, "
                    "supplier_id, alternate_of_id, path) VALUES (current_tenant_id(), :mission, "
                    ":code, :label, :kind, :supplier, :alternate, "
                    "ST_GeomFromText(:wkt, 4326)::geography) RETURNING id"
                ),
                {
                    "mission": r.mission_id,
                    "code": r.code,
                    "label": r.label,
                    "kind": r.kind,
                    "supplier": ids[r.supplier_code] if r.supplier_code else None,
                    "alternate": route_ids[r.alternate_of_code] if r.alternate_of_code else None,
                    "wkt": _wkt(r.points),
                },
            )
            assert route_id is not None
            route_ids[r.code] = route_id
            added_routes += 1
        waiting = [r for r in waiting if r.code not in route_ids]
    if added_suppliers or added_routes:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="SUPPLY.SEED",
            entity_type="supplier",
            details={"suppliers": added_suppliers, "routes": added_routes},
        )
    return added_suppliers, added_routes
