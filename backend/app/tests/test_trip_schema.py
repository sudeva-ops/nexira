"""Migration 0003 (PC-14, PC-15, PC-16; D-32), checked as nexira_api: a user's trip
starts as a DRAFT, is frozen once submitted (with its travellers and itinerary), moves
only forward, is approved only by a second person (a LOW trip on submission), and is
never deleted; seeded trips load as they are, with no approver."""

import uuid

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the triggers' RAISE EXCEPTION (P0001)
ADD_TRAVELLER = (
    "INSERT INTO trip_traveller (tenant_id, trip_id, person_id) "
    "VALUES (current_tenant_id(), $1, $2)"
)
ADD_SEGMENT = (
    "INSERT INTO trip_segment (tenant_id, trip_id, seq, kind, title, starts_at, ends_at) "
    "VALUES (current_tenant_id(), $1, $2, 'STAY', 'Hotel', now(), now())"
)


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Trips"))
    return api


async def user(conn: asyncpg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, 'U')",
        user_id,
        f"sub-{user_id}",
        f"{user_id}@users.invalid",
    )
    return user_id


async def person(conn: asyncpg.Connection) -> uuid.UUID:
    person_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO person (id, tenant_id, person_type, full_name) "
        "VALUES ($1, current_tenant_id(), 'DIPLOMAT', 'Fictional Traveller')",
        person_id,
    )
    return person_id


async def trip(
    conn: asyncpg.Connection,
    requester: uuid.UUID | None,
    status: str = "DRAFT",
    risk: str = "HIGH",
) -> uuid.UUID:
    trip_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO trip (id, tenant_id, reference, origin, destination, destination_country, "
        "starts_on, ends_on, risk_level, approval_status, requested_by) VALUES ($1, "
        "current_tenant_id(), $2, 'HQ', 'Paris', 'FR', current_date, current_date + 3, $3, $4, $5)",
        trip_id,
        f"TRP-{trip_id.hex[:6]}",
        risk,
        status,
        requester,
    )
    return trip_id


async def submit(conn: asyncpg.Connection, trip_id: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE trip SET approval_status = 'PENDING', submitted_at = now() WHERE id = $1", trip_id
    )


async def approve(
    conn: asyncpg.Connection, trip_id: uuid.UUID, by: uuid.UUID | None, level: str
) -> None:
    await conn.execute(
        "UPDATE trip SET approval_status = 'APPROVED', approved_by = $2, "
        "approved_risk_level = $3 WHERE id = $1",
        trip_id,
        by,
        level,
    )


async def status_of(conn: asyncpg.Connection, trip_id: uuid.UUID) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT approval_status, approved_by, approved_at, approved_risk_level FROM trip "
        "WHERE id = $1",
        trip_id,
    )
    assert row is not None
    return row


# --- creating ------------------------------------------------------------------------


async def test_a_users_trip_starts_as_a_draft(tenant: asyncpg.Connection) -> None:
    requester = await user(tenant)
    with pytest.raises(REFUSED, match="a trip starts as a DRAFT"):
        await trip(tenant, requester, status="APPROVED")
    assert (await status_of(tenant, await trip(tenant, requester)))["approval_status"] == "DRAFT"


async def test_a_seeded_trip_loads_approved_but_never_with_an_approver(
    tenant: asyncpg.Connection,
) -> None:
    seeded = await trip(tenant, None, status="APPROVED", risk="MODERATE")
    row = await status_of(tenant, seeded)
    assert (row["approved_at"] is not None, row["approved_risk_level"]) == (True, "MODERATE")
    with pytest.raises(REFUSED, match="cannot be created with an approval"):
        await tenant.execute(
            "INSERT INTO trip (tenant_id, reference, origin, destination, starts_on, ends_on, "
            "approval_status, approved_by) VALUES (current_tenant_id(), 'TRP-X', 'A', 'B', "
            "current_date, current_date, 'APPROVED', $1)",
            await user(tenant),
        )


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("approved_at", "now()", "cannot be created with an approval"),
        ("approved_risk_level", "'LOW'", "cannot be created with an approval"),
        ("submitted_at", "now() - interval '9 days'", "cannot be created as submitted"),
        ("rejection_reason", "'fake'", "cannot be created as submitted or rejected"),
    ],
)
async def test_a_trip_is_never_created_with_a_recorded_step(
    tenant: asyncpg.Connection, column: str, value: str, message: str
) -> None:
    for requester in (await user(tenant), None):
        with pytest.raises(REFUSED, match=message):
            await tenant.execute(
                f"INSERT INTO trip (tenant_id, reference, origin, destination, starts_on, ends_on, "
                f"risk_level, requested_by, {column}) VALUES (current_tenant_id(), "
                f"'TRP-{uuid.uuid4().hex[:6]}', 'A', 'B', current_date, current_date, 'CRITICAL', "
                f"$1, {value})",
                requester,
            )


