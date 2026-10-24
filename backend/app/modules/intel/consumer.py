"""RAW_SIGNAL handler for the stream consumer (app/workers).

One event, one transaction: the signal, its normalisation, the fusion and their
audit rows commit together. INCIDENT_CREATED / INCIDENT_UPDATED is published
after the commit, so a listener never sees an incident that is not stored yet.
"""

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
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
