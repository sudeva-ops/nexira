"""Reading tracked flights (AT-02, AT-03, AT-07; D-33). Flights exist only for approved,
unrestricted trips (PC-19 guard), so nothing here needs to filter restricted trips out."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.travel.models import FlightEvent
from app.modules.travel.schemas import FlightDetailOut, FlightEventOut, FlightOut
from app.modules.travel.tracker import DELAY_MIN, progress_of

DISRUPTED = ("DELAYED", "HOLDING", "DIVERTED", "CANCELLED")

_FLIGHTS = """
    SELECT f.id, f.flight_number, f.status, f.from_airport, fa.city AS from_city,
           f.to_airport, ta.city AS to_city, f.diverted_to, da.city AS diverted_city,
           f.scheduled_dep, f.scheduled_arr, f.estimated_dep, f.estimated_arr,
           ST_Y(f.position::geometry) AS lat, ST_X(f.position::geometry) AS lon,
           f.altitude_ft, f.speed_kt, f.updated_at,
           ST_Y(fa.location::geometry) AS from_lat, ST_X(fa.location::geometry) AS from_lon,
           ST_Y(ta.location::geometry) AS to_lat, ST_X(ta.location::geometry) AS to_lon,
           ST_Y(da.location::geometry) AS div_lat, ST_X(da.location::geometry) AS div_lon,
           t.id AS trip_id, t.reference AS trip_reference,
           (SELECT max(e.occurred_at) FROM flight_event e
             WHERE e.flight_id = f.id AND e.event_type = 'DIVERTED') AS diverted_at,
           coalesce((SELECT array_agg(p.full_name ORDER BY p.full_name)
                       FROM trip_traveller tt JOIN person p ON p.id = tt.person_id
                      WHERE tt.trip_id = t.id), '{}') AS travellers
      FROM flight f
      JOIN trip_segment s ON s.id = f.trip_segment_id
      JOIN trip t ON t.id = s.trip_id
      JOIN airport fa ON fa.tenant_id = f.tenant_id AND fa.iata = f.from_airport
      JOIN airport ta ON ta.tenant_id = f.tenant_id AND ta.iata = f.to_airport
      LEFT JOIN airport da ON da.tenant_id = f.tenant_id AND da.iata = f.diverted_to
"""


def _out(r: Any, now: datetime) -> FlightOut:
    delay = max(0, round((r.estimated_arr - r.scheduled_arr).total_seconds() / 60))
    if r.status in ("LANDED",):
        progress = 1.0
    elif r.status in ("SCHEDULED", "DELAYED", "CANCELLED"):
        progress = 0.0
    elif r.status == "DIVERTED" and r.diverted_at is not None:
        progress = progress_of(r.diverted_at, r.estimated_arr, now)
    else:
        progress = progress_of(r.estimated_dep, r.estimated_arr, now)
    route = [(r.from_lat, r.from_lon), (r.to_lat, r.to_lon)]
    if r.div_lat is not None:
        route.append((r.div_lat, r.div_lon))
    return FlightOut(
        id=r.id,
        flight_number=r.flight_number,
        status=r.status,
        from_airport=r.from_airport,
        from_city=r.from_city,
        to_airport=r.to_airport,
        to_city=r.to_city,
        diverted_to=r.diverted_to,
        diverted_city=r.diverted_city,
        scheduled_dep=r.scheduled_dep,
        scheduled_arr=r.scheduled_arr,
        estimated_dep=r.estimated_dep,
        estimated_arr=r.estimated_arr,
        delay_min=delay,
        disrupted=r.status in DISRUPTED or (r.status != "LANDED" and delay >= DELAY_MIN),
        lat=r.lat,
        lon=r.lon,
        altitude_ft=r.altitude_ft,
        speed_kt=r.speed_kt,
        progress=round(progress, 3),
        route=route,
        travellers=list(r.travellers),
        trip_id=r.trip_id,
        trip_reference=r.trip_reference,
        updated_at=r.updated_at,
        simulated=True,
    )


async def list_flights(
    session: AsyncSession, now: datetime, status: str | None = None, disrupted: bool | None = None
) -> list[FlightOut]:
    """In the air first, then by estimated arrival."""
    query = _FLIGHTS + " WHERE (CAST(:status AS text) IS NULL OR f.status = :status)"
    query += """
     ORDER BY f.status IN ('LANDED', 'CANCELLED'), f.estimated_arr
     LIMIT 200
    """
    rows = (await session.execute(text(query), {"status": status})).all()
    out = [_out(r, now) for r in rows]
    if disrupted is not None:
        out = [f for f in out if f.disrupted == disrupted]
    return out


async def flight_detail(
    session: AsyncSession, flight_id: uuid.UUID, now: datetime
) -> FlightDetailOut | None:
    row = (await session.execute(text(_FLIGHTS + " WHERE f.id = :id"), {"id": flight_id})).first()
    if row is None:
        return None
    events = await session.scalars(
        select(FlightEvent).where(FlightEvent.flight_id == flight_id).order_by(FlightEvent.id)
    )
    return FlightDetailOut(
        **_out(row, now).model_dump(),
        events=[
            FlightEventOut(event_type=e.event_type, occurred_at=e.occurred_at, details=e.details)
            for e in events
        ],
    )


async def segment_flights(
    session: AsyncSession, segment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    """segment id -> (flight id, status), for the trip API (AT-07)."""
    if not segment_ids:
        return {}
    rows = await session.execute(
        text("SELECT trip_segment_id, id, status FROM flight WHERE trip_segment_id = ANY(:ids)"),
        {"ids": segment_ids},
    )
    return {segment: (flight, status) for segment, flight, status in rows}
