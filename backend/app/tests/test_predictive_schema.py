"""Migration 0015 (PC-46, PC-47; D-46), checked as nexira_api: a computed index row is for
today and only today's computed row changes, and only its value and components; illustrative
history lies before today; calendar entries are fixed once added; the database writes the times;
every reference is to the same tenant, even for a role that bypasses RLS; nothing is deleted
(docs/plan-pilot-prd.md §13)."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
PT = "'SRID=4326;POINT(38.74 9.03)'"
FORGED = datetime(2000, 1, 1, tzinfo=UTC)


def today() -> date:
    return datetime.now(UTC).date()


async def db_today(conn: asyncpg.Connection) -> date:
    """The guard's own "today" (review of Prompt 100, L4)."""
    found: date = await conn.fetchval("SELECT (now() AT TIME ZONE 'UTC')::date")
    return found


async def mission(conn: asyncpg.Connection, code: str = "ADD") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Addis Ababa', 'ET', {PT})",
        mission_id,
        code,
    )
    return mission_id


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.mission = await mission(self.conn)
        self.today = await self.index(today(), "COMPUTED")
        self.history = await self.index(today() - timedelta(days=1), "ILLUSTRATIVE")
        self.event = await self.calendar()
        return self

    async def index(self, day: date, source: str, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "mission_id": self.mission,
            "day": day,
            "value": 35,
            "components": json.dumps({"baseline": 35}),
            "source": source,
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(
            [
                "current_tenant_id()",
                *(
                    f"${n}::jsonb" if name == "components" else f"${n}"
                    for n, name in enumerate(columns, start=1)
                ),
            ]
        )
        row_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO risk_index ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )
        return row_id

    async def calendar(self, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "mission_id": self.mission,
            "kind": "RALLY",
            "title": "Rally near the industrial park",
            "starts_on": today() + timedelta(days=5),
            "ends_on": today() + timedelta(days=5),
            "attendance": 5000,
            "weight": 30,
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
        row_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO mission_event ({names}) VALUES ({values}) RETURNING id",
            *columns.values(),
        )
        return row_id


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Predictive"))
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


# --- PC-46 · risk_index --------------------------------------------------------------------------


async def test_only_todays_computed_row_changes(world: World, owner: asyncpg.Connection) -> None:
    update = "UPDATE risk_index SET value = 80, components = '{\"incidents\": 45}' WHERE id = $1"
    async with world.conn.transaction():
        await world.conn.execute(update, world.today)
        row = await world.conn.fetchrow(
            "SELECT value, computed_at = now() AS fresh FROM risk_index WHERE id = $1", world.today
        )
    assert row is not None
    assert tuple(row) == (80, True)
    with pytest.raises(REFUSED, match="only today's computed row changes"):
        await world.conn.execute(update, world.history)
    # The owner too, on an illustrative row (a past computed row: L1, below).
    with pytest.raises(REFUSED, match="only today's computed row changes"):
        await owner.execute(update, world.history)
    with pytest.raises(UNIQUE):
        await world.index(today(), "COMPUTED")


async def test_computed_is_today_and_history_is_before_it(world: World) -> None:
    with pytest.raises(REFUSED, match="a computed row is for today"):
        await world.index(today() - timedelta(days=2), "COMPUTED")
    with pytest.raises(REFUSED, match="a computed row is for today"):
        await world.index(today() + timedelta(days=1), "COMPUTED")
    with pytest.raises(REFUSED, match="illustrative history lies before today"):
        await world.index(today() + timedelta(days=3), "ILLUSTRATIVE")
    other = await mission(world.conn, "NBO")
    with pytest.raises(REFUSED, match="illustrative history lies before today"):
        await world.index(today(), "ILLUSTRATIVE", mission_id=other)


