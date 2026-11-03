"""NBO-SUPPLY and the Supply Chain seed (D-44, SUP-01, SUP-07; docs/plan-pilot-sup.md §2, §3,
§8): the scenario's content, the seeded register and routes against the plan's constraints, and
a play-through on the seeded world after NBO-CIVIL-UNREST scenes 1-2, through the worker's
handlers (with a replay, G-6). The Phase 1 scenario still starts with no active incident and an
empty Decision Queue, and nothing is mitigated or sent by the scenario."""

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents.models import AgentProposal
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.supply import consumer
from app.modules.supply import service as supply
from app.modules.supply.schemas import SummaryOut, SupplierOut
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import func, select, text

from nexira_sim.scenarios import nbo_supply
from nexira_sim.seed import data, world
from tests.scene_helpers import DAY, seed, seeded_incident, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-cccccccccccc")
W = world.build(DAY, TENANT)
EVENTS = nbo_supply.build_events(W, TENANT)
# The design's ten (plan §2): code -> (name, service, mission, tier).
DESIGN = {
    "SUP-104": ("Swiftline Couriers", "Diplomatic pouch courier", "NBO", 1),
    "SUP-117": ("Equator Guard Services", "Guard force contractor", "NBO", 1),
    "SUP-121": ("Rift Valley Fuels", "Generator fuel supply", "NBO", 2),
    "SUP-126": ("Savanna IT Networks", "Local ISP & IT support", "NBO", 1),
    "SUP-130": ("Kilima Catering", "Catering services", "NBO", 3),
    "SUP-208": ("Gulfstar Logistics", "Freight & relocation", "RUH", 2),
    "SUP-233": ("Nile Secure Mobility", "Armoured vehicle leasing", "CAI", 1),
    "SUP-251": ("Indus Facilities", "Facilities management", "ISB", 2),
    "SUP-262": ("Archipelago Movers", "Local transport", "JKT", 3),
    "SUP-305": ("Northbridge Translations", "Interpretation services", None, 3),
}


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3]
    assert nbo_supply.build_events(world.build(DAY, TENANT), TENANT) == EVENTS
    # Reported statuses only: nothing mitigates, approves or proposes.
    assert {e.event_type for e in EVENTS} == {"SCENE_START", "SUPPLY_ROUTE", "SUPPLY_SUPPLIER"}
    assert [e.event_type for e in EVENTS if e.scene_no == 0] == ["SCENE_START"]
    for e in EVENTS:
        if e.event_type == "SUPPLY_ROUTE":
            consumer.RouteIn.model_validate(e.payload)
        elif e.event_type == "SUPPLY_SUPPLIER":
            consumer.SupplierIn.model_validate(e.payload)
    # Scene 1 resets before it blocks (G-6), so the block is its last event.
    scene_1 = [e for e in EVENTS if e.scene_no == 1]
    assert scene_1[-1].payload == {
        "route": "R-NBO-1",
        "status": "BLOCKED",
        "detail": nbo_supply.ROAD_CLOSED,
    }
    assert len({e.id for e in EVENTS}) == len(EVENTS)


# --- the seed ----------------------------------------------------------------------------------


@dataclass
class Played:
    suppliers: dict[str, SupplierOut] = field(default_factory=dict)
    seeded_summary: SummaryOut | None = None
    routes: dict[str, Any] = field(default_factory=dict)
    before: tuple[int, int] = (0, 0)  # active incidents, proposals
    after: dict[str, SummaryOut] = field(default_factory=dict)
    timeline: list[str] = field(default_factory=list)
    mitigations: int = 0
    sent: tuple[int, int] = (0, 0)
    sent_after: tuple[int, int] = (0, 0)


async def _summary(engine: Any, tenant_id: uuid.UUID) -> SummaryOut:
    async with tenant_session(tenant_id, engine) as session:
        return await supply.summary(session, await user(session, "duty.officer"), DAY)


async def _sent(engine: Any, tenant_id: uuid.UUID) -> tuple[int, int]:
    async with tenant_session(tenant_id, engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM notification_campaign) AS c, "
                    "(SELECT count(*) FROM partner_request) AS p"
                )
            )
        ).one()
        return int(row.c), int(row.p)


