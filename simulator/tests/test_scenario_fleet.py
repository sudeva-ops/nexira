"""NBO-FLEET and the Fleet seed (D-41, FLT-01, FLT-08; docs/plan-pilot-flt.md §2, §9): the
scenario's content, and a play-through on the seeded world. Before NBO-CIVIL-UNREST, Nairobi
has 4 of 5 vehicles available; with INC-1042 ACTIVE (scenes 1-2 through the worker handlers)
VH-02 on Haile Selassie Ave is in the zone and the garage vehicles are at site (G-1); then
NBO-FLEET goes through the worker's handlers (G-4, G-7)."""

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.fleet import consumer
from app.modules.fleet import service as fleet
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.intel.models import IncidentEvent
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.scenarios import nbo_fleet
from nexira_sim.seed import data, world
from tests.scene_helpers import DAY, seed, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-999999999999")
EVENTS = nbo_fleet.build_events(world.build(DAY, TENANT), TENANT)


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    dlat = (a[0] - b[0]) * 111_320
    dlon = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3]
    assert nbo_fleet.build_events(world.build(DAY, TENANT), TENANT) == EVENTS
    # Nothing in the scenario sets a status by hand or approves anything (§58 Q7).
    assert {e.event_type for e in EVENTS} == {"SCENE_START", "VEHICLE_POSITION", "WORKSHOP_DONE"}


def test_vh04_leaves_the_residence_site_on_the_second_position_and_returns() -> None:
    positions = {
        n: [e.payload for e in sorted(EVENTS, key=lambda e: e.offset_ms) if e.scene_no == n
            and e.event_type == "VEHICLE_POSITION"]
        for n in (0, 1, 2)
    }  # fmt: skip
    for scene in positions.values():
        for p in scene:
            consumer.PositionIn.model_validate(p)
            assert p["asset_code"] == "VH-04"
    at = [metres((p["lat"], p["lon"]), data.RESIDENCE) for p in positions[1]]
    assert at[0] < fleet.AT_SITE_M < at[1]  # G-1: the second point leaves the site
    assert all(metres((p["lat"], p["lon"]), data.EPICENTRE) < 5_000 for p in positions[1])
    assert (positions[0][0]["lat"], positions[0][0]["lon"]) == data.RESIDENCE
    assert (positions[2][-1]["lat"], positions[2][-1]["lon"]) == data.RESIDENCE
    fuel = [p["fuel_pct"] for p in positions[1] + positions[2]]
    assert fuel == sorted(fuel, reverse=True)
    workshop = [e.payload for e in EVENTS if e.event_type == "WORKSHOP_DONE"]
    assert workshop == [{"asset_code": "VH-05", "task": "Brake service"}]
    consumer.WorkshopIn.model_validate(workshop[0])


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    assets: int = 0
    vehicles: int = 0
    armoured: int = 0
    nairobi: list[tuple[str, str, int, str, bool]] = field(default_factory=list)
    alerts: list[tuple[str, str, bool]] = field(default_factory=list)
    before: dict[str, Any] = field(default_factory=dict)
    during: dict[str, Any] = field(default_factory=dict)
    driver: tuple[str | None, str | None] = (None, None)
    after_scene: dict[int, dict[str, Any]] = field(default_factory=dict)
    timeline: list[str] = field(default_factory=list)


async def _nairobi(engine: Any, tenant_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id, engine) as session:
        duty = await user(session, "duty.officer")
        missions = {m.mission_code: m.mission_id for m in await fleet.list_assets(session, duty)}
        out = await fleet.mission_fleet(session, duty, missions["NBO"])
        assets = await fleet.list_assets(session, duty, missions["NBO"])
        return {
            "available": (out.available, out.vehicles),
            "seats": (out.capacity.seats_available, out.capacity.seats_needed),
            "states": {a.code: [t.code for t in a.tags] for a in assets if a.kind == "VEHICLE"},
        }


