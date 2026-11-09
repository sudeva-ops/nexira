"""Migration 0016 (PC-49, PC-50; D-47), checked as nexira_api: a review starts only for an
incident that is no longer ACTIVE, once, as a draft, with the reference taken from the
incident's; it is finalised once, with its metrics, and only when no draft is left; an item is a
rule's draft or a reviewer's own accepted one; DRAFT → ACCEPTED or REJECTED, ACCEPTED → DONE and
nothing else; a final review takes no new item and no decision but DONE; the database writes the
times; every reference is to the same tenant, even for a role that bypasses RLS; nothing is
deleted (docs/plan-pilot-aar.md §6, §11)."""

import json
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
PT = "'SRID=4326;POINT(36.82 -1.28)'"
FORGED = datetime(2000, 1, 1, tzinfo=UTC)
DUE = date(2026, 12, 31)
METRICS = json.dumps({"detection_to_incident": {"value_s": 0, "target_s": 5, "met": True}})


async def user(conn: asyncpg.Connection, name: str = "reviewer") -> uuid.UUID:
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


async def incident(conn: asyncpg.Connection, number: int, status: str = "MONITORING") -> uuid.UUID:
    incident_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
        f"signal_severity, status, location) VALUES ($1, current_tenant_id(), $2, 'Civil unrest', "
        f"'CIVIL_UNREST', 'CRITICAL', 'HIGH', $3, {PT})",
        incident_id,
        f"INC-2026-{number}",
        status,
    )
    return incident_id


class World:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self.conn = conn

    async def build(self) -> "World":
        self.user = await user(self.conn)
        self.incident = await incident(self.conn, 1042)
        self.review = await self.start(self.incident)
        self.draft = await self.item("CHECKIN_SILENT")
        return self

    async def start(self, incident_id: uuid.UUID, **change: Any) -> uuid.UUID:
        columns: dict[str, Any] = {
            "incident_id": incident_id,
            "reference": "AAR-anything",
            "started_by": self.user,
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(
            [
                "current_tenant_id()",
                *(
                    f"${n}::jsonb" if name == "metrics" else f"${n}"
                    for n, name in enumerate(columns, start=1)
                ),
            ]
        )
        row_id: uuid.UUID = await self.conn.fetchval(
            f"INSERT INTO after_action_review ({names}) VALUES ({values}) RETURNING id",
            *columns.values(),
        )
        return row_id

    async def item(self, rule: str | None, review: uuid.UUID | None = None, **change: Any) -> Any:
        columns: dict[str, Any] = {
            "review_id": review or self.review,
            "rule_code": rule,
            "finding": "1 staff member did not answer NTF-3103 and was escalated",
            "action": "Confirm contact details and a second channel",
            "owner_team": "HR",
            "priority": "HIGH",
            **change,
        }
        names = ", ".join(["tenant_id", *columns])
        values = ", ".join(
            [
                "current_tenant_id()",
                *(
                    f"${n}::jsonb" if name == "evidence" else f"${n}"
                    for n, name in enumerate(columns, start=1)
                ),
            ]
        )
        return await self.conn.fetchval(
            f"INSERT INTO aar_item ({names}) VALUES ({values}) RETURNING id", *columns.values()
        )

    async def accept(self, item_id: uuid.UUID, conn: asyncpg.Connection | None = None) -> None:
        await (conn or self.conn).execute(
            "UPDATE aar_item SET status = 'ACCEPTED', owner_team = 'SECURITY', due_on = $2, "
            "decided_by = $3 WHERE id = $1",
            item_id,
            DUE,
            self.user,
        )

    async def finalise(self, review: uuid.UUID | None = None) -> None:
        await self.conn.execute(
            "UPDATE after_action_review SET status = 'FINAL', metrics = $2::jsonb, "
            "finalised_by = $3 WHERE id = $1",
            review or self.review,
            METRICS,
            self.user,
        )


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "AAR"))
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


# --- PC-49 · after_action_review ------------------------------------------------------------


async def test_a_review_starts_as_a_draft_with_the_incidents_reference(world: World) -> None:
    async with world.conn.transaction():
        other = await incident(world.conn, 1077, "CLOSED")
        row_id = await world.start(other, started_at=FORGED)
        row = await world.conn.fetchrow(
            "SELECT reference, status, metrics, finalised_at, started_at = now() AS fresh "
            "FROM after_action_review WHERE id = $1",
            row_id,
        )
    assert row is not None
    assert tuple(row) == ("AAR-2026-1077", "DRAFT", None, None, True)


async def test_a_review_waits_until_the_incident_is_not_active(world: World) -> None:
    active = await incident(world.conn, 1050, "ACTIVE")
    with pytest.raises(REFUSED, match="the incident is still active"):
        await world.start(active)
    with pytest.raises(UNIQUE):
        await world.start(world.incident)  # one review per incident


