"""Migration 0014 (PC-43..45; D-44), checked as nexira_api: suppliers and routes are seeded
and change only their reported status (the database writes the time); a backup serves the same
mission or is Global; a route is run by a supplier of its mission and is an alternate only within
it; a mitigation records the supplier's own backup and an alternate of its routes, at an incident
of its mission, is active once per supplier and is stood down once by a person of the tenant;
nothing is deleted (docs/plan-pilot-sup.md §11)."""

import itertools
import uuid
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
PT = "'SRID=4326;POINT(36.808 -1.295)'"
CBD = "SRID=4326;LINESTRING(36.808 -1.295, 36.8172 -1.2864, 36.9278 -1.3192)"
BYPASS = "SRID=4326;LINESTRING(36.808 -1.295, 36.80 -1.33, 36.9278 -1.3192)"
VETTED = date(2027, 6, 30)
_REFERENCES = itertools.count(1000)


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


async def incident(conn: asyncpg.Connection, mission_id: uuid.UUID | None) -> uuid.UUID:
    incident_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        f"mission_id, location) VALUES (current_tenant_id(), $1, 'Unrest', 'CIVIL_UNREST', "
        f"'CRITICAL', 'HIGH', $2, {PT}) RETURNING id",
        f"INC-2026-{next(_REFERENCES):04d}",  # unique per tenant (review of Prompt 90, L6)
        mission_id,
    )
    return incident_id


async def _insert(conn: asyncpg.Connection, table: str, columns: dict[str, Any]) -> uuid.UUID:
    names = ", ".join(["tenant_id", *columns])
    values = ", ".join(
        [
            "current_tenant_id()",
            *(
                f"${n}::geography" if name == "path" else f"${n}"
                for n, name in enumerate(columns, start=1)
            ),
        ]
    )
    row_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO {table} ({names}) VALUES ({values}) RETURNING id", *columns.values()
    )
    return row_id


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.mission = await mission(self.conn)
        self.cairo = await mission(self.conn, "CAI")
        self.duty = await user(self.conn)
        self.backup = await self.supplier("SUP-105", name="Kestrel Express Couriers", tier=2)
        self.courier = await self.supplier("SUP-104", backup_supplier_id=self.backup)
        self.cbd = await self.route("R-NBO-1")
        self.bypass = await self.route("R-NBO-2", path=BYPASS, alternate_of_id=self.cbd)
        self.unrest = await incident(self.conn, self.mission)
        return self

    async def supplier(self, code: str, **change: Any) -> uuid.UUID:
        return await _insert(
            self.conn,
            "supplier",
            {
                "code": code,
                "name": "Swiftline Couriers",
                "service": "Diplomatic pouch courier",
                "mission_id": self.mission,
                "tier": 1,
                "vetting_valid_until": VETTED,
                **change,
            },
        )

    async def route(self, code: str, **change: Any) -> uuid.UUID:
        return await _insert(
            self.conn,
            "logistics_route",
            {
                "mission_id": self.mission,
                "code": code,
                "label": "Pouch: Embassy → JKIA via CBD",
                "kind": "POUCH",
                "supplier_id": self.courier,
                "path": CBD,
                **change,
            },
        )

    async def mitigation(self, **change: Any) -> uuid.UUID:
        return await _insert(
            self.conn,
            "supply_mitigation",
            {
                "supplier_id": self.courier,
                "incident_id": self.unrest,
                "backup_supplier_id": self.backup,
                "route_id": self.bypass,
                "activated_by": self.duty,
                **change,
            },
        )


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Supply"))
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