async def test_the_database_records_created_and_submitted_times(
    tenant: asyncpg.Connection,
) -> None:
    trip_id = await trip(tenant, await user(tenant))
    with pytest.raises(REFUSED, match="submitted_at is recorded only on submission"):
        await tenant.execute("UPDATE trip SET submitted_at = now() WHERE id = $1", trip_id)
    await tenant.execute(
        "UPDATE trip SET approval_status = 'PENDING', submitted_at = '2020-01-01' WHERE id = $1",
        trip_id,
    )
    assert await tenant.fetchval(
        "SELECT submitted_at > now() - interval '1 minute' FROM trip WHERE id = $1", trip_id
    )
    seeded = await trip(tenant, None, status="PENDING")
    assert await tenant.fetchval("SELECT submitted_at FROM trip WHERE id = $1", seeded) is not None


# --- frozen once submitted --------------------------------------------------------------


async def test_a_draft_is_editable_with_its_travellers_and_itinerary(
    tenant: asyncpg.Connection,
) -> None:
    trip_id = await trip(tenant, await user(tenant))
    await tenant.execute("UPDATE trip SET destination = 'Lyon' WHERE id = $1", trip_id)
    traveller = await person(tenant)
    await tenant.execute(
        ADD_TRAVELLER,
        trip_id,
        traveller,
    )
    await tenant.execute("DELETE FROM trip_traveller WHERE trip_id = $1", trip_id)
    await tenant.execute(
        "INSERT INTO trip_segment (tenant_id, trip_id, seq, kind, title, starts_at, ends_at) "
        "VALUES (current_tenant_id(), $1, 1, 'STAY', 'Hotel', now(), now() + interval '1 day')",
        trip_id,
    )


async def test_a_submitted_trip_is_frozen_with_its_travellers_and_itinerary(
    tenant: asyncpg.Connection,
) -> None:
    trip_id = await trip(tenant, await user(tenant))
    traveller = await person(tenant)
    await tenant.execute(
        ADD_TRAVELLER,
        trip_id,
        traveller,
    )
    await submit(tenant, trip_id)
    for change in ("destination = 'Lyon'", "ends_on = current_date + 30", "risk_level = 'LOW'"):
        with pytest.raises(REFUSED, match="frozen once it leaves DRAFT"):
            await tenant.execute(f"UPDATE trip SET {change} WHERE id = $1", trip_id)
    with pytest.raises(REFUSED, match="travellers and itinerary are frozen"):
        await tenant.execute("DELETE FROM trip_traveller WHERE trip_id = $1", trip_id)
    with pytest.raises(REFUSED, match="travellers and itinerary are frozen"):
        await tenant.execute(
            "INSERT INTO trip_traveller (tenant_id, trip_id, person_id) "
            "VALUES (current_tenant_id(), $1, $2)",
            trip_id,
            await person(tenant),
        )
    with pytest.raises(REFUSED, match="travellers and itinerary are frozen"):
        await tenant.execute(
            "INSERT INTO trip_segment (tenant_id, trip_id, seq, kind, title, starts_at, ends_at) "
            "VALUES (current_tenant_id(), $1, 1, 'STAY', 'Hotel', now(), now())",
            trip_id,
        )


async def test_a_submitted_trips_children_cannot_change_or_move(
    tenant: asyncpg.Connection,
) -> None:
    trip_id, draft = await trip(tenant, await user(tenant)), await trip(tenant, await user(tenant))
    await tenant.execute(ADD_TRAVELLER, trip_id, await person(tenant))
    await tenant.execute(ADD_SEGMENT, trip_id, 1)
    await submit(tenant, trip_id)
    frozen = "travellers and itinerary are frozen"
    for statement in (
        "UPDATE trip_segment SET title = 'Other hotel' WHERE trip_id = $1",
        "DELETE FROM trip_segment WHERE trip_id = $1",
    ):
        with pytest.raises(REFUSED, match=frozen):
            await tenant.execute(statement, trip_id)
    with pytest.raises(REFUSED, match=frozen):
        await tenant.execute(
            "UPDATE trip_traveller SET person_id = $2 WHERE trip_id = $1",
            trip_id,
            await person(tenant),
        )
    for table in ("trip_traveller", "trip_segment"):
        with pytest.raises(REFUSED, match="cannot move to another trip"):
            await tenant.execute(
                f"UPDATE {table} SET trip_id = $2 WHERE trip_id = $1", trip_id, draft
            )
    for change in ("mission_id = gen_random_uuid()", "requested_by = NULL"):
        with pytest.raises(REFUSED):
            await tenant.execute(f"UPDATE trip SET {change} WHERE id = $1", trip_id)


