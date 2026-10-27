"""Simulated flight tracker (AT-01..04, AT-06, AT-08; D-33, docs/plan-pilot-air.md §2).

It plays the part of a flight-data provider: nothing external is called. It is the
only writer of flights (the seed adds scenario flights, plan G-3). A real provider later
replaces the "move" step and the FLIGHT_FEED consumer, nothing else.

- tick(): per tenant, every few seconds:
  1. ensure a flight for each FLIGHT segment with a number and airports, of an APPROVED
     trip that is not restricted, departing within 24 h and not yet due to land
     (the PC-19 guard refuses anything else);
  2. cancel a flight whose trip was cancelled, unless it is already in the air (the
     status table: a flight is never CANCELLED once airborne);
  3. move SIMULATED flights by the clock (depart, fly the great circle, land); SCENARIO
     flights change status only through FLIGHT_FEED;
  4. on landing, record each traveller at the landing airport (FLIGHT observation) and
     recompute exposure for ACTIVE incidents within 100 km (plan G-5).
- feed_handler(): FLIGHT_FEED events (the scenario player, or later a provider): a delay,
  departure, holding, diversion, landing or cancellation, with times relative to now.

Every status change is a flight_event and an audit row (actor SYSTEM, FLIGHT.<STATUS>);
positions are not audited. FLIGHT_UPDATED is published after commit for each change, and
FLIGHT_POSITIONS at most every 15 s per tenant while flights are in the air.
"""

import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.intel import exposure
from app.modules.people import location
from app.modules.people.service import ObservationIn, add_observations
from app.modules.tenancy.service import SYSTEM
from app.modules.travel.models import Flight, FlightEvent

log = logging.getLogger(__name__)

Now = Callable[[], datetime]

TRACK_AHEAD = timedelta(hours=24)
DELAY_MIN = 30  # D-33: 30 minutes or more late is a delay
NEARBY_KM = 100  # plan G-5
HOLD_SHORT_KM = 30  # a holding flight circles this far short of its destination
HOLD_RADIUS_KM = 8
CRUISE_FT, CRUISE_KT = 37_000, 460
HOLD_FT, HOLD_KT = 12_000, 230
POSITIONS_EVERY = timedelta(seconds=15)
EARTH_KM = 6371.0

IN_AIR = ("AIRBORNE", "HOLDING", "DIVERTED")
FINAL = ("LANDED", "CANCELLED")
ALLOWED = {  # the PC-19 status table (plan G-8)
    "SCHEDULED": {"DELAYED", "AIRBORNE", "CANCELLED"},
    "DELAYED": {"AIRBORNE", "CANCELLED"},
    "AIRBORNE": {"HOLDING", "DIVERTED", "LANDED"},
    "HOLDING": {"AIRBORNE", "DIVERTED", "LANDED"},
    "DIVERTED": {"HOLDING", "LANDED"},
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- geometry (spherical; simulated positions only) -------------------------------------


Point = tuple[float, float]  # (lat, lon)


def _vector(p: Point) -> tuple[float, float, float]:
    lat, lon = math.radians(p[0]), math.radians(p[1])
    return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))


def distance_km(a: Point, b: Point) -> float:
    va, vb = _vector(a), _vector(b)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(va, vb, strict=True))))
    return EARTH_KM * math.acos(dot)


def along(a: Point, b: Point, fraction: float) -> Point:
    """The point at fraction (0..1) of the great circle from a to b."""
    angle = distance_km(a, b) / EARTH_KM
    if angle < 1e-9:
        return a
    va, vb = _vector(a), _vector(b)
    wa = math.sin((1 - fraction) * angle) / math.sin(angle)
    wb = math.sin(fraction * angle) / math.sin(angle)
    x, y, z = (wa * p + wb * q for p, q in zip(va, vb, strict=True))
    return (math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x)))


