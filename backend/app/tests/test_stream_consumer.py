"""Stream consumer and the RAW_SIGNAL handler, on real Redis and PostgreSQL."""

import os
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, RedisPublisher, StreamConsumer
from app.modules.intel.consumer import raw_signal_handler
from app.modules.intel.models import Incident
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import intel_tenant, signal


@pytest.fixture
async def client() -> AsyncIterator[redis.Redis]:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.fail("REDIS_URL is not set; run `make up` and `make test`.", pytrace=False)
    c = redis.from_url(url, decode_responses=True)
    yield c
    await c.aclose()


@pytest.fixture
async def tenant(db: DbUrls, api_engine: AsyncEngine) -> uuid.UUID:
    return await intel_tenant(db, api_engine)


@pytest.fixture
async def stream(client: redis.Redis) -> AsyncIterator[str]:
    name = f"nexira:test:{uuid.uuid4()}"
    yield name
    await client.delete(name)


def event(n: int, kind: str = "PING") -> Event:
    return Event(type=kind, tenant_id=uuid.uuid4(), payload={"n": n}, source="test")


async def pending(client: redis.Redis, stream: str, group: str) -> int:
    info = await client.xpending(stream, group)
    return int(info["pending"])


async def test_events_are_handled_in_order_and_acknowledged(
    client: redis.Redis, stream: str
) -> None:
    seen: list[object] = []

    async def handler(e: Event) -> None:
        seen.append(e.payload["n"])

    consumer = StreamConsumer(
        client, group="g", consumer="c1", handlers={"PING": handler}, stream=stream, block_ms=10
    )
    await consumer.ensure_group()
    publisher = RedisPublisher(client, stream)
    for n in range(3):
        await publisher.publish(event(n))
    await publisher.publish(event(9, "OTHER"))  # no handler: acknowledged and skipped
    await consumer.process_batch()  # pending of our own first (none)
    assert await consumer.process_batch() == 3
    assert seen == [0, 1, 2]
    assert await pending(client, stream, "g") == 0


async def test_the_group_starts_at_the_end_of_the_stream(client: redis.Redis, stream: str) -> None:
    publisher = RedisPublisher(client, stream)
    await publisher.publish(event(0))  # before the group exists: not replayed
    seen: list[object] = []

    async def handler(e: Event) -> None:
        seen.append(e.payload["n"])

    consumer = StreamConsumer(
        client, group="g", consumer="c1", handlers={"PING": handler}, stream=stream, block_ms=10
    )
    await consumer.ensure_group()
    await consumer.ensure_group()  # idempotent
    await publisher.publish(event(1))
    await consumer.process_batch()
    await consumer.process_batch()
    assert seen == [1]


async def test_a_failed_event_is_retried_then_dropped(client: redis.Redis, stream: str) -> None:
    calls: list[object] = []

    async def flaky(e: Event) -> None:
        calls.append(e.payload["n"])
        if len(calls) < 2:
            raise RuntimeError("database unavailable")

    async def broken(e: Event) -> None:
        raise RuntimeError("poison")

    consumer = StreamConsumer(
        client,
        group="g",
        consumer="c1",
        handlers={"PING": flaky, "POISON": broken},
        stream=stream,
        block_ms=10,
        max_attempts=3,
    )
    await consumer.ensure_group()
    publisher = RedisPublisher(client, stream)
    await publisher.publish(event(0))
    await publisher.publish(event(1, "POISON"))
    for _ in range(6):
        await consumer.process_batch()
    assert calls == [0, 0]  # failed once, then handled from the pending list
    assert await pending(client, stream, "g") == 0  # the poison event was dropped


async def test_a_restarted_consumer_handles_its_pending_events(
    client: redis.Redis, stream: str
) -> None:
    seen: list[object] = []

    async def handler(e: Event) -> None:
        seen.append(e.payload["n"])

    first = StreamConsumer(client, group="g", consumer="c1", handlers={}, stream=stream)
    await first.ensure_group()
    await RedisPublisher(client, stream).publish(event(7))
    # Read but not acknowledged, as if the process died mid-event.
    await client.xreadgroup("g", "c1", {stream: ">"}, count=10)
    assert await pending(client, stream, "g") == 1

    restarted = StreamConsumer(
        client, group="g", consumer="c1", handlers={"PING": handler}, stream=stream, block_ms=10
    )
    await restarted.process_batch()
    assert seen == [7]
    assert await pending(client, stream, "g") == 0


async def test_signal_to_fused_incident_through_the_stream(
    client: redis.Redis, stream: str, api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    """INC-01..03 end to end, and the 5 s signal-to-incident target (requirements §5)."""
    published = ListPublisher()
    consumer = StreamConsumer(
        client,
        group="intel",
        consumer="c1",
        handlers={"RAW_SIGNAL": raw_signal_handler(api_engine, published)},
        stream=stream,
        block_ms=10,
    )
    await consumer.ensure_group()
    publisher = RedisPublisher(client, stream)
    sent = [signal("DATAMINR", "High"), signal("MAX", "Level 4"), signal("RISKLINE", "Moderate")]
    started = time.monotonic()
    for e in sent:
        await publisher.publish(
            Event(type=e.type, tenant_id=tenant, payload=e.payload, source="scenario:test")
        )
    await publisher.publish(  # a redelivered copy of the first signal
        Event(type="RAW_SIGNAL", tenant_id=tenant, payload=sent[0].payload, source="x")
    )
    while len(published.events) < 6 and time.monotonic() - started < 5:
        await consumer.process_batch()
    elapsed = time.monotonic() - started

    assert [e.type for e in published.events] == [
        "SIGNAL_INGESTED",
        "INCIDENT_CREATED",
        "SIGNAL_INGESTED",
        "INCIDENT_UPDATED",
        "SIGNAL_INGESTED",
        "INCIDENT_UPDATED",
    ]
    ingested = [e.payload for e in published.events if e.type == "SIGNAL_INGESTED"]
    assert [p["outcome"] for p in ingested] == ["FUSED"] * 3
    assert all(e.tenant_id == tenant for e in published.events)
    assert published.events[-1].payload["confidence"] == 92
    assert elapsed < 5
    await consumer.process_batch()  # the duplicate: handled, nothing published
    assert len(published.events) == 6
    async with tenant_session(tenant, api_engine) as session:
        (incident,) = (await session.scalars(select(Incident))).all()
    assert str(incident.id) == published.events[1].payload["incident_id"]
    assert {p["incident_id"] for p in ingested} == {str(incident.id)}
