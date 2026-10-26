"""Journey Management: trips from draft to approval (JR-01..07, JR-09; D-32, Prompt 25).

- A TRAVEL_DESK or DUTY_OFFICER user plans a trip on the travellers' behalf as a DRAFT,
  with its travellers and itinerary. Only the requester, still holding one of those
  roles, edits or submits it. requested_by is set here only, from the token's user,
  never from a request.
- Submitting takes the destination risk (D-32, plan G-1): the country's simulated base
  level (PC-16) raised to the worst ACTIVE incident whose mission is in that country.
  A LOW trip is approved at once with no second person (plan G-6); otherwise it waits
  for a second person. The scope is the single mission in the destination country, else
  none (HQ-level holders only, plan G-2, D-06).
- Approving and rejecting go through approvals.decide(). The level approved is the
  higher of the submitted and the live risk (plan G-7), and it decides the role:
  MODERATE needs TRAVEL_DESK or SECURITY_OFFICER, HIGH and CRITICAL SECURITY_OFFICER.
  Submitting is the first step, so the requester never decides the second.
  HIGH and CRITICAL need the four user checklist items first (JR-05).
- An approved trip whose live risk rises above the approved level is flagged, never
  revoked (JR-07).
- Every action is audited (JR-09). The database backs every rule (PC-15, migration 0003):
  content frozen once submitted, forward-only status, no self-approval.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.people.models import Mission, Person
from app.modules.travel.models import CountryRisk, Trip, TripSegment, TripTraveller

LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")  # D-08, as severity_rank()
SEGMENT_KINDS = ("FLIGHT", "STAY", "MEETING", "GROUND")
CHECK_ITEMS = ("security_briefing", "insurance_medical", "emergency_contacts", "checkin_schedule")
TRAVELLERS_MAX = 50
SEGMENTS_MAX = 30
REASON_MAX = 500

CREATORS = "TRAVEL_DESK|DUTY_OFFICER"
CHECKERS = "TRAVEL_DESK|DUTY_OFFICER|SECURITY_OFFICER"
CANCELLERS = "TRAVEL_DESK|ADMIN"  # besides the requester
APPROVERS = {
    "LOW": "TRAVEL_DESK|SECURITY_OFFICER",  # never pending in practice: LOW is auto-approved
    "MODERATE": "TRAVEL_DESK|SECURITY_OFFICER",
    "HIGH": "SECURITY_OFFICER",
    "CRITICAL": "SECURITY_OFFICER",
}


class TripError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SegmentIn:
    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    place_label: str | None = None


@dataclass(frozen=True)
class Plan:
    """What a draft says: everything a user may write (no author or approval fields)."""

    origin: str
    destination: str
    destination_country: str
    starts_on: date
    ends_on: date
    travellers: list[uuid.UUID]
    purpose: str | None = None
    segments: list[SegmentIn] = field(default_factory=list)


@dataclass
class Outcome:
    trip: Trip
    events: list[Event]


def rank(level: str | None) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


def worst(*levels: str | None) -> str:
    return max((lv for lv in levels if lv in LEVELS), key=rank, default="LOW")


def trip_event(trip: Trip) -> Event:
    return Event(
        type="TRIP_UPDATED",
        tenant_id=trip.tenant_id,
        payload={
            "trip_id": str(trip.id),
            "reference": trip.reference,
            "status": trip.approval_status,
        },
        source="travel.trips",
    )


async def _audit(
    session: AsyncSession,
    user: CurrentUser,
    action: str,
    trip: Trip,
    details: dict[str, Any] | None = None,
) -> None:
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action=f"TRIP.{action}",
        entity_type="trip",
        entity_id=trip.reference,
        details=details or {},
    )


# --- destination risk (JR-03) -----------------------------------------------------------


@dataclass(frozen=True)
class DestinationRisk:
    country: str
    level: str  # the base level raised to the worst ACTIVE incident
    base: CountryRisk | None  # None: no simulated level for the country (LOW)
    incident_level: str | None
    incidents: list[str]  # references of the ACTIVE incidents in the country


async def destination_risks(
    session: AsyncSession, countries: set[str]
) -> dict[str, DestinationRisk]:
    """Plan G-1: an incident counts for the country of its mission."""
    if not countries:
        return {}
    base = {
        r.country_code: r
        for r in await session.scalars(
            select(CountryRisk).where(CountryRisk.country_code.in_(countries))
        )
    }
    rows = (
        await session.execute(
            text(
                """
                SELECT m.country_code, i.severity, i.reference
                  FROM incident i JOIN mission m ON m.id = i.mission_id
                 WHERE i.status = 'ACTIVE' AND m.country_code = ANY(:countries)
                 ORDER BY severity_rank(i.severity) DESC, i.reference
                """
            ),
            {"countries": sorted(countries)},
        )
    ).all()
    incidents: dict[str, list[tuple[str, str]]] = {}
    for country, severity, reference in rows:
        incidents.setdefault(country, []).append((severity, reference))
    out = {}
    for country in countries:
        found = incidents.get(country, [])
        incident_level = found[0][0] if found else None
        row = base.get(country)
        out[country] = DestinationRisk(
            country=country,
            level=worst(row.level if row else "LOW", incident_level),
            base=row,
            incident_level=incident_level,
            incidents=[ref for _, ref in found],
        )
    return out


async def live_risk(session: AsyncSession, trip: Trip) -> str:
    if not trip.destination_country:
        return "LOW"
    risks = await destination_risks(session, {trip.destination_country})
    return risks[trip.destination_country].level


async def impacted_by(
    session: AsyncSession, trip_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """JR-06: ACTIVE incidents with a traveller in their exposure while the trip is on,
    by the exposure rule (D-22, plan G-11). Only trips that will happen (plan G-3)."""
    if not trip_ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT t.id, i.reference
              FROM trip t
              JOIN trip_traveller tt ON tt.trip_id = t.id
              JOIN incident_exposure e ON e.subject_type = 'PERSON' AND e.subject_id = tt.person_id
              JOIN incident i ON i.id = e.incident_id AND i.status = 'ACTIVE'
             WHERE t.id = ANY(:ids) AND t.approval_status IN ('PENDING', 'APPROVED')
               AND (i.opened_at AT TIME ZONE 'UTC')::date BETWEEN t.starts_on AND t.ends_on
             ORDER BY i.reference
            """
        ),
        {"ids": trip_ids},
    )
    out: dict[uuid.UUID, list[str]] = {}
    for trip_id, reference in rows:
        out.setdefault(trip_id, []).append(reference)
    return out


