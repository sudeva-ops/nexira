"""Migration 0012 (PC-35..38; D-42), checked as nexira_api: a visit is linked only to a
restricted trip and moves PLANNED -> LIVE -> COMPLETED (or CANCELLED) once; segments move
forward only while the visit is live, and their time or "virtual" changes only in the
transaction that approves a change decided by another person; checklist items are done once
(docs/plan-pilot-vip.md §5, §6, §12)."""

import uuid
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
UNIQUE = asyncpg.UniqueViolationError
PT = "'SRID=4326;POINT(38.90 9.00)'"
DAY = "current_date + 4"


async def mission(conn: asyncpg.Connection, code: str = "ADD") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Addis Ababa', 'ET', {PT})",
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


async def trip(conn: asyncpg.Connection, restricted: bool = True) -> uuid.UUID:
    trip_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO trip (tenant_id, reference, origin, destination, starts_on, ends_on, "
        "restricted) VALUES (current_tenant_id(), $1, 'HQ', 'Addis Ababa', current_date + 4, "
        "current_date + 6, $2) RETURNING id",
        f"TRP-{uuid.uuid4().int % 10_000:04d}",
        restricted,
    )
    return trip_id


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.mission = await mission(self.conn)
        self.trip = await trip(self.conn)
        self.security = await user(self.conn)
        self.hq = await user(self.conn)
        self.visit = await self.add_visit()
        self.segment = await self.add_segment(self.visit, 1)
        return self

    async def add_visit(self, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "reference": f"VV-2026-{uuid.uuid4().int % 1000:03d}",
            "title": "Minister's visit to Addis Ababa",
            "mission_id": self.mission,
            "principal_role": "Minister of Foreign Affairs",
            "trip_id": self.trip,
            **change,
        }
        names = ", ".join(["tenant_id", "starts_on", "ends_on", *columns])
        values = ", ".join(
            ["current_tenant_id()", DAY, "current_date + 6"]
            + [f"${n}" for n in range(1, len(columns) + 1)]
        )
        visit_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO vip_visit ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )
        return visit_id

    async def add_segment(self, visit_id: uuid.UUID, seq: int, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "visit_id": visit_id,
            "seq": seq,
            "kind": "SITE_VISIT",
            "title": "Site visit · Industrial park",
            "venue_name": "Industrial park",
            **change,
        }
        names = ", ".join(["tenant_id", "venue_location", "starts_at", *columns])
        values = ", ".join(
            ["current_tenant_id()", PT, "now() + interval '5 days'"]
            + [f"${n}" for n in range(1, len(columns) + 1)]
        )
        segment_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO vip_segment ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )
        return segment_id

    async def start(self, visit_id: uuid.UUID | None = None) -> None:
        await self.conn.execute(
            "UPDATE vip_visit SET status = 'LIVE', started_by = $2 WHERE id = $1",
            visit_id or self.visit,
            self.security,
        )

    async def propose(self, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "segment_id": self.segment,
            "reason": "Rally planned 1.2 km away",
            "proposed_by": self.security,
            **change,
        }
        if "make_virtual" not in columns and "new_starts_at" not in columns:
            change_sql = ", new_starts_at", ", now() + interval '5 days' - interval '2 hours'"
        else:
            change_sql = "", ""
        names = ", ".join(["tenant_id", *columns]) + change_sql[0]
        values = (
            ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
            + change_sql[1]
        )
        change_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO vip_segment_change ({names}) VALUES ({values}) RETURNING id",
            *columns.values(),
        )
        return change_id

    async def approve(self, change_id: uuid.UUID, by: uuid.UUID | None = None) -> None:
        """The decision and the segment's new time in one transaction (VIP-05)."""
        async with self.conn.transaction():
            await self.conn.execute(
                "UPDATE vip_segment_change SET status = 'APPROVED', decided_by = $2 WHERE id = $1",
                change_id,
                by or self.hq,
            )
            await self.conn.execute(
                "UPDATE vip_segment s SET starts_at = c.new_starts_at, ends_at = c.new_ends_at, "
                "virtual = c.make_virtual OR s.virtual FROM vip_segment_change c "
                "WHERE c.id = $1 AND s.id = c.segment_id",
                change_id,
            )


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "VIP"))
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


