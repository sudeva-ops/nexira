import asyncio
import logging
import socket

from app.core.db import get_engine, verify_connection_role
from app.core.events import RedisPublisher, StreamConsumer, get_redis
from app.modules.intel.consumer import raw_signal_handler

log = logging.getLogger("app.workers")


async def main() -> None:
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: same guard as the API
    client = get_redis()
    consumer = StreamConsumer(
        client,
        group="intel",
        consumer=socket.gethostname(),
        handlers={"RAW_SIGNAL": raw_signal_handler(engine, RedisPublisher(client))},
    )
    log.info("intel consumer started")
    try:
        await consumer.run()
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
