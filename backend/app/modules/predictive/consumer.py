"""The daily snapshot for the worker (plan-pilot-prd §3): every 15 minutes it stores or refreshes
today's index for each mission of each tenant; PREDICTIVE_UPDATED (counts only) follows."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Publisher
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