# --- PC-35 · visits ----------------------------------------------------------------------------


async def test_a_visit_starts_planned_and_the_database_writes_its_times(world: World) -> None:
    async with world.conn.transaction():
        visit_id = await world.add_visit(reference="VV-2026-031")
        row = await world.conn.fetchrow(
            "SELECT status, source, created_at = now() AS fresh, started_at FROM vip_visit "
            "WHERE id = $1",
            visit_id,
        )
    assert row is not None
    assert tuple(row) == ("PLANNED", "Illustrative visit (simulated)", True, None)
    with pytest.raises(UNIQUE):
        await world.add_visit(reference="VV-2026-031")
    with pytest.raises(REFUSED, match="a visit starts planned"):
        await world.add_visit(status="LIVE", started_by=world.security)


async def test_a_visit_links_only_to_a_restricted_trip_of_this_tenant(
    db: DbUrls, world: World
) -> None:
    with pytest.raises(REFUSED, match="restricted trip of this tenant"):
        await world.add_visit(trip_id=await trip(world.conn, restricted=False))
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs_trip, theirs_mission = await trip(world.conn), await mission(world.conn)
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="restricted trip of this tenant"):
        await world.add_visit(trip_id=theirs_trip)
    with pytest.raises(REFUSED, match="no such mission"):
        await world.add_visit(mission_id=theirs_mission)
    assert await world.add_visit(trip_id=None)  # a visit without a trip is allowed


@pytest.mark.parametrize(
    "change",
    [
        {"reference": "VV-31"},
        {"title": ""},
        {"principal_role": ""},
        {"status": "DRAFT"},
        {"detail": "[]"},
    ],
)
async def test_a_visit_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    if "detail" in change:
        with pytest.raises(CHECK):
            await world.conn.execute(
                "INSERT INTO vip_visit (tenant_id, reference, title, mission_id, principal_role, "
                "starts_on, ends_on, detail) VALUES (current_tenant_id(), 'VV-2026-099', 't', $1, "
                "'r', current_date, current_date, '[]'::jsonb)",
                world.mission,
            )
        return
    with pytest.raises((CHECK, REFUSED)):
        await world.add_visit(**change)


async def test_ends_on_is_not_before_starts_on(world: World) -> None:
    with pytest.raises(CHECK):
        await world.conn.execute(
            "INSERT INTO vip_visit (tenant_id, reference, title, mission_id, principal_role, "
            "starts_on, ends_on) VALUES (current_tenant_id(), 'VV-2026-098', 't', $1, 'r', "
            "current_date + 2, current_date + 1)",
            world.mission,
        )


async def test_a_visit_goes_live_completes_and_is_final(world: World) -> None:
    async with world.conn.transaction():
        await world.start()
        row = await world.conn.fetchrow(
            "SELECT status, started_by, started_at = now() AS fresh FROM vip_visit WHERE id = $1",
            world.visit,
        )
    assert row is not None
    assert tuple(row) == ("LIVE", world.security, True)
    with pytest.raises(REFUSED, match="LIVE cannot become PLANNED"):
        await world.conn.execute(
            "UPDATE vip_visit SET status = 'PLANNED' WHERE id = $1", world.visit
        )
    with pytest.raises(REFUSED, match="set once, on starting"):
        await world.conn.execute(
            "UPDATE vip_visit SET started_by = $2 WHERE id = $1", world.visit, world.hq
        )
    await world.conn.execute("UPDATE vip_visit SET status = 'COMPLETED' WHERE id = $1", world.visit)
    with pytest.raises(REFUSED, match="a completed visit is final"):
        await world.conn.execute(
            "UPDATE vip_visit SET status = 'CANCELLED', cancelled_by = $2, cancel_reason = 'x' "
            "WHERE id = $1",
            world.visit,
            world.hq,
        )


async def test_starting_needs_someone_of_this_tenant(db: DbUrls, world: World) -> None:
    with pytest.raises(REFUSED, match="started by someone of this tenant"):
        await world.conn.execute("UPDATE vip_visit SET status = 'LIVE' WHERE id = $1", world.visit)
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs = await user(world.conn)
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="started by someone of this tenant"):
        await world.conn.execute(
            "UPDATE vip_visit SET status = 'LIVE', started_by = $2 WHERE id = $1",
            world.visit,
            theirs,
        )