@pytest.mark.parametrize(
    "change",
    [
        {"status": "FINAL", "metrics": METRICS},
        {"metrics": METRICS},
    ],
)
async def test_a_review_cannot_start_final(world: World, change: dict[str, Any]) -> None:
    other = await incident(world.conn, 1060)
    with pytest.raises(REFUSED, match="a review starts as a draft"):
        await world.start(other, **dict(change))


async def test_a_review_starts_by_a_user_of_the_tenant(db: DbUrls, world: World) -> None:
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Other"))
    stranger = await user(world.conn, "stranger")
    await set_tenant(world.conn, mine)
    other = await incident(world.conn, 1061)
    with pytest.raises(REFUSED, match="after-action review: no such user"):
        await world.start(other, started_by=stranger)


async def test_finalising_needs_every_draft_decided(world: World) -> None:
    with pytest.raises(REFUSED, match="drafts are still to be decided"):
        await world.finalise()
    await world.accept(world.draft)
    async with world.conn.transaction():
        await world.finalise()
        row = await world.conn.fetchrow(
            "SELECT status, metrics IS NOT NULL AS frozen, finalised_at = now() AS fresh "
            "FROM after_action_review WHERE id = $1",
            world.review,
        )
    assert row is not None
    assert tuple(row) == ("FINAL", True, True)
    with pytest.raises(REFUSED, match="a review is finalised once"):
        await world.finalise()


async def test_a_review_is_final_with_its_metrics_and_by_a_person(world: World) -> None:
    await world.accept(world.draft)
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE after_action_review SET status = 'FINAL', finalised_by = $2 WHERE id = $1",
            world.review,
            world.user,
        )
    with pytest.raises(REFUSED, match="after-action review: no such user"):
        await world.conn.execute(
            "UPDATE after_action_review SET status = 'FINAL', metrics = $2::jsonb WHERE id = $1",
            world.review,
            METRICS,
        )
    with pytest.raises(REFUSED, match="a review is finalised once"):
        await world.conn.execute(
            "UPDATE after_action_review SET metrics = $2::jsonb WHERE id = $1",
            world.review,
            METRICS,
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("tenant_id", "gen_random_uuid()"),
        ("incident_id", "gen_random_uuid()"),
        ("reference", "'AAR-2026-1'"),
        ("started_by", "gen_random_uuid()"),
        ("started_at", "now() - interval '1 day'"),
        ("finalised_at", "now()"),
    ],
)
async def test_every_frozen_review_column(
    world: World, owner: asyncpg.Connection, column: str, value: str
) -> None:
    with pytest.raises(DENIED):
        await world.conn.execute(
            f"UPDATE after_action_review SET {column} = {value} WHERE id = $1", world.review
        )
    if column == "finalised_at":
        # Written by the database: a forged time on finalising is replaced.
        await world.accept(world.draft)
        async with owner.transaction():
            await owner.execute(
                "UPDATE after_action_review SET status = 'FINAL', metrics = $2::jsonb, "
                "finalised_by = $3, finalised_at = $4 WHERE id = $1",
                world.review,
                METRICS,
                world.user,
                FORGED,
            )
            assert await owner.fetchval(
                "SELECT finalised_at = now() FROM after_action_review WHERE id = $1",
                world.review,
            )
        return
    with pytest.raises(REFUSED, match="only finalising changes it"):
        await owner.execute(
            f"UPDATE after_action_review SET {column} = {value} WHERE id = $1", world.review
        )


async def test_a_review_finalised_by_a_user_of_the_tenant(db: DbUrls, world: World) -> None:
    await world.accept(world.draft)
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Elsewhere"))
    stranger = await user(world.conn, "stranger")
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="after-action review: no such user"):
        await world.conn.execute(
            "UPDATE after_action_review SET status = 'FINAL', metrics = $2::jsonb, "
            "finalised_by = $3 WHERE id = $1",
            world.review,
            METRICS,
            stranger,
        )


# --- PC-50 · aar_item -------------------------------------------------------------------------


async def test_a_rules_item_is_a_draft_and_a_reviewers_own_is_accepted(world: World) -> None:
    with pytest.raises(REFUSED, match="a rule's item starts as a draft"):
        await world.item("SITE_FAULT", status="ACCEPTED", decided_by=world.user, due_on=DUE)
    with pytest.raises(REFUSED, match="a reviewer's own item is accepted"):
        await world.item(None)
    async with world.conn.transaction():
        own = await world.item(
            None,
            status="ACCEPTED",
            decided_by=world.user,
            due_on=DUE,
            decided_at=FORGED,
            created_at=FORGED,
        )
        row = await world.conn.fetchrow(
            "SELECT decided_at = now() AND created_at = now() FROM aar_item WHERE id = $1", own
        )
    assert row is not None
    assert row[0]
    with pytest.raises(UNIQUE):
        await world.item("CHECKIN_SILENT")  # one per rule and review
    with pytest.raises(REFUSED, match="an item is done only once accepted"):
        await world.item(
            None, status="ACCEPTED", decided_by=world.user, due_on=DUE, done_by=world.user
        )