async def _scene(engine: Any, tenant_id: uuid.UUID, n: int) -> None:
    publisher = ListPublisher()
    handlers = {
        "SUPPLY_ROUTE": consumer.route_handler(engine, publisher),
        "SUPPLY_SUPPLIER": consumer.supplier_handler(engine, publisher),
    }
    events = nbo_supply.build_events(world.build(DAY, tenant_id), tenant_id)
    for e in sorted(events, key=lambda e: e.offset_ms):
        if e.scene_no == n and e.event_type in handlers:
            source = f"scenario:{nbo_supply.CODE}:test"
            await handlers[e.event_type](Event(e.event_type, tenant_id, dict(e.payload), source))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    result = Played()
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seed(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            result.before = (
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(Incident)
                        .where(Incident.status == "ACTIVE")
                    )
                    or 0
                ),
                int(await session.scalar(select(func.count()).select_from(AgentProposal)) or 0),
            )
            duty = await user(session, "duty.officer")
            result.suppliers = {s.code: s for s in await supply.list_suppliers(session, duty, DAY)}
            result.routes = {r.code: r for r in await supply.list_routes(session, duty, DAY)}
        result.seeded_summary = await _summary(engine, tenant_id)
    finally:
        await engine.dispose()
    # A second tenant with INC-1042 ACTIVE (NBO-CIVIL-UNREST scenes 1-2), then NBO-SUPPLY twice.
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seeded_incident(db, engine, tenant_id)
        result.sent = await _sent(engine, tenant_id)
        result.after["seeded"] = await _summary(engine, tenant_id)
        for run in ("first", "replay"):
            for n in (1, 2, 3):
                await _scene(engine, tenant_id, n)
                result.after[f"{run}:{n}"] = await _summary(engine, tenant_id)
        result.sent_after = await _sent(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            result.timeline = list(
                await session.scalars(
                    select(IncidentEvent.summary)
                    .where(IncidentEvent.event_type == "SUPPLY")
                    .order_by(IncidentEvent.id)
                )
            )
            result.mitigations = int(
                await session.scalar(text("SELECT count(*) FROM supply_mitigation")) or 0
            )
    finally:
        await engine.dispose()
    return result


async def test_the_register_meets_the_plan(played: Played) -> None:
    found = played.suppliers
    assert len(found) == 52
    assert len({s.mission_code for s in found.values() if s.mission_code}) == 36
    assert sum(1 for s in found.values() if s.tier == 1) == 14
    for code, (name, service, mission, tier) in DESIGN.items():
        s = found[code]
        assert (s.name, s.service, s.mission_code, s.tier) == (name, service, mission, tier), code
    # G-2: every Tier 1 and 2 supplier that is not itself a backup has a backup with the same
    # service, at its mission or Global.
    backups = {s.backup.code for s in found.values() if s.backup}
    for s in found.values():
        if s.tier <= 2 and s.code not in backups:
            assert s.backup is not None, s.code
            backup = found[s.backup.code]
            assert backup.service == s.service, s.code
            assert backup.mission_code in (None, s.mission_code), s.code
    assert found["SUP-104"].backup is not None
    assert found["SUP-104"].backup.name == "Falcon Express Couriers"
    assert {c for c, s in found.items() if s.status == "WATCH"} == {"SUP-251", "SUP-262"}
    assert all(s.vetting_current for s in found.values())
    assert all(s.in_bcp == (s.tier == 1) for s in found.values())
    assert found["SUP-104"].performance_score == 92
    assert found["SUP-121"].fuel_stock_hours == 72  # GEN-NBO 72% (G-7)
    assert all(s.source == "Illustrative supplier register (simulated)" for s in found.values())


async def test_the_routes_meet_the_plan(played: Played) -> None:
    routes = played.routes
    assert len(routes) == 37
    nairobi = {c: r for c, r in routes.items() if r.mission_code == "NBO"}
    shape = {c: (r.label, r.kind, r.supplier_code, r.alternate_of_code) for c, r in nairobi.items()}
    assert shape == {
        "R-NBO-1": ("Pouch: Embassy → JKIA via CBD", "POUCH", "SUP-104", None),
        "R-NBO-2": ("Pouch: Embassy → JKIA via Southern Bypass", "POUCH", "SUP-104", "R-NBO-1"),
        "R-NBO-3": ("Fuel: depot → Embassy", "FUEL", "SUP-121", None),
        "R-NBO-4": ("Staff shuttle: Westlands → Embassy", "STAFF_TRANSPORT", "SUP-117", None),
    }  # fmt: skip
    missions = {r.mission_code for r in routes.values()}
    assert not missions & data.SUPPLY_NO_ROUTE  # G-3
    assert len(missions) == 34
    assert all(r.status == "OPEN" for r in routes.values())
    assert all(r.supplier_code for r in routes.values())


async def test_phase_1_still_starts_with_no_incident_and_nothing_impacted(played: Played) -> None:
    assert played.before == (0, 0)
    s = played.seeded_summary
    assert s is not None
    assert (s.suppliers, s.missions, s.tier1, s.impacted, s.routes) == (52, 36, 14, 0, 37)


async def test_nbo_supply_blocks_impacts_three_and_recovers(played: Played) -> None:
    assert played.after["seeded"].impacted == 0  # INC-1042 ACTIVE, but nothing disrupted
    first = played.after["first:1"]
    assert (first.impacted, [s.code for b in first.banners for s in b.suppliers]) == (
        1,
        ["SUP-104"],
    )
    second = played.after["first:2"]
    [banner] = second.banners
    assert banner.incident_reference == f"INC-{DAY.year}-1042"
    assert [(s.code, s.shown) for s in banner.suppliers] == [
        ("SUP-104", "ROUTE_BLOCKED"),
        ("SUP-117", "AT_RISK"),
        ("SUP-121", "DELAYED"),
    ]
    assert played.after["first:3"].impacted == 0


async def test_a_replay_starts_from_the_seed(played: Played) -> None:
    assert [played.after[f"replay:{n}"].impacted for n in (1, 2, 3)] == [1, 3, 0]


async def test_the_timeline_has_ten_entries_a_run(played: Played) -> None:
    assert len(played.timeline) == 20  # plan §8: 1 + 4 + 5, twice
    assert played.timeline[:10] == played.timeline[10:]
    assert played.timeline[0] == (
        "Nairobi · Pouch: Embassy → JKIA via CBD: BLOCKED "
        "(Road closure CBD → JKIA; reroute via Southern Bypass, +55 min)."
    )
    guards = (
        "Nairobi · Equator Guard Services: AT RISK "
        "(18:00 shift change: 6 guards must cross the impact zone)."
    )
    assert guards in played.timeline


async def test_the_scenario_mitigates_and_sends_nothing(played: Played) -> None:
    assert played.mitigations == 0
    assert played.sent_after == played.sent