async def test_a_cancellation_needs_who_and_why_and_is_final(world: World) -> None:
    with pytest.raises(REFUSED, match="a cancellation sets the status"):
        await world.conn.execute(
            "UPDATE vip_visit SET cancel_reason = 'x' WHERE id = $1", world.visit
        )
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE vip_visit SET status = 'CANCELLED', cancelled_by = $2 WHERE id = $1",
            world.visit,
            world.hq,
        )
    await world.conn.execute(
        "UPDATE vip_visit SET status = 'CANCELLED', cancelled_by = $2, "
        "cancel_reason = 'Host nation postponed' WHERE id = $1",
        world.visit,
        world.hq,
    )
    assert await world.conn.fetchval(
        "SELECT cancelled_at IS NOT NULL FROM vip_visit WHERE id = $1", world.visit
    )
    with pytest.raises(REFUSED, match="a cancelled visit is final"):
        await world.start()


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE vip_visit SET title = 'x'",
        "UPDATE vip_visit SET principal_role = 'x'",
        "UPDATE vip_visit SET starts_on = starts_on + 1",
        "UPDATE vip_visit SET trip_id = NULL",
        """UPDATE vip_visit SET detail = '{"team_size": 9}'""",
        "UPDATE vip_visit SET source = 'real'",
    ],
)
async def test_what_a_visit_is_stays_fixed(
    world: World, owner: asyncpg.Connection, stmt: str
) -> None:
    with pytest.raises(DENIED):
        await world.conn.execute(stmt)
    with pytest.raises(REFUSED, match="stays fixed"):
        await owner.execute(stmt)


async def test_visits_segments_changes_and_items_are_kept(
    world: World, owner: asyncpg.Connection
) -> None:
    await world.propose()
    await world.conn.execute(
        "INSERT INTO vip_checklist_item (tenant_id, visit_id, label, due_on) "
        "VALUES (current_tenant_id(), $1, 'Venue survey', current_date)",
        world.visit,
    )
    for table, kept in (
        ("vip_checklist_item", "items are kept"),
        ("vip_segment_change", "changes are kept"),
        ("vip_segment", "the programme is kept"),
        ("vip_visit", "visits are kept"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"DELETE FROM {table}")
        with pytest.raises(REFUSED, match=kept):
            await owner.execute(f"DELETE FROM {table}")


# --- PC-36 · segments --------------------------------------------------------------------------


async def test_the_programme_is_set_before_the_visit_starts(world: World) -> None:
    await world.add_segment(world.visit, 2, kind="DEPARTURE", title="Departure")
    with pytest.raises(UNIQUE):
        await world.add_segment(world.visit, 2)
    with pytest.raises(REFUSED, match="a segment starts planned"):
        await world.add_segment(world.visit, 3, status="IN_PROGRESS")
    with pytest.raises(CHECK):
        await world.add_segment(world.visit, 4, kind="PARADE")
    await world.start()
    with pytest.raises(REFUSED, match="set before the visit starts"):
        await world.add_segment(world.visit, 5)


async def test_a_segment_names_only_this_tenants_visit(db: DbUrls, world: World) -> None:
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    other = await World(world.conn).build()
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="no such visit"):
        await world.add_segment(other.visit, 9)


async def test_segments_move_forward_one_step_while_the_visit_is_live(world: World) -> None:
    move = "UPDATE vip_segment SET status = $2 WHERE id = $1"
    with pytest.raises(REFUSED, match="only while the visit is live"):
        await world.conn.execute(move, world.segment, "IN_PROGRESS")
    await world.start()
    with pytest.raises(REFUSED, match="PLANNED cannot become COMPLETED"):
        await world.conn.execute(move, world.segment, "COMPLETED")
    await world.conn.execute(move, world.segment, "IN_PROGRESS")
    await world.conn.execute(move, world.segment, "COMPLETED")
    with pytest.raises(REFUSED, match="COMPLETED cannot become IN_PROGRESS"):
        await world.conn.execute(move, world.segment, "IN_PROGRESS")
    await world.conn.execute("UPDATE vip_visit SET status = 'COMPLETED' WHERE id = $1", world.visit)
    with pytest.raises(REFUSED, match="the visit is final"):
        await world.conn.execute(move, world.segment, "COMPLETED")