# --- validation ---------------------------------------------------------------------


def _text(value: str | None, name: str, limit: int, required: bool = True) -> None:
    if value is None or not value.strip():
        if required:
            raise TripError(422, f"{name} is required")
        return
    if len(value) > limit:
        raise TripError(422, f"{name} is at most {limit} characters")


async def _validate(session: AsyncSession, plan: Plan, home_tz: str) -> None:
    """Check a plan against the tenant's own rows (RLS); never trusts an id."""
    _text(plan.purpose, "purpose", 200, required=False)
    _text(plan.origin, "origin", 120)
    _text(plan.destination, "destination", 120)
    if (
        len(plan.destination_country) != 2
        or not plan.destination_country.isalpha()
        or (not plan.destination_country.isupper())
    ):
        raise TripError(422, "destination_country is a two-letter ISO code, e.g. FR")
    if plan.ends_on < plan.starts_on:
        raise TripError(422, "the trip ends before it starts")
    if not plan.travellers or len(plan.travellers) > TRAVELLERS_MAX:
        raise TripError(422, f"a trip has 1 to {TRAVELLERS_MAX} travellers")
    if len(set(plan.travellers)) != len(plan.travellers):
        raise TripError(422, "each traveller once")
    found = set(await session.scalars(select(Person.id).where(Person.id.in_(plan.travellers))))
    if found != set(plan.travellers):
        raise TripError(422, "unknown traveller")
    if len(plan.segments) > SEGMENTS_MAX:
        raise TripError(422, f"at most {SEGMENTS_MAX} segments")
    zone = ZoneInfo(home_tz)  # plan G-8: dates in the home time zone
    for n, segment in enumerate(plan.segments, start=1):
        if segment.kind not in SEGMENT_KINDS:
            raise TripError(422, f"segment {n}: kind is one of {', '.join(SEGMENT_KINDS)}")
        _text(segment.title, f"segment {n} title", 200)
        _text(segment.place_label, f"segment {n} place", 200, required=False)
        if segment.starts_at.tzinfo is None or segment.ends_at.tzinfo is None:
            raise TripError(422, f"segment {n}: times need a time zone")
        if segment.ends_at < segment.starts_at:
            raise TripError(422, f"segment {n} ends before it starts")
        first, last = (
            segment.starts_at.astimezone(zone).date(),
            segment.ends_at.astimezone(zone).date(),
        )
        if first < plan.starts_on or last > plan.ends_on:
            raise TripError(422, f"segment {n} is outside the trip's dates (JR-02)")


