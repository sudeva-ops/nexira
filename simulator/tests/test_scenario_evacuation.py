"""NBO-EVACUATION (D-40, EV-10; docs/plan-pilot-ev.md §11): its content, and a play-through
on the seeded world. NBO-CIVIL-UNREST runs to its check-in (scenes 1-4, as
test_checkin_nbo), then the scene 5 proposal is approved by the Nairobi Head of Mission and
the HQ Crisis Director, which activates EVP-NBO (EV-02). The scanner and the progress events
then go through the worker's handlers (G-2, G-9)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents import proposals
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.evacuations import consumer
from app.modules.evacuations import service as evacuations
from app.modules.evacuations.models import Evacuation, EvacuationPlan
from app.modules.notifications.consumer import dispatch_all
from app.modules.notifications.models import NotificationCampaign
from app.modules.partners.models import Partner, PartnerRequest
from app.modules.playbooks import engine as playbook_engine
from app.modules.playbooks import service as playbooks
from app.modules.scenarios.service import active_run, get_scenario
from app.modules.tenancy.service import Actor
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.scenarios import nbo_evacuation as evacuation
from nexira_sim.seed import data, world
from tests.scene_helpers import DAY, seeded_incident, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-888888888888")
EVENTS = evacuation.build_events(world.build(DAY, TENANT), TENANT)
T0 = datetime(2026, 10, 20, 6, 30, tzinfo=UTC)


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3, 4]
    assert evacuation.build_events(world.build(DAY, TENANT), TENANT) == EVENTS
    assert [e.event_type for e in EVENTS if e.scene_no == 0] == ["SCENE_START"]


def test_the_scanner_covers_the_manifest_and_progress_moves_one_step_a_scene() -> None:
    scans = [e for e in EVENTS if e.event_type == "MUSTER_SCAN"]
    assert {e.scene_no for e in scans} == {1}
    assert sum(e.payload["count"] for e in scans) == 60
    assert max(e.offset_ms for e in scans) == 30_000
    progress = [
        (e.scene_no, e.payload["step"]) for e in EVENTS if e.event_type == "EVACUATION_PROGRESS"
    ]
    assert progress == [(2, 4), (3, 5), (4, 6)]
    for e in scans:
        consumer.ScanIn.model_validate(e.payload)
    # Nothing in the scenario activates, stands down or approves (§53 Q10).
    assert {e.event_type for e in EVENTS} == {"SCENE_START", "MUSTER_SCAN", "EVACUATION_PROGRESS"}


def test_every_mission_has_a_plan_and_nairobi_is_the_designs() -> None:
    assert set(data.SAFE_HAVEN) == set(data.MISSION_COUNTRIES)
    assert [(o[0], o[1], o[3], o[4]) for o in data.NAIROBI_OPTIONS] == [
        ("PRIMARY", "CHARTER", 72, "ATL"),
        ("BACKUP", "COMMERCIAL", 30, None),
        ("CONTINGENCY", "ROAD", None, "SEN"),
    ]


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    plans: int = 0
    nbo_plan: dict[str, Any] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    after_first_approval: int = -1
    activated: dict[str, Any] = field(default_factory=dict)
    manifest: list[tuple[str, str | None, bool | None]] = field(default_factory=list)
    partners: list[tuple[str, str, str]] = field(default_factory=list)
    message: tuple[str, str] = ("", "")
    after_scan: dict[str, Any] = field(default_factory=dict)
    seats: list[str | None] = field(default_factory=list)
    steps: list[tuple[int, str]] = field(default_factory=list)


async def _check_in_scene_4(engine: Any, tenant_id: uuid.UUID, incident_id: uuid.UUID) -> None:
    """NBO-CIVIL-UNREST scenes 3-4, as test_checkin_nbo: PB-07's check-in, then the answers."""
    publisher = ListPublisher()
    async with tenant_session(tenant_id, engine) as session:
        scenario = await get_scenario(session, nbo.CODE)
        assert scenario is not None
        demo = await active_run(session, scenario.id, None)
        demo.status = "PAUSED"
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
    await dispatch_all(engine, tenant_id, publisher, now=lambda: T0)
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


async def _scene_5(engine: Any, tenant_id: uuid.UUID, incident_id: uuid.UUID) -> uuid.UUID:
    """The scene 5 proposal (nexira_sim.fixtures.evacuation), approved by two people."""
    async with tenant_session(tenant_id, engine) as session:
        outcome = await proposals.create(
            session,
            proposals.ProposalIn(
                agent_code="RESPONSE_PLANNER",
                proposal_key=f"TEST:START_EVACUATION:{incident_id}",
                action_type="START_EVACUATION",
                title="Evacuate Embassy staff via route B",
                proposed_action="Move personnel in the zone to the airport via route B.",
                action_payload={"route": "B"},
                incident_id=incident_id,
                evidence=[{"text": "Scene 5 test fixture (plan G-16)", "source": "test fixture"}],
            ),
            undo_window_s=300,
        )
        await session.commit()
        return outcome.proposal.id


async def _scene(engine: Any, tenant_id: uuid.UUID, n: int, publisher: ListPublisher) -> None:
    handlers = {
        "MUSTER_SCAN": consumer.scan_handler(engine, publisher),
        "EVACUATION_PROGRESS": consumer.progress_handler(engine, publisher),
    }
    for e in sorted(
        evacuation.build_events(world.build(DAY, tenant_id), tenant_id), key=lambda e: e.offset_ms
    ):
        if e.scene_no == n and e.event_type in handlers:
            await handlers[e.event_type](
                Event(e.event_type, tenant_id, dict(e.payload), "scenario")
            )


