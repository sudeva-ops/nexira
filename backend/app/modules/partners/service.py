"""Assistance partners (AS-01..08; D-36, docs/plan-pilot-ast.md).

- Requests are made, cancelled and completed by a person with DUTY_OFFICER,
  SECURITY_OFFICER or HEAD_OF_MISSION for the request's mission, checked through
  app/core/approvals.py (D-05, §4), or by a PB-07 step a person approved (§5). Agents never
  request (D-36).
- The partner's own moves (accept, decline, en route) come only from the partner adapter,
  through tick() in the worker (§3).
- The database enforces the status table, frozen content, coverage and the
  restricted-traveller rule (migration 0006); this module checks roles and inputs and gives
  clear messages first.

Every change is audited (PARTNER_REQUEST.*) and announced after commit as
PARTNER_REQUEST_UPDATED.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.approvals import user_has_role
from app.core.db import tenant_session
from app.core.events import Event, Publisher
from app.core.security import CurrentUser
from app.modules.intel.models import Incident
from app.modules.partners.adapter import PartnerAdapter, Pending
from app.modules.partners.models import SERVICES, Partner, PartnerRequest
from app.modules.people.models import Mission, Person
from app.modules.tenancy.service import SYSTEM, Actor

log = logging.getLogger(__name__)

REQUESTERS = "DUTY_OFFICER|SECURITY_OFFICER|HEAD_OF_MISSION"  # §33 Q2, scoped to the mission
PARTNER = Actor(type="SYSTEM", id="partners.simulated")
NOTE_MAX = 500
DEFAULT_SOS_SERVICE = "SECURE_TRANSPORT"  # §33 Q6
FINAL = ("COMPLETED", "DECLINED", "CANCELLED")
ACTIONS = {  # audit action per new status (plan §7)
    "ACCEPTED": "PARTNER_REQUEST.ACCEPT",
    "DECLINED": "PARTNER_REQUEST.DECLINE",
    "EN_ROUTE": "PARTNER_REQUEST.EN_ROUTE",
    "COMPLETED": "PARTNER_REQUEST.COMPLETE",
    "CANCELLED": "PARTNER_REQUEST.CANCEL",
}

Now = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PartnerError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


# --- the directory and the seed ----------------------------------------------------------------


@dataclass(frozen=True)
class PartnerIn:
    code: str
    name: str
    services: list[str]
    coverage: list[str]
    sla_minutes: int
    hours: str = "24/7"


async def ensure_partners(
    session: AsyncSession, partners: list[PartnerIn], actor: Actor = SYSTEM
) -> list[str]:
    """Create partners whose code is new; return the codes created (audited once each)."""
    if not partners:
        return []
    tenant_id = session.info["tenant_id"]
    created = await session.scalars(
        insert(Partner)
        .values(
            [
                {
                    "tenant_id": tenant_id,
                    "code": p.code,
                    "name": p.name,
                    "services": p.services,
                    "coverage": p.coverage,
                    "sla_minutes": p.sla_minutes,
                    "hours": p.hours,
                }
                for p in partners
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(Partner.code)
    )
    codes = sorted(created.all())
    for code in codes:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="PARTNER.CREATE",
            entity_type="partner",
            entity_id=code,
        )
    return codes


async def list_partners(session: AsyncSession) -> list[Partner]:
    return list(await session.scalars(select(Partner).order_by(Partner.name)))


@dataclass(frozen=True)
class MissionCoverage:
    mission_id: uuid.UUID
    code: str
    city: str
    country_code: str
    missing: list[str]  # services no active partner offers in the mission's country


async def coverage(session: AsyncSession) -> list[MissionCoverage]:
    """AS-07: per mission, the services no active partner covers there."""
    partners = [p for p in await list_partners(session) if p.is_active]
    out = []
    for m in await session.scalars(select(Mission).order_by(Mission.code)):
        covered = {s for p in partners if m.country_code in p.coverage for s in p.services}
        out.append(
            MissionCoverage(
                m.id, m.code, m.city, m.country_code, [s for s in SERVICES if s not in covered]
            )
        )
    return out


# --- where a person is, and who can help there (AS-06) -------------------------------------------


async def mission_for_person(session: AsyncSession, person: Person) -> uuid.UUID | None:
    """Plan G-4: the mission nearest to the person's current location (no reverse geocoding
    offline), or their own mission when they have no location."""
    nearest: uuid.UUID | None = await session.scalar(
        text(
            "SELECT m.id FROM person_location_current l, mission m WHERE l.person_id = :p "
            "ORDER BY ST_Distance(l.location, m.location), m.code LIMIT 1"
        ),
        {"p": person.id},
    )
    return nearest or person.mission_id


@dataclass(frozen=True)
class Suggestion:
    person_id: uuid.UUID
    service: str
    mission_id: uuid.UUID
    mission_code: str
    country_code: str
    partners: list[Partner]  # capable partners there, shortest SLA first (plan G-3)


async def suggest(
    session: AsyncSession, person_id: uuid.UUID, service: str = DEFAULT_SOS_SERVICE
) -> Suggestion:
    _service(service)
    person = await session.get(Person, person_id)
    if person is None:
        raise PartnerError(404, "No such person")
    if await _restricted(session, person.id):
        raise PartnerError(409, "A restricted traveller cannot be named (AS-08)")
    mission_id = await mission_for_person(session, person)
    if mission_id is None:
        raise PartnerError(422, "This person has no location and no mission")
    mission = await session.get_one(Mission, mission_id)
    capable = sorted(
        (
            p
            for p in await list_partners(session)
            if p.is_active and service in p.services and mission.country_code in p.coverage
        ),
        key=lambda p: (p.sla_minutes, p.name),
    )
    return Suggestion(person.id, service, mission.id, mission.code, mission.country_code, capable)


# --- requests ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestIn:
    partner_id: uuid.UUID
    service: str
    mission_id: uuid.UUID | None = None  # default: the person's (G-4), then the incident's
    incident_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    note: str | None = None


@dataclass
class Outcome:
    request: PartnerRequest
    events: list[Event]


def request_event(request: PartnerRequest) -> Event:
    return Event(
        type="PARTNER_REQUEST_UPDATED",
        tenant_id=request.tenant_id,
        payload={
            "request_id": str(request.id),
            "reference": request.reference,
            "status": request.status,
            "incident_id": str(request.incident_id) if request.incident_id else None,
        },
        source="partners",
    )


def _service(service: str) -> None:
    if service not in SERVICES:
        raise PartnerError(422, f"service is one of {', '.join(SERVICES)}")


_INSERT = text(
    """
    INSERT INTO partner_request (tenant_id, reference, partner_id, service, mission_id,
           incident_id, person_id, place_label, location, note, created_by_type, created_by)
    SELECT current_tenant_id(), next_reference('REQ', false), :partner, :service, m.id,
           :incident, :person, left(coalesce(l.place_label, m.city), 200),
           ST_SnapToGrid(coalesce(l.location, m.location)::geometry, 0.001)::geography,
           :note, :by_type, :by
      FROM mission m LEFT JOIN person_location_current l ON l.person_id = :person
     WHERE m.id = :mission
    RETURNING id
    """
)


async def _insert(
    session: AsyncSession,
    body: RequestIn,
    mission_id: uuid.UUID,
    created_by_type: str,
    created_by: str,
    actor: Actor,
) -> PartnerRequest:
    """AS-08: the request holds the place and an approximate location (the person's, else
    the mission's, plan G-9, on a 0.001° grid: about 100 m), the service and the note;
    nothing else about the person."""
    request_id = await session.scalar(
        _INSERT,
        {
            "partner": body.partner_id,
            "service": body.service,
            "mission": mission_id,
            "incident": body.incident_id,
            "person": body.person_id,
            "note": body.note,
            "by_type": created_by_type,
            "by": created_by,
        },
    )
    if request_id is None:
        raise PartnerError(404, "No such mission")
    request = await session.get_one(PartnerRequest, request_id)
    partner = await session.get_one(Partner, request.partner_id)
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PARTNER_REQUEST.CREATE",
        entity_type="partner_request",
        entity_id=request.reference,
        details={
            "partner": partner.code,
            "service": request.service,
            "mission_id": str(request.mission_id),
            "incident_id": str(request.incident_id) if request.incident_id else None,
            "person_id": str(request.person_id) if request.person_id else None,
            "created_by_type": created_by_type,
        },
    )
    return request


async def create_request(session: AsyncSession, user: CurrentUser, body: RequestIn) -> Outcome:
    """AS-02: a person asks a partner for one service, for a mission."""
    _service(body.service)
    note = (body.note or "").strip() or None
    if note is not None and (len(note) > NOTE_MAX or "\x00" in note):
        raise PartnerError(422, f"note is at most {NOTE_MAX} characters of text")
    partner = await session.get(Partner, body.partner_id)
    if partner is None:
        raise PartnerError(404, "No such partner")
    # The request is for one mission: the role, coverage and the place all follow it, so a
    # person or incident elsewhere cannot be named under another mission (D-05; review of
    # Prompt 45, H1).
    candidates: list[tuple[str, uuid.UUID | None]] = []
    if body.mission_id is not None:
        candidates.append(("the mission named", body.mission_id))
    if body.person_id is not None:
        person = await session.get(Person, body.person_id)
        if person is None:
            raise PartnerError(404, "No such person")
        candidates.append(
            ("the person's nearest mission", await mission_for_person(session, person))
        )
    if body.incident_id is not None:
        incident = await session.get(Incident, body.incident_id)
        if incident is None:
            raise PartnerError(404, "No such incident")
        if incident.mission_id is not None:
            candidates.append(("the incident's mission", incident.mission_id))
    known = {m for _, m in candidates if m is not None}
    if len(known) > 1:
        raise PartnerError(
            422,
            "The mission, the person and the incident must be at the same mission: "
            + ", ".join(what for what, _ in candidates)
            + " differ",
        )
    mission_id = next(iter(known), None)
    if mission_id is None:
        raise PartnerError(
            422, "A request is for a mission: name the mission, a person or an incident"
        )
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise PartnerError(404, "No such mission")
    if not await user_has_role(session, user, REQUESTERS, mission_id):
        raise PartnerError(
            403,
            "Requesting a partner needs Duty Officer, Security Officer, or "
            "Head of Mission for this mission",
        )
    # The guard refuses these too (migration 0006); checked here for a clear message.
    if not partner.is_active:
        raise PartnerError(409, f"{partner.name} is not active")
    if body.service not in partner.services:
        raise PartnerError(409, f"{partner.code} does not offer {body.service}")
    if mission.country_code not in partner.coverage:
        raise PartnerError(409, f"{partner.code} does not cover {mission.country_code}")
    if body.person_id is not None and await _restricted(session, body.person_id):
        raise PartnerError(409, "A restricted traveller cannot be named (AS-08)")
    clean = RequestIn(
        body.partner_id, body.service, mission_id, body.incident_id, body.person_id, note
    )
    actor = Actor(type="USER", id=str(user.id))
    request = await _insert(session, clean, mission_id, "USER", str(user.id), actor)
    return Outcome(request, [request_event(request)])


async def restricted_people(session: AsyncSession, person_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Those of person_ids who are restricted travellers now (plan G-5)."""
    if not person_ids:
        return set()
    rows = await session.scalars(
        text(
            "SELECT DISTINCT tt.person_id FROM trip t JOIN trip_traveller tt ON tt.trip_id = t.id "
            "WHERE tt.person_id = ANY(:ids) AND t.restricted "
            "AND t.approval_status IN ('DRAFT', 'PENDING', 'APPROVED') "
            "AND t.ends_on >= (now() AT TIME ZONE 'UTC')::date"
        ),
        {"ids": list(person_ids)},
    )
    return set(rows)


async def _restricted(session: AsyncSession, person_id: uuid.UUID) -> bool:
    """Plan G-5, as the guard: on a restricted trip being prepared, ahead or under way."""
    found = await session.scalar(
        text(
            "SELECT 1 FROM trip t JOIN trip_traveller tt ON tt.trip_id = t.id "
            "WHERE tt.person_id = :p AND t.restricted "
            "AND t.approval_status IN ('DRAFT', 'PENDING', 'APPROVED') "
            "AND t.ends_on >= (now() AT TIME ZONE 'UTC')::date LIMIT 1"
        ),
        {"p": person_id},
    )
    return found is not None


async def _mine(session: AsyncSession, user: CurrentUser, request_id: uuid.UUID) -> PartnerRequest:
    request = await session.scalar(
        select(PartnerRequest).where(PartnerRequest.id == request_id).with_for_update()
    )
    if request is None:
        raise PartnerError(404, "No such request")
    if not await user_has_role(session, user, REQUESTERS, request.mission_id):
        raise PartnerError(
            403, "Only Duty Officer, Security Officer, or Head of Mission for this mission"
        )
    return request


async def _move(
    session: AsyncSession, request: PartnerRequest, status: str, actor: Actor, **details: Any
) -> None:
    before = request.status
    request.status = status
    await session.flush()
    await session.refresh(request)  # the trigger writes the timestamps
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=ACTIONS[status],
        entity_type="partner_request",
        entity_id=request.reference,
        details={"from": before, "to": status, **details},
    )


