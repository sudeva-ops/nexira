"""Simulated telematics and the simulated workshop for the worker (plan-pilot-flt §6; G-5,
G-7). A VEHICLE_POSITION event moves a vehicle, fuel included, and a crossing of an ACTIVE
incident's impact zone writes a FLEET timeline entry; a WORKSHOP_DONE event marks an open
maintenance item done. Neither changes anything else. FLEET_UPDATED goes to browsers after the
commit."""

import logging

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.fleet import service

log = logging.getLogger(__name__)
CODE = r"^(VH-[0-9]{2,3}|[A-Z]{2,4}-[A-Z]{3})$"


class PositionIn(BaseModel):
    asset_code: str = Field(pattern=CODE)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = Field(min_length=1, max_length=150)
    fuel_pct: int = Field(ge=0, le=100)


class WorkshopIn(BaseModel):
    asset_code: str = Field(pattern=CODE)
    task: str = Field(min_length=1, max_length=200)


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    # As the other consumers: a publish that fails after the commit is logged, not retried;
    # the screen refetches on the next event.
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


def position_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        try:
            p = PositionIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("vehicle position refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.position(
                session, p.asset_code, p.lat, p.lon, p.label, p.fuel_pct
            )
            await session.commit()
        if outcome is not None:
            await _publish(publisher, outcome.events)

    return handle


def workshop_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        try:
            w = WorkshopIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("workshop event refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.workshop_done(session, w.asset_code, w.task)
            await session.commit()
        if outcome is not None:
            await _publish(publisher, outcome.events)

    return handle