async def _evacuation(engine: Any, tenant_id: uuid.UUID) -> Evacuation:
    async with tenant_session(tenant_id, engine) as session:
        row: Evacuation | None = await session.scalar(select(Evacuation))
        assert row is not None
        return row


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    publisher = ListPublisher()
    try:
        incident_id = await seeded_incident(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            plans = list(await session.scalars(select(EvacuationPlan)))
            result.plans = len(plans)
            nbo_plan = next(p for p in plans if p.reference == "EVP-NBO")
            names = {p.id: p.code for p in await session.scalars(select(Partner))}
            result.nbo_plan = {
                "muster": nbo_plan.muster_name,
                "destination": nbo_plan.destination,
                "options": [
                    (
                        o["label"],
                        o["seats"],
                        names.get(uuid.UUID(o["partner_id"])) if o["partner_id"] else None,
                    )
                    for o in nbo_plan.options
                ],
            }
            result.gaps = sorted(
                p.reference for p in plans if not any(o["partner_id"] for o in p.options[:1])
            )
        await _check_in_scene_4(engine, tenant_id, incident_id)
        proposal_id = await _scene_5(engine, tenant_id, incident_id)
        async with tenant_session(tenant_id, engine) as session:
            hom = await user(session, "hom.nairobi")
            await proposals.approve(session, hom, proposal_id)
            await session.commit()
        async with tenant_session(tenant_id, engine) as session:
            result.after_first_approval = len(list(await session.scalars(select(Evacuation))))
            hq = await user(session, "hq.director")
            await proposals.approve(session, hq, proposal_id)
            await session.commit()
        row = await _evacuation(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            hom = await user(session, "hom.nairobi")
            described = await evacuations.describe(session, row, DAY)
            result.activated = {
                "status": described.status,
                "step": described.step,
                "counts": described.counts,
                "seats": described.seats,
                "flagged": described.documents_flagged,
            }
            result.manifest = [
                (e.category or "", e.name, e.document_flag)
                for e in await evacuations.manifest(session, hom, row, DAY)
            ]
            result.partners = sorted(
                (p.code, r.service, r.status)
                for r, p in (
                    await session.execute(
                        select(PartnerRequest, Partner)
                        .join(Partner, Partner.id == PartnerRequest.partner_id)
                        .where(PartnerRequest.note.startswith(f"{row.reference} · "))
                    )
                ).all()
            )
            message = await session.scalar(
                select(NotificationCampaign).where(
                    NotificationCampaign.audience_filter["evacuation_id"].astext == str(row.id)
                )
            )
            assert message is not None
            result.message = (message.status, message.message)
        await _scene(engine, tenant_id, 1, publisher)
        row = await _evacuation(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            described = await evacuations.describe(session, row, DAY)
            result.after_scan = {"checked_in": described.checked_in, "step": described.step}
            hq = await user(session, "hq.director")
            result.seats = [e.seat for e in await evacuations.manifest(session, hq, row, DAY)]
        for n in (2, 3, 4):
            await _scene(engine, tenant_id, n, publisher)
            row = await _evacuation(engine, tenant_id)
            result.steps.append((row.step or 0, row.status))
    finally:
        await engine.dispose()
    return result


async def test_the_seed_has_a_plan_for_every_mission_and_nairobis_is_the_designs(
    played: Played,
) -> None:
    assert played.plans == 36
    assert played.nbo_plan == {
        "muster": "Embassy courtyard",
        "destination": "Dubai",
        "options": [
            ("Charter · Wilson Airport → Dubai", 72, "ATL"),
            ("Commercial · JKIA (seats held: 30)", 30, None),
            ("Road · Namanga border → Arusha", None, "SEN"),
        ],
    }
    assert played.gaps == ["EVP-BUE", "EVP-CBR"]  # no evacuation partner there (AS-07)


async def test_one_approval_activates_nothing_and_the_second_activates_evp_nbo(
    played: Played,
) -> None:
    assert played.after_first_approval == 0
    assert played.activated == {
        "status": "ACTIVE",
        "step": 2,
        # 12 diplomats, 3 delegates, 1 dependant; 4 needing help and 40 silent (EV-03)
        "counts": {"STAFF": 12, "DELEGATE": 3, "DEPENDANT": 1, "CITIZEN": 44},
        "seats": 72,
        "flagged": 2,
    }
    flagged = sorted(name or "" for _c, name, flag in played.manifest if flag)
    assert flagged == ["Aiko Takeda", "Hana Takeda"]


async def test_the_partners_are_asked_and_the_message_waits(played: Played) -> None:
    assert played.partners == [
        ("ATL", "EVACUATION", "REQUESTED"),
        ("SEN", "SECURE_TRANSPORT", "REQUESTED"),
    ]
    status, text = played.message
    assert status == "PENDING_APPROVAL"
    assert text.startswith("Evacuation of Nairobi is under way. Go to the Embassy courtyard")


async def test_the_scanner_checks_everyone_in_with_seats_1a_to_15d(played: Played) -> None:
    assert played.after_scan == {"checked_in": 60, "step": 3}
    assert played.seats[:5] == ["1A", "1B", "1C", "1D", "2A"]
    assert played.seats[-1] == "15D"
    assert len(set(played.seats)) == 60


async def test_the_convoy_the_charter_and_arrival_complete_it(played: Played) -> None:
    assert played.steps == [(4, "ACTIVE"), (5, "ACTIVE"), (6, "COMPLETED")]