async def cancel(session: AsyncSession, user: CurrentUser, request_id: uuid.UUID) -> Outcome:
    request = await _mine(session, user, request_id)
    if request.status in FINAL:
        raise PartnerError(409, f"{request.reference} is already {request.status.lower()}")
    await _move(session, request, "CANCELLED", Actor(type="USER", id=str(user.id)))
    return Outcome(request, [request_event(request)])


async def complete(session: AsyncSession, user: CurrentUser, request_id: uuid.UUID) -> Outcome:
    """§33 Q4: a person confirms the partner has done the job."""
    request = await _mine(session, user, request_id)
    if request.status != "EN_ROUTE":
        raise PartnerError(
            409, f"{request.reference} can be completed once the partner is en route"
        )
    await _move(session, request, "COMPLETED", Actor(type="USER", id=str(user.id)))
    return Outcome(request, [request_event(request)])


# --- the partner's side (AS-04; worker) ----------------------------------------------------------


async def respond_all(
    session: AsyncSession, adapter: PartnerAdapter, now: datetime
) -> list[PartnerRequest]:
    """Apply the adapter's response to every open request; return the ones that moved."""
    rows = (
        await session.execute(
            select(PartnerRequest, Partner.sla_minutes)
            .join(Partner, Partner.id == PartnerRequest.partner_id)
            .where(PartnerRequest.status.in_(("REQUESTED", "ACCEPTED")))
            .order_by(PartnerRequest.requested_at)
            .with_for_update(of=PartnerRequest, skip_locked=True)
        )
    ).all()
    moved = []
    for request, sla in rows:
        response = adapter.respond(
            Pending(
                request.id,
                request.status,
                sla,
                request.incident_id is not None,
                request.requested_at,
                request.accepted_at,
            ),
            now,
        )
        if response is None:
            continue
        if response.eta is not None:
            request.eta = response.eta
        await _move(
            session,
            request,
            response.status,
            PARTNER,
            **({"eta": response.eta.isoformat()} if response.eta else {}),
        )
        moved.append(request)
    return moved