@pytest.mark.parametrize(
    "change",
    [
        {"value": 101},
        {"value": -1},
        {"source": "FORECAST"},
        {"components": json.dumps([1, 2])},  # an object, not a list
    ],
)
async def test_an_index_row_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    other = await mission(world.conn, "BGW")
    change = dict(change)  # parametrize shares the dict (review of Prompt 100, L3)
    source = change.pop("source", "ILLUSTRATIVE")
    with pytest.raises(CHECK):
        await world.index(today() - timedelta(days=4), source, mission_id=other, **change)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("tenant_id", "gen_random_uuid()"),
        ("mission_id", "gen_random_uuid()"),
        ("day", "day - 1"),
        ("source", "'ILLUSTRATIVE'"),
    ],
)
async def test_every_frozen_index_column(
    world: World, owner: asyncpg.Connection, column: str, value: str
) -> None:
    with pytest.raises(DENIED):
        await world.conn.execute(
            f"UPDATE risk_index SET {column} = {value} WHERE id = $1", world.today
        )
    with pytest.raises(REFUSED, match="only the value and components change"):
        await owner.execute(f"UPDATE risk_index SET {column} = {value} WHERE id = $1", world.today)


async def test_the_database_writes_computed_at(world: World, owner: asyncpg.Connection) -> None:
    other = await mission(world.conn, "ISB")
    async with world.conn.transaction():
        row_id = await world.index(today(), "COMPUTED", mission_id=other, computed_at=FORGED)
        assert await world.conn.fetchval(
            "SELECT computed_at = now() FROM risk_index WHERE id = $1", row_id
        )
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE risk_index SET computed_at = now() WHERE id = $1", row_id)
    async with owner.transaction():
        await owner.execute(
            "UPDATE risk_index SET value = 40, computed_at = $2 WHERE id = $1", row_id, FORGED
        )
        assert await owner.fetchval(
            "SELECT computed_at = now() FROM risk_index WHERE id = $1", row_id
        )


# --- PC-47 · mission_event ------------------------------------------------------------------------


async def test_a_calendar_entry_is_fixed(world: World, owner: asyncpg.Connection) -> None:
    for column, value in (("title", "'x'"), ("weight", "1"), ("starts_on", "starts_on + 1")):
        with pytest.raises(DENIED):
            await world.conn.execute(f"UPDATE mission_event SET {column} = {value}")
        with pytest.raises(REFUSED, match="the calendar entry is fixed"):
            await owner.execute(f"UPDATE mission_event SET {column} = {value}")
    async with world.conn.transaction():
        row_id = await world.calendar(created_at=FORGED, title="Counter-demonstration", weight=10)
        assert await world.conn.fetchval(
            "SELECT created_at = now() AND source = 'Illustrative events calendar (simulated)' "
            "FROM mission_event WHERE id = $1",
            row_id,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "PARADE"},
        {"weight": 0},
        {"weight": 31},
        {"attendance": -1},
        {"title": ""},
        {"starts_on": date(2026, 11, 10), "ends_on": date(2026, 11, 9)},
    ],
)
async def test_a_calendar_entry_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    with pytest.raises(CHECK):
        await world.calendar(**change)


async def test_a_calendar_entry_may_have_a_place(world: World) -> None:
    row_id = await world.conn.fetchval(
        "INSERT INTO mission_event (tenant_id, mission_id, kind, title, place_label, location, "
        f"starts_on, ends_on, weight) VALUES (current_tenant_id(), $1, 'HOLIDAY', 'Holiday', "
        f"'Addis Ababa', {PT}, current_date, current_date, 8) RETURNING id",
        world.mission,
    )
    assert row_id


# --- every table ------------------------------------------------------------------------------


