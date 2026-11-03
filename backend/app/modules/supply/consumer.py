"""The simulated logistics feed and supplier notices for the worker (plan-pilot-sup §3). A
SUPPLY_ROUTE event reports a route's status; a SUPPLY_SUPPLIER event a supplier's. Only events
from the scenario player are taken (as SITE_SENSOR). SUPPLY_UPDATED goes to browsers after the
commit, with ids and statuses only (G-8)."""

import logging

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.supply import service

log = logging.getLogger(__name__)
SOURCE = "scenario:"  # the scenario player's events (app/modules/scenarios/player.py)


class RouteIn(BaseModel):
    route: str = Field(pattern=r"^R-[A-Z]{3}-[0-9]{1,2}$")
    status: str = Field(pattern=r"^(OPEN|RESTRICTED|DELAYED|BLOCKED)$")
    detail: str | None = Field(default=None, min_length=1, max_length=300)


class SupplierIn(BaseModel):
    supplier: str = Field(pattern=r"^SUP-[0-9]{3}$")
    status: str = Field(pattern=r"^(NORMAL|WATCH|DELAYED|AT_RISK)$")
    detail: str | None = Field(default=None, min_length=1, max_length=300)


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    # As the other consumers: a publish that fails after the commit is logged, not retried.
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


def route_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        if not event.source.startswith(SOURCE):
            log.warning("supply route report from %r ignored", event.source)
            return
        try:
            r = RouteIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("supply route report refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.route_status(session, r.route, r.status, r.detail)
            await session.commit()
        if outcome is None:
            log.warning("supply route report for unknown route %s", r.route)
            return
        await _publish(publisher, outcome.events)

    return handle


def supplier_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        if not event.source.startswith(SOURCE):
            log.warning("supplier notice from %r ignored", event.source)
            return
        try:
            s = SupplierIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("supplier notice refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            outcome = await service.supplier_status(session, s.supplier, s.status, s.detail)
            await session.commit()
        if outcome is None:
            log.warning("supplier notice for unknown supplier %s", s.supplier)
            return
        await _publish(publisher, outcome.events)

    return handle
