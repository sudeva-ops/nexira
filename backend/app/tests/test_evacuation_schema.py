"""Migration 0010 (PC-30..32; D-40), checked as nexira_api: plans are seeded reference data
with checked options; an evacuation is requested by one person and activated by another,
its sequence moves forward one step at a time, and complete or stood down is final; the
manifest is built only in the activating transaction and changes only by one check-in
(docs/plan-pilot-ev.md §3-§8, §13)."""

import asyncio
import json
import uuid
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
PT = "'SRID=4326;POINT(36.82 -1.29)'"
ACTIVATE = "UPDATE evacuation SET status = 'ACTIVE', activated_by = $2, step = 2 WHERE id = $1"
CHARTER = {"role": "PRIMARY", "kind": "CHARTER", "label": "Wilson Airport → Dubai", "seats": 72}


async def mission(conn: asyncpg.Connection, code: str = "NBO") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Nairobi', 'KE', {PT})",
        mission_id,
        code,
    )
    return mission_id


async def user(conn: asyncpg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, 'U')",
        user_id,
        f"sub-{user_id}",
        f"{user_id}@x",
    )
    return user_id


async def person(conn: asyncpg.Connection, mission_id: uuid.UUID, person_type: str) -> uuid.UUID:
    person_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
        "VALUES (current_tenant_id(), $1, $2, 'Fictional Person') RETURNING id",
        mission_id,
        person_type,
    )
    return person_id


async def partner(conn: asyncpg.Connection) -> uuid.UUID:
    partner_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
        "VALUES (current_tenant_id(), 'ATL', 'Atlas', '{EVACUATION}', '{KE}', 240) RETURNING id"
    )
    return partner_id


async def plan(
    conn: asyncpg.Connection, mission_id: uuid.UUID, options: Any = None, code: str = "NBO"
) -> uuid.UUID:
    plan_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
        f"muster_location, route_label, destination, options) VALUES (current_tenant_id(), $1, "
        f"$2, 'Embassy courtyard', {PT}, 'Route B', 'Dubai', $3::jsonb) RETURNING id",
        mission_id,
        f"EVP-{code}",
        json.dumps([CHARTER] if options is None else options),
    )
    return plan_id


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.mission = await mission(self.conn)
        self.plan = await plan(self.conn, self.mission)
        self.hom = await user(self.conn)
        self.hq = await user(self.conn)
        self.diplomat = await person(self.conn, self.mission, "DIPLOMAT")
        self.citizen = await person(self.conn, self.mission, "CITIZEN")
        return self

    async def request(self, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "reference": f"EVN-{uuid.uuid4().int % 10_000:04d}",
            "plan_id": self.plan,
            "mission_id": self.mission,
            "requested_by": self.hom,
            "requested_role": "HEAD_OF_MISSION",
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
        evacuation_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO evacuation ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )
        return evacuation_id

    async def activate(self, evacuation_id: uuid.UUID, people: list[tuple[uuid.UUID, str]]) -> None:
        """Activation and the manifest, in one transaction (EV-03)."""
        async with self.conn.transaction():
            await self.conn.execute(
                ACTIVATE,
                evacuation_id,
                self.hq,
            )
            for person_id, category in people:
                await self.conn.execute(
                    "INSERT INTO evacuation_manifest (tenant_id, evacuation_id, person_id, "
                    "category) VALUES (current_tenant_id(), $1, $2, $3)",
                    evacuation_id,
                    person_id,
                    category,
                )

    async def active(self) -> uuid.UUID:
        evacuation_id = await self.request()
        await self.activate(evacuation_id, [(self.diplomat, "STAFF"), (self.citizen, "CITIZEN")])
        return evacuation_id

    async def row(self, evacuation_id: uuid.UUID) -> asyncpg.Record:
        record = await self.conn.fetchrow("SELECT * FROM evacuation WHERE id = $1", evacuation_id)
        assert record is not None
        return record


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Evacuation"))
    return api


@pytest.fixture
async def world(api_tenant: asyncpg.Connection) -> World:
    return await World(api_tenant).build()


