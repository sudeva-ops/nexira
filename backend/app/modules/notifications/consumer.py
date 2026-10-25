"""Notification handlers for the worker: send queued deliveries (outbox), move
receipts on, and escalate check-in non-responders."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.checkin import service as checkin
from app.modules.notifications.service import complete_campaigns, dispatch, refresh_receipts

Now = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def dispatch_all(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    publisher: Publisher,
    *,
    campaign_id: uuid.UUID | None = None,
    adapter: str = "simulated",
    now: Now = _utcnow,
) -> int:
    """Send every QUEUED delivery, one committed batch at a time. Returns the count."""
    total = 0
    while True:
        async with tenant_session(tenant_id, engine) as session:
            result = await dispatch(session, now(), campaign_id, adapter)
            await session.commit()
        for campaign in result.completed:
            await publisher.publish(checkin.updated_event(campaign, "CAMPAIGN_UPDATED"))
        sent = sum(result.sent.values())
        total += sent
        if sent == 0:
            return total


def campaign_handler(engine: AsyncEngine, publisher: Publisher, adapter: str) -> Handler:
    async def handle(event: Event) -> None:
        await dispatch_all(
            engine,
            event.tenant_id,
            publisher,
            campaign_id=uuid.UUID(event.payload["campaign_id"]),
            adapter=adapter,
        )

    return handle


async def tick(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    publisher: Publisher,
    *,
    adapter: str = "simulated",
    now: Now = _utcnow,
) -> None:
    """The periodic pass: leftover deliveries, receipts, escalations."""
    await dispatch_all(engine, tenant_id, publisher, adapter=adapter, now=now)
    async with tenant_session(tenant_id, engine) as session:
        completed = await complete_campaigns(session, now(), adapter)  # after split batches
        await refresh_receipts(session, now(), adapter)
        escalated = await checkin.escalate_due(session, now())
        await session.commit()
    for campaign in completed:
        await publisher.publish(checkin.updated_event(campaign, "CAMPAIGN_UPDATED"))
    for result in escalated:
        await publisher.publish(checkin.updated_event(result.campaign, "CHECKIN_ESCALATED"))
