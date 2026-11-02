"""The simulated access control and building systems for the worker (plan-pilot-twn §3, §4).
A SITE_PRESENCE event moves an occupant, adds an arrival or removes a departure; a SITE_SENSOR
event changes a sensor's status. Only events from the scenario player are taken (review of
Prompt 84, L5; as VIP_PROGRESS). SITE_UPDATED goes to browsers after the commit, with ids and
counts only (G-8)."""

import logging

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.twin import service

log = logging.getLogger(__name__)
SOURCE = "scenario:"  # the scenario player's events (app/modules/scenarios/player.py)
SITE = r"^[A-Z]{3}:(EMBASSY|CONSULATE|RESIDENCE|OFFICE)$"


class PresenceIn(BaseModel):
    site: str = Field(pattern=SITE)
    # A person's id (staff), or "Guard n" / "Visitor n".
    occupant: str = Field(pattern=r"^([0-9a-f-]{36}|(Guard|Visitor) [0-9]{1,3})$")
    zone: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,20}$")


class SensorIn(BaseModel):
    site: str = Field(pattern=SITE)
    code: str = Field(pattern=r"^[A-Z0-9-]{1,20}$")
    status: str = Field(pattern=r"^(OK|DEGRADED|FAULT|OFFLINE)$")
    detail: str | None = Field(default=None, min_length=1, max_length=100)


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    # As the other consumers: a publish that fails after the commit is logged, not retried.
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


def presence_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        if not event.source.startswith(SOURCE):
            log.warning("site presence from %r ignored", event.source)
            return
        try:
            p = PresenceIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("site presence refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.presence(session, p.site, p.occupant, p.zone)
            await session.commit()
        if outcome is None:
            log.warning("site presence %s %s did not apply", p.site, p.zone)
            return
        await _publish(publisher, outcome.events)

    return handle


def sensor_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        if not event.source.startswith(SOURCE):
            log.warning("site sensor from %r ignored", event.source)
            return
        try:
            s = SensorIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("site sensor refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.sensor(session, s.site, s.code, s.status, s.detail)
            await session.commit()
        if outcome is None:
            log.warning("site sensor %s %s did not apply", s.site, s.code)
            return
        await _publish(publisher, outcome.events)

    return handle