@pytest.mark.parametrize(
    "stmt",
    [
        "UPDATE vip_segment SET title = 'x'",
        "UPDATE vip_segment SET venue_name = 'x'",
        "UPDATE vip_segment SET attendees = 10",
        "UPDATE vip_segment SET kind = 'EVENT'",
    ],
)
async def test_what_a_segment_is_stays_fixed(
    world: World, owner: asyncpg.Connection, stmt: str
) -> None:
    with pytest.raises(DENIED):
        await world.conn.execute(stmt)
    with pytest.raises(REFUSED, match="stays fixed"):
        await owner.execute(stmt)


async def test_the_time_changes_only_with_a_change_approved_in_the_same_transaction(
    world: World,
) -> None:
    for stmt in (
        "UPDATE vip_segment SET starts_at = starts_at - interval '2 hours' WHERE id = $1",
        "UPDATE vip_segment SET virtual = true WHERE id = $1",
    ):
        with pytest.raises(REFUSED, match="only with an approved change"):
            await world.conn.execute(stmt, world.segment)
    change_id = await world.propose()
    await world.approve(change_id)
    row = await world.conn.fetchrow(
        "SELECT s.starts_at = c.new_starts_at AS moved, s.virtual FROM vip_segment s "
        "JOIN vip_segment_change c ON c.segment_id = s.id WHERE c.id = $1",
        change_id,
    )
    assert row is not None
    assert tuple(row) == (True, False)
    # The approval was in an earlier transaction: it does not allow a later move.
    with pytest.raises(REFUSED, match="only with an approved change"):
        await world.conn.execute(
            "UPDATE vip_segment SET starts_at = starts_at + interval '1 hour' WHERE id = $1",
            world.segment,
        )


async def test_the_segment_takes_exactly_the_approved_change(world: World) -> None:
    change_id = await world.propose()
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE vip_segment_change SET status = 'APPROVED', decided_by = $2 WHERE id = $1",
            change_id,
            world.hq,
        )
        with pytest.raises(REFUSED, match="the time is the approved change's"):
            await world.conn.execute(
                "UPDATE vip_segment SET starts_at = now() + interval '9 days' WHERE id = $1",
                world.segment,
            )
    # The refused update rolled the approval back; a second segment shows the virtual case.
    world.segment = await world.add_segment(world.visit, 2)
    virtual = await world.propose(make_virtual=True)
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE vip_segment_change SET status = 'APPROVED', decided_by = $2 WHERE id = $1",
            virtual,
            world.hq,
        )
        with pytest.raises(REFUSED, match="makes it virtual, nothing else"):
            await world.conn.execute(
                "UPDATE vip_segment SET virtual = true, starts_at = starts_at + interval '1 h' "
                "WHERE id = $1",
                world.segment,
            )


async def test_only_a_planned_segment_changes(world: World) -> None:
    change_id = await world.propose()
    await world.start()
    await world.conn.execute(
        "UPDATE vip_segment SET status = 'IN_PROGRESS' WHERE id = $1", world.segment
    )
    with pytest.raises(REFUSED, match="only a planned segment changes"):
        await world.approve(change_id)


# --- PC-38 · changes ---------------------------------------------------------------------------