@pytest.fixture
async def owner(db: DbUrls, api_tenant: asyncpg.Connection) -> Any:
    """The table owner in the same tenant: the guards hold for it too (defence in depth)."""
    conn = await asyncpg.connect(db.owner_plain)
    await set_tenant(conn, await api_tenant.fetchval("SELECT current_tenant_id()"))
    try:
        yield conn
    finally:
        await conn.close()


# --- PC-30 · plans -----------------------------------------------------------------------------


async def test_a_plan_has_one_to_three_options_with_the_primary_first(
    api_tenant: asyncpg.Connection,
) -> None:
    conn = api_tenant
    atlas = await partner(conn)
    options = [
        {**CHARTER, "partner_id": str(atlas)},
        {"role": "BACKUP", "kind": "COMMERCIAL", "label": "JKIA · 30 seats held", "seats": 30},
        {"role": "CONTINGENCY", "kind": "ROAD", "label": "Namanga → Arusha", "seats": None},
    ]
    plan_id = await plan(conn, await mission(conn), options)
    row = await conn.fetchrow("SELECT * FROM evacuation_plan WHERE id = $1", plan_id)
    assert row is not None
    assert json.loads(row["options"]) == options
    assert row["source"] == "Illustrative evacuation plan (simulated)"


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ([], "one to three options"),
        ({"role": "PRIMARY"}, "one to three options"),
        ([CHARTER] * 4, "one to three options"),
        (["charter"], "role, kind, label, seats and partner_id only"),
        ([{"role": "PRIMARY", "kind": "CHARTER"}], "role, kind, label, seats and partner_id only"),
        ([{**CHARTER, "pilot": "x"}], "role, kind, label, seats and partner_id only"),
        ([{**CHARTER, "role": 1}], "role, kind, label, seats and partner_id only"),
        ([{**CHARTER, "role": "FIRST"}], "bad option role, kind or label"),
        ([{**CHARTER, "kind": "BOAT"}], "bad option role, kind or label"),
        ([{**CHARTER, "label": ""}], "bad option role, kind or label"),
        ([CHARTER, CHARTER], "each role once"),
        ([{**CHARTER, "role": "BACKUP"}], "the primary option comes first"),
        ([{**CHARTER, "role": "BACKUP"}, CHARTER], "the primary option comes first"),
        ([{**CHARTER, "seats": 72.5}], "seats is a whole number"),
        ([{**CHARTER, "seats": "72"}], "seats is a whole number"),
        ([{**CHARTER, "seats": 0}], "seats is a whole number"),
        ([{**CHARTER, "seats": 5000}], "seats is a whole number"),
        ([{**CHARTER, "partner_id": "atlas"}], "partner_id is a partner id"),
        ([{**CHARTER, "partner_id": 7}], "partner_id is a partner id"),
        ([{**CHARTER, "partner_id": str(uuid.uuid4())}], "no such partner"),
    ],
)
async def test_a_plan_refuses_badly_shaped_options(
    api_tenant: asyncpg.Connection, options: Any, message: str
) -> None:
    with pytest.raises(REFUSED, match=message):
        await plan(api_tenant, await mission(api_tenant), options)


async def test_a_plan_names_only_this_tenants_partner(
    db: DbUrls, api_tenant: asyncpg.Connection
) -> None:
    conn = api_tenant
    mine = await conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(conn, await create_tenant(db, "Other"))
    theirs = await partner(conn)
    await set_tenant(conn, mine)
    with pytest.raises(REFUSED, match="no such partner"):
        await plan(conn, await mission(conn), [{**CHARTER, "partner_id": str(theirs)}])


async def test_a_plan_is_one_per_mission_and_never_changed_or_deleted(
    world: World, owner: asyncpg.Connection
) -> None:
    with pytest.raises(UNIQUE):
        await plan(world.conn, world.mission)
    for stmt in ("UPDATE evacuation_plan SET route_label = 'x'", "DELETE FROM evacuation_plan"):
        with pytest.raises(DENIED):
            await world.conn.execute(stmt)
    with pytest.raises(REFUSED, match="seeded plans are not changed"):
        await owner.execute("UPDATE evacuation_plan SET route_label = 'x'")
    with pytest.raises(REFUSED, match="plans are kept"):  # review of Prompt 66, L2
        await owner.execute("DELETE FROM evacuation_plan")


