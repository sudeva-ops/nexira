"""Realtime push to the browser over a WebSocket (PLT-05).

Protocol on /ws:
- The client's first message is {"type": "auth", "token": "<access token>"},
  within AUTH_TIMEOUT_S. The token is never put in the URL, so it does not end
  up in proxy or server logs. It is validated exactly as for HTTP requests
  (security.principal_from_token), and the user needs an active account and a
  role. The client sends a new auth message whenever it refreshes its token;
  the subject and tenant must stay the same.
- The server answers {"type": "ready"}, then sends
  {"type": "event", "event": <type>, "id", "occurred_at", "data"} for each
  forwarded event of the user's tenant.
- Close codes: 4401 not authenticated or token expired, 4403 no role,
  4408 the client could not keep up.

Fan-out: one Redis reader per API process reads the stream from its end, with
no consumer group, so every API process sees every event. An event goes only to
sockets whose user belongs to the event's tenant_id. Only FORWARDED types are
sent; their payloads carry ids, references and counts, not personal data or raw
provider text. Clients refetch what they show through the REST API, which
applies RLS and role checks as usual.
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Annotated, Any, cast

import redis.asyncio as redis
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.approvals import user_has_role
from app.core.config import Settings, get_settings
from app.core.db import engine_dependency, tenant_session
from app.core.events import STREAM, Event, get_redis
from app.core.security import (
    InvalidCredentialsError,
    JwksCache,
    Principal,
    active_user,
    get_jwks,
    principal_from_token,
)
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)

AUTH_TIMEOUT_S = 10
QUEUE_SIZE = 1_000
FORWARDED = frozenset(
    {
        "SIGNAL_INGESTED",
        "INCIDENT_CREATED",
        "INCIDENT_UPDATED",
        "INCIDENT_NOTE_ADDED",
        "EXPOSURE_COMPUTED",
        "PLAYBOOK_RUN_STARTED",
        "PLAYBOOK_RUN_UPDATED",
        "PLAYBOOK_STEP",
        "PLAYBOOK_STEP_APPROVED",
        "CAMPAIGN_QUEUED",
        "CAMPAIGN_UPDATED",
        "CHECKIN_UPDATED",
        "CHECKIN_ESCALATED",
        "PROPOSAL_CREATED",
        "PROPOSAL_UPDATED",
        "PROPOSAL_EXPIRED",  # plan G-18: a notice for holders of the open step's role
    }
)

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_TOO_SLOW = 4408

router = APIRouter()


def message(event: Event) -> dict[str, Any]:
    return {
        "type": "event",
        "event": event.type,
        "id": str(event.id),
        "occurred_at": event.occurred_at.isoformat(),
        "data": event.payload,
    }


class Subscriber:
    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(QUEUE_SIZE)
        self.overflowed = False

    def offer(self, item: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.overflowed = True  # the socket is closed; the client reconnects and refetches


class RealtimeHub:
    """Reads the event stream and hands each forwarded event to its tenant's sockets."""

    def __init__(self, client: redis.Redis | None = None, stream: str = STREAM) -> None:
        self._client = client
        self._stream = stream
        self._subscribers: dict[uuid.UUID, set[Subscriber]] = {}
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    def subscribe(self, tenant_id: uuid.UUID) -> Subscriber:
        subscriber = Subscriber(tenant_id)
        self._subscribers.setdefault(tenant_id, set()).add(subscriber)
        if self._task is None or self._task.done():
            self._ready = asyncio.Event()
            self._task = asyncio.create_task(self._read(), name="realtime-hub")
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.get(subscriber.tenant_id, set()).discard(subscriber)

    async def started(self) -> None:
        """Wait until the reader has its position in the stream (tests)."""
        await self._ready.wait()

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def dispatch(self, event: Event) -> None:
        if event.type not in FORWARDED:
            return
        item = message(event)
        for subscriber in list(self._subscribers.get(event.tenant_id, ())):
            subscriber.offer(item)

    async def _read(self) -> None:
        client = self._client or get_redis()
        # Start at the current end of the stream: a browser refetches on connect.
        last = "$"
        latest = await client.xrevrange(self._stream, count=1)
        if latest:
            last = str(latest[0][0])
        self._ready.set()
        while True:
            try:
                response = await client.xread({self._stream: last}, block=1_000, count=100)
            except redis.RedisError:
                log.exception("realtime: reading the stream failed; retrying")
                await asyncio.sleep(1)
                continue
            streams = cast(list[tuple[str, list[tuple[str, dict[str, str]]]]], response or [])
            for _stream, entries in streams:
                for entry_id, fields in entries:
                    last = entry_id
                    try:
                        event = Event.from_fields(fields)
                    except (KeyError, ValueError):
                        log.warning("realtime: skipping malformed event %s", entry_id)
                        continue
                    self.dispatch(event)


