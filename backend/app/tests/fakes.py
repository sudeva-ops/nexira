"""Test doubles shared by backend and simulator tests."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.core.events import Event


class FakeClock:
    """Virtual time. sleep() waits until the test calls advance() past its deadline,
    so tests decide exactly when time moves and can pause at any moment."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = 0.0
        self._start = start or datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []
        self._n = 0

    def monotonic(self) -> float:
        return self._t

    def now(self) -> datetime:
        return self._start + timedelta(seconds=self._t)

    async def sleep(self, seconds: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._n += 1
        self._sleepers.append((self._t + seconds, self._n, future))
        await future

    async def advance(self, seconds: float) -> None:
        """Move time forward, waking each sleeper at its own deadline, in order."""
        target = self._t + seconds
        await _settle()
        while True:
            live = sorted(s for s in self._sleepers if not s[2].done())
            self._sleepers = live
            if not live or live[0][0] > target:
                break
            deadline, _, future = live[0]
            self._t = max(self._t, deadline)
            future.set_result(None)
            await _settle()
        self._t = target
        await _settle()


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


class ListPublisher:
    """Collects published events, with the virtual time they were published at."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.events: list[Event] = []
        self.times: list[float] = []
        self._clock = clock

    async def publish(self, event: Event) -> None:
        self.events.append(event)
        self.times.append(self._clock.monotonic() if self._clock else 0.0)
