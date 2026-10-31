"""Hazard handlers for the worker (plan-pilot-hz §4, §5).

- DEMO_CLOCK (a demo scene): moves the hazard clock on, then starts the armed runs that
  are now due, in the same transaction.
- tick(): every 30 s, starts the armed runs whose time has come (or disarms those whose
  incident is no longer ACTIVE). It also runs at worker start, so a run that came due
  while the worker was down starts on the first pass, late (the timeline says by how much).
Events are published after the commit; the playbook engine then runs the steps.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.hazards import clock
from app.modules.playbooks import service as playbooks
from app.modules.playbooks.models import PlaybookRun

log = logging.getLogger(__name__)


def _events(runs: list[PlaybookRun]) -> list[Event]:
    return [
        playbooks.run_started_event(r) if r.status == "RUNNING" else playbooks.run_disarmed_event(r)
        for r in runs
    ]


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


async def _due(session: AsyncSession) -> list[Event]:
    return _events(await playbooks.start_due(session))


async def tick(engine: AsyncEngine, tenant_id: uuid.UUID, publisher: Publisher) -> int:
    """One pass for a tenant; returns how many armed runs started or were disarmed."""
    async with tenant_session(tenant_id, engine) as session:
        events = await _due(session)
        await session.commit()
    await _publish(publisher, events)
    return len(events)


def clock_handler(engine: AsyncEngine, publisher: Publisher) -> Handler:
    async def handle(event: Event) -> None:
        async with tenant_session(event.tenant_id, engine) as session:
            hours = await clock.advance(session, event)
            events = await _due(session) if hours else []
            await session.commit()
        if hours:
            events.insert(0, clock.demo_clock_event(event.tenant_id, hours))
        await _publish(publisher, events)

    return handle