hub = RealtimeHub()


def get_hub() -> RealtimeHub:
    """FastAPI dependency; tests override it."""
    return hub


async def _authorise(
    token: object, settings: Settings, jwks: JwksCache, engine: AsyncEngine
) -> tuple[Principal | None, int]:
    if not isinstance(token, str) or not token:
        return None, CLOSE_UNAUTHENTICATED
    try:
        principal = await principal_from_token(token, settings=settings, jwks=jwks, engine=engine)
    except InvalidCredentialsError:
        return None, CLOSE_UNAUTHENTICATED
    async with tenant_session(principal.tenant_id, engine) as session:
        user = await active_user(session, principal)
        if user is None:
            return None, CLOSE_UNAUTHENTICATED
        if not await user_has_role(session, user, ROLES):
            return None, CLOSE_FORBIDDEN
    return principal, 0


@router.websocket("/ws")
async def realtime(
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings)],
    jwks: Annotated[JwksCache, Depends(get_jwks)],
    engine: Annotated[AsyncEngine, Depends(engine_dependency)],
    events: Annotated[RealtimeHub, Depends(get_hub)],
) -> None:
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_S)
    except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError, KeyError):
        await _close(websocket, CLOSE_UNAUTHENTICATED, "authenticate first")
        return
    token = first.get("token") if isinstance(first, dict) and first.get("type") == "auth" else None
    principal, code = await _authorise(token, settings, jwks, engine)
    if principal is None:
        await _close(
            websocket, code, "not authenticated" if code == CLOSE_UNAUTHENTICATED else "forbidden"
        )
        return

    session = _Session(principal)
    subscriber = events.subscribe(principal.tenant_id)
    try:
        await websocket.send_json({"type": "ready"})
        async with asyncio.TaskGroup() as tasks:
            sender = tasks.create_task(_send(websocket, subscriber, session))
            tasks.create_task(_receive(websocket, session, settings, jwks, engine, sender))
    except* WebSocketDisconnect:
        pass
    finally:
        events.unsubscribe(subscriber)


class _Session:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal  # replaced when the client renews its token


async def _send(websocket: WebSocket, subscriber: Subscriber, session: _Session) -> None:
    while True:
        remaining = session.principal.expires_at - time.time()
        if remaining <= 0:
            code, reason = CLOSE_UNAUTHENTICATED, "token expired"
            break
        try:
            item = await asyncio.wait_for(subscriber.queue.get(), timeout=min(remaining, 5))
        except TimeoutError:
            continue
        if subscriber.overflowed:
            code, reason = CLOSE_TOO_SLOW, "too slow"
            break
        await websocket.send_json(item)
    await _close(websocket, code, reason)
    raise WebSocketDisconnect(code)


async def _receive(
    websocket: WebSocket,
    session: _Session,
    settings: Settings,
    jwks: JwksCache,
    engine: AsyncEngine,
    sender: asyncio.Task[None],
) -> None:
    """Token renewals. Anything else from the client is ignored."""
    while True:
        try:
            msg = await websocket.receive_json()
        except json.JSONDecodeError:
            continue
        except WebSocketDisconnect:
            sender.cancel()
            raise
        if not isinstance(msg, dict) or msg.get("type") != "auth":
            continue
        renewed, _code = await _authorise(msg.get("token"), settings, jwks, engine)
        if (
            renewed is None
            or renewed.subject != session.principal.subject
            or renewed.tenant_id != session.principal.tenant_id
        ):
            continue  # keep the current token; it expires on its own schedule
        session.principal = renewed


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.close(code=code, reason=reason)
