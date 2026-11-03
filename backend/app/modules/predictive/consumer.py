"""The daily snapshot for the worker (plan-pilot-prd §3): every 15 minutes it stores or refreshes
today's index for each mission of each tenant; PREDICTIVE_UPDATED (counts only) follows. And the
scenario player's MISSION_EVENT, which adds a calendar entry (§7, §10)."""

import logging
import uuid

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.predictive import service

log = logging.getLogger(__name__)
SNAPSHOT_EVERY_S = 900


async def tick(engine: AsyncEngine, tenant_id: uuid.UUID, publisher: Publisher) -> int:
    async with tenant_session(tenant_id, engine) as session:
        written = await service.snapshot(session)
        await session.commit()
    if written:
        try:
            await publisher.publish(service.updated_event(tenant_id, written))
        except Exception:
            log.exception("publishing PREDICTIVE_UPDATED failed after commit")
    return written


class EventPayload(BaseModel):
    """MISSION_EVENT from the scenario player (plan-pilot-prd §7, §10): dates as offsets from
    the day it is played."""

    mission: str = Field(pattern=r"^[A-Z]{3}$")
    kind: str = Field(pattern=r"^(RALLY|ELECTION|HOLIDAY|SUMMIT|SPORTS|OTHER)$")
    title: str = Field(min_length=1, max_length=200)
    starts_in_days: int = Field(ge=0, le=60)
    days: int = Field(default=1, ge=1, le=14)
    weight: int = Field(ge=1, le=30)
    place_label: str | None = Field(default=None, min_length=1, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    attendance: int | None = Field(default=None, ge=0)


SOURCE = "scenario:"  # the scenario player's events (app/modules/scenarios/player.py)


def event_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    """Adds the entry, refreshes today's index, and publishes MISSION_EVENT_ADDED (for the
    Forecast agent) and PREDICTIVE_UPDATED. Only events from the scenario player are taken."""

    async def handle(event: Event) -> None:
        if not event.source.startswith(SOURCE):
            log.warning("mission event from %r ignored", event.source)
            return
        try:
            p = EventPayload.model_validate(event.payload)
        except ValidationError as e:
            log.warning("mission event refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            today = await service.db_today(session)
            added = await service.add_event(session, _event_in(p), today)
            written = await service.snapshot(session) if added else 0
            await session.commit()
        if added is None:
            log.info("mission event %s %r: already there, or no such mission", p.mission, p.title)
            return
        for out in (
            service.event_added(event.tenant_id, *added),
            service.updated_event(event.tenant_id, written),
        ):
            try:
                await publisher.publish(out)
            except Exception:
                log.exception("publishing %s failed after commit", out.type)

    return handle


def _event_in(p: EventPayload) -> service.EventIn:
    return service.EventIn(
        mission_code=p.mission,
        kind=p.kind,
        title=p.title,
        starts_in_days=p.starts_in_days,
        weight=p.weight,
        days=p.days,
        place_label=p.place_label,
        lat=p.lat,
        lon=p.lon,
        attendance=p.attendance,
    )
