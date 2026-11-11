"""Migration 0020 (PC-54; D-52), checked as nexira_api: a map annotation is added ACTIVE by a
user of the tenant, as a point, a line or a polygon matching its kind; a linked incident's
mission is its own (plan-pilot-map G-2); the label, note, shape and end time change through the
column grants, with the editor named; it is withdrawn once, with a reason, and then kept as it
is; the database writes the times; every reference is to the same tenant, even for a role that
bypasses RLS; nothing is deleted (docs/plan-pilot-map.md §2)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
PT = "'SRID=4326;POINT(36.82 -1.28)'"
FORGED = datetime(2000, 1, 1, tzinfo=UTC)
SHAPES = {
    "MARK": "SRID=4326;POINT(36.817 -1.283)",
    "LINE": "SRID=4326;LINESTRING(36.81 -1.28, 36.82 -1.29, 36.83 -1.29)",
    "AREA": "SRID=4326;POLYGON((36.81 -1.28, 36.83 -1.28, 36.83 -1.30, 36.81 -1.28))",
}


async def user(conn: asyncpg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, 'operator')",
        user_id,
        f"sub-{user_id}",
        f"{user_id}@x",
    )
    return user_id


async def mission(conn: asyncpg.Connection) -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Nairobi', 'KE', {PT})",
        mission_id,
        f"M{mission_id.hex[:6]}",
    )
    return mission_id


async def incident(conn: asyncpg.Connection, mission_id: uuid.UUID | None) -> uuid.UUID:
    incident_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
        "signal_severity, status, location, mission_id) VALUES ($1, current_tenant_id(), $2, "
        f"'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', 'ACTIVE', {PT}, $3)",
        incident_id,
        f"INC-2026-{incident_id.int % 9000 + 1000}",
        mission_id,
    )
    return incident_id


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.user = await user(self.conn)
        self.mission = await mission(self.conn)
        self.incident = await incident(self.conn, self.mission)
        return self

    async def add(self, kind: str = "MARK", **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "kind": kind,
            "symbol": "CHECKPOINT" if kind == "MARK" else None,
            "shape": SHAPES[kind],
            "label": "Checkpoint · Uhuru Highway",
            "created_by": self.user,
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(
            [
                "current_tenant_id()",
                *(
                    f"ST_GeogFromText(${n})" if name == "shape" else f"${n}"
                    for n, name in enumerate(columns, start=1)
                ),
            ]
        )
        annotation: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO map_annotation ({names}) VALUES ({values}) RETURNING id",
            *columns.values(),
        )
        return annotation

    async def row(self, annotation: uuid.UUID) -> Any:
        return await self.conn.fetchrow(
            "SELECT *, ST_AsText(shape) AS wkt FROM map_annotation WHERE id = $1", annotation
        )


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "ANN"))
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


async def test_each_kind_is_added_active_with_the_database_s_times(world: World) -> None:
    for kind in ("MARK", "LINE", "AREA"):
        added = await world.row(
            await world.add(kind, incident_id=world.incident, mission_id=world.mission)
        )
        assert added["status"] == "ACTIVE"
        assert added["wkt"].startswith(
            {"MARK": "POINT", "LINE": "LINESTRING", "AREA": "POLYGON"}[kind]
        )
        assert added["created_at"] > datetime.now(UTC) - timedelta(minutes=1)
        assert (added["updated_at"], added["withdrawn_at"]) == (None, None)
    forged = await world.row(
        await world.add(created_at=FORGED, updated_at=FORGED, withdrawn_at=FORGED)
    )
    assert forged["created_at"] > FORGED
    assert (forged["updated_at"], forged["withdrawn_at"]) == (None, None)


async def test_the_shape_is_the_kind_s(world: World) -> None:
    with pytest.raises(CHECK):
        await world.add("MARK", shape=SHAPES["LINE"])
    with pytest.raises(CHECK):
        await world.add("AREA", shape=SHAPES["MARK"])
    with pytest.raises(CHECK):
        await world.add("LINE", shape=SHAPES["AREA"])
    with pytest.raises(CHECK):  # a mark has a symbol, a line or an area none
        await world.add("MARK", symbol=None)
    with pytest.raises(CHECK):
        await world.add("LINE", symbol="CHECKPOINT")
    with pytest.raises(CHECK):
        await world.add("MARK", symbol="TANK")
    points = ", ".join(f"36.{n:03d} -1.28" for n in range(501))
    with pytest.raises(CHECK):  # not a huge one
        await world.add("LINE", shape=f"SRID=4326;LINESTRING({points})")
    for label in ("", "x" * 81):
        with pytest.raises(CHECK):
            await world.add(label=label)
    with pytest.raises(CHECK):
        await world.add(note="x" * 281)


async def test_it_is_added_active_and_ends_after_it_was_added(world: World) -> None:
    with pytest.raises(REFUSED, match="an annotation is added active"):
        await world.add(status="WITHDRAWN")
    with pytest.raises(REFUSED, match="an annotation is added active"):
        await world.add(status="WITHDRAWN", reason="r", withdrawn_by=world.user)
    with pytest.raises(REFUSED, match="an annotation is added active"):
        await world.add(updated_by=world.user)
    with pytest.raises(REFUSED, match="it ends after it was added"):
        await world.add(ends_at=datetime.now(UTC) - timedelta(minutes=1))
    later = datetime.now(UTC) + timedelta(hours=6)
    assert (await world.row(await world.add(ends_at=later)))["ends_at"] == later


async def test_an_incident_s_annotation_is_its_mission_s(world: World) -> None:
    with pytest.raises(REFUSED, match="its mission's"):
        await world.add(incident_id=world.incident)  # no mission
    with pytest.raises(REFUSED, match="its mission's"):
        await world.add(incident_id=world.incident, mission_id=await mission(world.conn))
    tenant_wide = await incident(world.conn, None)
    assert await world.add(incident_id=tenant_wide)  # an incident with no mission: any or none
    assert await world.add(mission_id=world.mission)  # no incident: the nearest mission's


async def test_an_edit_names_its_user_and_the_database_times_it(world: World) -> None:
    annotation = await world.add("AREA")
    with pytest.raises(REFUSED, match="an edit names its user"):
        await world.conn.execute(
            "UPDATE map_annotation SET label = 'Avoid' WHERE id = $1", annotation
        )
    editor = await user(world.conn)
    await world.conn.execute(
        "UPDATE map_annotation SET label = 'Avoid: crowd', note = 'Moving north', "
        "shape = ST_GeogFromText($2), "
        "updated_by = $3 WHERE id = $1",
        annotation,
        "SRID=4326;POLYGON((36.80 -1.28, 36.84 -1.28, 36.84 -1.31, 36.80 -1.28))",
        editor,
    )
    edited = await world.row(annotation)
    assert (edited["label"], edited["note"], edited["updated_by"]) == (
        "Avoid: crowd",
        "Moving north",
        editor,
    )
    assert edited["wkt"].startswith("POLYGON((36.8 -1.28")
    assert edited["updated_at"] is not None
    assert edited["withdrawn_at"] is None
    with pytest.raises(REFUSED, match="it ends after it was added"):
        await world.conn.execute(
            "UPDATE map_annotation SET ends_at = $2, updated_by = $3 WHERE id = $1",
            annotation,
            FORGED,
            editor,
        )
    with pytest.raises(CHECK):  # still the kind's shape
        await world.conn.execute(
            "UPDATE map_annotation SET shape = ST_GeogFromText($2), updated_by = $3 WHERE id = $1",
            annotation,
            SHAPES["MARK"],
            editor,
        )


async def test_only_the_granted_columns_change(world: World, owner: asyncpg.Connection) -> None:
    annotation = await world.add(incident_id=world.incident, mission_id=world.mission)
    for column, value in (
        ("kind", "'LINE'"),
        ("symbol", "'NOTE'"),
        ("mission_id", "NULL"),
        ("incident_id", "NULL"),
        ("created_by", "NULL"),
        ("created_at", "now()"),
        ("updated_at", "now()"),
        ("withdrawn_at", "now()"),
        ("tenant_id", "NULL"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(
                f"UPDATE map_annotation SET {column} = {value} WHERE id = $1", annotation
            )
    # The owner holds every column; the guard still keeps them fixed.
    with pytest.raises(REFUSED, match="its kind, author, incident and mission are fixed"):
        await owner.execute(
            "UPDATE map_annotation SET symbol = 'NOTE', updated_by = $2 WHERE id = $1",
            annotation,
            world.user,
        )


async def test_it_is_withdrawn_once_with_a_reason_and_kept_as_it_is(world: World) -> None:
    annotation = await world.add()
    withdraw = (
        "UPDATE map_annotation SET status = 'WITHDRAWN', reason = $2, withdrawn_by = $3 "
        "WHERE id = $1"
    )
    with pytest.raises(CHECK):
        await world.conn.execute(withdraw, annotation, None, world.user)
    with pytest.raises(REFUSED, match="withdrawing changes nothing else"):
        await world.conn.execute(
            "UPDATE map_annotation SET status = 'WITHDRAWN', reason = 'Cleared', "
            "withdrawn_by = $2, label = 'Gone' WHERE id = $1",
            annotation,
            world.user,
        )
    await world.conn.execute(withdraw, annotation, "Cleared by police", world.user)
    withdrawn = await world.row(annotation)
    assert (withdrawn["status"], withdrawn["reason"]) == ("WITHDRAWN", "Cleared by police")
    assert withdrawn["withdrawn_at"] is not None
    assert withdrawn["updated_at"] is None
    with pytest.raises(REFUSED, match="kept as it is"):
        await world.conn.execute(withdraw, annotation, "Again", world.user)
    with pytest.raises(REFUSED, match="kept as it is"):
        await world.conn.execute(
            "UPDATE map_annotation SET label = 'Back', updated_by = $2 WHERE id = $1",
            annotation,
            world.user,
        )
    with pytest.raises(REFUSED, match="kept as it is"):  # no way back to ACTIVE
        await world.conn.execute(
            "UPDATE map_annotation SET status = 'ACTIVE', reason = NULL, withdrawn_by = NULL "
            "WHERE id = $1",
            annotation,
        )


async def test_nothing_is_deleted(world: World, owner: asyncpg.Connection) -> None:
    annotation = await world.add()
    with pytest.raises(DENIED):
        await world.conn.execute("DELETE FROM map_annotation WHERE id = $1", annotation)
    with pytest.raises(REFUSED, match="annotations are kept"):
        await owner.execute("DELETE FROM map_annotation WHERE id = $1", annotation)
    with pytest.raises(DENIED):
        await world.conn.execute("TRUNCATE map_annotation")
    with pytest.raises(REFUSED, match="annotations are kept"):
        await owner.execute("TRUNCATE map_annotation")


async def test_the_guard_compares_tenants_even_without_rls(db: DbUrls, world: World) -> None:
    """A superuser bypasses RLS, so only the guard's own tenant checks stop an annotation of
    this tenant from pointing at another tenant's user, mission or incident."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Theirs"))
    theirs = await World(world.conn).build()
    await set_tenant(world.conn, mine)
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        assert await conn.fetchval(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        add = (
            "INSERT INTO map_annotation (tenant_id, kind, symbol, shape, label, created_by, "
            "mission_id, incident_id) "
            "VALUES ($1, 'MARK', 'NOTE', ST_GeogFromText($2), 'Note', $3, $4, $5)"
        )
        with pytest.raises(REFUSED, match="no such user"):
            await conn.execute(add, mine, SHAPES["MARK"], theirs.user, None, None)
        with pytest.raises(REFUSED, match="no such mission"):
            await conn.execute(add, mine, SHAPES["MARK"], world.user, theirs.mission, None)
        with pytest.raises(REFUSED, match="no such incident"):
            await conn.execute(add, mine, SHAPES["MARK"], world.user, None, theirs.incident)
        annotation = await world.add()
        with pytest.raises(REFUSED, match="an edit names its user"):
            await conn.execute(
                "UPDATE map_annotation SET label = 'L', updated_by = $2 WHERE id = $1",
                annotation,
                theirs.user,
            )
        with pytest.raises(REFUSED, match="no such user"):
            await conn.execute(
                "UPDATE map_annotation SET status = 'WITHDRAWN', reason = 'r', withdrawn_by = $2 "
                "WHERE id = $1",
                annotation,
                theirs.user,
            )
    finally:
        await conn.close()


async def test_each_tenant_sees_only_its_own(db: DbUrls, world: World) -> None:
    annotation = await world.add()
    await set_tenant(world.conn, await create_tenant(db, "Third"))
    assert await world.conn.fetchval("SELECT count(*) FROM map_annotation") == 0
    assert (
        await world.conn.execute(
            "UPDATE map_annotation SET label = 'x', updated_by = updated_by WHERE id = $1",
            annotation,
        )
        == "UPDATE 0"
    )
