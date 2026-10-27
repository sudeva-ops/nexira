import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.tenancy.service import SYSTEM, Actor
from app.modules.travel.models import CountryRisk, Trip, TripTraveller


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
