"""Scene 4 of NBO-CIVIL-UNREST: the safety check-in (decisions.md §7, Prompt 10).

A demo scenario run is active, so the check-in escalates after 20 s. PB-07 runs to
its approval gate (step 5 creates the check-in for 229 people), the dispatcher sends
it, and the scenario's 188 CHECKIN_RESPONSE events go through the worker's handler.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.checkin import service as checkin
from app.modules.checkin.consumer import response_handler
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
                20,
            )
            campaign_id = campaign.id

        # Scene 4: every answer as the player publishes it.
        handle = response_handler(engine, publisher)
        for e in nbo.build_events(world.build(DAY, tenant_id), tenant_id):
            if e.event_type == "CHECKIN_RESPONSE":
                await handle(Event("CHECKIN_RESPONSE", tenant_id, dict(e.payload), "scenario"))

        async with tenant_session(tenant_id, engine) as session:
            tallies = await checkin.tally(session, campaign_id)
            assert await checkin.escalate_due(session, T0 + timedelta(seconds=19)) == []
            first = await checkin.escalate_due(session, T0 + timedelta(seconds=20))
            again = await checkin.escalate_due(session, T0 + timedelta(seconds=60))
            await session.commit()
    finally:
        await engine.dispose()

    personnel, citizens = tallies["personnel"], tallies["citizens"]
    assert (personnel.safe, personnel.need_help, personnel.pending) == (15, 1, 1)
    assert (citizens.safe, citizens.need_help, citizens.pending) == (168, 4, 40)
    assert personnel.accounted_pct == 94.1
    assert [(r.personnel, r.citizens) for r in first] == [(["Hana Takeda"], 40)]
    assert again == []  # Hana is escalated once