async def test_nothing_is_deleted(world: World, owner: asyncpg.Connection) -> None:
    for table, kept in (
        ("risk_index", "the history is kept"),
        ("mission_event", "the calendar entry is fixed"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"DELETE FROM {table}")
        with pytest.raises(REFUSED, match=kept):
            await owner.execute(f"DELETE FROM {table}")


async def test_the_guards_compare_tenants_even_without_rls(db: DbUrls, world: World) -> None:
    """A superuser bypasses RLS, so only the guards' own tenant checks stop a row of this tenant
    from pointing at another tenant's mission (the lesson of the Prompt 90 review, L1)."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs = await mission(world.conn, "CAI")
    await set_tenant(world.conn, mine)
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        assert await conn.fetchval(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        with pytest.raises(REFUSED, match="risk index: no such mission"):
            await conn.execute(
                "INSERT INTO risk_index (tenant_id, mission_id, day, value, components, source) "
                "VALUES ($1, $2, $3, 35, '{}', 'COMPUTED')",
                mine,
                theirs,
                today(),
            )
        with pytest.raises(REFUSED, match="mission event: no such mission"):
            await conn.execute(
                "INSERT INTO mission_event (tenant_id, mission_id, kind, title, starts_on, "
                "ends_on, weight) VALUES ($1, $2, 'RALLY', 'x', current_date, current_date, 5)",
                mine,
                theirs,
            )
    finally:
        await conn.close()


async def test_each_tenant_sees_only_its_own(db: DbUrls, world: World) -> None:
    other = await create_tenant(db, "Third")
    await set_tenant(world.conn, other)
    assert await world.conn.fetchval("SELECT count(*) FROM risk_index") == 0
    assert await world.conn.fetchval("SELECT count(*) FROM mission_event") == 0


async def test_the_backup_role_reads_the_predictive_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w FROM unnest(ARRAY["
            "'mission_event', 'risk_index']) t ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [("mission_event", True, False), ("risk_index", True, False)]


# --- review of Prompt 100 ----------------------------------------------------------------------


async def test_a_past_computed_row_is_refused(world: World, owner: asyncpg.Connection) -> None:
    """L1: yesterday's snapshot stays as it was. The row is made with the guard off, as the
    owner, in one transaction; then the guard refuses the update for both roles."""
    yesterday = await db_today(world.conn) - timedelta(days=1)
    other = await mission(world.conn, "JKT")
    async with owner.transaction():
        await owner.execute("ALTER TABLE risk_index DISABLE TRIGGER predictive_risk_index_guard")
        past = await owner.fetchval(
            "INSERT INTO risk_index (tenant_id, mission_id, day, value, components, source) "
            "VALUES (current_tenant_id(), $1, $2, 40, '{}', 'COMPUTED') RETURNING id",
            other,
            yesterday,
        )
        await owner.execute("ALTER TABLE risk_index ENABLE TRIGGER predictive_risk_index_guard")
    with pytest.raises(REFUSED, match="only today's computed row changes"):
        await world.conn.execute("UPDATE risk_index SET value = 90 WHERE id = $1", past)
    with pytest.raises(REFUSED, match="only today's computed row changes"):
        await owner.execute("UPDATE risk_index SET value = 90 WHERE id = $1", past)


UPSERT = (
    "INSERT INTO risk_index (tenant_id, mission_id, day, value, components, source) "
    "VALUES (current_tenant_id(), $1, $2, $3, $4::jsonb, $5) "
    "ON CONFLICT (mission_id, day) DO UPDATE SET value = EXCLUDED.value, "
    "components = EXCLUDED.components RETURNING value"
)


async def test_the_snapshot_upserts_todays_row(world: World) -> None:
    """L2: the snapshot's path as nexira_api: insert, then update the same day's row."""
    other = await mission(world.conn, "ABV")
    day = await db_today(world.conn)
    assert await world.conn.fetchval(UPSERT, other, day, 50, '{"baseline": 50}', "COMPUTED") == 50
    assert await world.conn.fetchval(UPSERT, other, day, 62, '{"events": 12}', "COMPUTED") == 62
    rows = await world.conn.fetchval("SELECT count(*) FROM risk_index WHERE mission_id = $1", other)
    assert rows == 1
    # A history day is never a computed row.
    history = day - timedelta(days=1)
    with pytest.raises(REFUSED, match="a computed row is for today"):
        await world.conn.fetchval(UPSERT, other, history, 70, "{}", "COMPUTED")
