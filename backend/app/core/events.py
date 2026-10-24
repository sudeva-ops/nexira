"""Internal events on Redis Streams.

Every event carries its tenant_id, so consumers and background workers can set
the tenant for each event without reading the tenant table (plan G-01).
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

import redis.asyncio as redis

from app.core.config import get_settings

STREAM = "nexira:events"
MAX_LEN = 100_000  # approximate trim; streams are a transport, not the record


@dataclass(frozen=True)
class Event:
    type: str  # RAW_SIGNAL, CHECKIN_RESPONSE, SCENE_START, SCENARIO_SETTINGS, ...
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
