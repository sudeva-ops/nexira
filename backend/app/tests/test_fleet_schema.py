"""Migration 0011 (PC-33..34; D-41), checked as nexira_api: the asset register is seeded
reference data whose position, fuel and status alone change, positions move forward in time,
and a maintenance item is done once (docs/plan-pilot-flt.md §2, §5, §6, §12)."""

import asyncio
import uuid
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
PT = "'SRID=4326;POINT(36.808 -1.295)'"
MOVED = "'SRID=4326;POINT(36.8195 -1.2985)'"


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


async def person(conn: asyncpg.Connection, mission_id: uuid.UUID) -> uuid.UUID:
    person_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
        "VALUES (current_tenant_id(), $1, 'LOCAL_STAFF', 'Fictional Driver') RETURNING id",
        mission_id,
    )
    return person_id


async def asset(conn: asyncpg.Connection, mission_id: uuid.UUID, **change: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "mission_id": mission_id,
        "code": "VH-01",
        "kind": "VEHICLE",
        "type_label": "Armoured SUV (B6)",
        "armoured": True,
        "seats": 4,
        "location_label": "Embassy garage",
        "fuel_pct": 82,
        **change,
    }
    names = ", ".join(["tenant_id", "location", *columns])
    values = ", ".join(["current_tenant_id()", PT, *(f"${n}" for n in range(1, len(columns) + 1))])
    asset_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO fleet_asset ({names}) VALUES ({values}) RETURNING id", *columns.values()
    )
    return asset_id


async def item(conn: asyncpg.Connection, asset_id: uuid.UUID, **change: Any) -> uuid.UUID:
    columns: dict[str, Any] = {"asset_id": asset_id, "task": "Brake service", **change}
    names = ", ".join(["tenant_id", "due_on", *columns])
    values = ", ".join(
        ["current_tenant_id()", "current_date", *(f"${n}" for n in range(1, len(columns) + 1))]
    )
    item_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO fleet_maintenance ({names}) VALUES ({values}) RETURNING id",
        *columns.values(),
    )
    return item_id


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Fleet"))
    return api


@pytest.fixture
async def owner(db: DbUrls, api_tenant: asyncpg.Connection) -> Any:
    """The table owner in the same tenant: the guards hold for it too (defence in depth)."""
    conn = await asyncpg.connect(db.owner_plain)
    await set_tenant(conn, await api_tenant.fetchval("SELECT current_tenant_id()"))
    try:
        yield conn
    finally:
        await conn.close()


# --- PC-33 · the asset register ---------------------------------------------------------------


async def test_an_asset_is_added_with_the_database_writing_its_times(
    api_tenant: asyncpg.Connection,
) -> None:
    conn = api_tenant
    async with conn.transaction():  # one now() for the inserts and the read
        nbo = await mission(conn)
        vehicle = await asset(conn, nbo, driver_id=await person(conn, nbo))
        generator = await asset(
            conn, nbo, code="GEN-NBO", kind="EQUIPMENT", type_label="Generator 250 kVA",
            armoured=False, seats=None, location_label="Embassy", fuel_pct=72,
        )  # fmt: skip
        rows = await conn.fetch(
            "SELECT code, status, source, created_at = now() AS fresh FROM fleet_asset "
            "WHERE id = ANY($1::uuid[]) ORDER BY code",
            [vehicle, generator],
        )
        assert [tuple(r) for r in rows] == [
            ("GEN-NBO", "AVAILABLE", "Illustrative asset register (simulated)", True),
            ("VH-01", "AVAILABLE", "Illustrative asset register (simulated)", True),
        ]
    with pytest.raises(UNIQUE):
        await asset(conn, nbo)


