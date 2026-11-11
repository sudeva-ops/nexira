"""The Site Twin's normal day (TWN-13; D-53; docs/plan-pilot-twa.md §2, G-1..G-4): the choice of
move (pure), a tick through twin.service.presence() audited like any presence move, the pauses
(shelter, an ACTIVE evacuation, an NBO-SITE run mid-scenario) and the switch (a flag per tenant,
then the default, then the setting), with the presenter's audited API. Real PostgreSQL."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.main import app
from app.modules.scenarios.router import get_flags
from app.modules.twin import ambient
from app.modules.twin.ambient import Occupant, Plan, next_move, plan_of
from app.tests.auth_helpers import Idp
from app.tests.test_twin import EMBASSY, World, _shelter_run, make_world, pt

T0 = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)
PLAN = Plan(gate="g1", lobby="lob", consular="cons", office="ch", conference="conf", muster="must")


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    return await make_world(client, idp)


class MemoryFlags:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str) -> object:
        self.values[name] = value
        return True


def occ(key: str, kind: str, zone: str, minutes: int = 0) -> Occupant:
    return Occupant(key=key, kind=kind, zone=zone, since=T0 + timedelta(minutes=minutes))


def visitors(n: int, zone: str = "cons") -> list[Occupant]:
    return [occ(f"Visitor {i}", "VISITOR", zone, i) for i in range(1, n + 1)]


# --- choosing a move (pure) ----------------------------------------------------------------------


def test_the_plan_is_read_from_the_zones_kinds() -> None:
    zones = [
        ("g2", "GATE"),
        ("g1", "GATE"),
        ("lob", "LOBBY"),
        ("ch", "OFFICE"),
        ("cons", "CONSULAR"),
    ]
    assert plan_of(zones) == Plan(
        gate="g1", lobby="lob", consular="cons", office="ch", conference=None, muster=None
    )


def test_a_visitor_comes_in_waits_is_seen_and_leaves() -> None:
    at_gate = [*visitors(7), occ("Visitor 9", "VISITOR", "g1", 30)]
    assert next_move(PLAN, at_gate, 0) == ("Visitor 9", "lob")  # admit
    waiting = [*visitors(7), occ("Visitor 9", "VISITOR", "lob", 30)]
    assert next_move(PLAN, waiting, 1) == ("Visitor 9", "cons")  # consult
    assert next_move(PLAN, visitors(8), 2) == ("Visitor 1", None)  # the longest seen leaves
    assert next_move(PLAN, visitors(8), 3) == ("Visitor 9", "g1")  # the first absent arrives


def test_the_site_keeps_its_band_of_visitors() -> None:
    six = visitors(6)
    assert next_move(PLAN, six, 2) != ("Visitor 1", None)  # no one leaves below seven
    eleven = visitors(11)
    move = next_move(PLAN, eleven, 3)
    assert move is None or move[1] != "g1"  # no one arrives at eleven


def test_staff_go_to_the_conference_room_and_back_and_a_guard_walks_a_round() -> None:
    staff = [occ("a", "STAFF", "ch"), occ("b", "STAFF", "conf"), occ("c", "STAFF", "comms")]
    assert next_move(PLAN, staff, 4) == ("a", "conf")
    assert next_move(PLAN, staff, 10) == ("b", "ch")
    assert next_move(PLAN, staff, 16) is not None  # the IT team stays: another move is chosen
    guards = [occ("Guard 1", "GUARD", "g1"), occ("Guard 3", "GUARD", "lob")]
    assert next_move(PLAN, guards, 5) == ("Guard 3", "must")
    assert next_move(PLAN, [occ("Guard 3", "GUARD", "must")], 5) == ("Guard 3", "lob")


def test_a_move_with_nothing_to_do_hands_over_to_the_next() -> None:
    assert next_move(PLAN, visitors(6), 0) == ("Visitor 7", "g1")  # admit, consult, leave: none
    assert next_move(PLAN, [], 0) == ("Visitor 1", "g1")
    assert next_move(Plan(None, None, None, None, None, None), visitors(3), 0) is None


def test_the_pace_is_about_a_minute() -> None:
    waits = [ambient.wait_s(step) for step in range(200)]
    assert min(waits) >= 45
    assert max(waits) <= 75
    assert len(set(waits)) > 10


# --- the switch (G-2) ----------------------------------------------------------------------------


async def test_the_switch_is_the_tenants_then_the_default_then_the_setting() -> None:
    flags = MemoryFlags()
    tenant = uuid.uuid4()
    assert await ambient.is_on(flags, tenant, True) is True
    assert await ambient.is_on(flags, tenant, False) is False
    flags.values[f"{ambient.FLAG}default"] = "off"  # make reset-demo
    assert await ambient.is_on(flags, tenant, True) is False
    await ambient.switch(flags, tenant, True)  # the presenter
    assert await ambient.is_on(flags, tenant, False) is True
    assert await ambient.is_on(flags, uuid.uuid4(), True) is False  # another tenant: the default


# --- a tick on the database ----------------------------------------------------------------------


async def _tick(world: World, flags: MemoryFlags, step: int = 0, on: bool = True) -> int:
    return await ambient.tick(
        world.idp.engine, world.idp.tenant_id, world.publisher, flags, step, on
    )


async def test_a_tick_moves_one_occupant_audited_and_published(world: World) -> None:
    flags = MemoryFlags()
    assert await _tick(world, flags) == 1
    # Two visitors on site, none at the gate or in a lobby: the first absent visitor arrives.
    occupants = {
        (o["label"], o["zone_code"]) for o in (await world.twin())["occupants"] if o["label"]
    }
    assert ("Visitor 3", "g1") in occupants
    [moved] = await world.audit("SITE.PRESENCE")
    assert (moved.actor_type, moved.details) == (
        "SYSTEM",
        {"kind": "VISITOR", "from": None, "to": "g1", "label": "Visitor 3"},
    )
    assert [e.type for e in world.publisher.events] == ["SITE_UPDATED"]
    assert await _tick(world, flags, step=4) == 1  # a staff member goes to a meeting
    assert len(await world.audit("SITE.PRESENCE")) == 2


async def test_switched_off_nothing_moves(world: World) -> None:
    flags = MemoryFlags()
    assert await _tick(world, flags, on=False) == 0
    await ambient.switch(flags, world.idp.tenant_id, False)
    assert await _tick(world, flags, on=True) == 0
    assert await world.audit("SITE.PRESENCE") == []


async def test_it_waits_while_the_site_shelters(world: World) -> None:
    incident = await world.incident()
    await _shelter_run(world, incident, "DONE")
    assert await _tick(world, MemoryFlags()) == 0
    await world.sql("UPDATE incident SET status = 'MONITORING' WHERE id = :i", i=incident)
    assert await _tick(world, MemoryFlags()) == 1


async def test_it_waits_while_the_mission_evacuates(world: World) -> None:
    await world.sql(
        "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
        "muster_location, route_label, destination, options) VALUES (current_tenant_id(), :m, "
        "'EVP-NBO', 'Courtyard', :pt, 'Route B', 'Dubai', "
        '\'[{"role": "PRIMARY", "kind": "CHARTER", "label": "C", "seats": 72}]\')',
        m=world.nbo,
        pt=pt(EMBASSY),
    )
    await world.sql(
        "INSERT INTO evacuation (tenant_id, reference, plan_id, mission_id, requested_by, "
        "requested_role) SELECT current_tenant_id(), 'EVN-1001', id, mission_id, :u, "
        "'HQ_CRISIS_DIRECTOR' FROM evacuation_plan",
        u=world.users["duty"],
    )
    assert await _tick(world, MemoryFlags()) == 1  # requested, not yet active
    await world.sql(
        "UPDATE evacuation SET status = 'ACTIVE', activated_by = :a, step = 2",
        a=world.users["hom.nbo"],
    )
    assert await _tick(world, MemoryFlags()) == 0


async def test_it_waits_while_nbo_site_is_mid_scenario(world: World) -> None:
    await world.sql(
        """
        WITH s AS (INSERT INTO scenario (tenant_id, code, name)
                   VALUES (current_tenant_id(), 'NBO-SITE', 'Site') RETURNING id)
        INSERT INTO scenario_event (tenant_id, scenario_id, scene_no, offset_ms, event_type,
                                    payload)
        SELECT current_tenant_id(), s.id, n, 0, 'SCENE_START', '{}' FROM s,
               generate_series(0, 3) AS n
        """
    )
    await world.sql(
        "INSERT INTO scenario_run (tenant_id, scenario_id, status, current_scene) "
        "SELECT current_tenant_id(), id, 'PAUSED', 2 FROM scenario"
    )
    assert await _tick(world, MemoryFlags()) == 0  # sheltering in the scenario
    await world.sql("UPDATE scenario_run SET status = 'PLAYING', current_scene = 3")
    assert await _tick(world, MemoryFlags()) == 0
    await world.sql("UPDATE scenario_run SET status = 'PAUSED'")  # scene 3 done: recovered
    assert await _tick(world, MemoryFlags()) == 1


# --- the presenter's switch (G-2) ---------------------------------------------------------------


@pytest.fixture
def flags() -> MemoryFlags:
    store = MemoryFlags()
    app.dependency_overrides[get_flags] = lambda: store
    return store


async def test_the_presenter_switches_it_audited(world: World, flags: MemoryFlags) -> None:
    on = await world.send("duty", "GET", "/api/scenarios/normal-day")
    assert (on.status_code, on.json()) == (200, {"on": True})  # TWIN_NORMAL_DAY's default
    off = await world.send("duty", "POST", "/api/scenarios/normal-day", {"on": False})
    assert (off.status_code, off.json()) == (200, {"on": False})
    assert flags.values == {f"{ambient.FLAG}{world.idp.tenant_id}": "off"}
    assert (await world.send("duty", "GET", "/api/scenarios/normal-day")).json() == {"on": False}
    [switched] = await world.audit("SITE.NORMAL_DAY")
    assert (switched.actor_type, switched.details) == ("USER", {"on": False})
    for who in ("viewer", "security"):
        assert (await world.send(who, "GET", "/api/scenarios/normal-day")).status_code == 403
        refused = await world.send(who, "POST", "/api/scenarios/normal-day", {"on": True})
        assert refused.status_code == 403