def holding_point(a: Point, b: Point, now: datetime) -> Point:
    """Circling HOLD_RADIUS_KM around a point HOLD_SHORT_KM short of b."""
    total = distance_km(a, b)
    centre = along(a, b, max(0.0, 1 - HOLD_SHORT_KM / total)) if total else b
    angle = (now.timestamp() / 90) % (2 * math.pi)  # one turn in about 9 minutes
    dlat = HOLD_RADIUS_KM / 111.0 * math.cos(angle)
    dlon = HOLD_RADIUS_KM / (111.0 * max(0.1, math.cos(math.radians(centre[0])))) * math.sin(angle)
    return (centre[0] + dlat, centre[1] + dlon)


def profile(progress: float) -> tuple[int, int]:
    """Altitude (ft) and speed (kt) along a flight: climb, cruise, descend."""
    if progress < 0.1:
        share = progress / 0.1
    elif progress > 0.85:
        share = (1 - progress) / 0.15
    else:
        share = 1.0
    share = max(0.0, min(1.0, share))
    return round(CRUISE_FT * share), round(160 + (CRUISE_KT - 160) * share)


def progress_of(start: datetime, end: datetime, now: datetime) -> float:
    span = (end - start).total_seconds()
    return 1.0 if span <= 0 else max(0.0, min(1.0, (now - start).total_seconds() / span))


def _wkt(p: Point) -> str:
    return f"SRID=4326;POINT({p[1]} {p[0]})"


# --- one change, recorded ------------------------------------------------------------------


@dataclass
class Result:
    changed: list[Flight] = field(default_factory=list)
    landed: list[tuple[Flight, str]] = field(default_factory=list)  # (flight, airport)
    moving: bool = False


async def _airports(session: AsyncSession) -> dict[str, tuple[Point, str, str]]:
    rows = await session.execute(
        text(
            "SELECT iata, ST_Y(location::geometry), ST_X(location::geometry), name, city "
            "FROM airport"
        )
    )
    return {iata: ((lat, lon), name, city) for iata, lat, lon, name, city in rows}


async def _position(session: AsyncSession, flight: Flight) -> Point | None:
    if flight.position is None:
        return None
    row = (
        await session.execute(
            text(
                "SELECT ST_Y(position::geometry), ST_X(position::geometry) FROM flight "
                "WHERE id = :id"
            ),
            {"id": flight.id},
        )
    ).one()
    return (row[0], row[1])


async def _record(
    session: AsyncSession,
    flight: Flight,
    event_type: str,
    details: dict[str, Any],
    result: Result,
    audit_action: str | None = None,
) -> None:
    session.add(
        FlightEvent(
            tenant_id=flight.tenant_id, flight_id=flight.id, event_type=event_type, details=details
        )
    )
    await session.flush()
    await audit.write(
        session,
        actor_type=SYSTEM.type,
        actor_id=SYSTEM.id,
        action=f"FLIGHT.{audit_action or event_type}",
        entity_type="flight",
        entity_id=str(flight.id),
        details={"flight_number": flight.flight_number, **details},
    )
    result.changed.append(flight)


async def _change(
    session: AsyncSession,
    flight: Flight,
    status: str,
    event_type: str | None,
    details: dict[str, Any],
    result: Result,
) -> bool:
    """Move flight to status (same rules as the PC-19 guard). False if not allowed."""
    if status != flight.status and status not in ALLOWED.get(flight.status, set()):
        log.warning("flight %s: %s -> %s ignored", flight.flight_number, flight.status, status)
        return False
    flight.status = status
    await session.flush()
    if event_type is not None:
        await _record(session, flight, event_type, details, result)
    return True


