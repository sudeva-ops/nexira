"""ADD-FORECAST and the Predictive Risk seed (D-46, PRD-01, PRD-05, PRD-08; docs/plan-pilot-prd.md
§3, §7, §10): the scenario's content; the seeded calendar and the 30-day illustrative history; the
calm state (every forecast below 70, an empty Decision Queue); scene 1 through the worker's
handler, which takes Addis Ababa over 70 and lets the Forecast agent advise; a replay adds
nothing. Seeded for today, since the calendar is relative to the scenario date."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents.models import AgentProposal
from app.modules.agents.runner import run_agents
from app.modules.predictive import consumer
from app.modules.predictive import service as predictive
from app.modules.predictive.schemas import OverviewOut
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import func, select, text

from nexira_sim.scenarios import add_forecast
from nexira_sim.seed import data, world
from tests.scene_helpers import seed

pytestmark = pytest.mark.asyncio(loop_scope="module")
TODAY = datetime.now(UTC).date()
TENANT = uuid.UUID("11111111-2222-3333-4444-dddddddddddd")
EVENTS = add_forecast.build_events(world.build(TODAY, TENANT), TENANT)


def test_the_scenario_adds_two_calendar_entries_only() -> None:
    assert [e.event_type for e in EVENTS] == [
        "SCENE_START",
        "SCENE_START",
        "MISSION_EVENT",
        "MISSION_EVENT",
    ]
    assert add_forecast.build_events(world.build(TODAY, TENANT), TENANT) == EVENTS
    for e in EVENTS:
        if e.event_type == "MISSION_EVENT":
            consumer.EventPayload.model_validate(e.payload)
    # Nothing of a VIP visit in the scenario's payloads (G-1).
    assert "visit" not in repr([e.payload for e in EVENTS]).lower()


@dataclass
class Played:
    calm: OverviewOut | None = None
    history_days: dict[str, int] = field(default_factory=dict)
    calendar: int = 0
    proposals_before: int = 0
    after: OverviewOut | None = None
    published: list[str] = field(default_factory=list)
    advice: list[AgentProposal] = field(default_factory=list)
    replay_published: list[str] = field(default_factory=list)
    calendar_after_replay: int = 0
    audit: list[str] = field(default_factory=list)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    result = Played()
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seed(db, engine, tenant_id, day=TODAY)
        async with tenant_session(tenant_id, engine) as session:
            result.calm = await predictive.overview(session)
            rows = await session.execute(
                text(
                    "SELECT m.code, count(*) AS n FROM risk_index r JOIN mission m "
                    "ON m.id = r.mission_id WHERE r.source = 'ILLUSTRATIVE' GROUP BY m.code"
                )
            )
            result.history_days = {r.code: int(r.n) for r in rows}
            result.calendar = int(
                await session.scalar(text("SELECT count(*) FROM mission_event")) or 0
            )
            result.proposals_before = int(
                await session.scalar(select(func.count()).select_from(AgentProposal)) or 0
            )
        handle = consumer.event_handler(engine, publisher := ListPublisher())
        source = f"scenario:{add_forecast.CODE}:test"
        for e in EVENTS:
            if e.event_type == "MISSION_EVENT":
                await handle(Event(e.event_type, tenant_id, dict(e.payload), source))
        result.published = [e.type for e in publisher.events]
        for published in publisher.events:
            await run_agents(engine, ListPublisher(), published, undo_window_s=300)
        async with tenant_session(tenant_id, engine) as session:
            result.after = await predictive.overview(session)
            result.advice = list(
                await session.scalars(
                    select(AgentProposal).where(
                        AgentProposal.action_type == "ADVISE_READINESS_CHECK"
                    )
                )
            )
            result.audit = list(
                await session.scalars(
                    text(
                        "SELECT action FROM audit_log WHERE action LIKE 'PREDICTIVE.%' ORDER BY id"
                    )
                )
            )
        replay = ListPublisher()
        handle = consumer.event_handler(engine, replay)
        for e in EVENTS:
            if e.event_type == "MISSION_EVENT":
                await handle(Event(e.event_type, tenant_id, dict(e.payload), source))
        result.replay_published = [e.type for e in replay.events]
        async with tenant_session(tenant_id, engine) as session:
            result.calendar_after_replay = int(
                await session.scalar(text("SELECT count(*) FROM mission_event")) or 0
            )
    finally:
        await engine.dispose()
    return result


async def test_the_seed_has_the_history_and_the_calm_calendar(played: Played) -> None:
    assert played.calendar == len(data.PREDICTIVE_CALENDAR) == 12
    assert len(played.history_days) == 36
    assert set(played.history_days.values()) == {30}


async def test_the_calm_state_stays_below_the_threshold(played: Played) -> None:
    calm = played.calm
    assert calm is not None
    assert [r.mission_code for r in calm.rising if r.crosses] == []
    assert max(r.peak for r in calm.rising) < 70
    assert played.proposals_before == 0  # the Phase 1 scenario starts with an empty queue


async def test_the_rally_takes_addis_over_70_and_the_agent_advises(played: Played) -> None:
    after = played.after
    assert after is not None
    first = after.rising[0]
    assert (first.mission_code, first.crosses) == ("ADD", True)
    assert first.peak >= 70
    assert first.peak_day == TODAY + timedelta(days=add_forecast.RALLY_DAY)
    assert played.published.count("MISSION_EVENT_ADDED") == 2
    assert "PREDICTIVE_UPDATED" in played.published
    [advice] = played.advice
    assert (advice.action_type, advice.effective_level) == ("ADVISE_READINESS_CHECK", 4)
    assert advice.title.startswith("Addis Ababa risk forecast ")
    assert "visit" not in (advice.title + advice.proposed_action).lower()
    assert any(
        a.mission_code == "ADD" and "Rally near the industrial park" in a.text
        for a in after.actions
    )
    assert {
        "PREDICTIVE.HISTORY",
        "PREDICTIVE.CALENDAR_SEED",
        "PREDICTIVE.EVENT",  # the scenario's entries, one by one
        "PREDICTIVE.SNAPSHOT",
    } <= set(played.audit)


async def test_a_replay_adds_nothing(played: Played) -> None:
    assert played.replay_published == []
    assert played.calendar_after_replay == played.calendar + 2
