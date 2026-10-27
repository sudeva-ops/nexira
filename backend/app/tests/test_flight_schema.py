"""Migration 0004 (PC-17, PC-18, PC-19; D-33), checked as nexira_api: a flight exists only
for a FLIGHT segment of an approved trip that is not restricted, matches its segment,
starts SCHEDULED, keeps its identity and schedule, follows the status table (plan G-8),
and its events are append-only; restricted is fixed once a trip leaves DRAFT."""

import uuid

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the triggers' RAISE EXCEPTION (P0001)
PT = "'SRID=4326;POINT(0 0)'"


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Flights"))
    for iata in ("AUH", "NBO", "MBA"):
        await api.execute(
            "INSERT INTO airport (tenant_id, iata, name, city, country_code, location) "
            f"VALUES (current_tenant_id(), $1::text, $1::text, $1::text, 'XX', {PT})",
            iata,
        )
    return api


async def trip_with_flight(
    conn: asyncpg.Connection,
    status: str = "APPROVED",
    restricted: bool = False,
    kind: str = "FLIGHT",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A seeded trip (no requester) and one segment, loaded in one transaction."""
    trip_id, segment_id = uuid.uuid4(), uuid.uuid4()
    flight = kind == "FLIGHT"
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO trip (id, tenant_id, reference, origin, destination, starts_on, ends_on, "
            "approval_status, restricted) VALUES ($1, current_tenant_id(), $2, 'AUH', 'NBO', "
            "current_date, current_date + 1, $3, $4)",
            trip_id,
            f"TRP-{trip_id.hex[:6]}",
            status,
            restricted,
        )
        await conn.execute(
            "INSERT INTO trip_segment (id, tenant_id, trip_id, seq, kind, title, starts_at, "
            "ends_at, flight_number, from_airport, to_airport) VALUES ($1, current_tenant_id(), "
            "$2, 1, $3, 'XW 451', now(), now() + interval '4 hours', $4, $5, $6)",
            segment_id,
            trip_id,
            kind,
            "XW 451" if flight else None,
            "AUH" if flight else None,
            "NBO" if flight else None,
        )
    return trip_id, segment_id


async def add_flight(
    conn: asyncpg.Connection,
    segment_id: uuid.UUID,
    number: str = "XW 451",
    to: str = "NBO",
    status: str = "SCHEDULED",
) -> uuid.UUID:
    flight_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO flight (id, tenant_id, trip_segment_id, flight_number, from_airport, "
        "to_airport, scheduled_dep, scheduled_arr, estimated_dep, estimated_arr, status) "
        "VALUES ($1, current_tenant_id(), $2, $3, 'AUH', $4, now(), now() + interval '4 hours', "
        "now(), now() + interval '4 hours', $5)",
        flight_id,
        segment_id,
        number,
        to,
        status,
    )
    return flight_id


async def set_status(
    conn: asyncpg.Connection, flight_id: uuid.UUID, status: str, diverted_to: str | None = None
) -> None:
    await conn.execute(
        "UPDATE flight SET status = $2, diverted_to = coalesce($3, diverted_to) WHERE id = $1",
        flight_id,
        status,
        diverted_to,
    )


# --- which flights may exist (AT-01, AT-05) -------------------------------------------


@pytest.mark.parametrize("status", ["DRAFT", "PENDING", "CANCELLED"])
async def test_only_an_approved_trip_is_tracked(tenant: asyncpg.Connection, status: str) -> None:
    _, segment = await trip_with_flight(tenant, status=status)
    with pytest.raises(REFUSED, match="only an approved trip is tracked"):
        await add_flight(tenant, segment)


async def test_a_restricted_trip_is_never_tracked(tenant: asyncpg.Connection) -> None:
    _, segment = await trip_with_flight(tenant, restricted=True)
    with pytest.raises(REFUSED, match="restricted trip is never tracked"):
        await add_flight(tenant, segment)
    assert await tenant.fetchval("SELECT count(*) FROM flight") == 0


async def test_a_flight_matches_its_segment_and_starts_scheduled(
    tenant: asyncpg.Connection,
) -> None:
    _, segment = await trip_with_flight(tenant)
    with pytest.raises(REFUSED, match="must match its segment"):
        await add_flight(tenant, segment, number="XW 999")
    with pytest.raises(REFUSED, match="must match its segment"):
        await add_flight(tenant, segment, to="MBA")
    with pytest.raises(REFUSED, match="starts SCHEDULED"):
        await add_flight(tenant, segment, status="AIRBORNE")
    _, stay = await trip_with_flight(tenant, kind="STAY")
    with pytest.raises(REFUSED, match="must match its segment"):
        await add_flight(tenant, stay)
    await add_flight(tenant, segment)
    with pytest.raises(asyncpg.UniqueViolationError):
        await add_flight(tenant, segment)  # one flight per segment


async def test_a_flight_needs_a_segment_in_its_own_tenant(
    db: DbUrls, tenant: asyncpg.Connection
) -> None:
    _, segment = await trip_with_flight(tenant)
    await set_tenant(tenant, await create_tenant(db, "Other"))
    with pytest.raises(REFUSED, match="no such segment"):
        await add_flight(tenant, segment)


# --- identity, status and events (plan G-8) --------------------------------------------


async def test_identity_and_schedule_never_change(tenant: asyncpg.Connection) -> None:
    flight = await add_flight(tenant, (await trip_with_flight(tenant))[1])
    for change in (
        "flight_number = 'XW 1'",
        "to_airport = 'MBA'",
        "scheduled_arr = scheduled_arr + interval '1 hour'",
        "source = 'SCENARIO'",
        "created_at = now() - interval '1 day'",
    ):
        with pytest.raises(REFUSED, match="identity and schedule cannot change"):
            await tenant.execute(f"UPDATE flight SET {change} WHERE id = $1", flight)
    # Estimates, position and speed are what the tracker updates.
    await tenant.execute(
        "UPDATE flight SET estimated_arr = estimated_arr + interval '40 minutes', "
        f"position = {PT}, altitude_ft = 37000, speed_kt = 450 WHERE id = $1",
        flight,
    )


async def test_status_follows_the_table(tenant: asyncpg.Connection) -> None:
    flight = await add_flight(tenant, (await trip_with_flight(tenant))[1])
    for refused in ("LANDED", "HOLDING", "DIVERTED"):
        with pytest.raises(REFUSED, match="status cannot go from SCHEDULED"):
            await set_status(tenant, flight, refused, "MBA" if refused == "DIVERTED" else None)
    for step in ("DELAYED", "AIRBORNE", "HOLDING", "AIRBORNE", "HOLDING"):
        await set_status(tenant, flight, step)
    with pytest.raises(REFUSED, match="status cannot go from HOLDING to CANCELLED"):
        await set_status(tenant, flight, "CANCELLED")  # never cancelled in the air
    await set_status(tenant, flight, "DIVERTED", "MBA")
    with pytest.raises(REFUSED, match="status cannot go from DIVERTED to AIRBORNE"):
        await set_status(tenant, flight, "AIRBORNE")
    await set_status(tenant, flight, "LANDED")
    with pytest.raises(REFUSED, match="a LANDED flight is final"):
        await tenant.execute("UPDATE flight SET speed_kt = 0 WHERE id = $1", flight)


async def test_a_cancelled_flight_is_final(tenant: asyncpg.Connection) -> None:
    flight = await add_flight(tenant, (await trip_with_flight(tenant))[1])
    await set_status(tenant, flight, "CANCELLED")
    with pytest.raises(REFUSED, match="a CANCELLED flight is final"):
        await set_status(tenant, flight, "AIRBORNE")


async def test_the_diversion_airport_is_set_only_by_diverting(tenant: asyncpg.Connection) -> None:
    flight = await add_flight(tenant, (await trip_with_flight(tenant))[1])
    await set_status(tenant, flight, "AIRBORNE")
    with pytest.raises(REFUSED, match="set only by diverting"):
        await tenant.execute("UPDATE flight SET diverted_to = 'MBA' WHERE id = $1", flight)
    with pytest.raises(asyncpg.CheckViolationError):
        await set_status(tenant, flight, "DIVERTED")  # without the airport
    await set_status(tenant, flight, "DIVERTED", "MBA")
    with pytest.raises(REFUSED, match="set only by diverting"):
        await tenant.execute("UPDATE flight SET diverted_to = 'AUH' WHERE id = $1", flight)


async def test_flights_are_never_deleted_and_events_are_append_only(
    db: DbUrls, tenant: asyncpg.Connection
) -> None:
    flight = await add_flight(tenant, (await trip_with_flight(tenant))[1])
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("DELETE FROM flight")
    await tenant.execute(
        "INSERT INTO flight_event (tenant_id, flight_id, event_type, occurred_at) "
        "VALUES (current_tenant_id(), $1, 'DEPARTED', '2020-01-01')",
        flight,
    )
    recorded = await tenant.fetchval(
        "SELECT occurred_at > now() - interval '1 minute' FROM flight_event"
    )
    assert recorded  # the database records the time
    for statement in ("UPDATE flight_event SET details = '{}'", "DELETE FROM flight_event"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await tenant.execute(statement)
    await set_tenant(tenant, await create_tenant(db, "Other"))
    with pytest.raises(REFUSED, match="no such flight"):
        await tenant.execute(
            "INSERT INTO flight_event (tenant_id, flight_id, event_type) "
            "VALUES (current_tenant_id(), $1, 'LANDED')",
            flight,
        )


# --- segments and restricted trips (PC-17) ----------------------------------------------


async def test_flight_fields_belong_to_flight_segments_with_known_airports(
    tenant: asyncpg.Connection,
) -> None:
    trip_id, _ = await trip_with_flight(tenant, status="DRAFT")
    insert = (
        "INSERT INTO trip_segment (tenant_id, trip_id, seq, kind, title, starts_at, ends_at, "
        "flight_number, from_airport, to_airport) VALUES (current_tenant_id(), $1, $2, $3, 'x', "
        "now(), now(), $4, $5, $6)"
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await tenant.execute(insert, trip_id, 2, "STAY", "XW 451", None, None)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await tenant.execute(insert, trip_id, 2, "FLIGHT", "XW 451", "AUH", "ZZZ")
    with pytest.raises(asyncpg.CheckViolationError):
        await tenant.execute(insert, trip_id, 2, "FLIGHT", "not a flight", "AUH", "NBO")
    await tenant.execute(insert, trip_id, 2, "FLIGHT", None, None, None)  # untracked flight


async def test_an_airport_belongs_to_its_tenant(db: DbUrls, tenant: asyncpg.Connection) -> None:
    await set_tenant(tenant, await create_tenant(db, "No airports"))
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await trip_with_flight(tenant, status="DRAFT")  # AUH and NBO are the other tenant's


async def test_restricted_is_fixed_once_the_trip_leaves_draft(tenant: asyncpg.Connection) -> None:
    trip_id, _ = await trip_with_flight(tenant, status="DRAFT")
    await tenant.execute("UPDATE trip SET restricted = true WHERE id = $1", trip_id)
    await tenant.execute("UPDATE trip SET restricted = false WHERE id = $1", trip_id)
    approved, _ = await trip_with_flight(tenant, restricted=True)
    with pytest.raises(REFUSED, match="frozen once it leaves DRAFT"):
        await tenant.execute("UPDATE trip SET restricted = false WHERE id = $1", approved)
