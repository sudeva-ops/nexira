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
    with pytest.raises(REFUSED, match="cannot be created with an approver"):
        await tenant.execute(
            "INSERT INTO trip (tenant_id, reference, origin, destination, starts_on, ends_on, "
            "approval_status, approved_by) VALUES (current_tenant_id(), 'TRP-X', 'A', 'B', "
            "current_date, current_date, 'APPROVED', $1)",
            await user(tenant),
        )


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