@pytest.mark.parametrize(
    "change",
    [
        {"code": "CAR-1"},  # neither VH-nn nor <KIND>-<mission>
        {"kind": "BOAT"},
        {"code": "GEN-NBO"},  # a vehicle's code starts VH-
        {"kind": "EQUIPMENT", "seats": None},  # equipment is not VH-
        {"code": "GEN-NBO", "kind": "EQUIPMENT"},  # equipment has no seats
        {"code": "GEN-NBO", "kind": "EQUIPMENT", "seats": None},  # nor armour
        {"seats": None},  # a vehicle has seats
        {"seats": 0},
        {"fuel_pct": 101},
        {"fuel_pct": -1},
        {"type_label": ""},
        {"status": "BLOCKED"},  # blocked, in zone and assigned are derived (§58 Q3)
        {"status": "MAINTENANCE"},  # needs a reason
        {"status": "AVAILABLE", "status_reason": ""},
    ],
)
async def test_an_asset_refuses_bad_values(
    api_tenant: asyncpg.Connection, change: dict[str, Any]
) -> None:
    with pytest.raises(CHECK):
        await asset(api_tenant, await mission(api_tenant), **change)


async def test_equipment_is_never_in_use(api_tenant: asyncpg.Connection) -> None:
    with pytest.raises(CHECK):
        await asset(
            api_tenant, await mission(api_tenant), code="SAT-NBO", kind="EQUIPMENT",
            type_label="Satellite terminal", armoured=False, seats=None, status="IN_USE",
        )  # fmt: skip


async def test_an_asset_names_only_this_tenants_mission_and_this_missions_driver(
    db: DbUrls, api_tenant: asyncpg.Connection
) -> None:
    conn = api_tenant
    mine = await conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(conn, await create_tenant(db, "Other"))
    their_mission = await mission(conn)
    their_driver = await person(conn, their_mission)
    await set_tenant(conn, mine)
    with pytest.raises(REFUSED, match="no such mission"):
        await asset(conn, their_mission)
    nbo = await mission(conn)
    with pytest.raises(REFUSED, match="the driver is a person of this mission"):
        await asset(conn, nbo, driver_id=their_driver)
    elsewhere = await person(conn, await mission(conn, "CAI"))
    with pytest.raises(REFUSED, match="the driver is a person of this mission"):
        await asset(conn, nbo, driver_id=elsewhere)


async def test_a_seeded_position_is_not_in_the_future(api_tenant: asyncpg.Connection) -> None:
    with pytest.raises(REFUSED, match="not in the future"):
        await api_tenant.execute(
            "INSERT INTO fleet_asset (tenant_id, mission_id, code, kind, type_label, seats, "
            f"location, location_label, fuel_pct, position_at) VALUES (current_tenant_id(), $1, "
            f"'VH-01', 'VEHICLE', 'Pickup 4x4', 3, {PT}, 'Residence', 64, now() + interval '1 h')",
            await mission(api_tenant),
        )


async def test_the_app_moves_position_fuel_and_status_only(api_tenant: asyncpg.Connection) -> None:
    conn = api_tenant
    vehicle = await asset(conn, await mission(conn))
    before = await conn.fetchrow("SELECT * FROM fleet_asset WHERE id = $1", vehicle)
    await asyncio.sleep(0.01)  # a new now(), later than the seeded position
    await conn.execute(
        f"UPDATE fleet_asset SET location = {MOVED}, location_label = 'Haile Selassie Ave', "
        "fuel_pct = 46, position_at = now(), status = 'IN_USE' WHERE id = $1",
        vehicle,
    )
    after = await conn.fetchrow("SELECT * FROM fleet_asset WHERE id = $1", vehicle)
    assert after is not None
    assert before is not None
    assert (after["location_label"], after["fuel_pct"], after["status"]) == (
        "Haile Selassie Ave",
        46,
        "IN_USE",
    )
    assert after["updated_at"] > before["updated_at"]
    for stmt in (
        "UPDATE fleet_asset SET code = 'VH-02'",
        "UPDATE fleet_asset SET seats = 13",
        "UPDATE fleet_asset SET driver_id = NULL",
        "UPDATE fleet_asset SET mission_id = mission_id",
        "UPDATE fleet_asset SET updated_at = now()",
        "DELETE FROM fleet_asset",
    ):
        with pytest.raises(DENIED):
            await conn.execute(stmt)


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE fleet_asset SET code = 'VH-02'",
        "UPDATE fleet_asset SET seats = 13",
        "UPDATE fleet_asset SET armoured = false",
        "UPDATE fleet_asset SET type_label = 'Sedan'",
        "UPDATE fleet_asset SET source = 'real'",
    ],
)
async def test_what_an_asset_is_stays_fixed_for_the_owner_too(
    api_tenant: asyncpg.Connection, owner: asyncpg.Connection, stmt: str
) -> None:
    await asset(api_tenant, await mission(api_tenant))
    with pytest.raises(REFUSED, match="are fixed"):
        await owner.execute(stmt)