async def test_a_seeded_trip_takes_its_travellers_only_when_it_is_loaded(
    tenant: asyncpg.Connection,
) -> None:
    async with tenant.transaction():  # the seed: the trip and its travellers together
        seeded = await trip(tenant, None, status="APPROVED")
        await tenant.execute(ADD_TRAVELLER, seeded, await person(tenant))
        async with tenant.transaction():  # a savepoint (SQLAlchemy begin_nested)
            await tenant.execute(ADD_SEGMENT, seeded, 1)
    frozen = "travellers and itinerary are frozen"
    with pytest.raises(REFUSED, match=frozen):
        await tenant.execute("DELETE FROM trip_traveller WHERE trip_id = $1", seeded)
    with pytest.raises(REFUSED, match=frozen):
        await tenant.execute(ADD_SEGMENT, seeded, 2)
    pending = await trip(tenant, None, status="PENDING")
    with pytest.raises(REFUSED, match=frozen):
        await tenant.execute(ADD_TRAVELLER, pending, await person(tenant))


async def test_children_need_a_trip_in_the_same_tenant(
    db: DbUrls, tenant: asyncpg.Connection
) -> None:
    trip_id = await trip(tenant, await user(tenant))
    await set_tenant(tenant, await create_tenant(db, "Other"))
    with pytest.raises(REFUSED, match="no such trip"):
        await tenant.execute(ADD_SEGMENT, trip_id, 1)


async def test_a_submission_waits_for_a_traveller_being_added(
    db: DbUrls, tenant: asyncpg.Connection
) -> None:
    trip_id = await trip(tenant, await user(tenant))
    tenant_id = await tenant.fetchval("SELECT current_tenant_id()")
    other = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(other, tenant_id)
        async with tenant.transaction():
            await tenant.execute(ADD_TRAVELLER, trip_id, await person(tenant))
            await other.execute("SET lock_timeout = '200ms'")
            with pytest.raises(asyncpg.LockNotAvailableError):
                await submit(other, trip_id)
    finally:
        await other.close()


# --- approval ---------------------------------------------------------------------------


async def test_the_requester_cannot_approve_and_a_second_person_does(
    tenant: asyncpg.Connection,
) -> None:
    requester, security = await user(tenant), await user(tenant)
    trip_id = await trip(tenant, requester)
    await submit(tenant, trip_id)
    with pytest.raises(REFUSED, match="requester cannot approve"):
        await approve(tenant, trip_id, requester, "HIGH")
    await approve(tenant, trip_id, security, "HIGH")
    row = await status_of(tenant, trip_id)
    assert (row["approval_status"], row["approved_by"], row["approved_at"] is not None) == (
        "APPROVED",
        security,
        True,
    )
    with pytest.raises(REFUSED, match="approval cannot change"):
        await tenant.execute("UPDATE trip SET approved_risk_level = 'LOW' WHERE id = $1", trip_id)


async def test_only_a_low_trip_is_approved_without_an_approver(tenant: asyncpg.Connection) -> None:
    requester = await user(tenant)
    low = await trip(tenant, requester, risk="LOW")
    await tenant.execute(
        "UPDATE trip SET approval_status = 'APPROVED', submitted_at = now(), "
        "approved_risk_level = 'LOW' WHERE id = $1",
        low,
    )
    assert (await status_of(tenant, low))["approved_at"] is not None
    moderate = await trip(tenant, requester, risk="MODERATE")
    with pytest.raises(REFUSED, match="only a LOW trip is approved without an approver"):
        await approve(tenant, moderate, None, "MODERATE")
    pending = await trip(tenant, requester, risk="LOW")
    await submit(tenant, pending)
    with pytest.raises(REFUSED, match="only a LOW trip is approved without an approver"):
        await approve(tenant, pending, None, "LOW")  # a pending trip needs a second person


async def test_an_approval_is_written_only_by_approving(tenant: asyncpg.Connection) -> None:
    # Review F1: a pre-set approval must not turn a HIGH trip into a "LOW auto-approval".
    trip_id = await trip(tenant, await user(tenant), risk="HIGH")
    for change in ("approved_at = now()", "approved_risk_level = 'HIGH'"):
        with pytest.raises(REFUSED, match="recorded only by approving"):
            await tenant.execute(f"UPDATE trip SET {change} WHERE id = $1", trip_id)
    await submit(tenant, trip_id)
    with pytest.raises(REFUSED, match="recorded only by approving"):
        await tenant.execute("UPDATE trip SET approved_at = now() WHERE id = $1", trip_id)
    with pytest.raises(REFUSED, match="only a LOW trip is approved without an approver"):
        await approve(tenant, trip_id, None, "HIGH")


