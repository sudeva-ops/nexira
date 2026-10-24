"""Intel handlers for the stream consumers (app/workers).

One event, one transaction: a signal with its normalisation and fusion, or an
incident's exposure, commits together with its audit rows. The follow-up event
(INCIDENT_CREATED / INCIDENT_UPDATED, EXPOSURE_COMPUTED) is published after the
commit, so a listener never sees state that is not stored yet.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.intel import exposure
from app.modules.intel.service import incident_event, ingest_signal


def raw_signal_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        # The tenant comes from the event envelope (plan G-01); RLS scopes every read.
        async with tenant_session(event.tenant_id, engine) as session:
            ingested = await ingest_signal(session, event)
            await session.commit()
        published = incident_event(ingested, event.tenant_id)
        if published is not None:
            await publisher.publish(published)

    return handle


def exposure_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    """INCIDENT_CREATED / INCIDENT_UPDATED -> recompute exposure (INC-05)."""

    async def handle(event: Event) -> None:
        async with tenant_session(event.tenant_id, engine) as session:
            computed = await exposure.compute(session, uuid.UUID(event.payload["incident_id"]))
            await session.commit()
        if computed is not None:
            await publisher.publish(exposure.exposure_event(computed, event.tenant_id))

    return handle
