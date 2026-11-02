"""ADD-VISIT and the VIP seed (D-42, VIP-01, VIP-08; docs/plan-pilot-vip.md §2, §9): the
scenario's content, the seeded visit as the design, and a play-through on the seeded world
through the worker's handlers and the agents (the in-memory bus of the Nairobi agents test).
The Phase 1 scenario still starts with no active incident and an empty Decision Queue."""

import math
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents.models import AgentProposal
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident
from app.modules.playbooks.models import PlaybookRun
from app.modules.travel.models import Trip, TripTraveller
from app.modules.vip import consumer
from app.modules.vip import service as vip
from app.modules.vip.schemas import VisitOut
from app.tests.conftest import DbUrls
from sqlalchemy import func, select

from nexira_sim.scenarios import add_visit
from nexira_sim.seed import data, world
from tests.scene_helpers import DAY, seed, user
from tests.test_agents_nbo import Bus

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-aaaaaaaaaaaa")
W = world.build(DAY, TENANT)
EVENTS = add_visit.build_events(W, TENANT)
REFERENCE = f"VV-{DAY.year}-031"


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (a[0] - b[0]) * 111_320
    dlon = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3]
    assert add_visit.build_events(world.build(DAY, TENANT), TENANT) == EVENTS
    # Progress and one signal: nothing approves, proposes or moves a position (VIP-04, VIP-08).
    assert {e.event_type for e in EVENTS} == {"SCENE_START", "VIP_PROGRESS", "RAW_SIGNAL"}
    assert [e.event_type for e in EVENTS if e.scene_no == 0] == ["SCENE_START"]
    for e in EVENTS:
        if e.event_type == "VIP_PROGRESS":
            consumer.ProgressIn.model_validate(e.payload)
            assert e.payload["visit"] == REFERENCE


def test_the_rally_is_1_2_km_from_the_park_and_far_from_the_city() -> None:
    rally = next(e.payload for e in EVENTS if e.event_type == "RAW_SIGNAL")
    at = (rally["lat"], rally["lon"])
    assert rally["provider_severity"] == "Medium"  # MODERATE: PB-07 needs HIGH
    assert 1_150 < metres(at, data.INDUSTRIAL_PARK) < 1_250
    assert 10_500 < metres(data.INDUSTRIAL_PARK, data.AIRPORT_ADD) < 11_500  # G-4
    for _kind, _title, venue, where, *_ in data.VIP_SEGMENTS:
        if venue != "Industrial park":
            # Beyond the 5 km zone plus 5 km: no reason for any other segment.
            assert metres(at, where) > 10_000, venue
    mission = next(m for m in data.MISSIONS if m[0] == "ADD")
    assert metres(at, (mission[4], mission[5])) > 15_000


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    seeded: VisitOut | None = None
    viewer: list[Any] = field(default_factory=list)
    trip: tuple[str, bool, str, int] | None = None
    before: tuple[int, int, int] = (0, 0, 0)  # active incidents, proposals, runs
    after: dict[int, VisitOut] = field(default_factory=dict)
    incident: tuple[str, str, str, Any] | None = None
    proposals: list[tuple[str, str, int]] = field(default_factory=list)
    runs: int = 0
    audit: list[tuple[str, str, str | None]] = field(default_factory=list)
    officer: uuid.UUID | None = None


async def _visit(engine: Any, tenant_id: uuid.UUID) -> VisitOut:
    async with tenant_session(tenant_id, engine) as session:
        security = await user(session, "security.officer")
        visit_id = (await vip.list_visits(session, security))[0].id
        return await vip.visit_out(session, security, visit_id, DAY)


