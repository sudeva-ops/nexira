"""Scenario player with a fake clock (Prompt 5 tests)."""

import uuid

import pytest

from app.modules.scenarios.player import Player, ScenarioEvent, Status
from app.tests.fakes import FakeClock, ListPublisher

TENANT = uuid.uuid4()


def ev(scene: int, offset_s: float, kind: str = "RAW_SIGNAL", key: str = "") -> ScenarioEvent:
    payload: dict[str, object] = {"key": key or f"{scene}:{offset_s}"}
    if kind == "RAW_SIGNAL":
        payload["external_id"] = f"ext-{key or offset_s}"
    return ScenarioEvent(uuid.uuid4(), scene, int(offset_s * 1000), kind, payload)


EVENTS = [
    ev(0, 0, "SCENE_START", "s0"),
    ev(1, 0, "SCENE_START", "s1"),
    ev(1, 0, key="dataminr"),
    ev(1, 30, key="paris"),
    ev(1, 45, key="max"),
    ev(1, 100, key="riskline"),
    ev(2, 0, "SCENE_START", "s2"),
]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def pub(clock: FakeClock) -> ListPublisher:
    return ListPublisher(clock)


@pytest.fixture
def player(clock: FakeClock, pub: ListPublisher) -> Player:
    return Player(
        code="TEST",
        tenant_id=TENANT,
        run_id=uuid.uuid4(),
        events=EVENTS,
        publisher=pub,
        clock=clock,
    )


def keys(pub: ListPublisher) -> list[object]:
    return [e.payload["key"] for e in pub.events]


async def test_events_replay_in_order_with_relative_timing(
    player: Player, clock: FakeClock, pub: ListPublisher
) -> None:
    await player.play()  # scene 0
    await clock.advance(0)
    assert keys(pub) == ["s0"]

    await player.next()  # scene 1
    start = clock.monotonic()
    await clock.advance(200)
    assert keys(pub)[1:] == ["s1", "dataminr", "paris", "max", "riskline"]
    assert [t - start for t in pub.times[1:]] == [0, 0, 30, 45, 100]
    assert player.status is Status.PAUSED
    assert player.scene_complete


async def test_pause_and_resume_keep_order_and_remaining_time(
    player: Player, clock: FakeClock, pub: ListPublisher
) -> None:
    await player.next()  # scene 1
    await clock.advance(40)
    assert keys(pub) == ["s1", "dataminr", "paris"]

    await player.pause()
    assert player.status is Status.PAUSED
    await clock.advance(1000)
    assert keys(pub) == ["s1", "dataminr", "paris"]  # nothing while paused

    await player.play()
    await clock.advance(4.9)
    assert keys(pub)[-1] == "paris"  # MAX is due 5 s after resuming (45 - 40)
    await clock.advance(0.1)
    assert keys(pub)[-1] == "max"
    await clock.advance(55)
    assert keys(pub) == ["s1", "dataminr", "paris", "max", "riskline"]
    assert pub.times[-1] - pub.times[-2] == 55  # 100 - 45: spacing unchanged


async def test_reset_returns_to_scene_0(player: Player, clock: FakeClock) -> None:
    await player.next()
    await clock.advance(10)
    new_run = uuid.uuid4()
    await player.reset(new_run)
    assert (player.current_scene, player.position, player.status) == (0, 0, Status.IDLE)
    assert player.run_id == new_run


async def test_each_run_gets_fresh_signal_ids(
    player: Player, clock: FakeClock, pub: ListPublisher
) -> None:
    await player.next()
    await clock.advance(200)
    first = {e.payload["external_id"] for e in pub.events if e.type == "RAW_SIGNAL"}
    await player.reset(uuid.uuid4())
    await player.next()
    await clock.advance(200)
    second = {e.payload["external_id"] for e in pub.events if e.type == "RAW_SIGNAL"} - first
    assert len(first) == len(second) == 4


async def test_envelope_carries_tenant_and_source(
    player: Player, clock: FakeClock, pub: ListPublisher
) -> None:
    published_at = clock.now()
    await player.next()
    await clock.advance(1)
    event = pub.events[1]
    assert event.tenant_id == TENANT
    assert event.source == f"scenario:TEST:{player.run_id}"
    assert event.payload["external_id"] == f"ext-dataminr:{player.run_id}"
    assert event.payload["occurred_at"] == published_at.isoformat()
    assert event.occurred_at == published_at


async def test_next_past_the_last_scene_finishes(player: Player, clock: FakeClock) -> None:
    await player.next()
    await player.next()  # scene 2, the last
    await clock.advance(1)
    await player.next()
    assert player.status is Status.FINISHED
    await player.play()  # no effect once finished
    assert player.status is Status.FINISHED


async def test_scene_done_reports_run_and_scene(clock: FakeClock, pub: ListPublisher) -> None:
    done: list[tuple[uuid.UUID, int]] = []

    async def on_done(run_id: uuid.UUID, scene: int) -> None:
        done.append((run_id, scene))

    run_id = uuid.uuid4()
    p = Player(
        code="TEST",
        tenant_id=TENANT,
        run_id=run_id,
        events=EVENTS,
        publisher=pub,
        clock=clock,
        on_scene_done=on_done,
    )
    await p.next()
    await clock.advance(200)
    assert done == [(run_id, 1)]


async def test_play_twice_does_not_duplicate(
    player: Player, clock: FakeClock, pub: ListPublisher
) -> None:
    await player.next()
    await player.play()
    await player.play()
    await clock.advance(200)
    assert keys(pub) == ["s1", "dataminr", "paris", "max", "riskline"]
