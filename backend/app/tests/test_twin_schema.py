"""Migration 0013 (PC-39..42; D-43; plan-pilot-twn G-1), checked as nexira_api: the floor plan
and routes are seeded and fixed; presence moves between zones of the same site and leaves (staff
are people of the site's mission, guards and visitors labels); sensors change only status and
detail; readiness items are done once by a person of the tenant; the database writes the times
(docs/plan-pilot-twn.md §2-§6, §12)."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
FK = asyncpg.ForeignKeyViolationError
PT = "'SRID=4326;POINT(36.808 -1.295)'"


async def mission(conn: asyncpg.Connection, code: str = "NBO") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Nairobi', 'KE', {PT})",
        mission_id,
        code,
    )
    return mission_id


async def site(conn: asyncpg.Connection, mission_id: uuid.UUID) -> uuid.UUID:
    site_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO site (tenant_id, mission_id, site_type, name, location, readiness_score) "
        f"VALUES (current_tenant_id(), $1, 'EMBASSY', 'Embassy Nairobi', {PT}, 79) RETURNING id",
        mission_id,
    )
    return site_id


async def person(conn: asyncpg.Connection, mission_id: uuid.UUID) -> uuid.UUID:
    person_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
        "VALUES (current_tenant_id(), $1, 'DIPLOMAT', 'Fictional Officer') RETURNING id",
        mission_id,
    )
    return person_id


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


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.mission = await mission(self.conn)
        self.other_mission = await mission(self.conn, "CAI")
        self.site = await site(self.conn, self.mission)
        self.other_site = await site(self.conn, self.other_mission)
        self.officer = await person(self.conn, self.mission)
        self.security = await user(self.conn)
        self.chancery = await self.zone("ch", "OFFICE")
        self.safe = await self.zone("safe", "SAFE_ROOM", capacity=20)
        self.gate = await self.zone("g2", "GATE")
        self.elsewhere = await self.zone("ch", "OFFICE", site_id=self.other_site)
        return self

    async def zone(self, code: str, kind: str, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "site_id": self.site,
            "code": code,
            "name": code.title(),
            "kind": kind,
            "x": 10,
            "y": 10,
            "w": 100,
            "h": 80,
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
        zone_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO site_zone ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )
        return zone_id

    async def present(self, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "site_id": self.site,
            "zone_id": self.chancery,
            "kind": "STAFF",
            "person_id": self.officer,
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
        presence_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO site_presence ({names}) VALUES ({values}) RETURNING id",
            *columns.values(),
        )
        return presence_id

    async def sensor(self, code: str = "G2-READER", **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "site_id": self.site,
            "zone_id": self.gate,
            "code": code,
            "kind": "BADGE_READER",
            "label": "Gate 2 · badge reader",
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
        sensor_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO site_sensor ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )
        return sensor_id

    async def route(self, path: Any, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "site_id": self.site,
            "code": "B",
            "label": "Route B → vehicles via Gate 2",
            "exit_zone_id": self.gate,
            **change,
        }
        names = ", ".join(["tenant_id", "path", *columns])
        values = ", ".join(
            ["current_tenant_id()", "$1::jsonb", *(f"${n}" for n in range(2, len(columns) + 2))]
        )
        route_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO site_route ({names}) VALUES ({values}) RETURNING id",
            json.dumps(path),
            *columns.values(),
        )
        return route_id


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Twin"))
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


async def _other_tenant(db: DbUrls, world: World) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Another tenant's site, mission's person and user, created as nexira_api."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs_mission = await mission(world.conn)
    found = (
        await site(world.conn, theirs_mission),
        await person(world.conn, theirs_mission),
        await user(world.conn),
    )
    await set_tenant(world.conn, mine)
    return found


# --- PC-39 · the floor plan ---------------------------------------------------------------------


async def test_a_zone_is_seeded_once_and_fixed(world: World, owner: asyncpg.Connection) -> None:
    async with world.conn.transaction():
        zone_id = await world.zone("lob", "LOBBY")
        assert await world.conn.fetchval(
            "SELECT created_at = now() FROM site_zone WHERE id = $1", zone_id
        )
    with pytest.raises(UNIQUE):
        await world.zone("lob", "LOBBY")
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE site_zone SET name = 'x'")
    with pytest.raises(REFUSED, match="the floor plan is fixed"):
        await owner.execute("UPDATE site_zone SET name = 'x'")


@pytest.mark.parametrize(
    "change",
    [
        {"code": "Lobby!"},
        {"kind": "KITCHEN"},
        {"w": 0},
        {"x": -1},
        {"capacity": 20},  # only a safe room or the muster point has a capacity
        {"kind": "SAFE_ROOM", "capacity": 0},
        {"x": 9950, "w": 100},  # off the plan (review of Prompt 84, L3)
    ],
)
async def test_a_zone_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    with pytest.raises(CHECK):
        await world.zone(change.pop("code", "z1"), change.pop("kind", "OFFICE"), **change)


async def test_a_zone_belongs_to_a_site_of_this_tenant(db: DbUrls, world: World) -> None:
    theirs, _, _ = await _other_tenant(db, world)
    with pytest.raises(REFUSED, match="site zone: no such site"):
        await world.zone("x", "OFFICE", site_id=theirs)


# --- PC-40 · routes ----------------------------------------------------------------------------


async def test_a_route_leaves_by_a_gate_of_the_same_site(
    world: World, owner: asyncpg.Connection
) -> None:
    path = [[680, 200], [680, 300], [725, 340]]
    route_id = await world.route(path)
    assert route_id
    with pytest.raises(REFUSED, match="the exit is a gate of this site"):
        await world.route(path, code="C", exit_zone_id=world.safe)
    with pytest.raises((FK, REFUSED)):
        await world.route(path, code="D", exit_zone_id=world.elsewhere)
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE site_route SET label = 'x'")
    with pytest.raises(REFUSED, match="the routes are fixed"):
        await owner.execute("UPDATE site_route SET label = 'x'")


@pytest.mark.parametrize(
    "path",
    [
        [[1, 2]],  # one point
        [[1, 2], [3]],
        [[1, 2], ["a", 4]],
        [[1, 2], [3.5, 4]],
        [[1, 2], [-3, 4]],
        {"x": 1},
        [[i, i] for i in range(21)],
        [[1, 2], [10001, 4]],  # off the plan (review of Prompt 84, L3)
        [[1, 2], [123456, 4]],
        [5, [1, 2]],  # a scalar point (L4)
        [[1, 2], "x"],
    ],
)
async def test_a_route_path_is_points_on_the_plan(world: World, path: Any) -> None:
    with pytest.raises((CHECK, REFUSED)):
        await world.route(path)


# --- PC-41 · presence --------------------------------------------------------------------------


async def test_staff_presence_moves_within_the_site_and_the_database_writes_since(
    world: World,
) -> None:
    async with world.conn.transaction():
        presence_id = await world.present()
        assert await world.conn.fetchval(
            "SELECT since = now() FROM site_presence WHERE id = $1", presence_id
        )
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE site_presence SET zone_id = $2 WHERE id = $1", presence_id, world.safe
        )
        row = await world.conn.fetchrow(
            "SELECT zone_id, since = now() AS fresh, source FROM site_presence WHERE id = $1",
            presence_id,
        )
    assert row is not None
    assert tuple(row) == (world.safe, True, "Access control + Wi-Fi presence (simulated)")
    with pytest.raises(UNIQUE):
        await world.present()  # one row per person per site
    # Nor at another site of the mission: one place at a time (review of Prompt 84, M1).
    residence = await site(world.conn, world.mission)
    hall = await world.zone("hall", "LOBBY", site_id=residence)
    with pytest.raises(UNIQUE):
        await world.present(site_id=residence, zone_id=hall)
    with pytest.raises((FK, REFUSED)):
        await world.conn.execute(
            "UPDATE site_presence SET zone_id = $2 WHERE id = $1", presence_id, world.elsewhere
        )


async def test_a_departure_deletes_the_row(world: World) -> None:
    presence_id = await world.present()
    assert await world.conn.execute("DELETE FROM site_presence WHERE id = $1", presence_id) == (
        "DELETE 1"
    )


async def test_guards_and_visitors_are_labels_never_people(world: World) -> None:
    assert await world.present(kind="GUARD", person_id=None, label="Guard 1", zone_id=world.gate)
    assert await world.present(kind="VISITOR", person_id=None, label="Visitor 7")
    with pytest.raises(UNIQUE):
        await world.present(kind="VISITOR", person_id=None, label="Visitor 7")
    for change in (
        {"kind": "GUARD"},  # a person, not a label
        {"kind": "VISITOR", "person_id": None, "label": "Guard 3"},
        {"kind": "VISITOR", "person_id": None, "label": "Mr Smith"},
        {"kind": "STAFF", "label": "Visitor 9"},
        {"kind": "STAFF", "person_id": None},
    ):
        with pytest.raises(CHECK):
            await world.present(**change)


async def test_staff_are_people_of_the_sites_mission(db: DbUrls, world: World) -> None:
    cairo = await person(world.conn, world.other_mission)
    with pytest.raises(REFUSED, match="people of the site's mission"):
        await world.present(person_id=cairo)
    theirs_site, theirs_person, _ = await _other_tenant(db, world)
    with pytest.raises(REFUSED, match="people of the site's mission"):
        await world.present(person_id=theirs_person)
    with pytest.raises(REFUSED, match="site presence: no such site"):
        await world.present(site_id=theirs_site)
    with pytest.raises((FK, REFUSED)):
        await world.present(zone_id=world.elsewhere)


async def test_only_the_zone_of_a_presence_changes(world: World, owner: asyncpg.Connection) -> None:
    presence_id = await world.present()
    other = await person(world.conn, world.mission)
    for column, value in (("person_id", other), ("kind", "GUARD"), ("site_id", world.other_site)):
        with pytest.raises(DENIED):
            await world.conn.execute(
                f"UPDATE site_presence SET {column} = $2 WHERE id = $1", presence_id, value
            )
    with pytest.raises(REFUSED, match="only the zone changes"):
        await owner.execute(
            "UPDATE site_presence SET person_id = $2 WHERE id = $1", presence_id, other
        )


# --- PC-42 · sensors and readiness items -------------------------------------------------------


async def test_a_sensor_changes_only_status_and_detail(
    world: World, owner: asyncpg.Connection
) -> None:
    sensor_id = await world.sensor()
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE site_sensor SET status = 'FAULT', detail = 'Fault · manual guard' "
            "WHERE id = $1",
            sensor_id,
        )
        row = await world.conn.fetchrow(
            "SELECT status, detail, status_at = now() AS fresh FROM site_sensor WHERE id = $1",
            sensor_id,
        )
    assert row is not None
    assert tuple(row) == ("FAULT", "Fault · manual guard", True)
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE site_sensor SET status = 'BROKEN' WHERE id = $1", sensor_id
        )
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE site_sensor SET label = 'x'")
    with pytest.raises(REFUSED, match="only the status and detail change"):
        await owner.execute("UPDATE site_sensor SET label = 'x'")
    with pytest.raises(UNIQUE):
        await world.sensor()


async def test_a_sensor_belongs_to_this_site(db: DbUrls, world: World) -> None:
    with pytest.raises((FK, REFUSED)):
        await world.sensor("CAM-01", kind="CCTV", zone_id=world.elsewhere)
    assert await world.sensor("ALARM-01", kind="ALARM", zone_id=None)  # site-wide
    theirs, _, _ = await _other_tenant(db, world)
    with pytest.raises(REFUSED, match="site sensor: no such site"):
        await world.sensor("CAM-02", kind="CCTV", site_id=theirs, zone_id=None)


async def test_a_readiness_item_is_done_once_by_someone_of_this_tenant(
    db: DbUrls, world: World, owner: asyncpg.Connection
) -> None:
    item_id = await world.conn.fetchval(
        "INSERT INTO site_readiness_item (tenant_id, site_id, label) "
        "VALUES (current_tenant_id(), $1, 'Generator load test witnessed') RETURNING id",
        world.site,
    )
    _, _, theirs = await _other_tenant(db, world)
    done = "UPDATE site_readiness_item SET done_by = $2 WHERE id = $1"
    with pytest.raises(REFUSED, match="done by someone of this tenant"):
        await world.conn.execute(done, item_id, theirs)
    async with world.conn.transaction():
        await world.conn.execute(done, item_id, world.security)
        assert await world.conn.fetchval(
            "SELECT done_at = now() FROM site_readiness_item WHERE id = $1", item_id
        )
    with pytest.raises(REFUSED, match="done is final"):
        await world.conn.execute(done, item_id, await user(world.conn))
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE site_readiness_item SET label = 'x'")
    with pytest.raises(REFUSED, match="stays fixed"):
        await owner.execute("UPDATE site_readiness_item SET label = 'x'")
    with pytest.raises(UNIQUE):
        await world.conn.execute(
            "INSERT INTO site_readiness_item (tenant_id, site_id, label) "
            "VALUES (current_tenant_id(), $1, 'Generator load test witnessed')",
            world.site,
        )


async def test_a_readiness_item_may_be_seeded_done(world: World) -> None:
    async with world.conn.transaction():
        fresh = await world.conn.fetchval(
            "INSERT INTO site_readiness_item (tenant_id, site_id, label, done_by) "
            "VALUES (current_tenant_id(), $1, 'Floor wardens assigned (3)', $2) "
            "RETURNING done_at = now()",
            world.site,
            world.security,
        )
    assert fresh is True


# --- every table -------------------------------------------------------------------------------


async def test_nothing_is_deleted_but_a_departure(world: World, owner: asyncpg.Connection) -> None:
    await world.route([[1, 2], [3, 4]])
    await world.sensor()
    await world.conn.execute(
        "INSERT INTO site_readiness_item (tenant_id, site_id, label) "
        "VALUES (current_tenant_id(), $1, 'Item')",
        world.site,
    )
    for table, kept in (
        ("site_readiness_item", "items are kept"),
        ("site_sensor", "sensors are kept"),
        ("site_route", "the routes are fixed"),
        ("site_zone", "the floor plan is fixed"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"DELETE FROM {table}")
        with pytest.raises(REFUSED, match=kept):
            await owner.execute(f"DELETE FROM {table}")


async def test_the_backup_role_reads_the_twin_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w FROM unnest(ARRAY["
            "'site_presence', 'site_readiness_item', 'site_route', 'site_sensor', 'site_zone']) t "
            "ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("site_presence", True, False),
        ("site_readiness_item", True, False),
        ("site_route", True, False),
        ("site_sensor", True, False),
        ("site_zone", True, False),
    ]


async def test_no_site_readiness_table(db: DbUrls) -> None:
    """Plan G-1: the score is site.readiness_score, not a second table."""
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        assert await conn.fetchval("SELECT to_regclass('public.site_readiness')") is None
    finally:
        await conn.close()


# --- review of Prompt 84 -----------------------------------------------------------------------


async def test_staff_are_active_mission_personnel(world: World) -> None:
    """M1."""
    for person_type in ("DEPENDANT", "CITIZEN", "DELEGATE"):
        other = await world.conn.fetchval(
            "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
            "VALUES (current_tenant_id(), $1, $2, 'Fictional') RETURNING id",
            world.mission,
            person_type,
        )
        with pytest.raises(REFUSED, match="active mission personnel"):
            await world.present(person_id=other)
    gone = await person(world.conn, world.mission)
    await world.conn.execute("UPDATE person SET is_active = false WHERE id = $1", gone)
    with pytest.raises(REFUSED, match="active mission personnel"):
        await world.present(person_id=gone)


async def test_the_database_writes_every_time_even_when_forged(
    world: World, owner: asyncpg.Connection
) -> None:
    """Finding 9: forged times on insert are overwritten; unchanged values keep theirs."""
    forged = datetime(2000, 1, 1, tzinfo=UTC)
    async with world.conn.transaction():
        presence_id = await world.conn.fetchval(
            "INSERT INTO site_presence (tenant_id, site_id, zone_id, kind, label, since) "
            "VALUES (current_tenant_id(), $1, $2, 'GUARD', 'Guard 1', $3::timestamptz) "
            "RETURNING id",
            world.site,
            world.gate,
            forged,
        )
        sensor_id = await world.conn.fetchval(
            "INSERT INTO site_sensor (tenant_id, site_id, code, kind, label, status_at, "
            "created_at) VALUES (current_tenant_id(), $1, 'CAM-01', 'CCTV', 'Camera 1', "
            "$2::timestamptz, $2::timestamptz) RETURNING id",
            world.site,
            forged,
        )
        item_id = await world.conn.fetchval(
            "INSERT INTO site_readiness_item (tenant_id, site_id, label, done_at, created_at) "
            "VALUES (current_tenant_id(), $1, 'Item', $2::timestamptz, $2::timestamptz) "
            "RETURNING id",
            world.site,
            forged,
        )
        zone_id = await world.conn.fetchval(
            "INSERT INTO site_zone (tenant_id, site_id, code, name, kind, x, y, w, h, created_at) "
            "VALUES (current_tenant_id(), $1, 'amb', 'Suite', 'SUITE', 1, 1, 9, 9, "
            "$2::timestamptz) RETURNING id",
            world.site,
            forged,
        )
        rows = await world.conn.fetchrow(
            "SELECT (SELECT since = now() FROM site_presence WHERE id = $1) AS since, "
            "(SELECT status_at = now() AND created_at = now() FROM site_sensor WHERE id = $2) "
            "AS sensor, (SELECT done_at IS NULL AND created_at = now() FROM site_readiness_item "
            "WHERE id = $3) AS item, (SELECT created_at = now() FROM site_zone WHERE id = $4) "
            "AS zone",
            presence_id,
            sensor_id,
            item_id,
            zone_id,
        )
    assert rows is not None
    assert tuple(rows) == (True, True, True, True)
    # The app cannot write the times at all; the owner's are overwritten.
    for statement in (
        "UPDATE site_presence SET since = now()",
        "UPDATE site_sensor SET status_at = now()",
        "UPDATE site_readiness_item SET done_at = now()",
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(statement)
    before = await world.conn.fetchrow(
        "SELECT (SELECT since FROM site_presence WHERE id = $1) AS since, "
        "(SELECT status_at FROM site_sensor WHERE id = $2) AS status_at",
        presence_id,
        sensor_id,
    )
    assert before is not None
    await owner.execute(
        "UPDATE site_presence SET since = $2::timestamptz WHERE id = $1", presence_id, forged
    )
    await owner.execute(
        "UPDATE site_sensor SET status_at = $2::timestamptz WHERE id = $1", sensor_id, forged
    )
    # Same zone, same status and detail: the times are kept, not forged.
    await world.conn.execute(
        "UPDATE site_presence SET zone_id = zone_id WHERE id = $1", presence_id
    )
    after = await world.conn.fetchrow(
        "SELECT (SELECT since FROM site_presence WHERE id = $1) AS since, "
        "(SELECT status_at FROM site_sensor WHERE id = $2) AS status_at",
        presence_id,
        sensor_id,
    )
    assert after is not None
    assert tuple(after) == tuple(before)


async def test_a_readiness_item_cannot_be_undone(world: World, owner: asyncpg.Connection) -> None:
    item_id = await world.conn.fetchval(
        "INSERT INTO site_readiness_item (tenant_id, site_id, label) "
        "VALUES (current_tenant_id(), $1, 'Open item') RETURNING id",
        world.site,
    )
    with pytest.raises(REFUSED, match="the only change is marking it done"):
        await world.conn.execute(
            "UPDATE site_readiness_item SET done_by = NULL WHERE id = $1", item_id
        )
    await world.conn.execute(
        "UPDATE site_readiness_item SET done_by = $2 WHERE id = $1", item_id, world.security
    )
    with pytest.raises(REFUSED, match="done is final"):
        await owner.execute("UPDATE site_readiness_item SET done_by = NULL WHERE id = $1", item_id)
