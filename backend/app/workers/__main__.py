import asyncio
import logging
import socket

from app.core.db import get_engine, verify_connection_role
from app.core.events import RedisPublisher, StreamConsumer, get_redis
from app.modules.intel.consumer import exposure_handler, raw_signal_handler

log = logging.getLogger("app.workers")


async def main() -> None:
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: same guard as the API
    client = get_redis()
    publisher = RedisPublisher(client)
    name = socket.gethostname()
    on_incident = exposure_handler(engine, publisher)
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
    ]
    log.info("consumers started: intel, exposure")
    try:
        async with asyncio.TaskGroup() as tasks:
            for consumer in consumers:
                tasks.create_task(consumer.run())
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
