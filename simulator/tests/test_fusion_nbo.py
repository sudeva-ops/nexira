"""Scene 1 of NBO-CIVIL-UNREST through the real ingestion path (decisions.md §7, Prompt 6).

The stored scenario is played with a fake clock, exactly as the player publishes
it, and each RAW_SIGNAL event goes to the same handler the worker uses.
"""

import uuid
from datetime import UTC, date, datetime

from app.core.db import create_engine, tenant_session
from app.modules.intel.consumer import raw_signal_handler
from app.modules.intel.models import Incident
from app.modules.scenarios.player import Player
from app.modules.scenarios.service import get_scenario, load_events
from app.tests.conftest import DbUrls
from app.tests.fakes import FakeClock, ListPublisher
from sqlalchemy import select

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed.load import seed_all


async def test_scene_1_gives_inc_1042_with_confidence_92_and_a_separate_paris_incident(
    db: DbUrls,
) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
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

        clock, stream, out = FakeClock(), ListPublisher(), ListPublisher()
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
        handle = raw_signal_handler(engine, out)
        for event in stream.events:
            if event.type == "RAW_SIGNAL":
                await handle(event)

        async with tenant_session(tenant_id, engine) as session:
            incidents = (await session.scalars(select(Incident).order_by(Incident.reference))).all()
    finally:
        await engine.dispose()

    year = datetime.now(UTC).year
    assert [(i.reference, i.category, i.confidence, i.signal_severity) for i in incidents] == [
        (f"INC-{year}-1042", "CIVIL_UNREST", 92, "HIGH"),
        (f"INC-{year}-1043", "TRANSPORT_STRIKE", 50, "MODERATE"),  # Paris (plan G-12)
    ]
    assert [e.type for e in out.events] == [
        "INCIDENT_CREATED",  # Dataminr, 0 s
        "INCIDENT_CREATED",  # Paris, 30 s
        "INCIDENT_UPDATED",  # MAX, 45 s
        "INCIDENT_UPDATED",  # Riskline, 100 s
    ]