async def test_seats_in_exponent_form_are_a_whole_number(api_tenant: asyncpg.Connection) -> None:
    plan_id = await api_tenant.fetchval(
        "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
        f"muster_location, route_label, destination, options) VALUES (current_tenant_id(), $1, "
        f"'EVP-NBO', 'Courtyard', {PT}, 'Route B', 'Dubai', "
        '\'[{"role": "PRIMARY", "kind": "CHARTER", "label": "C", '
        '"seats": 1e3}]\'::jsonb) RETURNING id',
        await mission(api_tenant),
    )
    options = json.loads(
        await api_tenant.fetchval("SELECT options FROM evacuation_plan WHERE id = $1", plan_id)
    )
    assert options[0]["seats"] == 1000


# --- PC-31 · evacuations -----------------------------------------------------------------------


async def test_a_request_starts_pending_and_the_database_writes_its_times(world: World) -> None:
    evacuation_id = await world.request(step_times=json.dumps({"1": "2000-01-01"}))
    row = await world.row(evacuation_id)
    assert (row["status"], row["step"], row["activated_by"]) == ("PENDING_ACTIVATION", None, None)
    assert json.loads(row["step_times"]) == {}
    assert row["requested_at"].year > 2000


@pytest.mark.parametrize(
    "change",
    [
        {"status": "ACTIVE"},
        {"step": 1},
        {"stood_down_reason": "x"},
    ],
)
async def test_an_evacuation_cannot_be_inserted_past_the_request(
    world: World, change: dict[str, Any]
) -> None:
    with pytest.raises(REFUSED, match="starts as a request"):
        await world.request(**change)


async def test_an_evacuation_cannot_be_inserted_activated(world: World) -> None:
    with pytest.raises(REFUSED, match="starts as a request"):
        await world.request(activated_by=world.hq)


async def test_a_request_needs_the_missions_own_plan_incident_and_a_tenant_user(
    world: World,
) -> None:
    other = await mission(world.conn, "CAI")
    with pytest.raises(REFUSED, match="no such plan for this mission"):
        await world.request(mission_id=other)
    incident_id = await world.conn.fetchval(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        f"location, mission_id) VALUES (current_tenant_id(), 'INC-T', 'I', 'CIVIL_UNREST', 'HIGH', "
        f"'HIGH', {PT}, $1) RETURNING id",
        other,
    )
    with pytest.raises(REFUSED, match="no such incident at this mission"):
        await world.request(incident_id=incident_id)
    with pytest.raises(REFUSED, match="no such user"):
        await world.request(requested_by=uuid.uuid4())
    with pytest.raises(CHECK):
        await world.request(requested_role="DUTY_OFFICER")


async def test_one_live_evacuation_per_mission(world: World) -> None:
    await world.request()
    with pytest.raises(UNIQUE):
        await world.request()


async def test_activation_needs_a_second_person_and_dates_steps_1_and_2(world: World) -> None:
    evacuation_id = await world.request()
    with pytest.raises(REFUSED, match="requester cannot also activate"):
        await world.conn.execute(
            ACTIVATE,
            evacuation_id,
            world.hom,
        )
    with pytest.raises(REFUSED, match="activation needs the second person"):
        await world.conn.execute(
            "UPDATE evacuation SET status = 'ACTIVE', step = 2 WHERE id = $1", evacuation_id
        )
    with pytest.raises(REFUSED, match=r"manifest \(step 2\)"):
        await world.conn.execute(
            "UPDATE evacuation SET status = 'ACTIVE', activated_by = $2, step = 3 WHERE id = $1",
            evacuation_id,
            world.hq,
        )
    with pytest.raises(REFUSED, match="the activator is set once"):
        await world.conn.execute(
            "UPDATE evacuation SET activated_by = $2 WHERE id = $1", evacuation_id, world.hq
        )
    await world.activate(evacuation_id, [])
    row = await world.row(evacuation_id)
    assert (row["status"], row["step"], row["activated_by"]) == ("ACTIVE", 2, world.hq)
    assert set(json.loads(row["step_times"])) == {"1", "2"}
    assert row["activated_at"] is not None
    with pytest.raises(REFUSED, match="the activator is set once"):
        await world.conn.execute(
            "UPDATE evacuation SET activated_by = $2 WHERE id = $1", evacuation_id, world.hom
        )