async def _counts(engine: Any, tenant_id: uuid.UUID) -> tuple[int, int, int]:
    async with tenant_session(tenant_id, engine) as session:
        return (
            int(
                await session.scalar(
                    select(func.count()).select_from(Incident).where(Incident.status == "ACTIVE")
                )
                or 0
            ),
            int(await session.scalar(select(func.count()).select_from(AgentProposal)) or 0),
            int(await session.scalar(select(func.count()).select_from(PlaybookRun)) or 0),
        )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed(db, engine, tenant_id)
        result.seeded = await _visit(engine, tenant_id)
        result.before = await _counts(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            result.viewer = await vip.list_visits(session, await user(session, "viewer"))
            result.officer = (await user(session, "security.officer")).id
            trip = await session.scalar(select(Trip).where(Trip.reference == "TRP-8834"))
            assert trip is not None
            travellers = await session.scalar(
                select(func.count())
                .select_from(TripTraveller)
                .where(TripTraveller.trip_id == trip.id)
            )
            result.trip = (trip.reference, trip.restricted, trip.approval_status, travellers or 0)
        bus = Bus(engine)
        bus.routes["VIP_PROGRESS"] = [consumer.progress_handler(engine)]
        events = add_visit.build_events(world.build(DAY, tenant_id), tenant_id)
        for n in (0, 1, 2, 3):
            await bus.deliver(
                [
                    Event(e.event_type, tenant_id, dict(e.payload), "scenario")
                    for e in sorted(events, key=lambda e: e.offset_ms)
                    if e.scene_no == n and e.event_type != "SCENE_START"
                ]
            )
            result.after[n] = await _visit(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            incident = await session.scalar(select(Incident))
            assert incident is not None
            result.incident = (
                incident.reference,
                incident.category,
                incident.severity,
                incident.mission_id,
            )
            result.proposals = [
                (p.action_type, p.status, p.effective_level)
                for p in await session.scalars(select(AgentProposal))
            ]
            result.runs = int(
                await session.scalar(select(func.count()).select_from(PlaybookRun)) or 0
            )
            result.audit = [
                (a.action, a.actor_type, a.actor_id)
                for a in await session.scalars(
                    select(AuditLog).where(AuditLog.action.like("VIP.%")).order_by(AuditLog.id)
                )
            ]
    finally:
        await engine.dispose()
    return result


async def test_the_seeded_visit_is_the_designs(played: Played) -> None:
    visit = played.seeded
    assert visit is not None
    assert (visit.reference, visit.title, visit.status) == (
        REFERENCE,
        "Minister's visit to Addis Ababa",
        "PLANNED",
    )
    assert (visit.mission_code, visit.principal_role) == ("ADD", "Minister of Foreign Affairs")
    first = DAY + timedelta(days=4)
    assert (visit.starts_on, visit.ends_on) == (first, first + timedelta(days=2))
    assert [(s.kind, s.attendees) for s in visit.segments] == [
        ("ARRIVAL", None),
        ("MOTORCADE", None),
        ("MEETING", None),
        ("EVENT", 600),
        ("SITE_VISIT", None),
        ("DEPARTURE", None),
    ]
    # 09:30 in Addis Ababa is 06:30 UTC; the motorcade lasts 14 minutes.
    arrival, motorcade = visit.segments[0], visit.segments[1]
    assert (arrival.starts_at.date(), arrival.starts_at.hour, arrival.starts_at.minute) == (
        first,
        6,
        30,
    )
    assert motorcade.ends_at is not None
    assert motorcade.ends_at - motorcade.starts_at == timedelta(minutes=14)
    # VIP-02 before the demo: the motorcade and the forum MODERATE, the visit MODERATE.
    assert [s.risk for s in visit.segments] == [
        "LOW", "MODERATE", "LOW", "MODERATE", "LOW", "LOW"
    ]  # fmt: skip
    assert (visit.risk, visit.country_risk) == ("MODERATE", "MODERATE")
    assert visit.trip_reference == "TRP-8834"


async def test_the_detail_and_the_checklist_are_the_designs(played: Played) -> None:
    visit = played.seeded
    assert visit is not None
    detail = visit.detail
    assert [(v.code, v.armoured) for v in detail.vehicles] == [("VH-11", True), ("VH-12", True)]
    assert all(v.state != "UNKNOWN" for v in detail.vehicles)
    assert detail.medical.facility_name is not None
    assert detail.medical.partner_name is not None
    assert "Kestrel" in detail.medical.partner_name
    assert detail.safe_havens[:2] == ["Embassy", "Hotel safe floor"]
    assert detail.safe_havens[2] == detail.medical.facility_name
    first = DAY + timedelta(days=4)
    assert [(c.label, c.done, c.due_on) for c in visit.checklist][-1] == (
        "Industrial park venue survey",
        False,
        first - timedelta(days=1),
    )
    assert sum(c.done for c in visit.checklist) == 3
    assert all(c.done_by_name for c in visit.checklist if c.done)
    kpis = visit.kpis
    assert (kpis.segments, kpis.high, kpis.team_size, kpis.vehicles, kpis.medics) == (6, 0, 8, 2, 1)
    assert (kpis.venues_surveyed, kpis.venues) == (4, 5)  # G-2: the design's 4 / 5


async def test_the_restricted_trip_and_nobody_else_sees_the_visit(played: Played) -> None:
    assert played.trip == ("TRP-8834", True, "APPROVED", 2)
    assert played.viewer == []


async def test_phase_1_still_starts_with_no_incident_and_an_empty_queue(played: Played) -> None:
    assert played.before == (0, 0, 0)


async def test_add_visit_plays_live_rally_forum(played: Played) -> None:
    status = {n: [s.status for s in v.segments] for n, v in played.after.items()}
    assert played.after[0].status == "PLANNED"
    assert played.after[1].status == "LIVE"
    assert status[1] == ["COMPLETED", "IN_PROGRESS", "PLANNED", "PLANNED", "PLANNED", "PLANNED"]
    # Scene 2: the rally opens an incident and the site visit turns HIGH (VIP-02).
    assert played.incident is not None
    reference, category, severity, mission = played.incident
    assert (category, severity, mission) == ("CIVIL_UNREST", "MODERATE", None)  # no site near
    site = played.after[2].segments[4]
    assert site.risk == "HIGH"
    assert [r.text for r in site.reasons] == [f"civil unrest 1.2 km away · {reference}"]
    assert site.recommendation == vip.RECOMMENDATION
    assert [s.risk for s in played.after[2].segments[:4]] == ["LOW", "MODERATE", "LOW", "MODERATE"]
    assert played.after[2].risk == "HIGH"
    # Scene 3: the motorcade, the meeting and the forum completed; the visit still LIVE.
    assert status[3] == ["COMPLETED"] * 4 + ["PLANNED", "PLANNED"]
    assert played.after[3].status == "LIVE"
    assert played.after[3].risk == "HIGH"


async def test_the_rally_proposes_nothing(played: Played) -> None:
    # MODERATE and nobody exposed: no PB-07 and nothing for the Decision Queue (plan §9); only
    # the Watch Officer's automatic log of a new incident (level 0), which names no visit.
    assert played.proposals == [("LOG_INFO", "AUTO_EXECUTED", 0)]
    assert played.runs == 0


async def test_progress_is_audited_as_the_simulated_system(played: Played) -> None:
    progress = ("SYSTEM", "visit progress (simulated)")
    assert played.audit[0] == ("VIP.SEED", "SYSTEM", "seed")
    assert played.audit[1] == ("VIP.START", *progress)
    assert [a for a, *_ in played.audit[2:]] == ["VIP.SEGMENT"] * 8
    assert {(t, i) for _, t, i in played.audit[1:]} == {progress}
    assert played.after[1].started_at is not None