async def _land(
    session: AsyncSession,
    flight: Flight,
    airports: dict[str, tuple[Point, str, str]],
    now: datetime,
    result: Result,
) -> None:
    """LANDED at the destination or the diversion airport; travellers move there (AT-04)."""
    at = flight.diverted_to or flight.to_airport
    point, name, city = airports[at]
    flight.position = _wkt(point)
    flight.altitude_ft, flight.speed_kt = 0, 0
    if not await _change(session, flight, "LANDED", "LANDED", {"airport": at}, result):
        return
    travellers = list(
        await session.scalars(
            text(
                "SELECT tt.person_id FROM trip_traveller tt "
                "JOIN trip_segment s ON s.trip_id = tt.trip_id WHERE s.id = :segment"
            ),
            {"segment": flight.trip_segment_id},
        )
    )
    if travellers:
        await add_observations(
            session,
            [
                ObservationIn(
                    person_id=p,
                    source="FLIGHT",
                    lat=point[0],
                    lon=point[1],
                    observed_at=now,
                    place_label=f"{city} · {name} (landed, {flight.flight_number})",
                )
                for p in travellers
            ],
        )
        await location.recompute(session, now, travellers)
    result.landed.append((flight, at))


# --- the tick --------------------------------------------------------------------------------


_ENSURE = text(
    """
    SELECT s.id, s.flight_number, s.from_airport, s.to_airport, s.starts_at, s.ends_at
      FROM trip_segment s
      JOIN trip t ON t.id = s.trip_id
     WHERE s.kind = 'FLIGHT' AND s.flight_number IS NOT NULL
       AND s.from_airport IS NOT NULL AND s.to_airport IS NOT NULL
       AND t.approval_status = 'APPROVED' AND NOT t.restricted
       AND s.starts_at <= :ahead AND s.ends_at > :now
       AND NOT EXISTS (SELECT 1 FROM flight f WHERE f.trip_segment_id = s.id)
    """
)

_STOP = text(
    """
    SELECT f.id FROM flight f
      JOIN trip_segment s ON s.id = f.trip_segment_id
      JOIN trip t ON t.id = s.trip_id
     WHERE t.approval_status = 'CANCELLED' AND f.status IN ('SCHEDULED', 'DELAYED')
    """
)


async def _ensure(session: AsyncSession, now: datetime, result: Result) -> None:
    rows = (await session.execute(_ENSURE, {"ahead": now + TRACK_AHEAD, "now": now})).all()
    for segment_id, number, origin, destination, departs, arrives in rows:
        flight = Flight(
            tenant_id=session.info["tenant_id"],
            trip_segment_id=segment_id,
            flight_number=number,
            from_airport=origin,
            to_airport=destination,
            scheduled_dep=departs,
            scheduled_arr=arrives,
            estimated_dep=departs,
            estimated_arr=arrives,
            source="SIMULATED",
        )
        try:
            # A savepoint each: another worker, or a trip cancelled since the select, must
            # not roll back the rest of the tick (review, L6).
            async with session.begin_nested():
                session.add(flight)
                await session.flush()
        except DBAPIError:
            log.info("flight %s not tracked now (taken or no longer approved)", number)
            continue
        await audit.write(
            session,
            actor_type=SYSTEM.type,
            actor_id=SYSTEM.id,
            action="FLIGHT.TRACK",
            entity_type="flight",
            entity_id=str(flight.id),
            details={"flight_number": number, "source": "SIMULATED"},
        )
        result.changed.append(flight)


async def _stop(session: AsyncSession, result: Result) -> None:
    for flight_id in (await session.scalars(_STOP)).all():
        flight = await session.scalar(
            select(Flight).where(Flight.id == flight_id).with_for_update()
        )
        if flight is not None and flight.status in ("SCHEDULED", "DELAYED"):
            await _change(
                session, flight, "CANCELLED", "CANCELLED", {"reason": "trip cancelled"}, result
            )