async def tick(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    publisher: Publisher,
    adapter: PartnerAdapter,
    *,
    now: Now = _utcnow,
) -> list[PartnerRequest]:
    async with tenant_session(tenant_id, engine) as session:
        moved = await respond_all(session, adapter, now())
        await session.commit()
    for request in moved:
        try:
            await publisher.publish(request_event(request))
        except Exception:
            log.exception("publishing PARTNER_REQUEST_UPDATED failed after commit")
    return moved


# --- PB-07 step 6 (AS-05, plan §5) ---------------------------------------------------------------


async def standby(
    session: AsyncSession,
    incident: Incident,
    config: dict[str, Any],
    run_id: uuid.UUID,
    actor: Actor,
) -> tuple[str, dict[str, Any]] | None:
    """A PARTNER_REQUEST step: a tracked standby request to the named partner for the
    incident's mission. None when the tenant has no such partner (plan G-1), so the engine
    keeps the Phase 1 behaviour."""
    name = str(config.get("partner") or "")
    service = str(config.get("service_code") or "MEDICAL")
    # Names are not unique: the active partner of that name offering the service, by code
    # (review of Prompt 45, L1).
    partner = await session.scalar(
        select(Partner)
        .where(Partner.name == name, Partner.is_active, Partner.services.contains([service]))
        .order_by(Partner.code)
        .limit(1)
    )
    if partner is None or incident.mission_id is None:
        return None
    mission = await session.get_one(Mission, incident.mission_id)
    if mission.country_code not in partner.coverage:
        return (
            f"no partner covers {mission.country_code} for {service} (simulated)",
            {"partner": partner.name, "service": service, "covered": False, "simulated": True},
        )
    request = await _insert(
        session,
        RequestIn(
            partner.id, service, mission.id, incident.id, None, f"Standby · {incident.reference}"
        ),
        mission.id,
        "PLAYBOOK",
        str(run_id),
        actor,
    )
    return (
        f"{partner.name} asked to stand by · {request.reference} (simulated)",
        {
            "partner": partner.name,
            "service": service,
            "request_id": str(request.id),
            "request_reference": request.reference,
            "simulated": True,
        },
    )