async def test_auto_approval_checks_the_trips_own_risk(tenant: asyncpg.Connection) -> None:
    # Review F3: approved_risk_level 'LOW' does not make a HIGH trip LOW.
    trip_id = await trip(tenant, await user(tenant), risk="HIGH")
    with pytest.raises(REFUSED, match="only a LOW trip is approved without an approver"):
        await approve(tenant, trip_id, None, "LOW")


async def test_an_approval_never_records_less_than_was_submitted(
    tenant: asyncpg.Connection,
) -> None:
    trip_id = await trip(tenant, await user(tenant), risk="CRITICAL")
    await submit(tenant, trip_id)
    with pytest.raises(REFUSED, match="lower risk than was submitted"):
        await approve(tenant, trip_id, await user(tenant), "LOW")
    other = await trip(tenant, await user(tenant), risk="MODERATE")
    await submit(tenant, other)
    await approve(tenant, other, await user(tenant), "HIGH")  # plan G-7: risk rose


async def test_a_draft_is_not_approved_by_a_second_person(tenant: asyncpg.Connection) -> None:
    trip_id = await trip(tenant, await user(tenant))
    with pytest.raises(REFUSED, match="only a pending trip is approved by a second person"):
        await approve(tenant, trip_id, await user(tenant), "HIGH")


async def test_an_approval_records_the_level(tenant: asyncpg.Connection) -> None:
    trip_id = await trip(tenant, await user(tenant))
    await submit(tenant, trip_id)
    with pytest.raises(REFUSED, match="records the risk level"):
        await tenant.execute(
            "UPDATE trip SET approval_status = 'APPROVED', approved_by = $2 WHERE id = $1",
            trip_id,
            await user(tenant),
        )


# --- status, rejection, checklist, deletion -----------------------------------------------


@pytest.mark.parametrize(
    ("start", "to"),
    [
        ("APPROVED", "PENDING"),
        ("APPROVED", "DRAFT"),
        ("CANCELLED", "DRAFT"),
        ("CANCELLED", "PENDING"),
        ("DRAFT", "REJECTED"),
    ],
)
async def test_status_only_moves_forward(tenant: asyncpg.Connection, start: str, to: str) -> None:
    trip_id = await trip(tenant, None, status=start)
    with pytest.raises(REFUSED, match="status cannot go"):
        await tenant.execute("UPDATE trip SET approval_status = $2 WHERE id = $1", trip_id, to)


async def test_a_rejection_returns_the_trip_to_draft(tenant: asyncpg.Connection) -> None:
    trip_id = await trip(tenant, await user(tenant))
    with pytest.raises(REFUSED, match="rejection reason is written only on rejection"):
        await tenant.execute("UPDATE trip SET rejection_reason = 'x' WHERE id = $1", trip_id)
    await submit(tenant, trip_id)
    await tenant.execute(
        "UPDATE trip SET approval_status = 'DRAFT', rejection_reason = 'Too risky' WHERE id = $1",
        trip_id,
    )
    await tenant.execute("UPDATE trip SET destination = 'Lyon' WHERE id = $1", trip_id)
    approved = await trip(tenant, None, status="APPROVED")
    with pytest.raises(REFUSED, match="rejection reason is written only on rejection"):
        await tenant.execute("UPDATE trip SET rejection_reason = 'x' WHERE id = $1", approved)


async def test_the_checklist_closes_once_approved(tenant: asyncpg.Connection) -> None:
    requester, security = await user(tenant), await user(tenant)
    trip_id = await trip(tenant, requester)
    tick = "UPDATE trip SET checklist = checklist || '{\"briefing\": true}' WHERE id = $1"
    await tenant.execute(tick, trip_id)
    await submit(tenant, trip_id)
    await tenant.execute(tick.replace("briefing", "insurance"), trip_id)  # still open
    await approve(tenant, trip_id, security, "HIGH")
    with pytest.raises(REFUSED, match="checklist is closed"):
        await tenant.execute(tick.replace("briefing", "contacts"), trip_id)
    cancelled = await trip(tenant, requester)
    await tenant.execute("UPDATE trip SET approval_status = 'CANCELLED' WHERE id = $1", cancelled)
    with pytest.raises(REFUSED, match="checklist is closed"):
        await tenant.execute(tick, cancelled)


async def test_trips_are_never_deleted_and_country_risk_is_read_only(
    tenant: asyncpg.Connection,
) -> None:
    await trip(tenant, await user(tenant))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("DELETE FROM trip")
    await tenant.execute(
        "INSERT INTO country_risk (tenant_id, country_code, level, security, unrest, health, "
        "transport, source) VALUES (current_tenant_id(), 'FR', 'MODERATE', 40, 55, 10, 45, "
        "'Riskline (simulated)')"
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("UPDATE country_risk SET level = 'LOW'")
