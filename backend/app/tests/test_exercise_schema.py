"""Migration 0017 (PC-51, PC-52; D-48), checked as nexira_api: an exercise starts RUNNING on a
scenario run in EXERCISE mode of the same scenario, one at a time per mission, by a user of the
tenant; it ends once, COMPLETED with its five scores and their rounded mean, or ABANDONED with a
reason; a seeded ILLUSTRATIVE one is added completed and in the past; the scores are frozen and
written only with the completion; the database writes the times; every reference is to the same
tenant, even for a role that bypasses RLS; nothing is deleted (docs/plan-pilot-exr.md §6, §11)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
PT = "'SRID=4326;POINT(36.82 -1.28)'"
FORGED = datetime(2000, 1, 1, tzinfo=UTC)
DIMENSIONS = ("DETECTION", "ACCOUNTABILITY", "DECISION_SPEED", "COMMUNICATION", "PLAN_ADHERENCE")
SCORES = (100, 94, 100, 100, 100)  # the demo record (plan §3): mean 98.8 → 99


async def user(conn: asyncpg.Connection, name: str = "operator") -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, $4)",
        user_id,
        f"sub-{user_id}",
        f"{user_id}@x",
        name,
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


async def scenario(conn: asyncpg.Connection) -> uuid.UUID:
    scenario_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO scenario (id, tenant_id, code, name) "
        "VALUES ($1, current_tenant_id(), $2, 'S')",
        scenario_id,
        f"SC-{scenario_id.hex[:8]}",
    )
    return scenario_id


async def run(conn: asyncpg.Connection, scenario_id: uuid.UUID, mode: str = "EXERCISE") -> Any:
    return await conn.fetchval(
        "INSERT INTO scenario_run (tenant_id, scenario_id, mode) "
        "VALUES (current_tenant_id(), $1, $2) RETURNING id",
        scenario_id,
        mode,
    )


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
        self.scenario = await scenario(self.conn)
        self.incident = await incident(self.conn, self.mission)
        self.exercise = await self.start()
        return self

    async def start(self, mission_id: uuid.UUID | None = None, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "mission_id": mission_id or self.mission,
            "scenario_id": self.scenario,
            "scenario_run_id": await run(self.conn, self.scenario),
            "name": "Civil unrest near the Nairobi Embassy",
            "kind": "FUNCTIONAL",
            "started_by": self.user,
            **change,
        }
        exercise_id: uuid.UUID = await insert(self.conn, "exercise", columns)
        return exercise_id

    async def complete(
        self,
        exercise: uuid.UUID | None = None,
        scores: tuple[int | None, ...] = SCORES,
        overall: int | None = 99,
        **change: Any,
    ) -> None:
        exercise = exercise or self.exercise
        async with self.conn.transaction():
            await self.conn.execute(
                "UPDATE exercise SET status = 'COMPLETED', overall_score = $2, participants = 16, "
                "incident_id = $3, ended_by = $4 WHERE id = $1",
                exercise,
                overall,
                change.get("incident_id", self.incident),
                change.get("ended_by", self.user),
            )
            await self.score(exercise, scores)

    async def score(self, exercise: uuid.UUID, scores: tuple[int | None, ...] = SCORES) -> None:
        for dimension, value in zip(DIMENSIONS, scores, strict=False):
            await insert(
                self.conn,
                "exercise_score",
                {
                    "exercise_id": exercise,
                    "dimension": dimension,
                    "score": value,
                    "measured": json.dumps({"figure": value}),
                },
            )

    async def illustrative(self, **change: Any) -> uuid.UUID:
        drilled = datetime.now(UTC) - timedelta(weeks=3)
        columns: dict[str, Any] = {
            "mission_id": self.mission,
            "name": "Civil unrest drill",
            "kind": "TABLETOP",
            "status": "COMPLETED",
            "overall_score": 79,
            "participants": 14,
            "source": "ILLUSTRATIVE",
            "started_at": drilled,
            "ended_at": drilled + timedelta(hours=2),
            **change,
        }
        async with self.conn.transaction():
            row_id: uuid.UUID = await insert(self.conn, "exercise", columns)
            await self.score(row_id, (80, 78, 79, 81, 77))
        return row_id


async def insert(conn: asyncpg.Connection, table: str, columns: dict[str, Any]) -> Any:
    names = ", ".join(["tenant_id", *columns])
    values = ", ".join(
        [
            "current_tenant_id()",
            *(
                f"${n}::jsonb" if name == "measured" else f"${n}"
                for n, name in enumerate(columns, start=1)
            ),
        ]
    )
    return await conn.fetchval(
        f"INSERT INTO {table} ({names}) VALUES ({values}) RETURNING id", *columns.values()
    )


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "EXR"))
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


async def row(world: World, exercise: uuid.UUID | None = None) -> Any:
    return await world.conn.fetchrow(
        "SELECT status, overall_score, participants, incident_id, ended_at, "
        "started_at = now() AS fresh, ended_at = now() AS ended_now FROM exercise WHERE id = $1",
        exercise or world.exercise,
    )


# --- PC-51 · exercise: starting -------------------------------------------------------------


async def test_an_exercise_starts_running_with_the_databases_time(world: World) -> None:
    async with world.conn.transaction():
        other = await world.start(await mission(world.conn), started_at=FORGED, ended_at=FORGED)
        found = await row(world, other)
    assert found is not None
    assert (found["status"], found["overall_score"], found["participants"]) == (
        "RUNNING",
        None,
        None,
    )
    assert (found["incident_id"], found["ended_at"], found["fresh"]) == (None, None, True)


async def test_an_exercise_needs_an_exercise_run_of_its_scenario(world: World) -> None:
    other = await mission(world.conn)
    with pytest.raises(REFUSED, match="no such exercise run"):
        await world.start(other, scenario_run_id=await run(world.conn, world.scenario, "DEMO"))
    with pytest.raises(REFUSED, match="no such exercise run"):
        await world.start(other, scenario_run_id=await run(world.conn, await scenario(world.conn)))
    with pytest.raises(REFUSED, match="no such exercise run"):
        await world.start(other, scenario_run_id=uuid.uuid4())


@pytest.mark.parametrize(
    "change",
    [
        {"status": "COMPLETED", "participants": 3, "ended_at": FORGED},
        {"status": "ABANDONED", "reason": "No", "ended_at": FORGED},
        {"ended_by": "USER"},
    ],
)
async def test_an_exercise_cannot_start_ended(world: World, change: dict[str, Any]) -> None:
    if change.get("ended_by") == "USER":
        change = {"ended_by": world.user}
    with pytest.raises(REFUSED, match="an exercise starts running"):
        await world.start(await mission(world.conn), **change)


async def test_an_exercise_cannot_start_with_an_incident(world: World) -> None:
    with pytest.raises(REFUSED, match="an exercise starts running"):
        await world.start(await mission(world.conn), incident_id=world.incident)


async def test_an_exercise_is_started_by_a_user_of_the_tenant(db: DbUrls, world: World) -> None:
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    stranger = await user(world.conn, "stranger")
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="exercise: no such user"):
        await world.start(await mission(world.conn), started_by=stranger)
    with pytest.raises(REFUSED, match="exercise: no such user"):
        await world.start(await mission(world.conn), started_by=None)


async def test_one_running_exercise_per_mission(world: World) -> None:
    with pytest.raises(UNIQUE, match="exercise_running_uq"):
        await world.start()
    await world.conn.execute(
        "UPDATE exercise SET status = 'ABANDONED', reason = 'Called off', ended_by = $2 "
        "WHERE id = $1",
        world.exercise,
        world.user,
    )
    await world.start()  # the mission is free again


async def test_a_run_is_one_exercise(world: World) -> None:
    taken = await world.conn.fetchval(
        "SELECT scenario_run_id FROM exercise WHERE id = $1", world.exercise
    )
    with pytest.raises(UNIQUE):
        await world.start(await mission(world.conn), scenario_run_id=taken)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "LIVE"},
        {"name": ""},
        {"source": "DEMO"},
    ],
)
async def test_an_exercise_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    with pytest.raises(CHECK):
        await world.start(await mission(world.conn), **change)


# --- PC-51 · exercise: ending ---------------------------------------------------------------


async def test_completing_freezes_the_scores_and_the_mean(world: World) -> None:
    async with world.conn.transaction():
        await world.complete()
        found = await row(world)
    assert found is not None
    assert (found["status"], found["overall_score"], found["participants"]) == ("COMPLETED", 99, 16)
    assert (found["incident_id"], found["ended_now"]) == (world.incident, True)
    scores = await world.conn.fetch(
        "SELECT dimension, score FROM exercise_score WHERE exercise_id = $1 ORDER BY dimension",
        world.exercise,
    )
    assert dict((r["dimension"], r["score"]) for r in scores) == dict(
        zip(DIMENSIONS, SCORES, strict=True)
    )


async def test_completing_needs_all_five_scores(world: World) -> None:
    with pytest.raises(REFUSED, match="has its five scores"):
        await world.complete(scores=SCORES[:4])
    with pytest.raises(REFUSED, match="has its five scores"):
        await world.conn.execute(
            "UPDATE exercise SET status = 'COMPLETED', overall_score = 99, participants = 16, "
            "ended_by = $2 WHERE id = $1",
            world.exercise,
            world.user,
        )
    assert (await row(world))["status"] == "RUNNING"


@pytest.mark.parametrize("overall", [98, 100, None])
async def test_the_overall_score_is_the_rounded_mean(world: World, overall: int | None) -> None:
    with pytest.raises(REFUSED, match="the overall score is the mean"):
        await world.complete(overall=overall)


async def test_scores_without_a_figure_are_left_out_of_the_mean(world: World) -> None:
    await world.complete(scores=(None, 94, None, 85, None), overall=90)  # 89.5 rounds up
    assert (await row(world))["overall_score"] == 90


async def test_an_exercise_with_no_figure_has_no_overall_score(world: World) -> None:
    await world.complete(scores=(None,) * 5, overall=None, incident_id=None)
    found = await row(world)
    assert (found["status"], found["overall_score"], found["incident_id"]) == (
        "COMPLETED",
        None,
        None,
    )


async def test_abandoning_needs_a_reason_and_takes_no_score(world: World) -> None:
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE exercise SET status = 'ABANDONED', ended_by = $2 WHERE id = $1",
            world.exercise,
            world.user,
        )
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE exercise SET status = 'ABANDONED', reason = 'No', overall_score = 50, "
            "ended_by = $2 WHERE id = $1",
            world.exercise,
            world.user,
        )
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE exercise SET status = 'ABANDONED', reason = 'No', incident_id = $3, "
            "ended_by = $2 WHERE id = $1",
            world.exercise,
            world.user,
            world.incident,
        )
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE exercise SET status = 'ABANDONED', reason = 'Called off', ended_by = $2 "
            "WHERE id = $1",
            world.exercise,
            world.user,
        )
        found = await row(world)
    assert (found["status"], found["ended_now"]) == ("ABANDONED", True)
    with pytest.raises(REFUSED, match="no such completed exercise"):
        await world.score(world.exercise)


async def test_an_exercise_ends_once(world: World) -> None:
    with pytest.raises(REFUSED, match="an exercise ends once"):
        await world.conn.execute(
            "UPDATE exercise SET status = 'RUNNING', ended_by = $2 WHERE id = $1",
            world.exercise,
            world.user,
        )
    await world.complete()
    for change in (
        "status = 'ABANDONED', reason = 'Late', overall_score = NULL, participants = NULL, "
        "incident_id = NULL",
        "overall_score = 99",
        "participants = 17",
    ):
        with pytest.raises(REFUSED, match="an exercise ends once"):
            await world.conn.execute(
                f"UPDATE exercise SET {change}, ended_by = $2 WHERE id = $1",
                world.exercise,
                world.user,
            )


async def test_only_ending_columns_can_be_updated(world: World) -> None:
    for column in (
        "name",
        "kind",
        "mission_id",
        "scenario_id",
        "scenario_run_id",
        "source",
        "started_by",
        "started_at",
        "ended_at",
        "tenant_id",
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"UPDATE exercise SET {column} = {column}")


@pytest.mark.parametrize(
    "column",
    [
        "name",
        "kind",
        "mission_id",
        "scenario_id",
        "scenario_run_id",
        "source",
        "started_by",
        "started_at",
    ],
)
async def test_every_fixed_column_is_fixed_for_the_owner(
    world: World, owner: asyncpg.Connection, column: str
) -> None:
    values = {
        "name": "'Renamed'",
        "kind": "'TABLETOP'",
        "mission_id": "gen_random_uuid()",
        "scenario_id": "gen_random_uuid()",
        "scenario_run_id": "gen_random_uuid()",
        "source": "'ILLUSTRATIVE'",
        "started_by": "NULL",
        "started_at": "now() - interval '1 day'",
    }
    with pytest.raises(REFUSED, match="only ending changes it"):
        await owner.execute(
            f"UPDATE exercise SET {column} = {values[column]}, status = 'ABANDONED', "
            "reason = 'No', ended_by = $2 WHERE id = $1",
            world.exercise,
            world.user,
        )


async def test_the_ending_is_by_a_user_of_the_tenant(db: DbUrls, world: World) -> None:
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Elsewhere"))
    stranger = await user(world.conn, "stranger")
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="exercise: no such user"):
        await world.complete(ended_by=stranger)


async def test_the_scored_incident_is_at_the_exercises_mission(world: World) -> None:
    elsewhere = await incident(world.conn, await mission(world.conn))
    with pytest.raises(REFUSED, match="no such incident at the mission"):
        await world.complete(incident_id=elsewhere)
    with pytest.raises(REFUSED, match="no such incident at the mission"):
        await world.complete(incident_id=await incident(world.conn, None))


# --- PC-51 · exercise: the seeded history ---------------------------------------------------


async def test_an_illustrative_exercise_keeps_its_past_dates(world: World) -> None:
    row_id = await world.illustrative()
    found = await world.conn.fetchrow(
        "SELECT status, overall_score, source, ended_at < now() - interval '1 week' AS past "
        "FROM exercise WHERE id = $1",
        row_id,
    )
    assert found is not None
    assert tuple(found) == ("COMPLETED", 79, "ILLUSTRATIVE", True)


@pytest.mark.parametrize(
    "change",
    [
        {"status": "RUNNING", "overall_score": None, "participants": None, "ended_at": None},
        {"started_by": "USER"},
        {"ended_by": "USER"},
        {"incident_id": "INCIDENT"},
    ],
)
async def test_an_illustrative_exercise_is_seeded_completed(
    world: World, change: dict[str, Any]
) -> None:
    lookup = {"USER": world.user, "INCIDENT": world.incident}
    change = {k: lookup.get(v, v) if isinstance(v, str) else v for k, v in change.items()}
    with pytest.raises(REFUSED, match="seeded completed"):
        await world.illustrative(**change)


async def test_an_illustrative_exercise_is_in_the_past(world: World) -> None:
    soon = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(REFUSED, match="in the past"):
        await world.illustrative(started_at=soon - timedelta(hours=2), ended_at=soon)
    with pytest.raises(REFUSED, match="in the past"):
        await world.illustrative(started_at=datetime.now(UTC) - timedelta(days=1), ended_at=FORGED)


async def test_an_illustrative_exercise_has_no_scenario_or_run(world: World) -> None:
    with pytest.raises(CHECK):
        await world.illustrative(scenario_id=world.scenario)
    with pytest.raises(CHECK):
        await world.illustrative(scenario_run_id=await run(world.conn, world.scenario))


async def test_a_real_exercise_has_a_scenario_and_a_run(world: World) -> None:
    with pytest.raises(REFUSED, match="no such exercise run"):
        await world.start(await mission(world.conn), scenario_run_id=None)


async def test_an_illustrative_exercise_cannot_change(world: World) -> None:
    row_id = await world.illustrative()
    with pytest.raises(REFUSED, match="an exercise ends once"):
        await world.conn.execute(
            "UPDATE exercise SET participants = 99, ended_by = $2 WHERE id = $1",
            row_id,
            world.user,
        )


# --- PC-52 · exercise_score -----------------------------------------------------------------


async def test_a_running_exercise_takes_no_score(world: World) -> None:
    with pytest.raises(REFUSED, match="no such completed exercise"):
        await world.score(world.exercise)


async def test_no_score_is_added_after_the_completion(world: World) -> None:
    await world.complete()
    with pytest.raises(UNIQUE):
        await world.score(world.exercise, (50,))


async def test_a_score_is_frozen(world: World, owner: asyncpg.Connection) -> None:
    await world.complete()
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE exercise_score SET score = 10")
    with pytest.raises(REFUSED, match="a score is frozen"):
        await owner.execute("UPDATE exercise_score SET score = 10")


async def test_a_score_times_itself(world: World) -> None:
    async with world.conn.transaction():
        await world.complete()
        fresh = await world.conn.fetchval(
            "SELECT bool_and(created_at = now()) FROM exercise_score WHERE exercise_id = $1",
            world.exercise,
        )
    assert fresh is True


@pytest.mark.parametrize(
    "change",
    [{"dimension": "SPEED"}, {"score": 101}, {"score": -1}, {"measured": "[]"}],
)
async def test_a_score_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    columns = {
        "exercise_id": world.exercise,
        "dimension": "DETECTION",
        "score": 90,
        "measured": "{}",
        **change,
    }
    await world.complete()  # the guard lets a completed exercise's score through to the CHECKs
    with pytest.raises(CHECK):
        await insert(world.conn, "exercise_score", columns)


# --- every table ----------------------------------------------------------------------------


async def test_nothing_is_deleted(world: World, owner: asyncpg.Connection) -> None:
    await world.complete()
    for table, kept in (
        ("exercise_score", "a score is frozen"),
        ("exercise", "the exercise is kept"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"DELETE FROM {table}")
        with pytest.raises(REFUSED, match=kept):
            await owner.execute(f"DELETE FROM {table}")


async def test_nothing_is_truncated(world: World, owner: asyncpg.Connection) -> None:
    for table in ("exercise_score", "exercise"):
        with pytest.raises(DENIED):
            await world.conn.execute(f"TRUNCATE {table} CASCADE")
        with pytest.raises(REFUSED, match="exercises and scores are kept"):
            await owner.execute(f"TRUNCATE {table} CASCADE")


async def test_the_guards_compare_tenants_even_without_rls(db: DbUrls, world: World) -> None:
    """A superuser bypasses RLS, so only the guards' own tenant checks stop a row of this tenant
    from pointing at another tenant's mission, run, incident or exercise."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Theirs"))
    theirs = await World(world.conn).build()
    await theirs.complete()
    their_run = await run(world.conn, theirs.scenario)
    await set_tenant(world.conn, mine)
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        assert await conn.fetchval(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        start = (
            "INSERT INTO exercise (tenant_id, mission_id, scenario_id, scenario_run_id, name, "
            "kind, started_by) VALUES ($1, $2, $3, $4, 'E', 'TABLETOP', $5)"
        )
        with pytest.raises(REFUSED, match="exercise: no such mission"):
            await conn.execute(
                start,
                mine,
                theirs.mission,
                world.scenario,
                await run(world.conn, world.scenario),
                world.user,
            )
        with pytest.raises(REFUSED, match="exercise: no such exercise run"):
            await conn.execute(
                start, mine, await mission(world.conn), theirs.scenario, their_run, world.user
            )
        with pytest.raises(REFUSED, match="no such incident at the mission"):
            await world.complete(incident_id=theirs.incident)
        with pytest.raises(REFUSED, match="exercise score: no such completed exercise"):
            await conn.execute(
                "INSERT INTO exercise_score (tenant_id, exercise_id, dimension) "
                "VALUES ($1, $2, 'DETECTION')",
                mine,
                theirs.exercise,
            )
    finally:
        await conn.close()


async def test_each_tenant_sees_only_its_own(db: DbUrls, world: World) -> None:
    await world.complete()
    await set_tenant(world.conn, await create_tenant(db, "Third"))
    assert await world.conn.fetchval("SELECT count(*) FROM exercise") == 0
    assert await world.conn.fetchval("SELECT count(*) FROM exercise_score") == 0


async def test_the_backup_role_reads_the_exercise_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w FROM unnest(ARRAY["
            "'exercise', 'exercise_score']) t ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("exercise", True, False),
        ("exercise_score", True, False),
    ]


# --- review of Prompt 113 -------------------------------------------------------------------


async def test_an_exercises_run_keeps_its_scenario_and_mode(world: World) -> None:
    """M1: the label and fusion's separation rest on the run's EXERCISE mode."""
    taken = await world.conn.fetchval(
        "SELECT scenario_run_id FROM exercise WHERE id = $1", world.exercise
    )
    with pytest.raises(REFUSED, match="keeps its scenario and mode"):
        await world.conn.execute("UPDATE scenario_run SET mode = 'DEMO' WHERE id = $1", taken)
    with pytest.raises(REFUSED, match="keeps its scenario and mode"):
        await world.conn.execute(
            "UPDATE scenario_run SET scenario_id = $2 WHERE id = $1",
            taken,
            await scenario(world.conn),
        )
    # The scenario engine still moves the run on, and other runs are untouched.
    await world.conn.execute(
        "UPDATE scenario_run SET status = 'PLAYING', current_scene = 1 WHERE id = $1", taken
    )
    free = await run(world.conn, world.scenario)
    await world.conn.execute("UPDATE scenario_run SET mode = 'DEMO' WHERE id = $1", free)


async def test_an_incident_is_scored_for_one_exercise(world: World) -> None:
    """L2."""
    await world.complete()
    again = World(world.conn)
    again.user, again.scenario, again.incident = world.user, world.scenario, world.incident
    again.mission = world.mission
    second = await again.start()
    with pytest.raises(UNIQUE, match="exercise_incident_uq"):
        await again.complete(second)


async def test_users_and_incidents_are_compared_by_tenant_without_rls(
    db: DbUrls, world: World
) -> None:
    """L3: through a role that bypasses RLS, only the guard's tenant check refuses them."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Bypassed"))
    their_user = await user(world.conn, "theirs")
    their_mission = await mission(world.conn)
    their_incident = await incident(world.conn, their_mission)
    await set_tenant(world.conn, mine)
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        with pytest.raises(REFUSED, match="exercise: no such user"):
            await conn.execute(
                "INSERT INTO exercise (tenant_id, mission_id, scenario_id, scenario_run_id, "
                "name, kind, started_by) VALUES ($1, $2, $3, $4, 'E', 'TABLETOP', $5)",
                mine,
                await mission(world.conn),
                world.scenario,
                await run(world.conn, world.scenario),
                their_user,
            )
        with pytest.raises(REFUSED, match="exercise: no such user"):
            await conn.execute(
                "UPDATE exercise SET status = 'ABANDONED', reason = 'No', ended_by = $2 "
                "WHERE id = $1",
                world.exercise,
                their_user,
            )
        # Their incident, pointed at this tenant's mission (foreign keys ignore RLS).
        await conn.execute(
            "UPDATE incident SET mission_id = $2 WHERE id = $1", their_incident, world.mission
        )
        with pytest.raises(REFUSED, match="no such incident at the mission"):
            await conn.execute(
                "UPDATE exercise SET status = 'COMPLETED', overall_score = NULL, "
                "participants = 0, incident_id = $3, ended_by = $2 WHERE id = $1",
                world.exercise,
                world.user,
                their_incident,
            )
    finally:
        await conn.close()


async def test_completing_at_repeatable_read_works(world: World) -> None:
    """L4: the deferred check counts the transaction's own scores at any isolation level."""
    async with world.conn.transaction(isolation="repeatable_read"):
        await world.conn.execute(
            "UPDATE exercise SET status = 'COMPLETED', overall_score = 99, participants = 16, "
            "incident_id = $2, ended_by = $3 WHERE id = $1",
            world.exercise,
            world.incident,
            world.user,
        )
        await world.score(world.exercise)
    assert (await row(world))["status"] == "COMPLETED"


async def test_checking_the_scores_early_refuses(world: World) -> None:
    """L4: SET CONSTRAINTS … IMMEDIATE can only make a completion fail."""
    early = world.conn.transaction()
    await early.start()
    await world.conn.execute(
        "UPDATE exercise SET status = 'COMPLETED', overall_score = 99, participants = 16, "
        "ended_by = $2 WHERE id = $1",
        world.exercise,
        world.user,
    )
    with pytest.raises(REFUSED, match="has its five scores"):
        await world.conn.execute("SET CONSTRAINTS exercise_scored_check IMMEDIATE")
    await early.rollback()
    assert (await row(world))["status"] == "RUNNING"


async def test_an_illustrative_exercise_needs_its_five_scores(world: World) -> None:
    """L4."""
    drilled = datetime.now(UTC) - timedelta(weeks=3)
    with pytest.raises(REFUSED, match="has its five scores"):
        await insert(
            world.conn,
            "exercise",
            {
                "mission_id": world.mission,
                "name": "Civil unrest drill",
                "kind": "TABLETOP",
                "status": "COMPLETED",
                "overall_score": 79,
                "participants": 14,
                "source": "ILLUSTRATIVE",
                "started_at": drilled,
                "ended_at": drilled,
            },
        )
