"""Scene 4 of NBO-CIVIL-UNREST: the safety check-in (decisions.md §7, Prompt 10).

A demo scenario run is active. PB-07 runs to its approval gate (step 5 creates the
check-in for 229 people) and the dispatcher sends it. Scene 4 starts the check-in
clock (CHECKIN_CLOCK: escalation 20 s later, however long scene 3 took) and its 188
CHECKIN_RESPONSE events go through the worker's handlers.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.checkin import service as checkin
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.intel import queries
from app.modules.notifications.consumer import dispatch_all
from app.modules.notifications.models import NotificationCampaign
from app.modules.playbooks import engine as playbook_engine
from app.modules.playbooks import service as playbooks
from app.modules.scenarios.service import active_run, get_scenario
from app.modules.tenancy.service import Actor
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import world
from tests.scene_helpers import DAY, seeded_incident, user

T0 = datetime(2026, 10, 20, 6, 30, tzinfo=UTC)


async def test_scene_4_ends_at_15_1_1_and_168_4_40_and_escalates_hana_once(db: DbUrls) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    publisher = ListPublisher()
    try:
        incident_id = await seeded_incident(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            scenario = await get_scenario(session, nbo.CODE)
            assert scenario is not None
            demo = await active_run(session, scenario.id, None)
            demo.status = "PAUSED"  # scene 1 has played: the demo is running
            duty = await user(session, "duty.officer")
            run = await playbooks.start_run(
                session,
                playbook_code="PB-07",
                incident_id=incident_id,
                actor=Actor(type="USER", id=str(duty.id)),
                started_by=duty.id,
            )
            await session.commit()
        assert await playbook_engine.advance(engine, tenant_id, run.id, publisher) == (
            "AWAITING_APPROVAL"
        )
        await dispatch_all(engine, tenant_id, publisher, now=lambda: T0)

        async with tenant_session(tenant_id, engine) as session:
            campaign = await session.scalar(
                select(NotificationCampaign).where(NotificationCampaign.campaign_type == "CHECKIN")
            )
            assert campaign is not None
            assert (campaign.status, campaign.sent_at, campaign.escalate_after_s) == (
                "SENT",
                T0,
                600,  # scene 3: the scenario's 20 s have not started (D-07 default)
            )
            campaign_id = campaign.id

        # Scene 4, 90 s after the check-in was sent: the clock event, then every answer.
        scene_4 = T0 + timedelta(seconds=90)
        handlers = {
            "CHECKIN_CLOCK": clock_handler(engine, publisher, now=lambda: scene_4),
            "CHECKIN_RESPONSE": response_handler(engine, publisher),
        }
        for e in sorted(
            nbo.build_events(world.build(DAY, tenant_id), tenant_id), key=lambda e: e.offset_ms
        ):
            if e.scene_no == 4 and e.event_type in handlers:
                await handlers[e.event_type](
                    Event(e.event_type, tenant_id, dict(e.payload), "scenario")
                )

        async with tenant_session(tenant_id, engine) as session:
            tallies = await checkin.tally(session, campaign_id)
            assert await checkin.escalate_due(session, scene_4 + timedelta(seconds=19)) == []
            first = await checkin.escalate_due(session, scene_4 + timedelta(seconds=20))
            again = await checkin.escalate_due(session, scene_4 + timedelta(seconds=60))
            await session.commit()
            found = await queries.get_incident(session, incident_id)
            assert found is not None
            exposed = found[1]
    finally:
        await engine.dispose()

    personnel, citizens = tallies["personnel"], tallies["citizens"]
    assert (personnel.safe, personnel.need_help, personnel.pending) == (15, 1, 1)
    assert (citizens.safe, citizens.need_help, citizens.pending) == (168, 4, 40)
    assert personnel.accounted_pct == 94.1
    assert [(r.personnel, r.citizens) for r in first] == [(["Hana Takeda"], 40)]
    assert again == []  # Hana is escalated once
    # The map pulses people by their answer (UI): every exposed person carries it.
    status = {e.name: e.checkin_status for e in exposed if e.subject_type == "PERSON"}
    assert (status["Peter Mwangi"], status["Hana Takeda"], status["Grace Wanjiru"]) == (
        "NEED_HELP",
        "PENDING",
        "SAFE",
    )
    people = [e.checkin_status for e in exposed if e.subject_type == "PERSON"]
    assert (people.count("NEED_HELP"), people.count("PENDING"), people.count("SAFE")) == (
        5,
        41,
        183,
    )
    assert all(e.checkin_status is None for e in exposed if e.subject_type != "PERSON")
