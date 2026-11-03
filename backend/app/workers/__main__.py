import asyncio
import logging
import socket
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.db import get_engine, verify_connection_role
from app.core.events import Publisher, RedisPublisher, StreamConsumer, get_redis
from app.modules.agents.runner import agents_handler, observed_types
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.evacuations import consumer as evacuation
from app.modules.fleet import consumer as fleet
from app.modules.hazards import consumer as hazards
from app.modules.health_intel.consumer import advisory_handler
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.notifications.consumer import campaign_handler, tick
from app.modules.partners import service as partners
from app.modules.partners.adapter import PartnerAdapter, adapter_for
from app.modules.playbooks.consumer import resume_runs, run_handler
from app.modules.predictive import consumer as predictive
from app.modules.supply import consumer as supply
from app.modules.travel import tracker
from app.modules.twin import consumer as twin
from app.modules.vip import consumer as vip
from app.modules.weather import feed as weather

RESUME_EVERY_S = 60
TICK_EVERY_S = 2  # dispatch leftovers, delivery receipts, check-in escalation
FLIGHTS_EVERY_S = 5  # the simulated flight tracker (D-33)
WEATHER_EVERY_S = 15 * 60  # the simulated weather feed (WX §28 Q2)
PARTNERS_EVERY_S = 2  # the simulated partners answer requests (AS-04, plan G-8)
ARMED_EVERY_S = 30  # armed playbook runs that are due (HZ-05, plan-pilot-hz §4)

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


async def flights_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID]
) -> None:
    while True:
        for tenant_id in tenant_ids:
            try:
                await tracker.tick(engine, tenant_id, publisher)
            except Exception:
                log.exception("flight tracker tick failed for %s", tenant_id)
        await asyncio.sleep(FLIGHTS_EVERY_S)


async def weather_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID]
) -> None:
    """From start, so every mission has conditions as soon as the worker runs."""
    while True:
        for tenant_id in tenant_ids:
            try:
                await weather.tick(engine, tenant_id, publisher)
            except Exception:
                log.exception("weather tick failed for %s", tenant_id)
        await asyncio.sleep(WEATHER_EVERY_S)


async def predictive_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID]
) -> None:
    """From start, so every mission has today's risk index as soon as the worker runs (D-46)."""
    while True:
        for tenant_id in tenant_ids:
            try:
                await predictive.tick(engine, tenant_id, publisher)
            except Exception:
                log.exception("risk index snapshot failed for %s", tenant_id)
        await asyncio.sleep(predictive.SNAPSHOT_EVERY_S)


async def partners_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID], adapter: PartnerAdapter
) -> None:
    while True:
        for tenant_id in tenant_ids:
            try:
                await partners.tick(engine, tenant_id, publisher, adapter)
            except Exception:
                log.exception("partner tick failed for %s", tenant_id)
        await asyncio.sleep(PARTNERS_EVERY_S)


async def armed_loop(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID]
) -> None:
    """From start, so a run that came due while the worker was down starts at once."""
    while True:
        for tenant_id in tenant_ids:
            try:
                started = await hazards.tick(engine, tenant_id, publisher)
                if started:
                    log.info("armed playbook runs started or disarmed: %d", started)
            except Exception:
                log.exception("armed runs tick failed for %s", tenant_id)
        await asyncio.sleep(ARMED_EVERY_S)


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
    partner_adapter = adapter_for(settings.partner_adapter)  # D-36: simulated only
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
            group="flights",
            consumer=name,
            handlers={"FLIGHT_FEED": tracker.feed_handler(engine, publisher)},
        ),
        StreamConsumer(
            client,
            group="weather",
            consumer=name,
            handlers={"WEATHER_FEED": weather.feed_handler(engine, publisher)},
        ),
        StreamConsumer(
            client,
            group="checkin",
            consumer=name,
            handlers={
                "CHECKIN_RESPONSE": response_handler(engine, publisher),
                "CHECKIN_CLOCK": clock_handler(engine, publisher),
            },
        ),
        StreamConsumer(
            client,
            group="hazards",
            consumer=name,
            handlers={"DEMO_CLOCK": hazards.clock_handler(engine, publisher)},
        ),
        StreamConsumer(
            client,
            group="health",
            consumer=name,
            handlers={"HEALTH_ADVISORY": advisory_handler(engine, publisher)},
        ),
        StreamConsumer(
            client,
            group="evacuation",
            consumer=name,
            handlers={
                "MUSTER_SCAN": evacuation.scan_handler(engine, publisher),
                "EVACUATION_PROGRESS": evacuation.progress_handler(engine, publisher),
            },
        ),
        StreamConsumer(
            client,
            group="fleet",
            consumer=name,
            handlers={
                "VEHICLE_POSITION": fleet.position_handler(engine, publisher),
                "WORKSHOP_DONE": fleet.workshop_handler(engine, publisher),
            },
        ),
        StreamConsumer(
            client,
            group="vip",
            consumer=name,
            handlers={"VIP_PROGRESS": vip.progress_handler(engine)},
        ),
        StreamConsumer(
            client,
            group="twin",
            consumer=name,
            handlers={
                "SITE_PRESENCE": twin.presence_handler(engine, publisher),
                "SITE_SENSOR": twin.sensor_handler(engine, publisher),
            },
        ),
        StreamConsumer(
            client,
            group="predictive",
            consumer=name,
            handlers={"MISSION_EVENT": predictive.event_handler(engine, publisher)},
        ),
        StreamConsumer(
            client,
            group="supply",
            consumer=name,
            handlers={
                "SUPPLY_ROUTE": supply.route_handler(engine, publisher),
                "SUPPLY_SUPPLIER": supply.supplier_handler(engine, publisher),
            },
        ),
    ]
    log.info(
        "consumers started: intel, exposure, playbooks, notifications, agents, flights, weather, "
        "checkin, hazards, health, evacuation, fleet, vip, twin, supply, predictive"
    )
    try:
        async with asyncio.TaskGroup() as tasks:
            for consumer in consumers:
                tasks.create_task(consumer.run())
            tasks.create_task(
                resume_loop(engine, publisher, tenant_ids, settings.playbook_step_delay_s)
            )
            tasks.create_task(tick_loop(engine, publisher, tenant_ids, settings.channel_adapter))
            tasks.create_task(flights_loop(engine, publisher, tenant_ids))
            tasks.create_task(weather_loop(engine, publisher, tenant_ids))
            tasks.create_task(predictive_loop(engine, publisher, tenant_ids))
            tasks.create_task(partners_loop(engine, publisher, tenant_ids, partner_adapter))
            tasks.create_task(armed_loop(engine, publisher, tenant_ids))
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
