"""DAC-CYCLONE (D-38, HZ-01..06, HZ-11; docs/plan-pilot-hz.md §9): its content, and scenes
1-5 through the worker's real handlers (fusion, exposure, agents, playbook runs, the demo
clock) on the same in-memory bus as the Nairobi agents test. The Security Officer approves
the arming proposal after scene 2, as in the acceptance (§42)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents import proposals
from app.modules.agents.models import AgentProposal
from app.modules.hazards import consumer
from app.modules.hazards import service as hazards
from app.modules.hazards.schemas import HazardOut
from app.modules.intel import hazards as rules
from app.modules.playbooks.models import Playbook, PlaybookRun
from app.tests.conftest import DbUrls
from sqlalchemy import select, text

from nexira_sim.scenarios import dac_cyclone as dac
from nexira_sim.seed import data, world
from tests.scene_helpers import seed
from tests.test_agents_nbo import Bus, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-666666666666")
EVENTS = dac.build_events(world.build(date(2026, 10, 31), TENANT), TENANT)


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3, 4, 5]
    assert dac.build_events(world.build(date(2026, 10, 31), TENANT), TENANT) == EVENTS
    assert [e.payload for e in EVENTS if e.event_type == "DEMO_CLOCK"] == [
        {"advance_h": 24},
        {"advance_h": 36},
    ]


def test_every_signal_maps_through_its_own_source_and_every_measure_parses() -> None:
    sources = {code: (sev, cat) for code, _n, _r, sev, cat, _e, _f in data.SOURCES}
    for e in EVENTS:
        if e.event_type != "RAW_SIGNAL":
            continue
        severity_map, category_map = sources[str(e.payload["source_code"])]
        category = category_map[str(e.payload["provider_category"])]
        if category in rules.MEASURED:
            assert rules.measure(category, dict(e.payload)) is not None, e.payload["external_id"]
        else:
            assert str(e.payload["provider_severity"]) in severity_map, e.payload["external_id"]


def test_the_phase_1_scenario_still_starts_with_nothing_from_this_one() -> None:
    """§43 Q8: nothing of DAC-CYCLONE is in scene 0."""
    assert [e.event_type for e in EVENTS if e.scene_no == 0] == ["SCENE_START"]


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    events: dict[int, list[HazardOut]] = field(default_factory=dict)
    advance: dict[int, int] = field(default_factory=dict)
    proposals: list[AgentProposal] = field(default_factory=list)
    runs: dict[int, list[tuple[str, str]]] = field(default_factory=dict)
    climate_top: str | None = None


def scene(n: int, tenant_id: uuid.UUID) -> list[Event]:
    return [
        Event(e.event_type, tenant_id, dict(e.payload), "scenario")
        for e in dac.build_events(world.build(datetime.now(UTC).date(), tenant_id), tenant_id)
        if e.scene_no == n and e.event_type != "SCENE_START"
    ]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed(db, engine, tenant_id, datetime.now(UTC).date())
        async with tenant_session(tenant_id, engine) as session:
            # The presenter bar has started the scenario (the demo clock needs a running demo).
            await session.execute(
                text(
                    "INSERT INTO scenario_run (tenant_id, scenario_id, status, started_at) "
                    "SELECT current_tenant_id(), id, 'PLAYING', now() - interval '1 minute' "
                    "FROM scenario WHERE code = :code"
                ),
                {"code": dac.CODE},
            )
            await session.commit()
        bus = Bus(engine)
        bus.routes["DEMO_CLOCK"] = [consumer.clock_handler(engine, bus.publisher)]

        async def play(n: int) -> None:
            await bus.deliver(scene(n, tenant_id))
            async with tenant_session(tenant_id, engine) as session:
                listed = await hazards.list_hazards(session)
                result.events[n] = listed.events
                result.advance[n] = listed.demo_advance_h
                rows = await session.execute(
                    select(Playbook.code, PlaybookRun.status)
                    .join(Playbook, Playbook.id == PlaybookRun.playbook_id)
                    .order_by(PlaybookRun.started_at)
                )
                result.runs[n] = [(r[0], r[1]) for r in rows]

        await play(1)
        await play(2)
        async with tenant_session(tenant_id, engine) as session:
            result.proposals = list(
                await session.scalars(select(AgentProposal).order_by(AgentProposal.created_at))
            )
            arming = next(p for p in result.proposals if p.action_type == "ARM_PLAYBOOK")
            outcome = await proposals.approve(
                session, await user(engine, tenant_id, "security.officer"), arming.id
            )
            await session.commit()
        await bus.deliver(outcome.events)
        async with tenant_session(tenant_id, engine) as session:
            result.runs[2] = [
                (r[0], r[1])
                for r in await session.execute(
                    select(Playbook.code, PlaybookRun.status).join(
                        Playbook, Playbook.id == PlaybookRun.playbook_id
                    )
                )
            ]
            climate = await hazards.list_climate(session)
            result.climate_top = climate[0].mission_code
        for n in (3, 4, 5):
            await play(n)
    finally:
        await engine.dispose()
    return result


def by_category(events: list[HazardOut]) -> dict[str, list[HazardOut]]:
    found: dict[str, list[HazardOut]] = {}
    for e in events:
        found.setdefault(e.category, []).append(e)
    return found


async def test_scene_1_brings_six_events_ankara_low_and_out_of_range(played: Played) -> None:
    events = by_category(played.events[1])
    assert sorted(events) == [
        "AIR_QUALITY",
        "EARTHQUAKE",
        "EXTREME_HEAT",
        "FLOOD",
        "TROPICAL_CYCLONE",
        "WILDFIRE",
    ]
    [quake] = events["EARTHQUAKE"]
    assert (quake.severity, quake.nearest_mission_code, quake.exposed) == ("LOW", "ANK", False)
    assert 200_000 < (quake.nearest_mission_m or 0) < 220_000
    [fire] = events["WILDFIRE"]
    assert (fire.within_range, fire.exposed, fire.severity) == (False, False, "MODERATE")
    [flood] = events["FLOOD"]
    assert (flood.nearest_mission_code, flood.exposure.homes) == ("JKT", 2)  # §42, the design
    [cyclone] = events["TROPICAL_CYCLONE"]
    assert (cyclone.severity, cyclone.hazard["cyclone_category"]) == ("MODERATE", 1)
    assert all(e.simulated for e in played.events[1])


async def test_scene_2_category_2_landfall_in_60_h_dhaka_exposed(played: Played) -> None:
    [cyclone] = by_category(played.events[2])["TROPICAL_CYCLONE"]
    # HIGH from Category 2, raised to CRITICAL by D-11: the chancery is in the zone (G-13).
    assert (cyclone.severity, cyclone.hazard["cyclone_category"]) == ("CRITICAL", 2)
    assert cyclone.landfall_in_h is not None
    assert 59 <= cyclone.landfall_in_h <= 60
    assert (cyclone.nearest_mission_code, cyclone.exposed) == ("DAC", True)
    assert cyclone.exposure.staff == 15


async def test_scene_2_the_planner_proposes_arming_pb06_and_approval_arms_it(
    played: Played,
) -> None:
    arming = [p for p in played.proposals if p.action_type == "ARM_PLAYBOOK"]
    assert [(p.title, p.effective_level, p.is_proactive) for p in arming] == [
        ("Arm PB-06 for Bay of Bengal · Barishal coast, 110 km south of Dhaka", 2, True)
    ]
    assert played.runs[2] == [("PB-06", "SCHEDULED")]
    # No "Run PB-06 now" for a cyclone, and no PB-01 for a LOW earthquake.
    assert [
        p.action_payload["playbook_code"]
        for p in played.proposals
        if p.action_type == "START_PLAYBOOK"
    ] == []


async def test_scene_3_at_36_h_the_armed_pb06_starts_by_itself(played: Played) -> None:
    assert played.advance[3] == 24
    assert played.runs[3][0][0] == "PB-06"
    assert played.runs[3][0][1] in ("RUNNING", "AWAITING_APPROVAL", "COMPLETED")
    [cyclone] = by_category(played.events[3])["TROPICAL_CYCLONE"]
    assert cyclone.landfall_in_h is not None
    assert 35 <= cyclone.landfall_in_h <= 36
    assert cyclone.armed is not None
    assert cyclone.armed.status != "SCHEDULED"


async def test_scene_4_landfall_floods_dhaka_as_a_separate_incident(played: Played) -> None:
    assert played.advance[4] == 60
    floods = by_category(played.events[4])["FLOOD"]
    dhaka = next(f for f in floods if f.nearest_mission_code == "DAC")
    assert dhaka.exposure.homes == 3  # the three flood-prone wards
    [cyclone] = by_category(played.events[4])["TROPICAL_CYCLONE"]
    assert cyclone.landfall_in_h == 0


async def test_scene_5_the_cyclone_weakens(played: Played) -> None:
    [cyclone] = by_category(played.events[5])["TROPICAL_CYCLONE"]
    assert cyclone.hazard["cyclone_category"] == 1
    assert cyclone.severity == "CRITICAL"  # severity never falls by itself (G-12)


async def test_jakarta_has_the_highest_2050_climate_score(played: Played) -> None:
    assert played.climate_top == "JKT"