async def _write_children(session: AsyncSession, trip: Trip, plan: Plan) -> None:
    """Travellers and segments are replaced as a list while the trip is a DRAFT."""
    await session.execute(delete(TripTraveller).where(TripTraveller.trip_id == trip.id))
    await session.execute(delete(TripSegment).where(TripSegment.trip_id == trip.id))
    await session.execute(
        insert(TripTraveller).values(
            [
                {"tenant_id": trip.tenant_id, "trip_id": trip.id, "person_id": p}
                for p in plan.travellers
            ]
        )
    )
    if plan.segments:
        await session.execute(
            insert(TripSegment).values(
                [
                    {
                        "tenant_id": trip.tenant_id,
                        "trip_id": trip.id,
                        "seq": n,
                        "kind": s.kind,
                        "title": s.title,
                        "place_label": s.place_label,
                        "starts_at": s.starts_at,
                        "ends_at": s.ends_at,
                    }
                    for n, s in enumerate(plan.segments, start=1)
                ]
            )
        )


def _details(plan: Plan) -> dict[str, Any]:
    return {
        "destination": plan.destination,
        "country": plan.destination_country,
        "starts_on": plan.starts_on.isoformat(),
        "ends_on": plan.ends_on.isoformat(),
        "travellers": len(plan.travellers),
        "segments": len(plan.segments),
    }


async def _locked(session: AsyncSession, trip_id: uuid.UUID) -> Trip:
    trip = await session.scalar(select(Trip).where(Trip.id == trip_id).with_for_update())
    if trip is None:
        raise TripError(404, "Trip not found")
    return trip


async def _requester_planning(
    session: AsyncSession, user: CurrentUser, trip: Trip, doing: str
) -> None:
    """The requester, still holding a creator role (as for campaigns)."""
    if trip.requested_by != user.id:
        raise TripError(403, f"Only the requester {doing}")
    if not await approvals.user_has_role(session, user, CREATORS):
        raise TripError(403, "Planning trips needs TRAVEL_DESK or DUTY_OFFICER")


# --- drafts (JR-01, JR-02) ---------------------------------------------------------------


async def create_draft(session: AsyncSession, user: CurrentUser, plan: Plan, home_tz: str) -> Trip:
    if not await approvals.user_has_role(session, user, CREATORS):
        raise TripError(403, "Planning trips needs TRAVEL_DESK or DUTY_OFFICER")
    await _validate(session, plan, home_tz)
    trip = Trip(
        tenant_id=session.info["tenant_id"],
        reference=await session.scalar(text("SELECT next_reference('TRP', false)")),
        purpose=plan.purpose,
        origin=plan.origin,
        destination=plan.destination,
        destination_country=plan.destination_country,
        starts_on=plan.starts_on,
        ends_on=plan.ends_on,
        approval_status="DRAFT",
        requested_by=user.id,  # from the token's user, never from the request
    )
    session.add(trip)
    await session.flush()
    await _write_children(session, trip, plan)
    await _audit(session, user, "DRAFT", trip, _details(plan))
    return trip


