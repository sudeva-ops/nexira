"""Event envelope and the Redis Streams publisher (real Redis from `make up`)."""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import redis.asyncio as redis

from app.core.events import Event, RedisPublisher


def test_envelope_round_trip() -> None:
    event = Event(type="RAW_SIGNAL", tenant_id=uuid.uuid4(), payload={"a": [1, "x"]}, source="t")
    assert Event.from_fields(event.to_fields()) == event


@pytest.fixture
async def client() -> AsyncIterator[redis.Redis]:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.fail("REDIS_URL is not set; run `make up` and `make test`.", pytrace=False)
    c = redis.from_url(url, decode_responses=True)
    yield c
    await c.aclose()


async def test_publisher_appends_to_the_stream_in_order(client: redis.Redis) -> None:
    stream = f"nexira:test:{uuid.uuid4()}"
    publisher = RedisPublisher(client, stream)
    tenant = uuid.uuid4()
    sent = [
        Event(type="RAW_SIGNAL", tenant_id=tenant, payload={"n": n}, source="test")
        for n in range(3)
    ]
    try:
        for event in sent:
            await publisher.publish(event)
        entries = await client.xrange(stream)
    finally:
        await client.delete(stream)
    received = [
        Event.from_fields({str(k): str(v) for k, v in fields.items()})
        for _id, fields in entries or []
        if fields
    ]
    assert received == sent
