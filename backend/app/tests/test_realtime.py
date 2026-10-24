"""WebSocket push (PLT-05): authentication, tenant scoping, expiry, latency.

The app runs under uvicorn on a random local port, against real PostgreSQL and
Redis, and a real WebSocket client connects to it.
"""

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import redis.asyncio as redis
import uvicorn
from httpx import AsyncClient
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.core import realtime
from app.core.events import Event, RedisPublisher
from app.main import app
from app.tests.auth_helpers import Idp


@pytest.fixture
async def redis_client() -> AsyncIterator[redis.Redis]:
    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.fail("REDIS_URL is not set; run `make up` and `make test`.", pytrace=False)
    c = redis.from_url(url, decode_responses=True)
    yield c
    await c.aclose()


@pytest.fixture
async def stream(redis_client: redis.Redis) -> AsyncIterator[str]:
    name = f"nexira:test:{uuid.uuid4()}"
    # The stream must exist for the hub to find its end.
    await RedisPublisher(redis_client, name).publish(Event("INIT", uuid.uuid4(), {}, "t"))
    yield name
    await redis_client.delete(name)


@pytest.fixture
async def server(
    client: AsyncClient, idp: Idp, redis_client: redis.Redis, stream: str
) -> AsyncIterator[tuple[str, realtime.RealtimeHub]]:
    """The app on a local port. `client` installs the test IdP's overrides."""
    hub = realtime.RealtimeHub(redis_client, stream)
    app.dependency_overrides[realtime.get_hub] = lambda: hub
    await idp.user("viewer", [("VIEWER", None)])
    await idp.user("norole")
    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    for _ in range(500):  # up to 5 s
        if srv.started:
            break
        await asyncio.sleep(0.01)
    port = srv.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/ws", hub
    finally:
        srv.should_exit = True
        await task
        await hub.close()


async def ready(url: str, token: str) -> ClientConnection:
    ws = await connect(url)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    assert json.loads(await asyncio.wait_for(ws.recv(), 5)) == {"type": "ready"}
    return ws


async def closed_with(ws: ClientConnection) -> int | None:
    with pytest.raises(ConnectionClosed) as info:
        await asyncio.wait_for(ws.recv(), 5)
    return info.value.rcvd.code if info.value.rcvd else None


def publisher(redis_client: redis.Redis, stream: str) -> RedisPublisher:
    return RedisPublisher(redis_client, stream)


async def test_events_reach_only_the_users_tenant_within_2_seconds(
    server: tuple[str, realtime.RealtimeHub], idp: Idp, redis_client: redis.Redis, stream: str
) -> None:
    url, hub = server
    ws = await ready(url, idp.token("viewer"))
    await hub.started()
    pub = publisher(redis_client, stream)
    incident = str(uuid.uuid4())
    sent = time.monotonic()
    await pub.publish(Event("INCIDENT_CREATED", uuid.uuid4(), {"incident_id": "other"}, "t"))
    await pub.publish(Event("RAW_SIGNAL", idp.tenant_id, {"title": "raw text"}, "t"))
    await pub.publish(Event("INCIDENT_CREATED", idp.tenant_id, {"incident_id": incident}, "t"))
    received: dict[str, Any] = json.loads(await asyncio.wait_for(ws.recv(), 2))
    assert time.monotonic() - sent < 2  # PLT-05
    assert (received["type"], received["event"], received["data"]) == (
        "event",
        "INCIDENT_CREATED",
        {"incident_id": incident},
    )
    # Nothing else: the other tenant's event and RAW_SIGNAL are not forwarded.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(ws.recv(), 0.5)
    await ws.close()


@pytest.mark.parametrize(
    ("first_message", "code"),
    [
        ({"type": "auth", "token": "not-a-jwt"}, 4401),
        ({"type": "hello"}, 4401),
        ("not json", 4401),
    ],
)
async def test_bad_authentication_is_refused(
    server: tuple[str, realtime.RealtimeHub], first_message: object, code: int
) -> None:
    url, _ = server
    async with connect(url) as ws:
        await ws.send(
            first_message if isinstance(first_message, str) else json.dumps(first_message)
        )
        assert await closed_with(ws) == code


async def test_unknown_users_and_users_without_a_role_are_refused(
    server: tuple[str, realtime.RealtimeHub], idp: Idp
) -> None:
    url, _ = server
    for sub, code in (("never-logged-in", 4401), ("norole", 4403)):
        async with connect(url) as ws:
            await ws.send(json.dumps({"type": "auth", "token": idp.token(sub)}))
            assert await closed_with(ws) == code, sub


async def test_no_authentication_in_time_closes(
    server: tuple[str, realtime.RealtimeHub], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(realtime, "AUTH_TIMEOUT_S", 0.2)
    url, _ = server
    async with connect(url) as ws:
        assert await closed_with(ws) == 4401


async def test_the_socket_closes_when_the_token_expires(
    server: tuple[str, realtime.RealtimeHub], idp: Idp
) -> None:
    url, _ = server
    ws = await ready(url, idp.token("viewer", lifetime_s=1))
    assert await closed_with(ws) == 4401


async def test_a_renewed_token_keeps_the_socket_open(
    server: tuple[str, realtime.RealtimeHub], idp: Idp, redis_client: redis.Redis, stream: str
) -> None:
    url, hub = server
    ws = await ready(url, idp.token("viewer", lifetime_s=2))
    await ws.send(json.dumps({"type": "auth", "token": idp.token("norole", lifetime_s=600)}))
    await ws.send(json.dumps({"type": "auth", "token": idp.token("viewer", lifetime_s=600)}))
    await asyncio.sleep(2.5)  # past the first token's expiry
    await hub.started()
    await publisher(redis_client, stream).publish(
        Event("EXPOSURE_COMPUTED", idp.tenant_id, {"incident_id": "x"}, "t")
    )
    received = json.loads(await asyncio.wait_for(ws.recv(), 2))
    assert received["event"] == "EXPOSURE_COMPUTED"
    await ws.close()


async def test_another_subjects_token_does_not_renew(
    server: tuple[str, realtime.RealtimeHub], idp: Idp
) -> None:
    url, _ = server
    await idp.user("viewer2", [("VIEWER", None)])
    ws = await ready(url, idp.token("viewer", lifetime_s=1))
    await ws.send(json.dumps({"type": "auth", "token": idp.token("viewer2", lifetime_s=600)}))
    assert await closed_with(ws) == 4401