async def test_the_sequence_moves_forward_one_step_at_a_time_to_completion(world: World) -> None:
    evacuation_id = await world.active()
    for stmt in ("step = 4", "step = 1", "step = NULL", "status = 'COMPLETED'"):
        with pytest.raises((REFUSED, CHECK)):
            await world.conn.execute(f"UPDATE evacuation SET {stmt} WHERE id = $1", evacuation_id)
    for step in (3, 4, 5):
        await world.conn.execute(
            "UPDATE evacuation SET step = $2 WHERE id = $1", evacuation_id, step
        )
    with pytest.raises(CHECK):  # arrival completes the evacuation (EV-05)
        await world.conn.execute("UPDATE evacuation SET step = 6 WHERE id = $1", evacuation_id)
    await world.conn.execute(
        "UPDATE evacuation SET step = 6, status = 'COMPLETED' WHERE id = $1", evacuation_id
    )
    row = await world.row(evacuation_id)
    assert set(json.loads(row["step_times"])) == {"1", "2", "3", "4", "5", "6"}
    with pytest.raises(REFUSED, match="a completed evacuation is final"):
        await world.conn.execute(
            "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, "
            "stood_down_reason = 'x' WHERE id = $1",
            evacuation_id,
            world.hq,
        )
    await world.request()  # no longer live: the mission may be evacuated again


async def test_a_stand_down_needs_who_and_why_before_the_flight_and_is_final(
    world: World,
) -> None:
    evacuation_id = await world.active()
    stand_down = (
        "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, stood_down_reason = $3 "
        "WHERE id = $1"
    )
    with pytest.raises(REFUSED, match="a stand-down needs who and why"):
        await world.conn.execute(stand_down, evacuation_id, world.hq, None)
    with pytest.raises(REFUSED, match="a stand-down sets the status"):
        await world.conn.execute(
            "UPDATE evacuation SET stood_down_reason = 'x' WHERE id = $1", evacuation_id
        )
    for step in (3, 4, 5):
        await world.conn.execute(
            "UPDATE evacuation SET step = $2 WHERE id = $1", evacuation_id, step
        )
    with pytest.raises(REFUSED, match="flight has departed"):
        await world.conn.execute(stand_down, evacuation_id, world.hq, "Routes closed")

    # A request still pending is withdrawn the same way (plan-pilot-ev G-11), at another mission.
    cairo = await mission(world.conn, "CAI")
    request = await world.request(
        mission_id=cairo, plan_id=await plan(world.conn, cairo, code="CAI")
    )
    await world.conn.execute(stand_down, request, world.hom, "Withdrawn: the situation eased")
    row = await world.row(request)
    assert (row["status"], row["stood_down_reason"]) == (
        "STOOD_DOWN",
        "Withdrawn: the situation eased",
    )
    assert row["stood_down_at"] is not None
    with pytest.raises(REFUSED, match="a stood down evacuation is final"):
        await world.conn.execute(
            ACTIVATE,
            request,
            world.hq,
        )


