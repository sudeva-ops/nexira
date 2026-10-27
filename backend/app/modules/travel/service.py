import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.tenancy.service import SYSTEM, Actor
from app.modules.travel.models import (
    Airport,
    CountryRisk,
    Flight,
    Trip,
    TripSegment,
    TripTraveller,
)


@dataclass(frozen=True)
class SegmentSeed:
    """A seeded itinerary segment (PC-14, PC-17)."""

    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    place_label: str | None = None
    flight_number: str | None = None
    from_airport: str | None = None
    to_airport: str | None = None


async def ensure_trip(
    session: AsyncSession,
    *,
    trip_id: uuid.UUID,
    reference: str,
    purpose: str,
    origin: str,
    destination: str,
    destination_country: str,
    starts_on: date,
    ends_on: date,
    traveller_ids: list[uuid.UUID],
    risk_level: str = "LOW",
    approval_status: str = "PENDING",
    mission_id: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
    restricted: bool = False,
    segments: list[SegmentSeed] | None = None,
    actor: Actor = SYSTEM,
) -> bool:
    """Create a trip with its travellers if the reference is new. Audited on create.
    Seed only: a trip with a requester must be a DRAFT (migration 0003); users plan
    trips through travel/trips.py."""
    tenant_id = session.info["tenant_id"]
    created = await session.scalar(
        insert(Trip)
        .values(
            id=trip_id,
            tenant_id=tenant_id,
            reference=reference,
            purpose=purpose,
            origin=origin,
            destination=destination,
            destination_country=destination_country,
            starts_on=starts_on,
            ends_on=ends_on,
            risk_level=risk_level,
            approval_status=approval_status,
            mission_id=mission_id,
            requested_by=requested_by,
            restricted=restricted,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "reference"])
        .returning(Trip.id)
    )
    if created is None:
        return False
    if traveller_ids:
        await session.execute(
            insert(TripTraveller).values(
                [
                    {"tenant_id": tenant_id, "trip_id": trip_id, "person_id": p}
                    for p in traveller_ids
                ]
            )
        )
    if segments:
        await session.execute(
            insert(TripSegment).values(
                [
                    {
                        "tenant_id": tenant_id,
                        "trip_id": trip_id,
                        "seq": n,
                        "kind": seg.kind,
                        "title": seg.title,
                        "place_label": seg.place_label,
                        "starts_at": seg.starts_at,
                        "ends_at": seg.ends_at,
                        "flight_number": seg.flight_number,
                        "from_airport": seg.from_airport,
                        "to_airport": seg.to_airport,
                    }
                    for n, seg in enumerate(segments, start=1)
                ]
            )
        )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="TRIP.CREATE",
        entity_type="trip",
        entity_id=str(trip_id),
        details={"reference": reference, "travellers": len(traveller_ids)},
    )
    return True


@dataclass(frozen=True)
class CountryRiskIn:
    country_code: str
    security: int
    unrest: int
    health: int
    transport: int
    source: str

    @property
    def level(self) -> str:
        """D-08 level from the worst of the four scores (0-100)."""
        worst = max(self.security, self.unrest, self.health, self.transport)
        return (
            "CRITICAL"
            if worst >= 90
            else "HIGH"
            if worst >= 70
            else ("MODERATE" if worst >= 45 else "LOW")
        )


async def ensure_country_risks(
    session: AsyncSession, risks: list[CountryRiskIn], actor: Actor = SYSTEM
) -> int:
    """Simulated base risk per country (PC-16, D-19), for the countries that are new.
    One audit row for the load, as for people and sites (plan G-20)."""
    if not risks:
        return 0
    created = await session.execute(
        insert(CountryRisk)
        .values(
            [
                {
                    "tenant_id": session.info["tenant_id"],
                    "country_code": r.country_code,
                    "level": r.level,
                    "security": r.security,
                    "unrest": r.unrest,
                    "health": r.health,
                    "transport": r.transport,
                    "source": r.source,
                }
                for r in risks
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "country_code"])
        .returning(CountryRisk.country_code)
    )
    count = len(created.all())
    if count:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="COUNTRY_RISK.BULK_LOAD",
            entity_type="country_risk",
            details={"count": count},
        )
    return count


@dataclass(frozen=True)
class AirportIn:
    iata: str
    name: str
    city: str
    country_code: str
    lat: float
    lon: float


async def ensure_airports(
    session: AsyncSession, airports: list[AirportIn], actor: Actor = SYSTEM
) -> int:
    """Simulated reference airports (PC-18, D-19), for the codes that are new."""
    if not airports:
        return 0
    created = await session.execute(
        insert(Airport)
        .values(
            [
                {
                    "tenant_id": session.info["tenant_id"],
                    "iata": a.iata,
                    "name": a.name,
                    "city": a.city,
                    "country_code": a.country_code,
                    "location": f"SRID=4326;POINT({a.lon} {a.lat})",
                }
                for a in airports
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "iata"])
        .returning(Airport.iata)
    )
    count = len(created.all())
    if count:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="AIRPORT.BULK_LOAD",
            entity_type="airport",
            details={"count": count},
        )
    return count


async def ensure_scenario_flight(
    session: AsyncSession, trip_id: uuid.UUID, actor: Actor = SYSTEM
) -> bool:
    """Seed only (plan G-3): the flight of a seeded trip's FLIGHT segment, driven by a
    scenario's FLIGHT_FEED events and never by the clock. The database refuses it for a
    trip that is restricted or not approved (PC-19)."""
    segment = await session.scalar(
        select(TripSegment).where(
            TripSegment.trip_id == trip_id,
            TripSegment.kind == "FLIGHT",
            TripSegment.flight_number.is_not(None),
        )
    )
    if segment is None or segment.flight_number is None:
        return False
    if segment.from_airport is None or segment.to_airport is None:
        return False
    if await session.scalar(select(Flight.id).where(Flight.trip_segment_id == segment.id)):
        # Already seeded: re-seeding must not hit the guard, e.g. after the trip was
        # cancelled (review of Prompt 29, L3).
        return False
    created = await session.scalar(
        insert(Flight)
        .values(
            tenant_id=session.info["tenant_id"],
            trip_segment_id=segment.id,
            flight_number=segment.flight_number,
            from_airport=segment.from_airport,
            to_airport=segment.to_airport,
            scheduled_dep=segment.starts_at,
            scheduled_arr=segment.ends_at,
            estimated_dep=segment.starts_at,
            estimated_arr=segment.ends_at,
            source="SCENARIO",
        )
        .on_conflict_do_nothing(index_elements=["trip_segment_id"])
        .returning(Flight.id)
    )
    if created is None:
        return False
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="FLIGHT.TRACK",
        entity_type="flight",
        entity_id=str(created),
        details={"flight_number": segment.flight_number, "source": "SCENARIO"},
    )
    return True
