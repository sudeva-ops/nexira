"""Migration 0008 (PC-24, PC-25; D-38), checked as nexira_api: armed playbook runs wait
SCHEDULED for a future time that never moves, then start or are disarmed, and count as
live (G-8); the database writes an armed run's start (G-2). Climate scores per mission,
in range, in the mission's own tenant, never changed or deleted
(docs/plan-pilot-hz.md §4, §11)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
PT = "'SRID=4326;POINT(90.41 23.81)'"
LATER = timedelta(hours=24)


async def mission(conn: asyncpg.Connection, code: str = "DAC") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Dhaka', 'BD', {PT})",
        mission_id,
        code,
    )
    return mission_id


async def incident(conn: asyncpg.Connection) -> uuid.UUID:
    incident_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        f"location) VALUES (current_tenant_id(), $1, 'Tropical cyclone · Dhaka', "
        f"'TROPICAL_CYCLONE', 'HIGH', 'HIGH', {PT}) RETURNING id",
        f"INC-T-{uuid.uuid4().hex[:8]}",
    )
    return incident_id


async def playbook(conn: asyncpg.Connection, code: str = "PB-06") -> uuid.UUID:
    playbook_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO playbook (tenant_id, code, name, category) "
        "VALUES (current_tenant_id(), $1, 'Severe weather', 'WEATHER') RETURNING id",
        code,
    )
    return playbook_id


async def run(
    conn: asyncpg.Connection,
    playbook_id: uuid.UUID,
    incident_id: uuid.UUID,
    status: str = "SCHEDULED",
    scheduled_for: datetime | None = None,
    **extra: Any,
) -> uuid.UUID:
    if status == "SCHEDULED" and scheduled_for is None:
        scheduled_for = datetime.now(UTC) + LATER
    columns: dict[str, Any] = {
        "playbook_id": playbook_id,
        "incident_id": incident_id,
        "status": status,
        "scheduled_for": scheduled_for,
        **extra,
    }
    names = ", ".join(["tenant_id", *columns])
    values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
    run_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO playbook_run ({names}) VALUES ({values}) RETURNING id", *columns.values()
    )
    return run_id


async def set_status(conn: asyncpg.Connection, run_id: uuid.UUID, status: str) -> None:
    await conn.execute("UPDATE playbook_run SET status = $2 WHERE id = $1", run_id, status)


async def row(conn: asyncpg.Connection, run_id: uuid.UUID) -> asyncpg.Record:
    record = await conn.fetchrow("SELECT * FROM playbook_run WHERE id = $1", run_id)
    assert record is not None
    return record


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> tuple[asyncpg.Connection, uuid.UUID]:
    """The API connection in a new tenant, with an incident and PB-06."""
    await set_tenant(api, await create_tenant(db, "Hazards"))
    return api, await incident(api)


@pytest.fixture
async def owner(db: DbUrls, tenant: tuple[asyncpg.Connection, uuid.UUID]) -> Any:
    """The table owner in the same tenant: the guard holds for it too (defence in depth)."""
    conn = await asyncpg.connect(db.owner_plain)
    await set_tenant(conn, await tenant[0].fetchval("SELECT current_tenant_id()"))
    try:
        yield conn
    finally:
        await conn.close()


# --- PC-24 · armed runs -----------------------------------------------------------------------


async def test_an_armed_run_starts_and_the_database_writes_when(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc)
    armed = await row(conn, run_id)
    assert armed["status"] == "SCHEDULED"
    await set_status(conn, run_id, "RUNNING")
    started = await row(conn, run_id)
    assert started["status"] == "RUNNING"
    assert started["scheduled_for"] == armed["scheduled_for"]
    assert started["started_at"] > armed["started_at"]  # G-2: when it started, not when armed
    await set_status(conn, run_id, "AWAITING_APPROVAL")
    await set_status(conn, run_id, "RUNNING")
    await set_status(conn, run_id, "COMPLETED")


async def test_an_armed_run_started_late_records_its_real_start(
    tenant: tuple[asyncpg.Connection, uuid.UUID], owner: asyncpg.Connection
) -> None:
    """Even a forged started_at in the same UPDATE is replaced by the database (G-2)."""
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc)
    await owner.execute(
        "UPDATE playbook_run SET status = 'RUNNING', started_at = '2000-01-01' WHERE id = $1",
        run_id,
    )
    assert (await row(conn, run_id))["started_at"].year > 2000


async def test_an_armed_run_can_be_disarmed_and_that_is_final(
    tenant: tuple[asyncpg.Connection, uuid.UUID], owner: asyncpg.Connection
) -> None:
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc)
    await set_status(conn, run_id, "DISARMED")
    for status in ("SCHEDULED", "RUNNING", "CANCELLED", "COMPLETED"):
        with pytest.raises(REFUSED, match="disarmed run is final"):
            await set_status(owner, run_id, status)
    # Nothing else about it changes either (review of Prompt 54, L3).
    for change in ("completed_at = now()", "started_by_type = 'AGENT'", "started_at = now()"):
        with pytest.raises(REFUSED, match="disarmed run is final"):
            await owner.execute(f"UPDATE playbook_run SET {change} WHERE id = $1", run_id)


@pytest.mark.parametrize("disarm", [False, True])
async def test_armed_and_disarmed_runs_are_never_deleted(
    tenant: tuple[asyncpg.Connection, uuid.UUID], owner: asyncpg.Connection, disarm: bool
) -> None:
    """The record of arming and disarming is kept, even for the owner (review L3); other
    runs keep the Phase 1 grants."""
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc)
    if disarm:
        await set_status(conn, run_id, "DISARMED")
    for who in (conn, owner):
        with pytest.raises(REFUSED, match="armed or disarmed run is kept"):
            await who.execute("DELETE FROM playbook_run WHERE id = $1", run_id)
    assert (await row(conn, run_id))["status"] == ("DISARMED" if disarm else "SCHEDULED")


@pytest.mark.parametrize("status", ["AWAITING_APPROVAL", "COMPLETED", "CANCELLED", "FAILED"])
async def test_an_armed_run_only_starts_or_is_disarmed(
    tenant: tuple[asyncpg.Connection, uuid.UUID], owner: asyncpg.Connection, status: str
) -> None:
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc)
    with pytest.raises(REFUSED, match="can only start or be disarmed"):
        await set_status(owner, run_id, status)


@pytest.mark.parametrize(
    "before", ["RUNNING", "AWAITING_APPROVAL", "COMPLETED", "CANCELLED", "FAILED"]
)
@pytest.mark.parametrize("after", ["SCHEDULED", "DISARMED"])
async def test_a_run_that_was_not_armed_never_becomes_armed_or_disarmed(
    tenant: tuple[asyncpg.Connection, uuid.UUID], owner: asyncpg.Connection, before: str, after: str
) -> None:
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc, status=before)
    with pytest.raises(REFUSED, match="cannot become"):
        await set_status(owner, run_id, after)


@pytest.mark.parametrize("when", [None, timedelta(0), timedelta(minutes=-5)])
async def test_an_armed_run_needs_a_time_in_the_future(
    tenant: tuple[asyncpg.Connection, uuid.UUID], when: timedelta | None
) -> None:
    """Against the database's clock, which the host's may not match exactly."""
    conn, inc = tenant
    pb = await playbook(conn)
    with pytest.raises(REFUSED, match="time in the future"):
        await conn.execute(
            "INSERT INTO playbook_run (tenant_id, playbook_id, incident_id, status, scheduled_for) "
            "VALUES (current_tenant_id(), $1, $2, 'SCHEDULED', now() + $3::interval)",
            pb,
            inc,
            when,
        )


@pytest.mark.parametrize(
    "status", ["RUNNING", "AWAITING_APPROVAL", "COMPLETED", "CANCELLED", "FAILED"]
)
async def test_only_an_armed_run_has_a_start_time(
    tenant: tuple[asyncpg.Connection, uuid.UUID], status: str
) -> None:
    conn, inc = tenant
    with pytest.raises(REFUSED, match="only an armed run has a start time"):
        await run(conn, await playbook(conn), inc, status, datetime.now(UTC) + LATER)


async def test_a_run_is_never_created_disarmed(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    conn, inc = tenant
    with pytest.raises(REFUSED, match="only an armed run can be disarmed"):
        await run(conn, await playbook(conn), inc, "DISARMED")


@pytest.mark.parametrize("value", [None, "shift"])
async def test_the_start_time_is_fixed_once_armed(
    tenant: tuple[asyncpg.Connection, uuid.UUID], owner: asyncpg.Connection, value: str | None
) -> None:
    conn, inc = tenant
    run_id = await run(conn, await playbook(conn), inc)
    if value is None:
        update = "UPDATE playbook_run SET scheduled_for = NULL WHERE id = $1"
    else:
        update = "UPDATE playbook_run SET scheduled_for = scheduled_for + interval '1 hour' "
        update += "WHERE id = $1"
    with pytest.raises(REFUSED, match="fixed once armed"):
        await owner.execute(update, run_id)
    # Nor can a running run be given one afterwards.
    other = await run(conn, await playbook(conn, "PB-07"), inc, "RUNNING")
    with pytest.raises(REFUSED, match="fixed once armed"):
        await owner.execute(
            "UPDATE playbook_run SET scheduled_for = now() + interval '1 day' WHERE id = $1", other
        )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("SCHEDULED", "SCHEDULED"),
        ("SCHEDULED", "RUNNING"),
        ("RUNNING", "SCHEDULED"),
        ("AWAITING_APPROVAL", "SCHEDULED"),
    ],
)
async def test_an_armed_run_is_live_so_there_is_only_one(
    tenant: tuple[asyncpg.Connection, uuid.UUID], first: str, second: str
) -> None:
    """G-8: a playbook is armed or running at most once per incident."""
    conn, inc = tenant
    pb = await playbook(conn)
    await run(conn, pb, inc, first)
    with pytest.raises(asyncpg.UniqueViolationError):
        await run(conn, pb, inc, second)


@pytest.mark.parametrize("ended", ["DISARMED", "RUNNING"])
async def test_after_disarming_or_starting_it_may_be_armed_again(
    tenant: tuple[asyncpg.Connection, uuid.UUID], ended: str
) -> None:
    """A disarmed run no longer counts; a started one does until it finishes."""
    conn, inc = tenant
    pb = await playbook(conn)
    run_id = await run(conn, pb, inc)
    await set_status(conn, run_id, ended)
    if ended == "RUNNING":
        with pytest.raises(asyncpg.UniqueViolationError):
            await run(conn, pb, inc)
        await set_status(conn, run_id, "COMPLETED")
    await run(conn, pb, inc)


async def test_existing_runs_behave_as_before(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    """Phase 1 runs: inserted RUNNING with no start time, every old transition allowed."""
    conn, inc = tenant
    pb = await playbook(conn)
    run_id = await run(conn, pb, inc, "RUNNING")
    started = (await row(conn, run_id))["started_at"]
    for status in ("AWAITING_APPROVAL", "RUNNING", "FAILED"):
        await set_status(conn, run_id, status)
    assert (await row(conn, run_id))["started_at"] == started
    await set_status(conn, await run(conn, pb, inc, "RUNNING"), "CANCELLED")
    await conn.execute("DELETE FROM playbook_run WHERE id = $1", run_id)  # grants unchanged


async def test_armed_runs_of_other_tenants_are_invisible(
    db: DbUrls, tenant: tuple[asyncpg.Connection, uuid.UUID]
) -> None:
    conn, inc = tenant
    await run(conn, await playbook(conn), inc)
    await set_tenant(conn, await create_tenant(db, "Elsewhere"))
    assert await conn.fetchval("SELECT count(*) FROM playbook_run") == 0


# --- PC-25 · climate risk ---------------------------------------------------------------------

CLIMATE = (
    "INSERT INTO mission_climate_risk (tenant_id, mission_id, hazards, score_today, score_2050, "
    "scenario) VALUES (current_tenant_id(), $1, $2, $3, $4, $5)"
)


async def test_one_climate_row_per_mission_labelled_simulated(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    conn, _ = tenant
    dhaka = await mission(conn)
    await conn.execute(CLIMATE, dhaka, ["FLOOD", "TROPICAL_CYCLONE"], 71, 86, "Illustrative 2050")
    r = await conn.fetchrow("SELECT * FROM mission_climate_risk WHERE mission_id = $1", dhaka)
    assert r is not None
    assert r["source"] == "Illustrative climate model (simulated)"
    assert (r["score_today"], r["score_2050"], r["hazards"]) == (
        71,
        86,
        ["FLOOD", "TROPICAL_CYCLONE"],
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(CLIMATE, dhaka, ["FLOOD"], 1, 2, "Illustrative 2050")


async def test_climate_rows_are_never_changed_or_deleted(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    conn, _ = tenant
    await conn.execute(CLIMATE, await mission(conn), ["FLOOD"], 40, 60, "Illustrative 2050")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute("UPDATE mission_climate_risk SET score_2050 = 1")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute("DELETE FROM mission_climate_risk")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute("TRUNCATE mission_climate_risk")


@pytest.mark.parametrize(
    ("hazards", "today", "in_2050", "scenario"),
    [
        ([], 10, 20, "x"),
        (["FLOOD", None], 10, 20, "x"),
        (["FLOOD"] * 11, 10, 20, "x"),
        (["FLOOD"], -1, 20, "x"),
        (["FLOOD"], 10, 101, "x"),
        (["FLOOD"], 10, 20, ""),
        (["FLOOD"], 10, 20, "x" * 101),
        (["FLOOD"], 101, 20, "x"),
        (["FLOOD"], 10, -1, "x"),
        ([""], 10, 20, "x"),
        (["F" * 301], 10, 20, "x"),
    ],
)
async def test_climate_values_are_checked(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
    hazards: list[str | None],
    today: int,
    in_2050: int,
    scenario: str,
) -> None:
    conn, _ = tenant
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(CLIMATE, await mission(conn), hazards, today, in_2050, scenario)


async def test_a_climate_row_needs_a_mission_in_its_own_tenant(
    db: DbUrls, tenant: tuple[asyncpg.Connection, uuid.UUID]
) -> None:
    """Foreign keys ignore RLS: another tenant's mission is refused by the guard."""
    conn, _ = tenant
    dhaka = await mission(conn)
    await set_tenant(conn, await create_tenant(db, "Other"))
    with pytest.raises(REFUSED, match="no such mission"):
        await conn.execute(CLIMATE, dhaka, ["FLOOD"], 10, 20, "x")