async def test_a_change_is_pending_once_per_segment_and_decided_once_by_another(
    world: World,
) -> None:
    change_id = await world.propose()
    with pytest.raises(UNIQUE):
        await world.propose()
    with pytest.raises(REFUSED, match="the proposer cannot decide"):
        await world.conn.execute(
            "UPDATE vip_segment_change SET status = 'APPROVED', decided_by = $2 WHERE id = $1",
            change_id,
            world.security,
        )
    await world.conn.execute(
        "UPDATE vip_segment_change SET status = 'REJECTED', decided_by = $2, "
        "decision_note = 'Keep the programme' WHERE id = $1",
        change_id,
        world.hq,
    )
    assert await world.conn.fetchval(
        "SELECT decided_at IS NOT NULL FROM vip_segment_change WHERE id = $1", change_id
    )
    with pytest.raises(REFUSED, match="a decision is final"):
        await world.conn.execute(
            "UPDATE vip_segment_change SET status = 'APPROVED' WHERE id = $1", change_id
        )
    assert await world.propose()  # the segment may get a new proposal after a decision


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"make_virtual": True, "new_starts_at": None}, None),  # virtual alone is fine
        ({"make_virtual": False, "new_starts_at": None}, CHECK),  # neither
        ({"status": "APPROVED"}, REFUSED),  # starts pending
        ({"reason": ""}, CHECK),
    ],
)
async def test_a_change_proposes_a_time_or_virtual(
    world: World, change: dict[str, Any], error: type[Exception] | None
) -> None:
    if error is None:
        assert await world.propose(**change)
        return
    with pytest.raises(error):
        await world.propose(**change)


async def test_a_change_is_proposed_and_decided_by_people_of_this_tenant(
    db: DbUrls, world: World
) -> None:
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs = await user(world.conn)
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="proposed by someone of this tenant"):
        await world.propose(proposed_by=theirs)
    change_id = await world.propose()
    with pytest.raises(REFUSED, match="decided by someone of this tenant"):
        await world.conn.execute(
            "UPDATE vip_segment_change SET status = 'APPROVED', decided_by = $2 WHERE id = $1",
            change_id,
            theirs,
        )
    for stmt in (
        "UPDATE vip_segment_change SET reason = 'x'",
        "UPDATE vip_segment_change SET new_starts_at = now()",
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(stmt)


async def test_no_change_once_the_visit_is_final(world: World) -> None:
    await world.conn.execute(
        "UPDATE vip_visit SET status = 'CANCELLED', cancelled_by = $2, cancel_reason = 'x' "
        "WHERE id = $1",
        world.visit,
        world.hq,
    )
    with pytest.raises(REFUSED, match="the visit is final"):
        await world.propose()


# --- PC-37 · the checklist ---------------------------------------------------------------------


async def test_a_checklist_item_is_done_once_by_someone_of_this_tenant(
    db: DbUrls, world: World, owner: asyncpg.Connection
) -> None:
    item_id = await world.conn.fetchval(
        "INSERT INTO vip_checklist_item (tenant_id, visit_id, label, due_on) "
        "VALUES (current_tenant_id(), $1, 'Industrial park venue survey', current_date + 3) "
        "RETURNING id",
        world.visit,
    )
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    theirs = await user(world.conn)
    await set_tenant(world.conn, mine)
    done = "UPDATE vip_checklist_item SET done_by = $2 WHERE id = $1"
    with pytest.raises(REFUSED, match="done by someone of this tenant"):
        await world.conn.execute(done, item_id, theirs)
    async with world.conn.transaction():
        await world.conn.execute(done, item_id, world.security)
        assert await world.conn.fetchval(
            "SELECT done_at = now() FROM vip_checklist_item WHERE id = $1", item_id
        )
    with pytest.raises(REFUSED, match="done is final"):
        await world.conn.execute(done, item_id, world.hq)
    with pytest.raises(DENIED):
        await world.conn.execute("UPDATE vip_checklist_item SET label = 'x'")
    with pytest.raises(REFUSED, match="stays fixed"):
        await owner.execute("UPDATE vip_checklist_item SET label = 'x'")


async def test_a_checklist_item_may_be_seeded_done(world: World) -> None:
    async with world.conn.transaction():
        row = await world.conn.fetchrow(
            "INSERT INTO vip_checklist_item (tenant_id, visit_id, label, due_on, done_by) "
            "VALUES (current_tenant_id(), $1, 'Threat assessment issued', current_date, $2) "
            "RETURNING done_at = now() AS fresh",
            world.visit,
            world.security,
        )
    assert row is not None
    assert row["fresh"] is True


async def test_the_backup_role_reads_the_vip_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w FROM unnest(ARRAY["
            "'vip_checklist_item', 'vip_segment', 'vip_segment_change', 'vip_visit']) t ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("vip_checklist_item", True, False),
        ("vip_segment", True, False),
        ("vip_segment_change", True, False),
        ("vip_visit", True, False),
    ]