async def update_draft(
    session: AsyncSession, user: CurrentUser, trip_id: uuid.UUID, plan: Plan, home_tz: str
) -> Trip:
    trip = await _locked(session, trip_id)
    await _requester_planning(session, user, trip, "edits a trip")
    if trip.approval_status != "DRAFT":
        raise TripError(409, f"{trip.reference} is {trip.approval_status}: only a draft is edited")
    await _validate(session, plan, home_tz)
    trip.purpose = plan.purpose
    trip.origin = plan.origin
    trip.destination = plan.destination
    trip.destination_country = plan.destination_country
    trip.starts_on = plan.starts_on
    trip.ends_on = plan.ends_on
    await session.flush()
    await _write_children(session, trip, plan)
    await _audit(session, user, "EDIT", trip, _details(plan))
    return trip


# --- checklist (JR-05) -----------------------------------------------------------------


async def check(
    session: AsyncSession, user: CurrentUser, trip_id: uuid.UUID, item: str, done: bool
) -> Trip:
    if item not in CHECK_ITEMS:
        raise TripError(422, f"item is one of {', '.join(CHECK_ITEMS)}")
    trip = await _locked(session, trip_id)
    if not await approvals.user_has_role(session, user, CHECKERS):
        raise TripError(403, "The checklist needs TRAVEL_DESK, DUTY_OFFICER or SECURITY_OFFICER")
    if trip.approval_status not in ("DRAFT", "PENDING"):
        raise TripError(409, f"{trip.reference} is {trip.approval_status}: the checklist is closed")
    trip.checklist = {**trip.checklist, item: done}
    await session.flush()
    await _audit(session, user, "CHECK", trip, {"item": item, "done": done})
    return trip


def open_items(trip: Trip) -> list[str]:
    return [item for item in CHECK_ITEMS if trip.checklist.get(item) is not True]


# --- submit, approve, reject, cancel (JR-03, JR-04) -----------------------------------------


async def _scope(session: AsyncSession, country: str) -> uuid.UUID | None:
    """Plan G-2: the single mission in the destination country, else none (HQ only)."""
    missions = list(
        await session.scalars(select(Mission.id).where(Mission.country_code == country))
    )
    return missions[0] if len(missions) == 1 else None


async def submit(session: AsyncSession, user: CurrentUser, trip_id: uuid.UUID) -> Outcome:
    trip = await _locked(session, trip_id)
    await _requester_planning(session, user, trip, "submits a trip")
    if trip.approval_status != "DRAFT":
        raise TripError(409, f"{trip.reference} is {trip.approval_status}")
    travellers = await session.scalar(select(func.count()).where(TripTraveller.trip_id == trip.id))
    if not travellers:
        raise TripError(409, f"{trip.reference} has no travellers")
    level = await live_risk(session, trip)
    # One UPDATE: the risk, the scope and the status together; the database records
    # submitted_at (and approved_at for a LOW trip).
    trip.risk_level = level
    trip.mission_id = await _scope(session, trip.destination_country or "")
    if level == "LOW":
        trip.approval_status = "APPROVED"
        trip.approved_risk_level = "LOW"
    else:
        trip.approval_status = "PENDING"
    await session.flush()
    await session.refresh(trip, ["submitted_at", "approved_at"])
    await _audit(session, user, "SUBMIT", trip, {"risk": level})
    if level == "LOW":
        # No second person (D-32, plan G-6): the requester is named as the actor.
        await _audit(session, user, "AUTO_APPROVE", trip, {"risk": level})
    return Outcome(trip, [trip_event(trip)])


async def approval_level(session: AsyncSession, trip: Trip) -> str:
    """Plan G-7: the higher of the submitted and the live risk."""
    return worst(trip.risk_level, await live_risk(session, trip))