async def _scene(engine: Any, tenant_id: uuid.UUID, n: int) -> None:
    publisher = ListPublisher()
    handlers = {
        "VEHICLE_POSITION": consumer.position_handler(engine, publisher),
        "WORKSHOP_DONE": consumer.workshop_handler(engine, publisher),
    }
    for e in sorted(
        nbo_fleet.build_events(world.build(DAY, tenant_id), tenant_id), key=lambda e: e.offset_ms
    ):
        if e.scene_no == n and e.event_type in handlers:
            await handlers[e.event_type](
                Event(e.event_type, tenant_id, dict(e.payload), "scenario")
            )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            duty = await user(session, "duty.officer")
            viewer = await user(session, "viewer")
            every = await fleet.list_assets(session, duty)
            result.assets = len(every)
            vehicles = [a for a in every if a.kind == "VEHICLE"]
            result.vehicles, result.armoured = len(vehicles), sum(a.armoured for a in vehicles)
            result.nairobi = [
                (a.code, a.type_label, a.fuel_pct, a.status, a.at_site)
                for a in every
                if a.mission_code == "NBO"
            ]
            result.alerts = [
                (m.asset_code, m.task, m.overdue)
                for m in await fleet.maintenance(session, DAY)
                if m.alert
            ]
            vh02 = {a.code: a for a in every}["VH-02"]
            seen = {a.code: a for a in await fleet.list_assets(session, viewer)}["VH-02"]
            result.driver = (vh02.driver_name, seen.driver_name)
        result.before = await _nairobi(engine, tenant_id)
        # NBO-CIVIL-UNREST scenes 1-2 through the worker handlers (as scene_helpers).
        incidents, out = ListPublisher(), ListPublisher()
        on_signal = raw_signal_handler(engine, incidents)
        on_incident = exposure_handler(engine, out)
        for e in nbo.build_events(world.build(DAY, tenant_id), tenant_id):
            if e.event_type == "RAW_SIGNAL" and e.payload["place_label"] != "Paris":
                await on_signal(Event("RAW_SIGNAL", tenant_id, dict(e.payload), "test"))
        for published in incidents.events:
            if published.type.startswith("INCIDENT_"):
                await on_incident(published)
        result.during = await _nairobi(engine, tenant_id)
        for n in (0, 1, 2, 3):
            await _scene(engine, tenant_id, n)
            result.after_scene[n] = await _nairobi(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            result.timeline = list(
                await session.scalars(
                    select(IncidentEvent.summary)
                    .where(IncidentEvent.event_type == "FLEET")
                    .order_by(IncidentEvent.id)
                )
            )
    finally:
        await engine.dispose()
    return result


async def test_the_register_has_48_vehicles_19_armoured_and_nairobi_is_the_designs(
    played: Played,
) -> None:
    assert (played.vehicles, played.armoured) == (48, 19)
    assert played.assets == 48 + 2 * 36  # a generator and a satellite terminal everywhere
    assert played.nairobi == [
        ("VH-01", "Armoured SUV (B6)", 82, "AVAILABLE", True),
        ("VH-02", "Armoured SUV (B6)", 46, "IN_USE", False),
        ("VH-03", "Minibus 14-seat", 90, "AVAILABLE", True),
        ("VH-04", "Pickup 4x4", 64, "AVAILABLE", True),
        ("VH-05", "Sedan (official)", 30, "MAINTENANCE", True),
        ("GEN-NBO", "Generator 250 kVA", 72, "AVAILABLE", True),
        ("SAT-NBO", "Satellite terminal", 100, "AVAILABLE", True),
    ]
    assert played.driver == ("Peter Mwangi", None)  # names only within the scope (G-8)


async def test_the_maintenance_alerts_are_the_designs(played: Played) -> None:
    assert played.alerts == [
        ("VH-05", "Brake service", True),
        ("VH-21", "Tyre replacement (run-flat)", False),
        ("GEN-ISB", "Load test", False),
    ]  # VH-11's armour inspection is 30 days out: not yet an alert


async def test_nairobi_before_and_during_the_unrest(played: Played) -> None:
    assert played.before == {
        "available": (4, 5),
        "seats": (24, 16),  # 12 diplomats, 3 delegates and a dependant
        "states": {
            "VH-01": [],
            "VH-02": [],
            "VH-03": [],
            "VH-04": [],
            "VH-05": ["MAINTENANCE"],
        },
    }
    # INC-1042 ACTIVE: VH-02 on the road is in the zone; the garage and residence are at site.
    assert played.during["available"] == (3, 5)
    assert played.during["seats"] == (20, 16)
    assert played.during["states"]["VH-02"] == ["IN_ZONE"]
    assert played.during["states"]["VH-01"] == played.during["states"]["VH-04"] == []


async def test_nbo_fleet_drives_vh04_in_and_out_and_returns_vh05(played: Played) -> None:
    assert played.after_scene[0]["states"]["VH-04"] == []
    assert played.after_scene[1]["states"]["VH-04"] == ["IN_ZONE"]
    assert played.after_scene[1]["available"] == (2, 5)
    assert played.after_scene[2]["states"]["VH-04"] == []
    assert played.after_scene[3]["states"]["VH-05"] == []
    assert played.after_scene[3]["available"] == (4, 5)
    assert played.after_scene[3]["seats"] == (23, 16)
    year = DAY.year
    assert played.timeline == [
        f"VH-04 entered the impact zone of INC-{year}-1042 · Waiyaki Way.",
        f"VH-04 left the impact zone of INC-{year}-1042 · Residence.",
    ]