async def _move(
    session: AsyncSession,
    airports: dict[str, tuple[Point, str, str]],
    now: datetime,
    result: Result,
) -> None:
    flights = (
        await session.scalars(
            select(Flight).where(Flight.status.not_in(FINAL)).with_for_update(skip_locked=True)
        )
    ).all()
    for flight in flights:
        origin, destination = airports[flight.from_airport][0], airports[flight.to_airport][0]
        if flight.source == "SIMULATED":
            if flight.status in ("SCHEDULED", "DELAYED") and now >= flight.estimated_dep:
                await _change(session, flight, "AIRBORNE", "DEPARTED", {}, result)
            elif flight.status in ("AIRBORNE", "DIVERTED") and now >= flight.estimated_arr:
                await _land(session, flight, airports, now, result)
                continue
        if flight.status == "AIRBORNE":
            p = progress_of(flight.estimated_dep, flight.estimated_arr, now)
            flight.position = _wkt(along(origin, destination, p))
            flight.altitude_ft, flight.speed_kt = profile(p)
        elif flight.status == "HOLDING":
            # After a diversion it holds near the diversion airport (review, L10).
            target = airports[flight.diverted_to][0] if flight.diverted_to else destination
            flight.position = _wkt(holding_point(origin, target, now))
            flight.altitude_ft, flight.speed_kt = HOLD_FT, HOLD_KT
        elif flight.status == "DIVERTED" and flight.diverted_to:
            start, since = await _diversion_start(session, flight)
            p = progress_of(since or flight.updated_at, flight.estimated_arr, now)
            flight.position = _wkt(along(start or destination, airports[flight.diverted_to][0], p))
            flight.altitude_ft, flight.speed_kt = (
                round(HOLD_FT * (1 - p)),
                round(HOLD_KT * (1 - p / 2)),
            )
        else:
            continue
        result.moving = True
    await session.flush()


async def _diversion_start(
    session: AsyncSession, flight: Flight
) -> tuple[Point | None, datetime | None]:
    event = await session.scalar(
        select(FlightEvent)
        .where(FlightEvent.flight_id == flight.id, FlightEvent.event_type == "DIVERTED")
        .order_by(FlightEvent.id.desc())
        .limit(1)
    )
    if event is None:
        return None, None
    lat, lon = event.details.get("from_lat"), event.details.get("from_lon")
    start = (float(lat), float(lon)) if lat is not None and lon is not None else None
    return start, event.occurred_at


def flight_event(
    flight: Flight, kind: str = "FLIGHT_UPDATED", trip_id: uuid.UUID | None = None
) -> Event:
    return Event(
        type=kind,
        tenant_id=flight.tenant_id,
        payload={
            "flight_id": str(flight.id),
            "flight_number": flight.flight_number,
            "status": flight.status,
            "trip_id": str(trip_id) if trip_id else None,
        },
        source="travel.tracker",
    )


_last_positions: dict[uuid.UUID, datetime] = {}


async def _after(
    engine: AsyncEngine, tenant_id: uuid.UUID, publisher: Publisher, result: Result, now: datetime
) -> None:
    """After commit: events, and exposure near each landing airport (plan G-5)."""
    changed = {f.id: f for f in result.changed}
    trips: dict[uuid.UUID, uuid.UUID] = {}
    if changed:
        async with tenant_session(tenant_id, engine) as session:
            rows = await session.execute(
                text(
                    "SELECT f.id, s.trip_id FROM flight f "
                    "JOIN trip_segment s ON s.id = f.trip_segment_id WHERE f.id = ANY(:ids)"
                ),
                {"ids": list(changed)},
            )
            trips = {flight_id: trip_id for flight_id, trip_id in rows}
    for flight in changed.values():
        await publisher.publish(flight_event(flight, trip_id=trips.get(flight.id)))
    if (
        result.moving
        and now - _last_positions.get(tenant_id, datetime.min.replace(tzinfo=UTC))
        >= POSITIONS_EVERY
    ):
        _last_positions[tenant_id] = now
        await publisher.publish(
            Event(type="FLIGHT_POSITIONS", tenant_id=tenant_id, payload={}, source="travel.tracker")
        )
    for _flight, at in result.landed:
        async with tenant_session(tenant_id, engine) as session:
            nearby = (
                await session.scalars(
                    text(
                        "SELECT i.id FROM incident i, airport a WHERE i.status = 'ACTIVE' "
                        "AND a.iata = :at AND ST_DWithin(i.location, a.location, "
                        "greatest(i.impact_radius_m, :metres))"
                    ),
                    {"at": at, "metres": NEARBY_KM * 1000},
                )
            ).all()
        for incident_id in nearby:
            async with tenant_session(tenant_id, engine) as session:
                computed = await exposure.compute(session, incident_id)
                await session.commit()
            if computed is not None:
                await publisher.publish(exposure.exposure_event(computed, tenant_id))