@pytest.mark.parametrize(
    "change",
    [
        {"owner_team": "PRESS"},
        {"priority": "URGENT"},
        {"finding": ""},
        {"action": "x" * 501},
        {"rule_code": "lower"},
        {"evidence": json.dumps([1])},
    ],
)
async def test_an_item_refuses_bad_values(world: World, change: dict[str, Any]) -> None:
    change = dict(change)
    rule = change.pop("rule_code", "FLEET_ZONE")
    with pytest.raises(CHECK):
        await world.item(rule, **change)


async def test_accept_then_done(world: World) -> None:
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE aar_item SET status = 'ACCEPTED', action = 'Reworded', due_on = $2, "
            "decided_by = $3 WHERE id = $1",
            world.draft,
            DUE,
            world.user,
        )
        assert await world.conn.fetchval(
            "SELECT decided_at = now() FROM aar_item WHERE id = $1", world.draft
        )
    with pytest.raises(REFUSED, match="marking done changes nothing else"):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'DONE', done_by = $2, due_on = due_on + 1 WHERE id = $1",
            world.draft,
            world.user,
        )
    async with world.conn.transaction():
        await world.conn.execute(
            "UPDATE aar_item SET status = 'DONE', done_by = $2 WHERE id = $1",
            world.draft,
            world.user,
        )
        assert await world.conn.fetchval(
            "SELECT done_at = now() FROM aar_item WHERE id = $1", world.draft
        )
    with pytest.raises(REFUSED, match="ACCEPTED → DONE only"):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'ACCEPTED', done_by = NULL WHERE id = $1", world.draft
        )


async def test_accepting_needs_a_due_date_and_rejecting_a_reason(world: World) -> None:
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'ACCEPTED', decided_by = $2 WHERE id = $1",
            world.draft,
            world.user,
        )
    with pytest.raises(CHECK):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'REJECTED', decided_by = $2 WHERE id = $1",
            world.draft,
            world.user,
        )
    with pytest.raises(REFUSED, match="aar item: no such user"):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'ACCEPTED', due_on = $2 WHERE id = $1",
            world.draft,
            DUE,
        )  # nobody decided it
    await world.conn.execute(
        "UPDATE aar_item SET status = 'REJECTED', reason = 'Handled offline', decided_by = $2 "
        "WHERE id = $1",
        world.draft,
        world.user,
    )
    for status in ("DRAFT", "ACCEPTED", "DONE"):
        with pytest.raises((REFUSED, CHECK)):
            await world.conn.execute(
                f"UPDATE aar_item SET status = '{status}', reason = NULL, due_on = $2, "
                "done_by = CASE WHEN $3 THEN decided_by END WHERE id = $1",
                world.draft,
                DUE,
                status == "DONE",
            )


async def test_a_draft_is_not_reworded_without_a_decision(world: World) -> None:
    with pytest.raises(REFUSED, match="ACCEPTED → DONE only"):
        await world.conn.execute(
            "UPDATE aar_item SET finding = 'Changed' WHERE id = $1", world.draft
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("tenant_id", "gen_random_uuid()"),
        ("review_id", "gen_random_uuid()"),
        ("rule_code", "'OTHER_RULE'"),
        ("evidence", "'{\"count\": 9}'"),
        ("created_at", "now() - interval '1 day'"),
    ],
)
async def test_every_frozen_item_column(
    world: World, owner: asyncpg.Connection, column: str, value: str
) -> None:
    with pytest.raises(DENIED):
        await world.conn.execute(
            f"UPDATE aar_item SET {column} = {value} WHERE id = $1", world.draft
        )
    with pytest.raises(REFUSED, match=r"the review, rule and evidence are fixed|no such review"):
        await owner.execute(f"UPDATE aar_item SET {column} = {value} WHERE id = $1", world.draft)


async def test_a_final_review_takes_only_done(world: World) -> None:
    second = await world.item("SITE_FAULT", owner_team="FACILITIES")
    await world.accept(world.draft)
    await world.conn.execute(
        "UPDATE aar_item SET status = 'REJECTED', reason = 'Not needed', decided_by = $2 "
        "WHERE id = $1",
        second,
        world.user,
    )
    await world.finalise()
    with pytest.raises(REFUSED, match="the review is final"):
        await world.item("FLEET_ZONE")
    with pytest.raises(REFUSED, match="the review is final"):
        await world.item(None, status="ACCEPTED", decided_by=world.user, due_on=DUE)
    await world.conn.execute(
        "UPDATE aar_item SET status = 'DONE', done_by = $2 WHERE id = $1", world.draft, world.user
    )
    assert (
        await world.conn.fetchval("SELECT status FROM aar_item WHERE id = $1", world.draft)
        == "DONE"
    )


