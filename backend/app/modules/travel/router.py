"""Trips API (Prompt 25; JR-01..07, JR-09; D-32).

- Reading trips: any user with a role.
- Planning, the checklist, the second-person approval and cancelling:
  travel/trips.py, which checks roles through app/core/approvals.py. Events are
  published after commit.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.config import Settings, get_settings
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.people.models import Person
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import ROLES
from app.modules.travel import trips
from app.modules.travel.models import Trip, TripSegment, TripTraveller
from app.modules.travel.schemas import (
    CheckIn,
    CountryRiskOut,
    RejectIn,
    SegmentOut,
    TravellerOut,
    TripDetailOut,
    TripIn,
    TripOut,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["travel"])

LIST_MAX = 200
Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]
Config = Annotated[Settings, Depends(get_settings)]


async def trips_out(session: AsyncSession, rows: list[Trip]) -> list[TripOut]:
    ids = [t.id for t in rows]
    counts: dict[uuid.UUID, int] = {}
    names: dict[uuid.UUID, str] = {}
    if ids:
        found = await session.execute(
            select(TripTraveller.trip_id, func.count())
            .where(TripTraveller.trip_id.in_(ids))
            .group_by(TripTraveller.trip_id)
        )
        counts = {trip_id: n for trip_id, n in found}
        user_ids = {u for t in rows for u in (t.requested_by, t.approved_by) if u}
        if user_ids:
            users = await session.execute(
                select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(user_ids))
            )
            names = {user_id: name for user_id, name in users}
    risks = await trips.destination_risks(
        session, {t.destination_country for t in rows if t.destination_country}
    )
    impacted = await trips.impacted_by(session, ids)
    out = []
    for t in rows:
        live = risks[t.destination_country].level if t.destination_country else "LOW"
        fields: dict[str, Any] = {
            k: getattr(t, k)
            for k in (
                "id",
                "reference",
                "purpose",
                "origin",
                "destination",
                "destination_country",
                "starts_on",
                "ends_on",
                "approval_status",
                "mission_id",
                "requested_by",
                "submitted_at",
                "approved_by",
                "approved_at",
                "approved_risk_level",
                "rejection_reason",
                "created_at",
            )
        }
        out.append(
            TripOut(
                **fields,
                # Never submitted (a draft, or a draft cancelled): what submitting would
                # give now (review of Prompt 25, L3).
                risk_level=live if t.submitted_at is None else t.risk_level,
                live_risk=live,
                risk_changed=t.approval_status == "APPROVED"
                and trips.rank(live) > trips.rank(t.approved_risk_level),
                requested_by_name=names.get(t.requested_by) if t.requested_by else None,
                approved_by_name=names.get(t.approved_by) if t.approved_by else None,
                checklist={
                    **{item: t.checklist.get(item) is True for item in trips.CHECK_ITEMS},
                    "security_approval": t.approval_status == "APPROVED",
                },
                travellers_count=counts.get(t.id, 0),
                impacted_by=impacted.get(t.id, []),
            )
        )
    return out


async def trip_detail(session: AsyncSession, trip: Trip) -> TripDetailOut:
    summary = (await trips_out(session, [trip]))[0]
    travellers = await session.execute(
        select(Person.id, Person.full_name, Person.person_type)
        .join(TripTraveller, TripTraveller.person_id == Person.id)
        .where(TripTraveller.trip_id == trip.id)
        .order_by(Person.full_name)
    )
    segments = await session.scalars(
        select(TripSegment).where(TripSegment.trip_id == trip.id).order_by(TripSegment.seq)
    )
    country_risk = None
    if trip.destination_country:
        risk = (await trips.destination_risks(session, {trip.destination_country}))[
            trip.destination_country
        ]
        base = risk.base
        country_risk = CountryRiskOut(
            country_code=risk.country,
            level=risk.level,
            base_level=base.level if base else trips.UNRATED_LEVEL,
            rated=base is not None,
            security=base.security if base else None,
            unrest=base.unrest if base else None,
            health=base.health if base else None,
            transport=base.transport if base else None,
            source=base.source if base else None,
            incident_level=risk.incident_level,
            incidents=risk.incidents,
            simulated=True,
        )
    return TripDetailOut(
        **summary.model_dump(),
        travellers=[TravellerOut(id=i, full_name=n, person_type=p) for i, n, p in travellers],
        segments=[
            SegmentOut(
                seq=s.seq,
                kind=s.kind,
                title=s.title,
                place_label=s.place_label,
                starts_at=s.starts_at,
                ends_at=s.ends_at,
            )
            for s in segments
        ],
        country_risk=country_risk,
    )


@router.get("/trips")
async def list_trips(
    _user: Reader,
    session: Db,
    status_: Annotated[str | None, Query(alias="status")] = None,
    risk: str | None = None,
    mission_id: uuid.UUID | None = None,
    impacted: bool | None = None,
) -> list[TripOut]:
    """Soonest first. risk filters the risk shown (submitted, or live for a draft)."""
    query = select(Trip).order_by(Trip.starts_on, Trip.reference)
    if status_ is not None:
        query = query.where(Trip.approval_status == status_)
    if mission_id is not None:
        query = query.where(Trip.mission_id == mission_id)
    out = await trips_out(session, list(await session.scalars(query)))
    if risk is not None:
        out = [t for t in out if t.risk_level == risk]
    if impacted is not None:
        out = [t for t in out if bool(t.impacted_by) == impacted]
    return out[:LIST_MAX]  # after the filters computed here (review of Prompt 25, L6)


@router.get("/trips/{trip_id}")
async def get_trip(trip_id: uuid.UUID, _user: Reader, session: Db) -> TripDetailOut:
    trip = await session.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return await trip_detail(session, trip)


def _plan(body: TripIn) -> trips.Plan:
    return trips.Plan(
        purpose=body.purpose,
        origin=body.origin,
        destination=body.destination,
        destination_country=body.destination_country,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        travellers=body.travellers,
        segments=[
            trips.SegmentIn(
                kind=s.kind,
                title=s.title,
                place_label=s.place_label,
                starts_at=s.starts_at,
                ends_at=s.ends_at,
            )
            for s in body.segments
        ],
    )


def _http(error: trips.TripError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


@router.post("/trips", status_code=201)
async def create_trip(
    body: TripIn, user: Reader, session: Db, settings: Config, publisher: Pub
) -> TripDetailOut:
    try:
        trip = await trips.create_draft(session, user, _plan(body), settings.home_tz)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, [trips.trip_event(trip)])
    return await trip_detail(session, trip)


@router.patch("/trips/{trip_id}")
async def edit_trip(
    trip_id: uuid.UUID, body: TripIn, user: Reader, session: Db, settings: Config, publisher: Pub
) -> TripDetailOut:
    try:
        trip = await trips.update_draft(session, user, trip_id, _plan(body), settings.home_tz)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, [trips.trip_event(trip)])
    return await trip_detail(session, trip)


@router.post("/trips/{trip_id}/checklist")
async def check_trip(
    trip_id: uuid.UUID, body: CheckIn, user: Reader, session: Db, publisher: Pub
) -> TripDetailOut:
    try:
        trip = await trips.check(session, user, trip_id, body.item, body.done)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, [trips.trip_event(trip)])
    return await trip_detail(session, trip)


@router.post("/trips/{trip_id}/submit")
async def submit_trip(
    trip_id: uuid.UUID, user: Reader, session: Db, publisher: Pub
) -> TripDetailOut:
    try:
        outcome = await trips.submit(session, user, trip_id)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await trip_detail(session, outcome.trip)


@router.post("/trips/{trip_id}/approve")
async def approve_trip(
    trip_id: uuid.UUID, user: Reader, session: Db, publisher: Pub
) -> TripDetailOut:
    try:
        outcome = await trips.approve(session, user, trip_id)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await trip_detail(session, outcome.trip)


@router.post("/trips/{trip_id}/reject")
async def reject_trip(
    trip_id: uuid.UUID, body: RejectIn, user: Reader, session: Db, publisher: Pub
) -> TripDetailOut:
    try:
        outcome = await trips.reject(session, user, trip_id, body.reason)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await trip_detail(session, outcome.trip)


@router.post("/trips/{trip_id}/cancel")
async def cancel_trip(
    trip_id: uuid.UUID, user: Reader, session: Db, publisher: Pub
) -> TripDetailOut:
    try:
        outcome = await trips.cancel(session, user, trip_id)
    except trips.TripError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await trip_detail(session, outcome.trip)
