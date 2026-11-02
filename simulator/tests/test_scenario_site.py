"""NBO-SITE and the Site Twin seed (D-43, TWN-01, TWN-07; docs/plan-pilot-twn.md §2-§6, §9): the
scenario's content, the seeded embassy as the design, and a play-through on the seeded world after
NBO-CIVIL-UNREST scenes 1-2, through the worker's handlers (with a replay, G-9). The Phase 1
scenario still starts with no active incident and an empty Decision Queue, and presence never
changes People & Sites (D-43)."""

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents.models import AgentProposal
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.people.models import Site
from app.modules.playbooks.models import PlaybookRun
from app.modules.twin import consumer
from app.modules.twin import service as twin
from app.modules.twin.schemas import TwinOut
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import func, select, text

from nexira_sim.scenarios import nbo_site
from nexira_sim.seed import data, world
from tests.scene_helpers import DAY, seed, seeded_incident, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-bbbbbbbbbbbb")
W = world.build(DAY, TENANT)
EVENTS = nbo_site.build_events(W, TENANT)
STAFF_NAMES = [name for name, _, _ in data.TWIN_STAFF]


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3]
    assert nbo_site.build_events(world.build(DAY, TENANT), TENANT) == EVENTS
    # Presence and sensors only: nothing approves, proposes or moves anyone off the site.
    assert {e.event_type for e in EVENTS} == {"SCENE_START", "SITE_PRESENCE", "SITE_SENSOR"}
    assert [e.event_type for e in EVENTS if e.scene_no == 0] == ["SCENE_START"]
    for e in EVENTS:
        if e.event_type == "SITE_PRESENCE":
            consumer.PresenceIn.model_validate(e.payload)
        elif e.event_type == "SITE_SENSOR":
            consumer.SensorIn.model_validate(e.payload)
    # People by id, guards and visitors by label: no name in any event (§68 Q3).
    text_of_events = repr([e.payload for e in EVENTS])
    assert not any(name in text_of_events for name in STAFF_NAMES)


def test_the_seed_is_the_designs() -> None:
    assert len(data.TWIN_SENSORS) == 43
    assert len({code for code, *_ in data.TWIN_SENSORS}) == 43
    assert (len(data.TWIN_STAFF), len(data.TWIN_LABELS)) == (11, 14)  # 3 guards, 11 visitors
    to_safe = [n for n, normal, shelter in data.TWIN_STAFF if shelter == "safe" != normal]
    assert len(to_safe) == 9
    people = {name for name, _, place, *_ in data.NAIROBI_PEOPLE if place == "Embassy"}
    assert set(STAFF_NAMES) == people


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    seeded: TwinOut | None = None
    viewer: TwinOut | None = None
    before: tuple[int, int, int] = (0, 0, 0)  # active incidents, proposals, runs
    observations: tuple[int, int] = (0, 0)
    after: dict[str, TwinOut] = field(default_factory=dict)
    timeline: list[str] = field(default_factory=list)
    observations_after: tuple[int, int] = (0, 0)
    proposals: int = 0


async def _twin(engine: Any, tenant_id: uuid.UUID, who: str = "duty.officer") -> TwinOut:
    async with tenant_session(tenant_id, engine) as session:
        caller = await user(session, who)
        site_id = await session.scalar(
            select(Site.id).where(Site.name == "Embassy Nairobi", Site.site_type == "EMBASSY")
        )
        assert site_id is not None
        return await twin.twin(session, caller, site_id)


async def _counts(engine: Any, tenant_id: uuid.UUID) -> tuple[int, int, int]:
    async with tenant_session(tenant_id, engine) as session:
        return (
            int(
                await session.scalar(
                    select(func.count()).select_from(Incident).where(Incident.status == "ACTIVE")
                )
                or 0
            ),
            int(await session.scalar(select(func.count()).select_from(AgentProposal)) or 0),
            int(await session.scalar(select(func.count()).select_from(PlaybookRun)) or 0),
        )


async def _observations(engine: Any, tenant_id: uuid.UUID) -> tuple[int, int]:
    async with tenant_session(tenant_id, engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM location_observation) AS o, "
                    "(SELECT count(*) FROM person_location_current) AS c"
                )
            )
        ).one()
        return int(row.o), int(row.c)