async def test_a_temporary_mission_table_does_not_fool_the_climate_guard(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    conn, _ = tenant
    fake = uuid.uuid4()
    await conn.execute("CREATE TEMP TABLE mission (id uuid, tenant_id uuid)")
    await conn.execute("INSERT INTO mission VALUES ($1, current_tenant_id())", fake)
    with pytest.raises(REFUSED, match="no such mission"):
        await conn.execute(CLIMATE, fake, ["FLOOD"], 10, 20, "x")


async def test_climate_created_at_is_the_databases(
    tenant: tuple[asyncpg.Connection, uuid.UUID],
) -> None:
    conn, _ = tenant
    dhaka = await mission(conn)
    await conn.execute(
        "INSERT INTO mission_climate_risk (tenant_id, mission_id, hazards, score_today, "
        "score_2050, scenario, created_at) VALUES (current_tenant_id(), $1, '{FLOOD}', 1, 2, 'x', "
        "'2000-01-01')",
        dhaka,
    )
    created = await conn.fetchval("SELECT created_at FROM mission_climate_risk")
    assert created.year > 2000


async def test_other_tenants_climate_rows_are_invisible(
    db: DbUrls, tenant: tuple[asyncpg.Connection, uuid.UUID]
) -> None:
    conn, _ = tenant
    await conn.execute(CLIMATE, await mission(conn), ["FLOOD"], 10, 20, "x")
    await set_tenant(conn, await create_tenant(db, "Elsewhere"))
    assert await conn.fetchval("SELECT count(*) FROM mission_climate_risk") == 0


async def test_the_backup_role_reads_climate_rows(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        allowed = await conn.fetchrow(
            "SELECT has_table_privilege('nexira_backup', 'mission_climate_risk', 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', 'mission_climate_risk', 'INSERT') AS w"
        )
    finally:
        await conn.close()
    assert allowed is not None
    assert (allowed["r"], allowed["w"]) == (True, False)


@pytest.mark.parametrize("source", ["", "x" * 201])
async def test_the_climate_source_is_checked(
    tenant: tuple[asyncpg.Connection, uuid.UUID], source: str
) -> None:
    conn, _ = tenant
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "INSERT INTO mission_climate_risk (tenant_id, mission_id, hazards, score_today, "
            "score_2050, scenario, source) VALUES (current_tenant_id(), $1, '{FLOOD}', 1, 2, 'x', "
            "$2)",
            await mission(conn),
            source,
        )


async def test_a_role_that_bypasses_rls_still_needs_the_missions_tenant(
    db: DbUrls, tenant: tuple[asyncpg.Connection, uuid.UUID]
) -> None:
    """The guard's tenant_id condition, for a role that bypasses RLS (the superuser)."""
    conn, _ = tenant
    dhaka = await mission(conn)
    other = await create_tenant(db, "Other")
    admin = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        with pytest.raises(REFUSED, match="no such mission"):
            await admin.execute(
                "INSERT INTO mission_climate_risk (tenant_id, mission_id, hazards, score_today, "
                "score_2050, scenario) VALUES ($1, $2, '{FLOOD}', 1, 2, 'x')",
                other,
                dhaka,
            )
    finally:
        await admin.close()
