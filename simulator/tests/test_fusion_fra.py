"""Scenes 1-3 of FRA-NATIONAL-PROTESTS through the worker's real handlers (fusion,
then exposure), played with a fake clock exactly as the player publishes them."""

import uuid
from datetime import date

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.intel.models import Incident
from app.modules.people.models import Mission
from app.modules.scenarios.player import Player
from app.modules.scenarios.service import get_scenario, load_events
from app.tests.conftest import DbUrls
from app.tests.fakes import FakeClock, ListPublisher
from sqlalchemy import select

from nexira_sim.scenarios import fra_national_protests as fra
from nexira_sim.seed.load import seed_all

pytestmark = pytest.mark.asyncio(loop_scope="module")


class Played:
    def __init__(self) -> None:
        self.after_scene: dict[int, list[Incident]] = {}
        self.paris_mission: uuid.UUID | None = None


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed_all(
            engine,
            owner_dsn=db.owner,
            issuer=f"https://kc.test/realms/fra-{tenant_id}",
            scenario_date=date(2026, 10, 20),
            tenant_id=tenant_id,
        )
        async with tenant_session(tenant_id, engine) as session:
            scenario = await get_scenario(session, fra.CODE)
            assert scenario is not None
            events = await load_events(session, scenario.id)
            missions = {m.code: m.id for m in await session.scalars(select(Mission))}
            result.paris_mission = missions["PAR"]

        clock, stream = FakeClock(), ListPublisher()
        player = Player(
            code=fra.CODE,
            tenant_id=tenant_id,
            run_id=uuid.uuid4(),
            events=events,
            publisher=stream,
            clock=clock,
        )
        published = ListPublisher()
        on_signal = raw_signal_handler(engine, published)
        on_incident = exposure_handler(engine, ListPublisher())
        handled = 0
        for scene in (1, 2, 3):
            await player.next()
            await clock.advance(120)
            signals: list[Event] = [e for e in stream.events[handled:] if e.type == "RAW_SIGNAL"]
            handled = len(stream.events)
            for event in signals:
                seen = len(published.events)
                await on_signal(event)
                for incident_event in published.events[seen:]:
                    await on_incident(incident_event)
            async with tenant_session(tenant_id, engine) as session:
                result.after_scene[scene] = list(
                    await session.scalars(select(Incident).order_by(Incident.reference))
                )
    finally:
        await engine.dispose()
    return result


async def test_scene_1_fuses_the_paris_march_into_one_critical_incident(played: Played) -> None:
    [paris] = played.after_scene[1]
    assert (paris.category, paris.confidence, paris.signal_severity, paris.severity) == (
        "CIVIL_UNREST",
        92,  # Dataminr, MAX, Riskline (D-10)
        "HIGH",
        "CRITICAL",  # the Paris embassy is inside the impact radius (D-11)
    )
    assert paris.mission_id == played.paris_mission


async def test_scene_2_adds_separate_incidents_elsewhere(played: Played) -> None:
    incidents = played.after_scene[2]
    assert len(incidents) == 5
    by_place = {i.title: i for i in incidents}
    elsewhere = [i for i in incidents if i.mission_id is None]
    assert sorted((i.category, i.severity) for i in elsewhere) == [
        ("CIVIL_UNREST", "HIGH"),  # Lyon
        ("CIVIL_UNREST", "HIGH"),  # Nantes
        ("CIVIL_UNREST", "MODERATE"),  # Marseille
    ]
    transport = [i for i in by_place.values() if i.category == "TRANSPORT_STRIKE"]
    assert [(t.severity, t.mission_id) for t in transport] == [("MODERATE", played.paris_mission)]


async def test_scene_3_raises_the_paris_confidence_to_96(played: Played) -> None:
    incidents = played.after_scene[3]
    assert len(incidents) == 5  # the second-day report joins the Paris incident
    paris = next(i for i in incidents if i.category == "CIVIL_UNREST" and i.mission_id)
    assert (paris.confidence, paris.severity) == (96, "CRITICAL")
