import uuid
from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.tenancy.service import SYSTEM, Actor
from app.modules.travel.models import Trip, TripTraveller


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
    actor: Actor = SYSTEM,
) -> bool:
    """Create a trip with its travellers if the reference is new. Audited on create."""
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