async def test_assets_are_kept(api_tenant: asyncpg.Connection, owner: asyncpg.Connection) -> None:
    await asset(api_tenant, await mission(api_tenant))
    with pytest.raises(REFUSED, match="assets are kept"):
        await owner.execute("DELETE FROM fleet_asset")


async def test_positions_move_forward_in_time(api_tenant: asyncpg.Connection) -> None:
    conn = api_tenant
    vehicle = await asset(conn, await mission(conn))
    with pytest.raises(REFUSED, match="newer than the last"):
        await conn.execute(
            f"UPDATE fleet_asset SET location = {MOVED}, position_at = position_at - "
            "interval '1 min' WHERE id = $1",
            vehicle,
        )
    with pytest.raises(REFUSED, match="not in the future"):
        await conn.execute(
            f"UPDATE fleet_asset SET location = {MOVED}, position_at = now() + "
            "interval '1 min' WHERE id = $1",
            vehicle,
        )
    with pytest.raises(REFUSED, match="a new position has a new time"):
        await conn.execute(f"UPDATE fleet_asset SET location = {MOVED} WHERE id = $1", vehicle)


async def test_maintenance_needs_a_reason(api_tenant: asyncpg.Connection) -> None:
    conn = api_tenant
    vehicle = await asset(conn, await mission(conn))
    with pytest.raises(REFUSED, match="maintenance needs a reason"):
        await conn.execute("UPDATE fleet_asset SET status = 'MAINTENANCE' WHERE id = $1", vehicle)
    await conn.execute(
        "UPDATE fleet_asset SET status = 'MAINTENANCE', status_reason = 'Brake service overdue' "
        "WHERE id = $1",
        vehicle,
    )
    await conn.execute(
        "UPDATE fleet_asset SET status = 'AVAILABLE', status_reason = NULL WHERE id = $1", vehicle
    )
    assert await conn.fetchval("SELECT status FROM fleet_asset WHERE id = $1", vehicle) == (
        "AVAILABLE"
    )


# --- PC-34 · maintenance items ----------------------------------------------------------------


async def test_an_item_starts_not_done(api_tenant: asyncpg.Connection) -> None:
    conn = api_tenant
    vehicle = await asset(conn, await mission(conn))
    item_id = await item(conn, vehicle)
    row = await conn.fetchrow("SELECT * FROM fleet_maintenance WHERE id = $1", item_id)
    assert row is not None
    assert (row["done_at"], row["done_by_type"], row["done_by"]) == (None, None, None)
    with pytest.raises(REFUSED, match="an item starts not done"):
        await item(conn, vehicle, done_by_type="WORKSHOP", done_by="workshop (simulated)")


async def test_an_item_names_only_this_tenants_asset(
    db: DbUrls, api_tenant: asyncpg.Connection
) -> None:
    conn = api_tenant
    mine = await conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(conn, await create_tenant(db, "Other"))
    theirs = await asset(conn, await mission(conn))
    await set_tenant(conn, mine)
    with pytest.raises(REFUSED, match="no such asset"):
        await item(conn, theirs)