async def gate(session: AsyncSession, trip: Trip, level: str | None = None) -> approvals.Gate:
    level = level or await approval_level(session, trip)
    return approvals.Gate(
        subject=f"Trip {trip.reference} ({level})",
        required_role=APPROVERS[level],
        mission_id=trip.mission_id,
        decided=trip.approved_at is not None,
        open=trip.approval_status == "PENDING",
        # Submitting is the first step: the requester cannot decide the second (D-32).
        deciders_of_other_steps=frozenset({trip.requested_by} if trip.requested_by else set()),
    )


async def approve(session: AsyncSession, user: CurrentUser, trip_id: uuid.UUID) -> Outcome:
    trip = await _locked(session, trip_id)
    level = await approval_level(session, trip)
    await approvals.decide(session, user, await gate(session, trip, level))
    if rank(level) >= rank("HIGH") and (missing := open_items(trip)):
        raise TripError(
            409, f"{trip.reference} is {level}: the checklist item {missing[0]} is not done (JR-05)"
        )
    trip.approval_status = "APPROVED"
    trip.approved_by = user.id
    trip.approved_risk_level = level
    await session.flush()
    await session.refresh(trip, ["approved_at"])
    await _audit(session, user, "APPROVE", trip, {"risk": level})
    return Outcome(trip, [trip_event(trip)])


async def reject(
    session: AsyncSession, user: CurrentUser, trip_id: uuid.UUID, reason: str
) -> Outcome:
    if not reason.strip() or len(reason) > REASON_MAX:
        raise TripError(422, f"a reason of 1 to {REASON_MAX} characters is needed")
    trip = await _locked(session, trip_id)
    await approvals.decide(session, user, await gate(session, trip))
    trip.approval_status = "DRAFT"  # back to the requester, who may edit and submit again
    trip.rejection_reason = reason
    await session.flush()
    await _audit(session, user, "REJECT", trip, {"reason": reason})
    return Outcome(trip, [trip_event(trip)])


async def _may_cancel(session: AsyncSession, user: CurrentUser, trip: Trip) -> bool:
    return trip.requested_by == user.id or await approvals.user_has_role(session, user, CANCELLERS)


async def cancel(session: AsyncSession, user: CurrentUser, trip_id: uuid.UUID) -> Outcome:
    trip = await _locked(session, trip_id)
    if not await _may_cancel(session, user, trip):
        raise TripError(403, "Only the requester, TRAVEL_DESK or ADMIN cancels a trip")
    if trip.approval_status not in ("DRAFT", "PENDING", "APPROVED"):
        raise TripError(409, f"{trip.reference} is {trip.approval_status}: it cannot be cancelled")
    was = trip.approval_status
    trip.approval_status = "CANCELLED"
    await session.flush()
    await _audit(session, user, "CANCEL", trip, {"was": was})
    return Outcome(trip, [trip_event(trip)])


# --- permissions (plan G-07) -----------------------------------------------------------


@dataclass(frozen=True)
class Permissions:
    edit: bool
    submit: bool
    approve: bool
    check: bool
    cancel: bool


async def permissions(session: AsyncSession, user: CurrentUser, trip: Trip) -> Permissions:
    planning = (
        trip.requested_by == user.id
        and trip.approval_status == "DRAFT"
        and await approvals.user_has_role(session, user, CREATORS)
    )
    may_approve = False
    if trip.approval_status == "PENDING":
        may_approve = (await approvals.can_decide(session, user, await gate(session, trip))).allowed
    may_check = trip.approval_status in ("DRAFT", "PENDING") and await approvals.user_has_role(
        session, user, CHECKERS
    )
    may_cancel = trip.approval_status in ("DRAFT", "PENDING", "APPROVED") and await _may_cancel(
        session, user, trip
    )
    return Permissions(
        edit=planning, submit=planning, approve=may_approve, check=may_check, cancel=may_cancel
    )