async def test_a_decision_on_a_final_review_is_refused(
    world: World, owner: asyncpg.Connection
) -> None:
    """A DRAFT left on a final review cannot exist through the guards; made here with the guard
    off, as the owner, it still cannot be decided."""
    await world.accept(world.draft)
    await world.finalise()
    async with owner.transaction():
        await owner.execute("ALTER TABLE aar_item DISABLE TRIGGER aar_item_guard")
        stray = await owner.fetchval(
            "INSERT INTO aar_item (tenant_id, review_id, rule_code, finding, action, owner_team, "
            "priority) VALUES (current_tenant_id(), $1, 'SUPPLY_IMPACT', 'F', 'A', 'LOGISTICS', "
            "'MEDIUM') RETURNING id",
            world.review,
        )
        await owner.execute("ALTER TABLE aar_item ENABLE TRIGGER aar_item_guard")
    with pytest.raises(REFUSED, match="the review is final"):
        await world.accept(stray)


async def test_items_are_decided_by_users_of_the_tenant(db: DbUrls, world: World) -> None:
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Far"))
    stranger = await user(world.conn, "stranger")
    await set_tenant(world.conn, mine)
    with pytest.raises(REFUSED, match="aar item: no such user"):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'ACCEPTED', due_on = $2, decided_by = $3 WHERE id = $1",
            world.draft,
            DUE,
            stranger,
        )
    with pytest.raises(REFUSED, match="aar item: no such user"):
        await world.item(None, status="ACCEPTED", decided_by=stranger, due_on=DUE)
    await world.accept(world.draft)
    with pytest.raises(REFUSED, match="aar item: no such user"):
        await world.conn.execute(
            "UPDATE aar_item SET status = 'DONE', done_by = $2 WHERE id = $1",
            world.draft,
            stranger,
        )


# --- every table ------------------------------------------------------------------------------


async def test_nothing_is_deleted(world: World, owner: asyncpg.Connection) -> None:
    for table, kept in (
        ("aar_item", "the item is kept"),
        ("after_action_review", "the review is kept"),
    ):
        with pytest.raises(DENIED):
            await world.conn.execute(f"DELETE FROM {table}")
        with pytest.raises(REFUSED, match=kept):
            await owner.execute(f"DELETE FROM {table}")


async def test_the_guards_compare_tenants_even_without_rls(db: DbUrls, world: World) -> None:
    """A superuser bypasses RLS, so only the guards' own tenant checks stop a row of this tenant
    from pointing at another tenant's incident or review (the lesson of the Prompt 90 review)."""
    mine = await world.conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(world.conn, await create_tenant(db, "Theirs"))
    their_user = await user(world.conn, "theirs")
    theirs = await incident(world.conn, 2001)
    starter = World(world.conn)
    starter.user = their_user
    their_review = await starter.start(theirs)
    await set_tenant(world.conn, mine)
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        assert await conn.fetchval(
            "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        with pytest.raises(REFUSED, match="after-action review: no such incident"):
            await conn.execute(
                "INSERT INTO after_action_review (tenant_id, incident_id, reference, started_by) "
                "VALUES ($1, $2, 'AAR-', $3)",
                mine,
                theirs,
                world.user,
            )
        with pytest.raises(REFUSED, match="aar item: no such review"):
            await conn.execute(
                "INSERT INTO aar_item (tenant_id, review_id, rule_code, finding, action, "
                "owner_team, priority) VALUES ($1, $2, 'FLEET_ZONE', 'F', 'A', 'FLEET', 'LOW')",
                mine,
                their_review,
            )
    finally:
        await conn.close()


async def test_each_tenant_sees_only_its_own(db: DbUrls, world: World) -> None:
    await set_tenant(world.conn, await create_tenant(db, "Third"))
    assert await world.conn.fetchval("SELECT count(*) FROM after_action_review") == 0
    assert await world.conn.fetchval("SELECT count(*) FROM aar_item") == 0


async def test_the_backup_role_reads_the_review_tables(db: DbUrls) -> None:
    conn = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        rows = await conn.fetch(
            "SELECT t, has_table_privilege('nexira_backup', t, 'SELECT') AS r, "
            "has_table_privilege('nexira_backup', t, 'INSERT') AS w FROM unnest(ARRAY["
            "'aar_item', 'after_action_review']) t ORDER BY t"
        )
    finally:
        await conn.close()
    assert [tuple(r) for r in rows] == [
        ("aar_item", True, False),
        ("after_action_review", True, False),
    ]