async def _other_tenant(db: DbUrls, world: World) -> dict[str, uuid.UUID]:
    """Another tenant's mission, supplier, route, incident and user, created as nexira_api."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs = World(world.conn)
    await theirs.build()
    await set_tenant(world.conn, mine)
    return {
        "mission": theirs.mission,
        "supplier": theirs.courier,
        "route": theirs.cbd,
        "incident": theirs.unrest,
        "user": theirs.duty,
    }


# --- PC-43 · suppliers ---------------------------------------------------------------------------


async def test_a_supplier_changes_only_its_reported_status(
    world: World, owner: asyncpg.Connection
) -> None:
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE supplier SET status = 'DELAYED', "
            "status_detail = 'Fuel delivery postponed 24 h' WHERE id = $1",
            world.courier,
        )
        row = await world.conn.fetchrow(
            "SELECT status, status_detail, status_at = now() AS fresh, source FROM supplier "
            "WHERE id = $1",
            world.courier,
        )
    assert row is not None
    assert tuple(row) == (
        "DELAYED",
        "Fuel delivery postponed 24 h",
        True,
        "Illustrative supplier register (simulated)",
    )
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE supplier SET status = 'BLOCKED' WHERE id = $1", world.courier
        )
    for column, value in (
        ("tier", 3),
        ("name", "x"),
        ("backup_supplier_id", None),
        ("in_bcp", True),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(
                f"UPDATE supplier SET {column} = $2 WHERE id = $1", world.courier, value
            )
        with pytest.raises(REFUSED, match="only the reported status changes"):
            await owner.execute(
                f"UPDATE supplier SET {column} = $2 WHERE id = $1", world.courier, value
            )
    with pytest.raises(UNIQUE):
        await world.supplier("SUP-104")


@pytest.mark.parametrize(
    "change",
    [
        {"code": "SUP-1"},
        {"code": "S-104"},
        {"tier": 0},
        {"tier": 4},
        {"performance_score": 101},
        {"status": "ROUTE_BLOCKED"},  # shown, never stored (§73 Q2)
        {"name": ""},
        {"status_detail": "x" * 301},
    ],
)
async def test_a_supplier_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    with pytest.raises(CHECK):
        await world.supplier(change.pop("code", "SUP-200"), **change)


async def test_a_backup_serves_the_same_mission_or_is_global(db: DbUrls, world: World) -> None:
    global_backup = await world.supplier(
        "SUP-305", mission_id=None, name="Northbridge Translations"
    )
    assert await world.supplier("SUP-106", backup_supplier_id=global_backup)
    cairo = await world.supplier("SUP-233", mission_id=world.cairo)
    with pytest.raises(REFUSED, match="same mission or Global"):
        await world.supplier("SUP-107", backup_supplier_id=cairo)
    theirs = await _other_tenant(db, world)
    with pytest.raises(REFUSED, match="same mission or Global"):
        await world.supplier("SUP-108", backup_supplier_id=theirs["supplier"])
    with pytest.raises(REFUSED, match="supplier: no such mission"):
        await world.supplier("SUP-109", mission_id=theirs["mission"])
    with pytest.raises(REFUSED, match="the backup is a supplier"):  # not its own (L5)
        await world.conn.execute(
            "INSERT INTO supplier (id, tenant_id, code, name, service, tier, vetting_valid_until, "
            "backup_supplier_id) "
            "VALUES ($1, current_tenant_id(), 'SUP-110', 'Self', 'x', 1, $2, $1)",
            uuid.uuid4(),
            VETTED,
        )


# --- PC-44 · logistics routes ------------------------------------------------------------------


async def test_a_route_changes_only_its_reported_status(
    world: World, owner: asyncpg.Connection
) -> None:
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE logistics_route SET status = 'BLOCKED', detail = 'Road closure CBD → JKIA' "
            "WHERE id = $1",
            world.cbd,
        )
        row = await world.conn.fetchrow(
            "SELECT status, detail, status_at = now() AS fresh FROM logistics_route WHERE id = $1",
            world.cbd,
        )
    assert row is not None
    assert tuple(row) == ("BLOCKED", "Road closure CBD → JKIA", True)
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE logistics_route SET status = 'ALTERNATE' WHERE id = $1", world.cbd
        )
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE logistics_route SET label = 'x'")
    for statement in (
        "UPDATE logistics_route SET label = 'x'",
        "UPDATE logistics_route SET alternate_of_id = NULL",
        f"UPDATE logistics_route SET path = '{BYPASS}'::geography WHERE code = 'R-NBO-1'",
    ):
        with pytest.raises(REFUSED, match="only the reported status changes"):
            await owner.execute(statement)
    with pytest.raises(UNIQUE):
        await world.route("R-NBO-1")


@pytest.mark.parametrize(
    "change",
    [
        {"code": "NBO-1"},
        {"kind": "AIR"},
        {"status": "CLOSED"},
        {"path": "SRID=4326;LINESTRING(" + ", ".join(f"36.{i:03d} -1.29" for i in range(51)) + ")"},
    ],
)
async def test_a_route_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    with pytest.raises(CHECK):
        await world.route(change.pop("code", "R-NBO-8"), **change)


async def test_a_route_path_is_a_line_of_2_to_50_points(world: World) -> None:
    assert await world.route("R-NBO-8", path="SRID=4326;LINESTRING(36.8 -1.29, 36.9 -1.31)")
    fifty = ", ".join(f"36.{i:03d} -1.29" for i in range(50))
    assert await world.route("R-NBO-9", path=f"SRID=4326;LINESTRING({fifty})")
    for path in ("SRID=4326;POINT(36.8 -1.29)", "SRID=4326;POLYGON((0 0, 1 0, 1 1, 0 0))"):
        with pytest.raises(asyncpg.PostgresError):
            await world.route("R-NBO-7", path=path)


async def test_a_route_is_run_and_replaced_within_its_mission(db: DbUrls, world: World) -> None:
    cairo_supplier = await world.supplier("SUP-233", mission_id=world.cairo)
    with pytest.raises(REFUSED, match="run by a supplier of this mission"):
        await world.route("R-NBO-3", supplier_id=cairo_supplier)
    cairo_route = await world.route("R-CAI-1", mission_id=world.cairo, supplier_id=cairo_supplier)
    with pytest.raises(REFUSED, match="an alternate for a route of the same mission"):
        await world.route("R-NBO-4", alternate_of_id=cairo_route)
    global_courier = await world.supplier("SUP-305", mission_id=None)
    assert await world.route("R-NBO-5", supplier_id=global_courier)
    assert await world.route("R-NBO-6", supplier_id=None)
    theirs = await _other_tenant(db, world)
    for change, message in (
        ({"mission_id": theirs["mission"], "supplier_id": None}, "no such mission"),
        ({"supplier_id": theirs["supplier"]}, "run by a supplier"),
        ({"alternate_of_id": theirs["route"]}, "an alternate for a route"),
    ):
        with pytest.raises(REFUSED, match=message):
            await world.route("R-NBO-10", **change)


# --- PC-45 · mitigations -----------------------------------------------------------------------


async def test_a_mitigation_is_active_once_and_stood_down_once(
    db: DbUrls, world: World, owner: asyncpg.Connection
) -> None:
    async with world.conn.transaction():
        mitigation_id = await world.mitigation(note="Backup on standby")
        assert await world.conn.fetchval(
            "SELECT activated_at = now() AND stood_down_at IS NULL FROM supply_mitigation "
            "WHERE id = $1",
            mitigation_id,
        )
    with pytest.raises(UNIQUE):
        await world.mitigation()  # one active per supplier
    stand_down = "UPDATE supply_mitigation SET stood_down_by = $2 WHERE id = $1"
    theirs = await _other_tenant(db, world)
    with pytest.raises(REFUSED, match="stood down by someone of this tenant"):
        await world.conn.execute(stand_down, mitigation_id, theirs["user"])
    async with world.conn.transaction():
        await world.conn.execute(stand_down, mitigation_id, world.duty)
        assert await world.conn.fetchval(
            "SELECT stood_down_at = now() FROM supply_mitigation WHERE id = $1", mitigation_id
        )
    with pytest.raises(REFUSED, match="stood down is final"):
        await world.conn.execute(stand_down, mitigation_id, await user(world.conn))
    with pytest.raises(REFUSED, match="stood down is final"):
        await owner.execute(
            "UPDATE supply_mitigation SET stood_down_by = NULL WHERE id = $1", mitigation_id
        )
    assert await world.mitigation()  # a new one after the stand-down
    someone = await user(world.conn)
    for column, value in (("note", "x"), ("route_id", None), ("activated_by", someone)):
        with pytest.raises(DENIED):
            await world.conn.execute(f"UPDATE supply_mitigation SET {column} = $1", value)
        with pytest.raises(REFUSED, match="the only change is standing it down"):
            await owner.execute(f"UPDATE supply_mitigation SET {column} = $1", value)


async def test_a_mitigation_cannot_be_undone_or_start_stood_down(world: World) -> None:
    mitigation_id = await world.mitigation(route_id=None, backup_supplier_id=None)
    with pytest.raises(REFUSED, match="standing it down, by someone"):
        await world.conn.execute(
            "UPDATE supply_mitigation SET stood_down_by = NULL WHERE id = $1", mitigation_id
        )
    other = await world.supplier("SUP-126", name="Savanna IT Networks")
    with pytest.raises(REFUSED, match="starts active"):
        await world.mitigation(
            supplier_id=other, backup_supplier_id=None, route_id=None, stood_down_by=world.duty
        )


async def test_a_mitigation_records_only_what_belongs_to_the_supplier(
    db: DbUrls, world: World
) -> None:
    stranger = await world.supplier("SUP-122", name="Mara Energy Supplies", tier=2)
    fuel = await world.supplier("SUP-121", name="Rift Valley Fuels", backup_supplier_id=stranger)
    cairo_incident = await incident(world.conn, world.cairo)
    no_mission = await incident(world.conn, None)
    fuel_route = await world.route("R-NBO-3", supplier_id=fuel, kind="FUEL")
    fuel_alternate = await world.route("R-NBO-4", supplier_id=fuel, alternate_of_id=fuel_route)
    theirs = await _other_tenant(db, world)
    for change, message in (
        ({"backup_supplier_id": stranger}, "the supplier's own backup"),
        ({"route_id": world.cbd}, "an alternate for one of the supplier's routes"),
        ({"route_id": fuel_alternate}, "an alternate for one of the supplier's routes"),
        ({"incident_id": cairo_incident}, "an incident at the supplier's mission"),
        ({"incident_id": no_mission}, "an incident at the supplier's mission"),
        ({"incident_id": theirs["incident"]}, "an incident at the supplier's mission"),
        ({"supplier_id": theirs["supplier"]}, "no such supplier"),
        ({"activated_by": theirs["user"]}, "activated by someone of this tenant"),
    ):
        with pytest.raises(REFUSED, match=message):
            await world.mitigation(**change)
    global_supplier = await world.supplier("SUP-305", mission_id=None)
    with pytest.raises(REFUSED, match="an incident at the supplier's mission"):
        await world.mitigation(supplier_id=global_supplier, backup_supplier_id=None, route_id=None)
    assert await world.mitigation(
        supplier_id=fuel, backup_supplier_id=stranger, route_id=None, incident_id=None
    )


async def test_the_database_writes_every_time_even_when_forged(
    world: World, owner: asyncpg.Connection
) -> None:
    forged = datetime(2000, 1, 1, tzinfo=UTC)
    async with world.conn.transaction():
        supplier_id = await world.supplier("SUP-130", status_at=forged, created_at=forged)
        route_id = await world.route("R-NBO-3", status_at=forged, created_at=forged)
        mitigation_id = await world.mitigation(activated_at=forged, stood_down_at=None)
        fresh = await world.conn.fetchrow(
            "SELECT (SELECT status_at = now() AND created_at = now() FROM supplier "
            "WHERE id = $1) AS s, (SELECT status_at = now() AND created_at = now() "
            "FROM logistics_route WHERE id = $2) AS r, (SELECT activated_at = now() "
            "FROM supply_mitigation WHERE id = $3) AS m",
            supplier_id,
            route_id,
            mitigation_id,
        )
    assert fresh is not None
    assert tuple(fresh) == (True, True, True)
    for statement in (
        "UPDATE supplier SET status_at = now()",
        "UPDATE logistics_route SET status_at = now()",
        "UPDATE supply_mitigation SET stood_down_at = now()",
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(statement)
    before = await world.conn.fetchval("SELECT status_at FROM supplier WHERE id = $1", supplier_id)
    await owner.execute(
        "UPDATE supplier SET status_at = $2::timestamptz WHERE id = $1", supplier_id, forged
    )
    await owner.execute(
        "UPDATE logistics_route SET status_at = $2::timestamptz WHERE id = $1", route_id, forged
    )
    # Same status and detail: the time is kept, not forged.
    assert (
        await world.conn.fetchval("SELECT status_at FROM supplier WHERE id = $1", supplier_id)
        == before
    )
    assert await world.conn.fetchval(
        "SELECT status_at <> $2::timestamptz FROM logistics_route WHERE id = $1", route_id, forged
    )
    with pytest.raises(REFUSED, match="the only change is standing it down"):
        await owner.execute(
            "UPDATE supply_mitigation SET activated_at = $2::timestamptz WHERE id = $1",
            mitigation_id,
            forged,
        )


# --- every table -------------------------------------------------------------------------------


async def test_nothing_is_deleted(world: World, owner: asyncpg.Connection) -> None:
    await world.mitigation()
    for table, kept in (
        ("supply_mitigation", "mitigations are kept"),
        ("logistics_route", "routes are kept"),
        ("supplier", "suppliers are kept"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"DELETE FROM {table}")
        with pytest.raises(REFUSED, match=kept):
            await owner.execute(f"DELETE FROM {table}")


async def test_each_tenant_sees_only_its_own(db: DbUrls, world: World) -> None:
    await world.mitigation()
    await _other_tenant(db, world)
    counts = await world.conn.fetchrow(
        "SELECT (SELECT count(*) FROM supplier) AS s, (SELECT count(*) FROM logistics_route) AS r, "
        "(SELECT count(*) FROM supply_mitigation) AS m"
    )
    assert counts is not None
    assert tuple(counts) == (2, 2, 1)
    theirs = await create_tenant(db, "Third")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):  # WITH CHECK
        await world.conn.execute(
            "INSERT INTO supplier (tenant_id, code, name, service, tier, vetting_valid_until) "
            "VALUES ($1, 'SUP-999', 'x', 'x', 3, $2)",
            theirs,
            VETTED,
        )


async def test_the_backup_role_reads_the_supply_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w FROM unnest(ARRAY["
            "'logistics_route', 'supplier', 'supply_mitigation']) t ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("logistics_route", True, False),
        ("supplier", True, False),
        ("supply_mitigation", True, False),
    ]


# --- review of Prompt 90 -----------------------------------------------------------------------


async def test_a_route_is_not_its_own_alternate(world: World) -> None:
    """L5: the guard refuses first (the row does not exist yet); the CHECK is defence in depth."""
    route_id = uuid.uuid4()
    with pytest.raises(REFUSED, match="an alternate for a route of the same mission"):
        await world.route("R-NBO-3", id=route_id, alternate_of_id=route_id)


async def test_the_guards_compare_tenants_even_without_rls(db: DbUrls, world: World) -> None:
    """L1: a superuser bypasses RLS, so only the guards' own tenant checks stop a row of this
    tenant from pointing at another tenant's mission, supplier, route, incident or user."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    theirs = await _other_tenant(db, world)
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        assert await conn.fetchval(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        supplier = (
            "INSERT INTO supplier (tenant_id, code, name, service, tier, vetting_valid_until, "
            "mission_id, backup_supplier_id) VALUES ($1, $2, 'x', 'x', 1, $3, $4, $5)"
        )
        with pytest.raises(REFUSED, match="supplier: no such mission"):
            await conn.execute(supplier, mine, "SUP-501", VETTED, theirs["mission"], None)
        with pytest.raises(REFUSED, match="the backup is a supplier of this tenant"):
            await conn.execute(supplier, mine, "SUP-502", VETTED, None, theirs["supplier"])
        route = (
            "INSERT INTO logistics_route (tenant_id, mission_id, code, label, kind, supplier_id, "
            f"alternate_of_id, path) VALUES ($1, $2, $3, 'x', 'POUCH', $4, $5, '{CBD}')"
        )
        with pytest.raises(REFUSED, match="logistics route: no such mission"):
            await conn.execute(route, mine, theirs["mission"], "R-NBO-11", None, None)
        with pytest.raises(REFUSED, match="run by a supplier of this mission"):
            await conn.execute(route, mine, world.mission, "R-NBO-12", theirs["supplier"], None)
        with pytest.raises(REFUSED, match="an alternate for a route of the same mission"):
            await conn.execute(route, mine, world.mission, "R-NBO-13", None, theirs["route"])
        mitigation = (
            "INSERT INTO supply_mitigation (tenant_id, supplier_id, incident_id, activated_by) "
            "VALUES ($1, $2, $3, $4)"
        )
        for args, message in (
            ((theirs["supplier"], None, world.duty), "no such supplier"),
            ((world.courier, None, theirs["user"]), "activated by someone of this tenant"),
            ((world.courier, theirs["incident"], world.duty), "an incident at the supplier"),
        ):
            with pytest.raises(REFUSED, match=message):
                await conn.execute(mitigation, mine, *args)
        mitigation_id = await world.mitigation(route_id=None)
        with pytest.raises(REFUSED, match="stood down by someone of this tenant"):
            await conn.execute(
                "UPDATE supply_mitigation SET stood_down_by = $2 WHERE id = $1",
                mitigation_id,
                theirs["user"],
            )
    finally:
        await conn.close()


async def test_forged_stand_down_times_are_overwritten(
    world: World, owner: asyncpg.Connection
) -> None:
    """L2: a mitigation never starts stood down, and the database writes the stand-down time."""
    forged = datetime(2000, 1, 1, tzinfo=UTC)
    mitigation_id = await world.mitigation(stood_down_at=forged)
    assert await world.conn.fetchval(
        "SELECT stood_down_at IS NULL FROM supply_mitigation WHERE id = $1", mitigation_id
    )
    async with owner.transaction():
        await owner.execute(
            "UPDATE supply_mitigation SET stood_down_by = $2, stood_down_at = $3::timestamptz "
            "WHERE id = $1",
            mitigation_id,
            world.duty,
            forged,
        )
        assert await owner.fetchval(
            "SELECT stood_down_at = now() FROM supply_mitigation WHERE id = $1", mitigation_id
        )


async def test_a_status_change_gets_the_database_time_even_when_forged(
    world: World, owner: asyncpg.Connection
) -> None:
    """L3: a changed status with a forged time still gets now()."""
    forged = datetime(2000, 1, 1, tzinfo=UTC)
    async with owner.transaction():
        await owner.execute(
            "UPDATE supplier SET status = 'WATCH', status_at = $2::timestamptz WHERE id = $1",
            world.courier,
            forged,
        )
        await owner.execute(
            "UPDATE logistics_route SET status = 'BLOCKED', status_at = $2::timestamptz "
            "WHERE id = $1",
            world.cbd,
            forged,
        )
        row = await owner.fetchrow(
            "SELECT (SELECT status_at = now() FROM supplier WHERE id = $1) AS s, "
            "(SELECT status_at = now() FROM logistics_route WHERE id = $2) AS r",
            world.courier,
            world.cbd,
        )
    assert row is not None
    assert tuple(row) == (True, True)


FROZEN: dict[str, list[tuple[str, str]]] = {
    # (column, a new value in SQL) for every column the guards freeze (L4).
    "supplier": [
        ("tenant_id", "gen_random_uuid()"),
        ("code", "'SUP-999'"),
        ("name", "'x'"),
        ("service", "'x'"),
        ("mission_id", "NULL"),
        ("tier", "3"),
        ("backup_supplier_id", "NULL"),
        ("in_bcp", "NOT in_bcp"),
        ("vetting_valid_until", "vetting_valid_until + 1"),
        ("performance_score", "7"),
        ("source", "'x'"),
        ("created_at", "now() - interval '1 day'"),
    ],
    "logistics_route": [
        ("tenant_id", "gen_random_uuid()"),
        ("mission_id", "gen_random_uuid()"),
        ("code", "'R-NBO-99'"),
        ("label", "'x'"),
        ("kind", "'FREIGHT'"),
        ("supplier_id", "NULL"),
        ("alternate_of_id", "NULL"),
        ("path", f"'{CBD}'"),
        ("created_at", "now() - interval '1 day'"),
    ],
    "supply_mitigation": [
        ("tenant_id", "gen_random_uuid()"),
        ("supplier_id", "gen_random_uuid()"),
        ("incident_id", "NULL"),
        ("backup_supplier_id", "NULL"),
        ("route_id", "NULL"),
        ("note", "'x'"),
        ("activated_by", "gen_random_uuid()"),
        ("activated_at", "now() - interval '1 day'"),
    ],
}


async def test_every_frozen_column_is_refused_for_the_owner(
    world: World, owner: asyncpg.Connection
) -> None:
    """L4: each frozen column on its own, as the owner (the app has no grant for any)."""
    await world.mitigation()
    messages = {
        "supplier": "only the reported status changes",
        "logistics_route": "only the reported status changes",
        "supply_mitigation": "the only change is standing it down",
    }
    for table, columns in FROZEN.items():
        target = {"supplier": world.courier, "logistics_route": world.bypass}.get(table)
        where = f"WHERE id = '{target}'" if target else ""
        for column, value in columns:
            with pytest.raises(REFUSED, match=messages[table]):
                await owner.execute(f"UPDATE {table} SET {column} = {value} {where}")
