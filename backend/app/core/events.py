"""Internal events on Redis Streams.

Every event carries its tenant_id, so consumers and background workers can set
the tenant for each event without reading the tenant table (plan G-01).
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol, cast

import redis.asyncio as redis
from redis.exceptions import ResponseError

from app.core.config import get_settings

log = logging.getLogger(__name__)

STREAM = "nexira:events"
MAX_LEN = 100_000  # approximate trim; streams are a transport, not the record


@dataclass(frozen=True)
class Event:
    type: str  # RAW_SIGNAL, CHECKIN_RESPONSE, CHECKIN_CLOCK, SCENE_START, ...
    tenant_id: uuid.UUID
    payload: dict[str, Any]
    source: str  # e.g. "scenario:NBO-CIVIL-UNREST:<run id>"
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_fields(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "type": self.type,
            "tenant_id": str(self.tenant_id),
            "source": self.source,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": json.dumps(self.payload, default=str),
        }

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "Event":
        return cls(
            id=uuid.UUID(fields["id"]),
            type=fields["type"],
            tenant_id=uuid.UUID(fields["tenant_id"]),
            source=fields["source"],
            occurred_at=datetime.fromisoformat(fields["occurred_at"]),
            payload=json.loads(fields["payload"]),
        )


class Publisher(Protocol):
    async def publish(self, event: Event) -> None: ...


class RedisPublisher:
    def __init__(self, client: redis.Redis, stream: str = STREAM) -> None:
        self._client = client
        self._stream = stream

    async def publish(self, event: Event) -> None:
        await self._client.xadd(
            self._stream,
            event.to_fields(),  # type: ignore[arg-type]  # redis-py's mapping type is too narrow
            maxlen=MAX_LEN,
            approximate=True,
        )


@lru_cache
def get_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis_url, decode_responses=True)


def get_publisher() -> Publisher:
    """FastAPI dependency; tests override it."""
    return RedisPublisher(get_redis())


Handler = Callable[[Event], Awaitable[None]]


class StreamConsumer:
    """Reads the stream as one member of a consumer group and dispatches by type.

    - The group starts at the end of the stream ("$"): events published before the
      group first existed are not replayed (a reset demo database must not get old
      signals back). After that, Redis tracks the group's position.
    - An event is acknowledged after its handler returns, or when no handler is
      registered for its type. A handler that raises leaves the event pending; it
      is retried, and dropped (logged) after max_attempts.
    - Handlers must be idempotent: a retry or restart can deliver an event twice.
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        group: str,
        consumer: str,
        handlers: Mapping[str, Handler],
        stream: str = STREAM,
        block_ms: int = 1_000,
        max_attempts: int = 5,
    ) -> None:
        self._client = client
        self._group = group
        self._consumer = consumer
        self._handlers = dict(handlers)
        self._stream = stream
        self._block_ms = block_ms
        self._max_attempts = max_attempts
        self._attempts: dict[str, int] = {}
        self._pending_first = True  # on start and after a failure, retry our pending events

    async def ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(self._stream, self._group, id="$", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run(self) -> None:
        await self.ensure_group()
        while True:
            await self.process_batch()
            if self._pending_first:
                await asyncio.sleep(1)  # back off before retrying failed events

    async def process_batch(self, count: int = 100) -> int:
        """Read and handle one batch; return how many events were handled."""
        start = "0" if self._pending_first else ">"
        response = await self._client.xreadgroup(  # [(stream, [(id, fields), ...])]
            self._group,
            self._consumer,
            {self._stream: start},
            count=count,
            block=None if start == "0" else self._block_ms,
        )
        streams = cast(list[tuple[str, list[tuple[str, dict[str, str] | None]]]], response or [])
        entries = [entry for _stream, batch in streams for entry in batch]
        if start == "0" and not entries:
            self._pending_first = False
        handled = 0
        for entry_id, fields in entries:
            if await self._handle(entry_id, fields):
                handled += 1
        return handled

    async def _handle(self, entry_id: str, fields: Mapping[str, str] | None) -> bool:
        if not fields:  # trimmed while pending
            await self._ack(entry_id)
            return False
        event = Event.from_fields(dict(fields))
        handler = self._handlers.get(event.type)
        if handler is None:
            await self._ack(entry_id)
            return False
        try:
            await handler(event)
        except Exception:
            attempts = self._attempts.get(entry_id, 0) + 1
            self._attempts[entry_id] = attempts
            if attempts >= self._max_attempts:
                log.exception("dropping %s %s after %d attempts", event.type, entry_id, attempts)
                await self._ack(entry_id)
            else:
                log.exception("%s %s failed (attempt %d)", event.type, entry_id, attempts)
                self._pending_first = True
            return False
        await self._ack(entry_id)
        return True

    async def _ack(self, entry_id: str) -> None:
        self._attempts.pop(entry_id, None)
        await self._client.xack(self._stream, self._group, entry_id)