async def _scene(engine: Any, tenant_id: uuid.UUID, n: int) -> None:
    publisher = ListPublisher()
    handlers = {
        "SITE_PRESENCE": consumer.presence_handler(engine, publisher),
        "SITE_SENSOR": consumer.sensor_handler(engine, publisher),
    }
    events = nbo_site.build_events(world.build(DAY, tenant_id), tenant_id)
    for e in sorted(events, key=lambda e: e.offset_ms):
        if e.scene_no == n and e.event_type in handlers:
            source = f"scenario:{nbo_site.CODE}:test"
            await handlers[e.event_type](Event(e.event_type, tenant_id, dict(e.payload), source))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    result = Played()
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seed(db, engine, tenant_id)
        result.before = await _counts(engine, tenant_id)
        result.seeded = await _twin(engine, tenant_id)
        result.viewer = await _twin(engine, tenant_id, "viewer")
    finally:
        await engine.dispose()
    # A second tenant with INC-1042 ACTIVE (NBO-CIVIL-UNREST scenes 1-2), then NBO-SITE twice.
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seeded_incident(db, engine, tenant_id)
        result.observations = await _observations(engine, tenant_id)
        for run in ("first", "replay"):
            for n in (1, 2, 3):
                await _scene(engine, tenant_id, n)
                result.after[f"{run}:{n}"] = await _twin(engine, tenant_id)
        result.observations_after = await _observations(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            result.timeline = list(
                await session.scalars(
                    select(IncidentEvent.summary)
                    .where(IncidentEvent.event_type == "SITE")
                    .order_by(IncidentEvent.id)
                )
            )
    finally:
        await engine.dispose()
    return result


async def test_the_seeded_embassy_is_the_designs(played: Played) -> None:
    out = played.seeded
    assert out is not None
    assert [z.code for z in out.zones] == [
        "ch", "amb", "comms", "safe", "conf", "lob", "cons", "must", "g1", "g2"
    ]  # fmt: skip
    counts = out.counts
    assert (counts.on_site, counts.staff, counts.guards, counts.visitors) == (25, 11, 3, 11)
    assert (counts.sensors_online, counts.sensors, counts.faults) == (43, 43, 0)
    assert (counts.safe_room, counts.safe_room_capacity) == (0, 20)
    assert {z.code: z.count for z in out.zones if z.count} == {
        "ch": 5,
        "conf": 2,
        "comms": 2,
        "cons": 11,  # 2 staff and 9 visitors
        "lob": 3,  # a guard and 2 visitors
        "g1": 1,
        "g2": 1,
    }
    assert [(s.code, s.state, s.fuel_pct) for s in out.systems] == [
        ("GEN-NBO", "AVAILABLE", 72),
        ("SAT-NBO", "AVAILABLE", 100),
    ]
    assert out.readiness.score == 79  # site.readiness_score, as People & Sites (G-1)
    items = {i.label: i.done for i in out.readiness.items}
    assert items == {
        "Floor wardens assigned (3)": True,
        "Safe room supplies checked · 14 d": True,
        "Evacuation routes A & B surveyed": True,
        "Generator load test witnessed": False,
        "All access points monitored": True,
    }
    assert sorted(o.name or "" for o in out.occupants if o.kind == "STAFF") == sorted(STAFF_NAMES)
    assert [r for r in (out.route, out.shelter)] == [None, None]


async def test_the_viewer_sees_the_counts_and_no_name(played: Played) -> None:
    assert played.viewer is not None
    assert played.viewer.counts.on_site == 25
    assert all(o.name is None for o in played.viewer.occupants)
    assert all(i.done_by_name is None for i in played.viewer.readiness.items)


async def test_phase_1_still_starts_with_no_incident_and_an_empty_queue(played: Played) -> None:
    assert played.before == (0, 0, 0)


async def test_nbo_site_faults_shelters_and_recovers(played: Played) -> None:
    faults = played.after["first:1"]
    assert (faults.counts.sensors_online, faults.counts.faults) == (41, 2)
    status = {s.code: (s.status, s.detail) for s in faults.sensors}
    assert status["G2-READER"] == ("FAULT", "Fault · manual guard")
    assert status["CAM-07"] == ("OFFLINE", "Offline")
    access = {i.label: i for i in faults.readiness.items}["All access points monitored"]
    assert (access.done, access.detail) == (False, "Gate 2 · badge reader: Fault · manual guard")

    shelter = played.after["first:2"]
    zones = {z.code: z.count for z in shelter.zones}
    assert (shelter.counts.safe_room, zones["conf"], zones["comms"]) == (9, 11, 2)
    assert (zones["ch"], zones["cons"], shelter.counts.on_site) == (0, 0, 25)
    assert {s.code: s.detail for s in shelter.sensors}["G1-MAIN"] == "Locked down"

    recovered = played.after["first:3"]
    assert (recovered.counts.sensors_online, recovered.counts.faults) == (43, 0)
    assert {s.code: s.detail for s in recovered.sensors}["G1-MAIN"] == "Open · screening"
    assert recovered.counts.safe_room == 9  # people stay sheltered until moved


async def test_a_replay_starts_from_the_seed(played: Played) -> None:
    replay = played.after["replay:1"]
    assert replay.counts.safe_room == 0  # scene 1 put everyone back (G-9)
    assert (replay.counts.sensors_online, replay.counts.faults) == (41, 2)
    assert played.after["replay:2"].counts.safe_room == 9
    assert played.after["replay:3"].counts.faults == 0


async def test_faults_and_recoveries_are_on_the_incident_timeline(played: Played) -> None:
    once = [
        "Embassy Nairobi · Gate 2 · badge reader: FAULT (Fault · manual guard).",
        "Embassy Nairobi · Camera 7: OFFLINE (Offline).",
        "Embassy Nairobi · Gate 2 · badge reader: OK (Online).",
        "Embassy Nairobi · Camera 7: OK.",
    ]
    assert played.timeline == once + once  # the first run and the replay


async def test_presence_never_changes_people_and_sites(played: Played) -> None:
    assert played.observations_after == played.observations
