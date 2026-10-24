"""Scenes 1 and 2 of NBO-CIVIL-UNREST through the real worker handlers
(decisions.md §7, Prompts 6 and 7).

The stored scenario is played with a fake clock, exactly as the player publishes
it. Each RAW_SIGNAL goes to the handler the worker uses, and each incident event
it publishes goes to the exposure handler, in stream order.
"""

import time
import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.people.models import Mission
from app.modules.scenarios.player import Player
from app.modules.scenarios.service import get_scenario, load_events
from app.tests.conftest import DbUrls
from app.tests.fakes import FakeClock, ListPublisher
from sqlalchemy import select

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed.load import seed_all

pytestmark = pytest.mark.asyncio(loop_scope="module")  # one seeded tenant for the module


class Result:
    def __init__(self) -> None:
        self.incidents: list[Incident] = []
        self.events: list[Event] = []
        self.timeline: list[str] = []
        self.nbo_mission: uuid.UUID | None = None
        self.paris_mission: uuid.UUID | None = None
        self.worst_signal_to_exposure_s = 0.0


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Result:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Result()
    try:
        await seed_all(
            engine,
            owner_dsn=db.owner,
            issuer=f"https://kc.test/realms/fusion-{tenant_id}",
            scenario_date=date(2026, 10, 20),
            tenant_id=tenant_id,
        )
        async with tenant_session(tenant_id, engine) as session:
            scenario = await get_scenario(session, nbo.CODE)
            assert scenario is not None
            events = await load_events(session, scenario.id)

        clock, stream = FakeClock(), ListPublisher()
        player = Player(
            code=nbo.CODE,
            tenant_id=tenant_id,
            run_id=uuid.uuid4(),
            events=events,
            publisher=stream,
            clock=clock,
        )
        await player.next()  # scene 1
        await clock.advance(200)

        incident_events, exposure_events = ListPublisher(), ListPublisher()
        on_signal = raw_signal_handler(engine, incident_events)
        on_incident = exposure_handler(engine, exposure_events)
        for event in stream.events:
            if event.type != "RAW_SIGNAL":
                continue
            started = time.monotonic()
            await on_signal(event)
            for published in incident_events.events[len(result.events) :]:
                result.events.append(published)
                await on_incident(published)
            result.worst_signal_to_exposure_s = max(
                result.worst_signal_to_exposure_s, time.monotonic() - started
            )
        result.events += exposure_events.events

        async with tenant_session(tenant_id, engine) as session:
            result.incidents = list(
                await session.scalars(select(Incident).order_by(Incident.reference))
            )
            result.timeline = list(
                await session.scalars(
                    select(IncidentEvent.event_type)
                    .where(IncidentEvent.incident_id == result.incidents[0].id)
                    .order_by(IncidentEvent.id)
                )
            )
            missions = {m.code: m.id for m in await session.scalars(select(Mission))}
            result.nbo_mission, result.paris_mission = missions["NBO"], missions["PAR"]
    finally:
        await engine.dispose()
    return result


async def test_scene_1_gives_inc_1042_with_confidence_92_and_a_separate_paris_incident(
    played: Result,
) -> None:
    year = datetime.now(UTC).year
    assert [
        (i.reference, i.category, i.confidence, i.signal_severity) for i in played.incidents
    ] == [
        (f"INC-{year}-1042", "CIVIL_UNREST", 92, "HIGH"),
        (f"INC-{year}-1043", "TRANSPORT_STRIKE", 50, "MODERATE"),  # Paris (plan G-12)
    ]
    assert [e.type for e in played.events if e.type.startswith("INCIDENT_")] == [
        "INCIDENT_CREATED",  # Dataminr, 0 s
        "INCIDENT_CREATED",  # Paris, 30 s
        "INCIDENT_UPDATED",  # MAX, 45 s
        "INCIDENT_UPDATED",  # Riskline, 100 s
    ]


async def test_scene_2_nairobi_exposure_matches_d23(played: Result) -> None:
    nairobi = played.incidents[0]
    final = [
        e
        for e in played.events
        if e.type == "EXPOSURE_COMPUTED" and e.payload["incident_id"] == str(nairobi.id)
    ][-1]
    assert final.payload["counts"] == {
        "staff": 14,
        "delegates": 3,
        "citizens": 212,
        "people": 229,
        "sites": 3,  # Embassy, Residence, Hotel
        "mission_sites": 2,  # the UI's Sites figure (D-23)
        "protected_sites": 2,
        "trips": 1,  # TRP-8812
    }
    assert (nairobi.mission_id, nairobi.signal_severity, nairobi.severity) == (
        played.nbo_mission,
        "HIGH",
        "CRITICAL",  # D-11: matches "CRITICAL · INC-2026-1042"
    )
    # Escalated once, when exposure first ran; later signals do not repeat it.
    assert played.timeline.count("ESCALATED") == 1
    assert played.timeline[:3] == ["SIGNAL", "EXPOSURE", "ESCALATED"]


async def test_paris_is_not_escalated(played: Result) -> None:
    paris = played.incidents[1]
    assert (paris.mission_id, paris.severity) == (played.paris_mission, "MODERATE")


async def test_signal_to_exposure_within_5_seconds(played: Result) -> None:
    """Requirements §5: signal to fused incident ≤ 5 s; incident to exposure ≤ 5 s."""
    assert played.worst_signal_to_exposure_s < 5
