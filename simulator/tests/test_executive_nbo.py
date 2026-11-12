"""The Executive Overview on the seeded world (D-45, EXE-01, EXE-02, EXE-06; plan-pilot-exe §2-§5,
§8): the calm state, then NBO-CIVIL-UNREST through scene 4 (PB-07 to its gate, the check-in sent
and answered). Every seeded mission is in a region, and no person's name is in the overview."""

import uuid
from datetime import UTC, datetime, timedelta
from statistics import mean

import pytest
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.executive import service as executive
from app.modules.executive.schemas import OverviewOut
from app.modules.notifications.consumer import dispatch_all
from app.modules.playbooks import engine as playbook_engine
from app.modules.playbooks import service as playbooks
from app.modules.scenarios.service import active_run, get_scenario
from app.modules.tenancy.service import Actor
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import data, world
from tests.scene_helpers import DAY, seed, seeded_incident, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
NAMES = [p.full_name for p in world.build(DAY, uuid.uuid4()).persons]


async def _overview(engine: AsyncEngine, tenant_id: uuid.UUID) -> OverviewOut:
    async with tenant_session(tenant_id, engine) as session:
        return await executive.overview(session, await user(session, "duty.officer"))


def test_every_seeded_mission_is_in_a_region() -> None:
    countries = {country for _, _, _, country, _, _, _ in data.MISSIONS}
    assert {executive.region_of(c) for c in countries} <= set(executive.REGIONS)


async def test_the_calm_state(db: DbUrls) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seed(db, engine, tenant_id)
        out = await _overview(engine, tenant_id)
        again = await _overview(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            scores = list(
                await session.scalars(
                    text("SELECT readiness_score FROM site WHERE site_type = 'EMBASSY'")
                )
            )
    finally:
        await engine.dispose()
    assert (out.posture.level, out.posture.critical_missions, out.posture.elevated_missions) == (
        "GUARDED",
        0,
        4,
    )
    assert (out.active_incidents, out.latest_incident) == (0, None)
    assert out.accounted.pct is None
    assert (out.detection.median_s, out.detection.incidents) == (None, 0)
    assert out.readiness.mean == round(mean(scores))
    assert {r.region: r.exposure for r in out.regions}["Africa"] == 25  # (5 x 20 + 50) / 6
    assert [r.region for r in out.regions] == list(executive.REGIONS)  # none unmapped
    assert sorted(a.mission_code for a in out.attention) == ["ABV", "BGW", "ISB", "JKT"]
    assert len(out.trend) == 30
    # GFX-05 (D-55): illustrative days, then live ones, ending today; the same on every read.
    sources = [d.source for d in out.trend]
    assert sources[-1] == "LIVE"
    assert sources == sorted(sources)  # every ILLUSTRATIVE day before every LIVE one
    assert sum(d.signals for d in out.trend if d.source == "ILLUSTRATIVE") > 0
    assert again.trend == out.trend
    assert out.timeline.incident is None
    _no_names(out)


async def test_the_unrest_through_the_check_in(db: DbUrls) -> None:
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
        sent = datetime.now(UTC)  # after the signals were received: a real timing
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
        out = await _overview(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            reference = await session.scalar(
                text("SELECT reference FROM incident WHERE id = :i"), {"i": incident_id}
            )
            exported = await executive.export(session, await user(session, "viewer"))
            await session.commit()
            audited = await session.scalar(
                text("SELECT details FROM audit_log WHERE action = 'EXECUTIVE.EXPORT'")
            )
    finally:
        await engine.dispose()
    assert (out.posture.level, out.posture.critical_missions) == ("SEVERE", 1)
    assert out.active_incidents == 1
    assert out.latest_incident is not None
    assert out.latest_incident.reference == reference
    assert out.accounted.pct == 94  # (15 + 1) / 17 personnel (decisions.md §7)
    assert out.accounted.incident_references == [reference]
    assert out.detection.current_reference == reference
    assert out.detection.current_s is not None
    assert out.detection.current_s >= 0
    assert out.detection.incidents == 1
    assert (out.trend[-1].source, out.trend[-1].incidents) == ("LIVE", 1)  # from the record
    assert {r.region: r.exposure for r in out.regions}["Africa"] == 38  # Nairobi CRITICAL
    first = out.attention[0]
    assert (first.mission_code, first.risk) == ("NBO", "CRITICAL")
    kinds = {d.kind: d for d in first.drivers}
    assert kinds["INCIDENT"].reference == reference
    assert kinds["SHELTER"].reference == reference  # PB-07 step 4's shelter alert
    assert kinds["FLEET"].label == "1 vehicle unavailable"  # VH-02: the driver's SOS
    assert out.timeline.incident is not None
    assert out.timeline.incident.reference == reference
    types = [e.event_type for e in out.timeline.events]
    assert "CHECKIN" in types
    assert "PLAYBOOK_STEP" in types
    assert "Check-in: a person needs help." in [e.summary for e in out.timeline.events]
    _no_names(out)
    _no_names(exported)
    assert audited is not None
    assert audited["personnel_accounted_pct"] == 94


def _no_names(out: OverviewOut) -> None:
    """EXE-04, G-11: aggregates and references only."""
    dumped = out.model_dump_json()
    assert not [name for name in NAMES if name in dumped]
