"""The simulated advisory feed for the worker (plan-pilot-hl §2): a HEALTH_ADVISORY event
(a demo scene) creates or updates an advisory in one transaction; HEALTH_ADVISORY_UPDATED
goes to browsers and the agents after the commit. A real feed adapter later calls the
same ingest() (HLT-05)."""

import logging

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.health_intel import service
from app.modules.tenancy.service import Actor

log = logging.getLogger(__name__)
FEED = Actor(type="SYSTEM", id="health.feed")


def advisory_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        try:
            bulletin = service.AdvisoryIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("health bulletin refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            result = await service.ingest(session, bulletin, FEED)
            await session.commit()
        if result is None:
            return
        # As the other consumers: a publish that fails after the commit is logged, not
        # retried, since a redelivered bulletin changes nothing and publishes nothing. The
        # advisory is right on the screen; only that bulletin's proposal may be missed, and
        # a person can still send the advisory (review of Prompt 61, M4).
        try:
            await publisher.publish(service.advisory_event(result))
        except Exception:
            log.exception("publishing HEALTH_ADVISORY_UPDATED failed after commit")

    return handle
