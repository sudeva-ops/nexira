"""The After-Action Review service on the seeded world (D-47, AAR-02..04, AAR-09;
plan-pilot-aar §2-§4, §9): NBO-CIVIL-UNREST through PB-07, the check-in and its escalation, step 7
approved by the Nairobi Head of Mission, then the incident set to MONITORING. The timeline names
no seeded person or user; the metrics agree with the run; the escalated person and the staff
member located below 80% are drafted."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.aar import rules, service
from app.modules.checkin import service as checkin
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.intel import service as intel
from app.modules.intel.models import Incident
from app.modules.notifications.consumer import dispatch_all
from app.modules.playbooks import engine as playbook_engine
from app.modules.playbooks import service as playbooks
from app.modules.playbooks.models import Playbook, PlaybookStep
from app.modules.scenarios.service import active_run, get_scenario
from app.modules.tenancy.service import Actor
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select, text

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import world
from tests.scene_helpers import DAY, seeded_incident, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
PEOPLE = [p.full_name for p in world.build(DAY, uuid.uuid4()).persons]


async def test_the_review_of_the_nairobi_unrest(db: DbUrls) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    publisher = ListPublisher()
    try:
        incident_id = await seeded_incident(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            scenario = await get_scenario(session, nbo.CODE)
            assert scenario is not None
            (await active_run(session, scenario.id, None)).status = "PAUSED"
            duty = await user(session, "duty.officer")
            run = await playbooks.start_run(
                session,
                playbook_code="PB-07",
                incident_id=incident_id,
                actor=Actor(type="USER", id=str(duty.id)),
                started_by=duty.id,
            )
            await session.commit()
        await playbook_engine.advance(engine, tenant_id, run.id, publisher)
        sent = datetime.now(UTC)
        await dispatch_all(engine, tenant_id, publisher, now=lambda: sent)
        handlers = {
            "CHECKIN_CLOCK": clock_handler(
                engine, publisher, now=lambda: sent + timedelta(seconds=90)
            ),
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
            # The worker's escalation loop, 20 s after scene 4's clock: the silent person.
            assert await checkin.escalate_due(session, sent + timedelta(seconds=110))
            await session.commit()
        async with tenant_session(tenant_id, engine) as session:
            step7 = await session.scalar(
                select(PlaybookStep.id)
                .join(Playbook, Playbook.id == PlaybookStep.playbook_id)
                .where(Playbook.code == "PB-07", PlaybookStep.seq == 7)
            )
            assert step7 is not None
            await playbooks.approve_step(session, await user(session, "hom.nairobi"), run.id, step7)
            await session.commit()
        await playbook_engine.advance(engine, tenant_id, run.id, publisher)
        async with tenant_session(tenant_id, engine) as session:
            found_incident = await session.get(Incident, incident_id)
            assert found_incident is not None
            await intel.change_status(
                session, found_incident, "MONITORING", Actor(type="USER", id=str(duty.id))
            )
            await session.commit()
        now = datetime.now(UTC)
        async with tenant_session(tenant_id, engine) as session:
            found = await service.incident(session, incident_id)
            assert found is not None
            lines = await service.timeline(session, found, now)
            metrics = {m.key: m for m in await service.metrics(session, found, now)}
            drafts = await rules.draft(session, found, now)
            users = list(await session.scalars(text("SELECT display_name FROM app_user")))
    finally:
        await engine.dispose()

    texts = [line.text for line in lines]
    assert "Step 7 · Approve evacuation route B: approved by the Head of Mission." in texts
    assert "Status ACTIVE → MONITORING." in texts
    assert any(t.startswith("Check-in NTF-") and "escalated" in t for t in texts)
    assert {line.source for line in lines} >= {"INCIDENT", "PLAYBOOK", "CHECKIN", "DECISION"}
    dumped = repr(lines) + repr(drafts) + repr(metrics)
    assert not [name for name in [*PEOPLE, *users] if name and name in dumped]

    assert metrics["personnel_accounted"].value == 94  # (15 + 1) / 17 (decisions.md §7)
    assert metrics["playbook"].value is not None
    assert metrics["detection_to_incident"].met is True
    assert metrics["incident_to_exposure"].met is True
    assert metrics["decision_slowest"].detail is not None
    codes = [d.rule_code for d in drafts]
    assert codes[:2] == ["CHECKIN_SILENT", "LOW_CONFIDENCE"]
    assert drafts[0].finding.endswith("and was escalated.")
    assert drafts[1].evidence["low"] == 1  # the cultural attaché, located from calendar data
    assert "GATE_WAIT" not in codes  # step 7 was approved within seconds (plan G-2)