async def test_an_item_is_done_once_and_the_database_writes_the_time(
    api_tenant: asyncpg.Connection,
) -> None:
    conn = api_tenant
    item_id = await item(conn, await asset(conn, await mission(conn)))
    by = await user(conn)
    async with conn.transaction():  # one now() for the update and the read
        await conn.execute(
            "UPDATE fleet_maintenance SET done_by_type = 'USER', done_by = $2 WHERE id = $1",
            item_id,
            str(by),
        )
        row = await conn.fetchrow(
            "SELECT done_by, done_at = now() AS fresh FROM fleet_maintenance WHERE id = $1",
            item_id,
        )
    assert row is not None
    assert (row["done_by"], row["fresh"]) == (str(by), True)
    for stmt in (
        "UPDATE fleet_maintenance SET done_by_type = 'WORKSHOP', done_by = 'w' WHERE id = $1",
        "UPDATE fleet_maintenance SET done_by_type = NULL, done_by = NULL WHERE id = $1",
    ):
        with pytest.raises(REFUSED, match="done is final"):
            await conn.execute(stmt, item_id)


async def test_the_simulated_workshop_marks_an_item_done(api_tenant: asyncpg.Connection) -> None:
    conn = api_tenant
    item_id = await item(conn, await asset(conn, await mission(conn)))
    await conn.execute(
        "UPDATE fleet_maintenance SET done_by_type = 'WORKSHOP', done_by = 'workshop (simulated)' "
        "WHERE id = $1",
        item_id,
    )
    assert await conn.fetchval(
        "SELECT done_at IS NOT NULL FROM fleet_maintenance WHERE id = $1", item_id
    )


@pytest.mark.parametrize(
    ("by_type", "by", "message"),
    [
        ("USER", "someone", "no such user"),
        ("USER", str(uuid.uuid4()), "no such user"),
        (None, None, "the only change is marking it done"),
        ("USER", None, "the only change is marking it done"),
    ],
)
async def test_an_item_is_done_by_someone_real(
    api_tenant: asyncpg.Connection, by_type: str | None, by: str | None, message: str
) -> None:
    conn = api_tenant
    item_id = await item(conn, await asset(conn, await mission(conn)))
    with pytest.raises(REFUSED, match=message):
        await conn.execute(
            "UPDATE fleet_maintenance SET done_by_type = $2, done_by = $3 WHERE id = $1",
            item_id,
            by_type,
            by,
        )


async def test_an_item_done_by_another_tenants_user_is_refused(
    db: DbUrls, api_tenant: asyncpg.Connection
) -> None:
    conn = api_tenant
    item_id = await item(conn, await asset(conn, await mission(conn)))
    mine = await conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(conn, await create_tenant(db, "Other"))
    theirs = await user(conn)
    await set_tenant(conn, mine)
    with pytest.raises(REFUSED, match="no such user"):
        await conn.execute(
            "UPDATE fleet_maintenance SET done_by_type = 'USER', done_by = $2 WHERE id = $1",
            item_id,
            str(theirs),
        )


async def test_an_items_task_stays_fixed_and_items_are_kept(
    api_tenant: asyncpg.Connection, owner: asyncpg.Connection
) -> None:
    conn = api_tenant
    await item(conn, await asset(conn, await mission(conn)))
    for stmt in (
        "UPDATE fleet_maintenance SET task = 'x'",
        "UPDATE fleet_maintenance SET due_on = current_date + 30",
        "DELETE FROM fleet_maintenance",
    ):
        with pytest.raises(DENIED):
            await conn.execute(stmt)
    for stmt in (
        "UPDATE fleet_maintenance SET task = 'x'",
        "UPDATE fleet_maintenance SET due_on = current_date + 30",
    ):
        with pytest.raises(REFUSED, match="are fixed"):
            await owner.execute(stmt)
    with pytest.raises(REFUSED, match="maintenance items are kept"):
        await owner.execute("DELETE FROM fleet_maintenance")


async def test_the_backup_role_reads_the_fleet_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w "
            "FROM unnest(ARRAY['fleet_asset', 'fleet_maintenance']) t ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("fleet_asset", True, False),
        ("fleet_maintenance", True, False),
    ]
