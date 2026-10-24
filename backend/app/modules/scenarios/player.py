"""Scenario player (PLT-06): replays a scenario's events onto the event stream at
their offsets, scene by scene.

- play:  play the rest of the current scene from where it stopped.
- pause: stop and remember the position, including time already elapsed.
- next:  move to the next scene and play it.
- reset: back to scene 0, nothing played (scenario state only; D-21).

The player only publishes events. It never writes business tables: signals and
check-in responses go through the same ingestion paths as real data.

Time comes from a Clock, so tests replay with a fake clock (app/tests/fakes.py)
and assert exact timing.
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from app.core.events import Event, Publisher


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def now(self) -> datetime: ...
    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True)
class ScenarioEvent:
    id: uuid.UUID
    scene_no: int
    offset_ms: int
    event_type: str
    payload: dict[str, Any]


class Status(StrEnum):  # matches scenario_run.status
    IDLE = "IDLE"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"


SceneDone = Callable[[uuid.UUID, int], Awaitable[None]]  # (run id, scene no)


class Player:
    def __init__(
        self,
        *,
        code: str,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        events: list[ScenarioEvent],
        publisher: Publisher,
        clock: Clock | None = None,
        current_scene: int = 0,
        on_scene_done: SceneDone | None = None,
    ) -> None:
        self.code = code
        self.tenant_id = tenant_id
        self.run_id = run_id
        # A scene's SCENE_START marker always comes first; then offset, then a stable id.
        self._events = sorted(
            events,
            key=lambda e: (e.scene_no, e.offset_ms, e.event_type != "SCENE_START", str(e.id)),
        )
        self.last_scene = max((e.scene_no for e in self._events), default=0)
        self._publisher = publisher
        self._clock = clock or SystemClock()
        self._on_scene_done = on_scene_done
        self.current_scene = current_scene
        self.status = Status.IDLE
        self.position = 0  # index of the next event within the current scene
        self._elapsed_s = 0.0  # scene time already played before the last pause
        self._task: asyncio.Task[None] | None = None

    # --- queries -------------------------------------------------------------------------

    def scene_events(self, scene: int | None = None) -> list[ScenarioEvent]:
        scene = self.current_scene if scene is None else scene
        return [e for e in self._events if e.scene_no == scene]

    @property
    def scene_complete(self) -> bool:
        return self.position >= len(self.scene_events())

    # --- commands --------------------------------------------------------------------------

    async def play(self) -> None:
        if self.status in (Status.PLAYING, Status.FINISHED) or self.scene_complete:
            return
        self.status = Status.PLAYING
        self._task = asyncio.create_task(self._run_scene(), name=f"scenario:{self.code}")

    async def pause(self) -> None:
        if self.status is not Status.PLAYING:
            return
        await self._cancel()
        self.status = Status.PAUSED

    async def next(self) -> None:
        await self._cancel()
        if self.current_scene >= self.last_scene:
            self.status = Status.FINISHED
            return
        self.current_scene += 1
        self.position = 0
        self._elapsed_s = 0.0
        self.status = Status.PAUSED
        await self.play()

    async def reset(self, run_id: uuid.UUID) -> None:
        await self._cancel()
        self.run_id = run_id
        self.current_scene = 0
        self.position = 0
        self._elapsed_s = 0.0
        self.status = Status.IDLE

    async def wait(self) -> None:
        """Wait until the current scene has finished playing (tests, scripts)."""
        if self._task is not None:
            await asyncio.shield(self._task)

    # --- internals ---------------------------------------------------------------------------

    async def _cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run_scene(self) -> None:
        events = self.scene_events()
        started = self._clock.monotonic() - self._elapsed_s
        try:
            while self.position < len(events):
                event = events[self.position]
                due = started + event.offset_ms / 1000
                delay = due - self._clock.monotonic()
                if delay > 0:
                    await self._clock.sleep(delay)
                await self._publisher.publish(self._envelope(event))
                self.position += 1
        finally:
            self._elapsed_s = self._clock.monotonic() - started
        self.status = Status.PAUSED
        if self._on_scene_done is not None:
            await self._on_scene_done(self.run_id, self.current_scene)

    def _envelope(self, event: ScenarioEvent) -> Event:
        payload = dict(event.payload)
        if event.event_type == "RAW_SIGNAL":
            # A fresh external id per run, so a reset scenario produces new signals
            # instead of being dropped as duplicates (raw_signal is unique on it).
            payload["external_id"] = f"{payload['external_id']}:{self.run_id}"
            payload.setdefault("occurred_at", self._clock.now().isoformat())
        return Event(
            type=event.event_type,
            tenant_id=self.tenant_id,
            payload=payload,
            source=f"scenario:{self.code}:{self.run_id}",
            occurred_at=self._clock.now(),
        )