async def test_what_was_requested_is_fixed_and_evacuations_are_kept(
    world: World, owner: asyncpg.Connection
) -> None:
    evacuation_id = await world.request()
    for stmt in (
        "UPDATE evacuation SET requested_role = 'HQ_CRISIS_DIRECTOR'",
        "UPDATE evacuation SET mission_id = mission_id",
        "UPDATE evacuation SET step_times = '{}'",
        "DELETE FROM evacuation",
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(stmt)
    with pytest.raises(REFUSED, match="what was requested is fixed"):
        await owner.execute(
            "UPDATE evacuation SET requested_role = 'HQ_CRISIS_DIRECTOR' WHERE id = $1",
            evacuation_id,
        )
    with pytest.raises(REFUSED, match="evacuations are kept"):
        await owner.execute("DELETE FROM evacuation WHERE id = $1", evacuation_id)
    # The times are the database's, for the owner too.
    await owner.execute(
        'UPDATE evacuation SET step_times = \'{"1": "2000-01-01"}\' WHERE id = $1', evacuation_id
    )
    assert json.loads((await world.row(evacuation_id))["step_times"]) == {}


# --- PC-32 · the manifest ----------------------------------------------------------------------


async def test_the_manifest_is_built_only_in_the_activating_transaction(world: World) -> None:
    evacuation_id = await world.active()
    rows = await world.conn.fetch(
        "SELECT category, status, seat FROM evacuation_manifest WHERE evacuation_id = $1 "
        "ORDER BY category",
        evacuation_id,
    )
    assert [tuple(r) for r in rows] == [("CITIZEN", "EXPECTED", None), ("STAFF", "EXPECTED", None)]
    late = await person(world.conn, world.mission, "DELEGATE")
    with pytest.raises(REFUSED, match="built at activation only"):
        await world.conn.execute(
            "INSERT INTO evacuation_manifest (tenant_id, evacuation_id, person_id, category) "
            "VALUES (current_tenant_id(), $1, $2, 'DELEGATE')",
            evacuation_id,
            late,
        )


@pytest.mark.parametrize(
    ("person_type", "category", "message"),
    [
        ("LOCAL_STAFF", "STAFF", "LOCAL_STAFF is not evacuated as STAFF"),
        ("CONTRACTOR", "STAFF", "CONTRACTOR is not evacuated as STAFF"),
        ("CITIZEN", "STAFF", "CITIZEN is not evacuated as STAFF"),
        ("DIPLOMAT", "CITIZEN", "DIPLOMAT is not evacuated as CITIZEN"),
    ],
)
async def test_the_manifest_category_follows_the_person(
    world: World, person_type: str, category: str, message: str
) -> None:
    evacuation_id = await world.request()
    someone = await person(world.conn, world.mission, person_type)
    with pytest.raises(REFUSED, match=message):
        await world.activate(evacuation_id, [(someone, category)])


async def test_the_manifest_holds_only_the_missions_people_once(world: World) -> None:
    evacuation_id = await world.request()
    elsewhere = await person(world.conn, await mission(world.conn, "CAI"), "DIPLOMAT")
    with pytest.raises(REFUSED, match="no such person at this mission"):
        await world.activate(evacuation_id, [(elsewhere, "STAFF")])
    with pytest.raises(UNIQUE):
        await world.activate(evacuation_id, [(world.diplomat, "STAFF"), (world.diplomat, "STAFF")])
    # Activation and a checked-in row in one transaction (a multi-statement simple query).
    with pytest.raises(REFUSED, match="everyone starts expected"):
        await world.conn.execute(
            f"UPDATE evacuation SET status = 'ACTIVE', activated_by = '{world.hq}', step = 2 "
            f"WHERE id = '{evacuation_id}'; INSERT INTO evacuation_manifest (tenant_id, "
            "evacuation_id, person_id, category, status, checked_in_by_type, checked_in_by) "
            f"VALUES (current_tenant_id(), '{evacuation_id}', '{world.diplomat}', 'STAFF', "
            "'CHECKED_IN', 'SCANNER', 'x')"
        )


async def test_a_check_in_is_once_with_its_seat_and_the_database_dates_it(world: World) -> None:
    evacuation_id = await world.active()
    entry = await world.conn.fetchval(
        "SELECT id FROM evacuation_manifest WHERE evacuation_id = $1 AND category = 'STAFF'",
        evacuation_id,
    )
    with pytest.raises(REFUSED, match="the only change is a check-in"):  # a seat comes with it
        await world.conn.execute("UPDATE evacuation_manifest SET seat = '1A' WHERE id = $1", entry)
    with pytest.raises(REFUSED, match="no such user"):
        await world.conn.execute(
            "UPDATE evacuation_manifest SET status = 'CHECKED_IN', checked_in_by_type = 'USER', "
            "checked_in_by = $2 WHERE id = $1",
            entry,
            str(uuid.uuid4()),
        )
    await world.conn.execute(
        "UPDATE evacuation_manifest SET status = 'CHECKED_IN', seat = '1A', "
        "checked_in_by_type = 'USER', checked_in_by = $2 WHERE id = $1",
        entry,
        str(world.hom),
    )
    row = await world.conn.fetchrow("SELECT * FROM evacuation_manifest WHERE id = $1", entry)
    assert row is not None
    assert (row["status"], row["seat"]) == ("CHECKED_IN", "1A")
    assert row["checked_in_at"] is not None
    with pytest.raises(REFUSED, match="a check-in is final"):
        await world.conn.execute("UPDATE evacuation_manifest SET seat = '2B' WHERE id = $1", entry)
    citizen = await world.conn.fetchval(
        "SELECT id FROM evacuation_manifest WHERE evacuation_id = $1 AND category = 'CITIZEN'",
        evacuation_id,
    )
    with pytest.raises(UNIQUE):  # one person per seat
        await world.conn.execute(
            "UPDATE evacuation_manifest SET status = 'CHECKED_IN', seat = '1A', "
            "checked_in_by_type = 'SCANNER', checked_in_by = 'muster-scanner (simulated)' "
            "WHERE id = $1",
            citizen,
        )


async def test_nothing_on_the_manifest_changes_once_the_evacuation_is_final(
    world: World, owner: asyncpg.Connection
) -> None:
    evacuation_id = await world.active()
    await world.conn.execute(
        "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, "
        "stood_down_reason = 'Routes closed' WHERE id = $1",
        evacuation_id,
        world.hq,
    )
    with pytest.raises(REFUSED, match="the evacuation is not active"):
        await world.conn.execute(
            "UPDATE evacuation_manifest SET status = 'CHECKED_IN', checked_in_by_type = 'SCANNER', "
            "checked_in_by = 'muster-scanner (simulated)' WHERE evacuation_id = $1",
            evacuation_id,
        )
    for stmt in (
        "UPDATE evacuation_manifest SET person_id = person_id",
        "DELETE FROM evacuation_manifest",
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(stmt)
    with pytest.raises(REFUSED, match="the manifest is kept"):
        await owner.execute(
            "DELETE FROM evacuation_manifest WHERE evacuation_id = $1", evacuation_id
        )


async def test_who_is_on_the_manifest_is_fixed_for_the_owner_too(
    world: World, owner: asyncpg.Connection
) -> None:
    evacuation_id = await world.active()
    with pytest.raises(REFUSED, match="who is on the manifest is fixed"):
        await owner.execute(
            "UPDATE evacuation_manifest SET category = 'CITIZEN', status = 'CHECKED_IN', "
            "checked_in_by_type = 'SCANNER', checked_in_by = 's' "
            "WHERE evacuation_id = $1 AND category = 'STAFF'",
            evacuation_id,
        )


# --- review of Prompt 66 -------------------------------------------------------------------------


async def other_tenant_user(db: DbUrls) -> uuid.UUID:
    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, await create_tenant(db, "Other"))
        return await user(conn)
    finally:
        await conn.close()


async def test_activators_and_stand_downs_are_this_tenants_users(db: DbUrls, world: World) -> None:
    stranger = await other_tenant_user(db)
    evacuation_id = await world.request()
    with pytest.raises(REFUSED, match="no such user"):
        await world.conn.execute(ACTIVATE, evacuation_id, stranger)
    with pytest.raises(REFUSED, match="no such user"):
        await world.conn.execute(ACTIVATE, evacuation_id, uuid.uuid4())
    with pytest.raises(REFUSED, match="no such user"):
        await world.conn.execute(
            "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, "
            "stood_down_reason = 'x' WHERE id = $1",
            evacuation_id,
            stranger,
        )
    await world.conn.execute(
        "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, "
        "stood_down_reason = 'x' WHERE id = $1",
        evacuation_id,
        world.hom,
    )
    checked = await world.active()
    with pytest.raises(REFUSED, match="no such user"):
        await world.conn.execute(
            "UPDATE evacuation_manifest SET status = 'CHECKED_IN', checked_in_by_type = 'USER', "
            "checked_in_by = $2 WHERE evacuation_id = $1 AND category = 'STAFF'",
            checked,
            str(stranger),
        )


async def test_only_an_evacuation_proposal_activates_once(world: World) -> None:
    agent = await world.conn.fetchval(
        "INSERT INTO agent (tenant_id, code, name) VALUES (current_tenant_id(), 'RP', 'R') "
        "RETURNING id"
    )

    async def proposal(action_type: str) -> uuid.UUID:
        proposal_id: uuid.UUID = await world.conn.fetchval(
            "INSERT INTO agent_proposal (tenant_id, agent_id, proposal_key, action_type, title, "
            "proposed_action) VALUES (current_tenant_id(), $1, $2, $3, 't', 'p') RETURNING id",
            agent,
            str(uuid.uuid4()),
            action_type,
        )
        return proposal_id

    with pytest.raises(REFUSED, match="no such evacuation proposal"):
        await world.request(proposal_id=await proposal("START_PLAYBOOK"))
    evacuation = await proposal("START_EVACUATION")
    first = await world.request(proposal_id=evacuation)
    await world.conn.execute(
        "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, "
        "stood_down_reason = 'x' WHERE id = $1",
        first,
        world.hom,
    )
    with pytest.raises(UNIQUE):
        await world.request(proposal_id=evacuation)


async def test_a_check_in_after_completion_is_refused_and_times_cannot_be_forged(
    world: World, owner: asyncpg.Connection
) -> None:
    evacuation_id = await world.active()
    activated_at = (await world.row(evacuation_id))["activated_at"]
    await owner.execute(
        "UPDATE evacuation SET activated_at = '2000-01-01', step = 3 WHERE id = $1", evacuation_id
    )
    assert (await world.row(evacuation_id))["activated_at"] == activated_at
    for step in (4, 5):
        await world.conn.execute(
            "UPDATE evacuation SET step = $2 WHERE id = $1", evacuation_id, step
        )
    await world.conn.execute(
        "UPDATE evacuation SET step = 6, status = 'COMPLETED' WHERE id = $1", evacuation_id
    )
    with pytest.raises(REFUSED, match="the evacuation is not active"):
        await world.conn.execute(
            "UPDATE evacuation_manifest SET status = 'CHECKED_IN', checked_in_by_type = 'SCANNER', "
            "checked_in_by = 'muster-scanner (simulated)' WHERE evacuation_id = $1",
            evacuation_id,
        )


async def test_a_check_in_waits_for_a_concurrent_stand_down_and_is_then_refused(
    db: DbUrls, world: World
) -> None:
    """Review of Prompt 66, M1: the manifest guard locks the evacuation FOR SHARE."""
    evacuation_id = await world.active()
    tenant = await world.conn.fetchval("SELECT current_tenant_id()")
    other = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(other, tenant)
        stand_down = other.transaction()
        await stand_down.start()
        await other.execute(
            "UPDATE evacuation SET status = 'STOOD_DOWN', stood_down_by = $2, "
            "stood_down_reason = 'Routes closed' WHERE id = $1",
            evacuation_id,
            world.hq,
        )
        check_in = asyncio.ensure_future(
            world.conn.execute(
                "UPDATE evacuation_manifest SET status = 'CHECKED_IN', "
                "checked_in_by_type = 'SCANNER', checked_in_by = 'muster-scanner (simulated)' "
                "WHERE evacuation_id = $1 AND category = 'STAFF'",
                evacuation_id,
            )
        )
        await asyncio.sleep(0.3)
        assert not check_in.done()  # waiting for the stand-down's lock
        await stand_down.commit()
        with pytest.raises(REFUSED, match="the evacuation is not active"):
            await check_in
    finally:
        await other.close()
