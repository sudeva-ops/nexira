import asyncio
import logging
import socket
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.db import get_engine, verify_connection_role
from app.core.events import Publisher, RedisPublisher, StreamConsumer, get_redis
from app.modules.agents.runner import agents_handler, observed_types
from app.modules.checkin.consumer import response_handler
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.notifications.consumer import campaign_handler, tick
from app.modules.playbooks.consumer import resume_runs, run_handler

RESUME_EVERY_S = 60
TICK_EVERY_S = 2  # dispatch leftovers, delivery receipts, check-in escalation

log = logging.getLogger("app.workers")


async def resume_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID], delay: float
) -> None:
    """Continue RUNNING playbook runs at start and then periodically, in case an
    event was lost (plan G-01: tenants from WORKER_TENANT_IDS)."""
    while True:
        try:
            resumed = await resume_runs(engine, publisher, tenant_ids, delay)
            if resumed:
                log.info("resumed %d playbook runs", resumed)
        except Exception:
            log.exception("resuming playbook runs failed")
        await asyncio.sleep(RESUME_EVERY_S)


async def tick_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID], adapter: str
) -> None:
    while True:
        for tenant_id in tenant_ids:
            try:
                await tick(engine, tenant_id, publisher, adapter=adapter)
            except Exception:
                log.exception("notifications tick failed for %s", tenant_id)
        await asyncio.sleep(TICK_EVERY_S)


async def main() -> None:
    settings = get_settings()
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: same guard as the API
    client = get_redis()
    publisher = RedisPublisher(client)
    name = socket.gethostname()
    on_incident = exposure_handler(engine, publisher)
    on_run = run_handler(engine, publisher, settings.playbook_step_delay_s)
    tenant_ids = [uuid.UUID(t) for t in settings.worker_tenant_ids]
    # One consumer group per concern, so each keeps its own position in the stream.
    consumers = [
        StreamConsumer(
            client,
            group="intel",
            consumer=name,
            handlers={"RAW_SIGNAL": raw_signal_handler(engine, publisher)},
        ),
        StreamConsumer(
            client,
            group="exposure",
            consumer=name,
            handlers={"INCIDENT_CREATED": on_incident, "INCIDENT_UPDATED": on_incident},
        ),
        StreamConsumer(
            client,
            group="playbooks",
            consumer=name,
            handlers={"PLAYBOOK_RUN_STARTED": on_run, "PLAYBOOK_STEP_APPROVED": on_run},
        ),
        StreamConsumer(
            client,
            group="notifications",
            consumer=name,
            handlers={
                "CAMPAIGN_QUEUED": campaign_handler(engine, publisher, settings.channel_adapter)
            },
        ),
        StreamConsumer(
            client,
            group="agents",
            consumer=name,
            handlers=dict.fromkeys(
                observed_types(), agents_handler(engine, publisher, settings.undo_window_s)
            ),
        ),
        StreamConsumer(
            client,
            group="checkin",
            consumer=name,
            handlers={"CHECKIN_RESPONSE": response_handler(engine, publisher)},
        ),
    ]
    log.info("consumers started: intel, exposure, playbooks, notifications, agents, checkin")
    try:
        async with asyncio.TaskGroup() as tasks:
            for consumer in consumers:
                tasks.create_task(consumer.run())
            tasks.create_task(
                resume_loop(engine, publisher, tenant_ids, settings.playbook_step_delay_s)
            )
            tasks.create_task(tick_loop(engine, publisher, tenant_ids, settings.channel_adapter))
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