async def tick(
    engine: AsyncEngine, tenant_id: uuid.UUID, publisher: Publisher, *, now: Now = _utcnow
) -> Result:
    moment = now()
    result = Result()
    async with tenant_session(tenant_id, engine) as session:
        airports = await _airports(session)
        await _ensure(session, moment, result)
        await _stop(session, result)
        await _move(session, airports, moment, result)
        await session.commit()
    await _after(engine, tenant_id, publisher, result, moment)
    return result


# --- the feed (FLIGHT_FEED) -------------------------------------------------------------------


MAX_MIN = 48 * 60  # feed times are relative minutes; anything outside 0..48 h is refused


@dataclass(frozen=True)
class Feed:
    """A validated FLIGHT_FEED payload (review of Prompt 30, L2): one change."""

    flight_number: str
    day: str
    status: str | None  # AIRBORNE, HOLDING, DIVERTED, LANDED, CANCELLED; None for a delay
    delay_min: int | None = None
    departed_min_ago: float = 0
    arrives_in_min: float | None = None
    to: str | None = None
    reason: str = ""


def _minutes(value: object, default: float | None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("minutes must be a number")
    if not math.isfinite(value) or not 0 <= value <= MAX_MIN:
        raise ValueError(f"minutes must be between 0 and {MAX_MIN}")
    return float(value)


def parse_feed(payload: dict[str, Any]) -> Feed | None:
    """None (logged) for anything malformed: a bad feed is dropped, never retried."""
    try:
        number, day = payload.get("flight_number"), payload.get("date")
        if not isinstance(number, str) or not isinstance(day, str):
            raise ValueError("flight_number and date are required")
        reason = payload.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason must be text")
        if "delay_min" in payload:
            delay = _minutes(payload["delay_min"], None)
            return Feed(number, day, None, delay_min=round(delay or 0), reason=reason[:200])
        status = payload.get("status")
        if status not in ("AIRBORNE", "HOLDING", "DIVERTED", "LANDED", "CANCELLED"):
            raise ValueError(f"unknown change {status!r}")
        to = payload.get("to")
        if status == "DIVERTED" and not isinstance(to, str):
            raise ValueError("a diversion names the airport")
        return Feed(
            number,
            day,
            str(status),
            departed_min_ago=_minutes(payload.get("departed_min_ago"), 0) or 0,
            arrives_in_min=_minutes(payload.get("arrives_in_min"), None),
            to=to if isinstance(to, str) else None,
            reason=reason[:200],
        )
    except ValueError as e:
        log.warning("FLIGHT_FEED ignored (%s): %s", e, payload)
        return None


async def _find(session: AsyncSession, number: str, day: str) -> list[Flight]:
    """Every tracked flight with this number departing on this home-zone date, not yet
    final: a provider's update is about the physical flight, which may carry several of
    our trips (review of Prompt 30, M2). Locked in a fixed order."""
    zone = ZoneInfo(get_settings().home_tz)
    flights = (
        await session.scalars(
            select(Flight)
            .where(Flight.flight_number == number, Flight.status.not_in(FINAL))
            .order_by(Flight.id)
            .with_for_update()
        )
    ).all()
    return [f for f in flights if f.scheduled_dep.astimezone(zone).date().isoformat() == day]


def _allowed(flight: Flight, status: str) -> bool:
    return status == flight.status or status in ALLOWED.get(flight.status, set())


async def _apply(
    session: AsyncSession,
    flight: Flight,
    feed: Feed,
    airports: dict[str, tuple[Point, str, str]],
    now: datetime,
    result: Result,
) -> None:
    """One change to one flight. The transition is checked before anything is written,
    so a refused change leaves the flight as it was (review, L1); a repeat of the
    current state writes nothing (L4)."""
    if feed.status is None:  # a delay
        minutes = feed.delay_min or 0
        if flight.status in IN_AIR:
            # In the air only the arrival moves; the departure happened (review, L3). Never
            # before the actual departure, whatever the schedule said.
            flight.estimated_arr = max(
                flight.scheduled_arr + timedelta(minutes=minutes), flight.estimated_dep
            )
        else:
            flight.estimated_dep = flight.scheduled_dep + timedelta(minutes=minutes)
            flight.estimated_arr = flight.scheduled_arr + timedelta(minutes=minutes)
        recorded = await session.scalar(
            select(FlightEvent.details)
            .where(FlightEvent.flight_id == flight.id, FlightEvent.event_type == "DELAYED")
            .order_by(FlightEvent.id.desc())
            .limit(1)
        )
        if minutes >= DELAY_MIN and (recorded or {}).get("minutes") != minutes:
            status = "DELAYED" if flight.status == "SCHEDULED" else flight.status
            await _change(session, flight, status, "DELAYED", {"minutes": minutes}, result)
        else:
            await session.flush()
        return
    status = feed.status
    if not _allowed(flight, status):
        log.warning("flight %s: %s -> %s ignored", flight.flight_number, flight.status, status)
        return
    if status == flight.status and status != "AIRBORNE":
        return  # a repeated HOLDING, DIVERTED: nothing new
    if status == "AIRBORNE":
        departed = flight.status in ("SCHEDULED", "DELAYED")
        if departed:
            flight.estimated_dep = now - timedelta(minutes=feed.departed_min_ago)
        if feed.arrives_in_min is not None:
            flight.estimated_arr = now + timedelta(minutes=feed.arrives_in_min)
        await _change(session, flight, "AIRBORNE", "DEPARTED" if departed else None, {}, result)
    elif status == "HOLDING":
        await _change(session, flight, "HOLDING", "HOLDING", {"reason": feed.reason}, result)
    elif status == "DIVERTED":
        to = feed.to or ""
        if to not in airports or to == flight.to_airport:
            log.warning("flight %s: diversion to %s ignored", flight.flight_number, to)
            return
        start = await _position(session, flight) or airports[flight.to_airport][0]
        flight.diverted_to = to
        flight.estimated_arr = now + timedelta(minutes=feed.arrives_in_min or 30)
        await _change(
            session,
            flight,
            "DIVERTED",
            "DIVERTED",
            {"to": to, "reason": feed.reason, "from_lat": start[0], "from_lon": start[1]},
            result,
        )
    elif status == "LANDED":
        await _land(session, flight, airports, now, result)
    else:  # CANCELLED
        await _change(session, flight, "CANCELLED", "CANCELLED", {"reason": feed.reason}, result)


async def apply_feed(
    session: AsyncSession, payload: dict[str, Any], now: datetime, result: Result
) -> list[Flight]:
    feed = parse_feed(payload)
    if feed is None:
        return []
    flights = await _find(session, feed.flight_number, feed.day)
    if not flights:
        log.info("FLIGHT_FEED for an untracked flight ignored: %s", feed.flight_number)
        return []
    airports = await _airports(session)
    for flight in flights:
        await _apply(session, flight, feed, airports, now, result)
    return flights


def feed_handler(engine: AsyncEngine, publisher: Publisher, now: Now = _utcnow) -> Handler:
    async def handle(event: Event) -> None:
        moment = now()
        result = Result()
        async with tenant_session(event.tenant_id, engine) as session:
            await apply_feed(session, event.payload, moment, result)
            await session.commit()
        await _after(engine, event.tenant_id, publisher, result, moment)

    return handle
