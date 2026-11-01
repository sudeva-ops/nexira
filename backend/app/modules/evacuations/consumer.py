"""The simulated muster-point scanner and evacuation progress for the worker (plan-pilot-ev
§5, §6, §11; G-2, G-9). A MUSTER_SCAN event checks in the next people expected at the
mission's ACTIVE evacuation; an EVACUATION_PROGRESS event moves its sequence one step. Both
only act on an evacuation two people activated; they never activate, stand down or approve
anything (§53 Q10). EVACUATION_UPDATED goes to browsers after the commit."""

import logging

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.evacuations import service

log = logging.getLogger(__name__)


class ScanIn(BaseModel):
    mission_code: str = Field(pattern=r"^[A-Z]{3}$")
    count: int = Field(ge=1, le=50)


class ProgressIn(BaseModel):
    mission_code: str = Field(pattern=r"^[A-Z]{3}$")
    step: int = Field(ge=4, le=6)  # convoy, flight, arrival (assembly follows the check-ins)


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    # As the other consumers: a publish that fails after the commit is logged, not retried;
    # the screen refetches on the next event.
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


def scan_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        try:
            scan = ScanIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("muster scan refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.scan(session, scan.mission_code, scan.count)
            await session.commit()
        if outcome is not None:
            await _publish(publisher, outcome.events)

    return handle


def progress_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        try:
            progress = ProgressIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("evacuation progress refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.progress(session, progress.mission_code, progress.step)
            await session.commit()
        if outcome is not None:
            await _publish(publisher, outcome.events)

    return handle
