"""Migration 0006 (PC-21, PC-22; D-36), checked as nexira_api: the partner directory, and
requests with their status table, frozen content, database-written timestamps, coverage
and the restricted-traveller rule (docs/plan-pilot-ast.md §2, §7, §10, G-5)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
PT = "'SRID=4326;POINT(36.8245 -1.2838)'"


@dataclass
class Ids:
    mission: uuid.UUID
    kes: uuid.UUID  # MEDICAL, covers KE
    sen: uuid.UUID  # SECURE_TRANSPORT, covers KE and FR
    idle: uuid.UUID  # inactive
    incident: uuid.UUID
    person: uuid.UUID


async def mission(conn: asyncpg.Connection, code: str, country: str) -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, $2, $3, {PT})",
        mission_id,
        code,
        country,
    )
    return mission_id


async def partner(
    conn: asyncpg.Connection,
    code: str,
    services: list[str],
    coverage: list[str],
    active: bool = True,
) -> uuid.UUID:
    partner_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes, is_active) "
        "VALUES (current_tenant_id(), $1, $1, $2, $3, 30, $4) RETURNING id",
        code,
        services,
        coverage,
        active,
    )
    return partner_id


async def world(conn: asyncpg.Connection) -> Ids:
    nbo = await mission(conn, "NBO", "KE")
    person, incident = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        "INSERT INTO person (id, tenant_id, mission_id, person_type, full_name) "
        "VALUES ($1, current_tenant_id(), $2, 'LOCAL_STAFF', 'Fictional Driver')",
        person,
        nbo,
    )
    await conn.execute(
        "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
        f"signal_severity, location) VALUES ($1, current_tenant_id(), 'INC-T', 'I', "
        f"'CIVIL_UNREST', 'HIGH', 'HIGH', {PT})",
        incident,
    )
    return Ids(
        mission=nbo,
        kes=await partner(conn, "KES", ["MEDICAL"], ["KE"]),
        sen=await partner(conn, "SEN", ["SECURE_TRANSPORT"], ["KE", "FR"]),
        idle=await partner(conn, "IDLE", ["MEDICAL"], ["KE"], active=False),
        incident=incident,
        person=person,
    )


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> tuple[asyncpg.Connection, Ids]:
    await set_tenant(api, await create_tenant(db, "Partners"))
    return api, await world(api)


_n = 0
LATER = datetime(2030, 1, 1, tzinfo=UTC)


async def request(
    conn: asyncpg.Connection,
    ids: Ids,
    *,
    partner_id: uuid.UUID | None = None,
    service: str = "MEDICAL",
    mission_id: uuid.UUID | None = None,
    located: bool = False,
    **extra: Any,
) -> uuid.UUID:
    """Insert a request; tenant_id is the session's, and the location (a PostGIS literal)
    goes into the SQL rather than through a parameter."""
    global _n
    _n += 1
    columns = {
        "reference": f"REQ-{_n}",
        "partner_id": partner_id or ids.kes,
        "service": service,
        "mission_id": mission_id or ids.mission,
        "created_by_type": "USER",
        "created_by": "duty.officer",
        **extra,
    }
    names = ", ".join(["tenant_id", *columns, *(["location"] if located else [])])
    values = ", ".join(
        ["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))]
        + ([PT] if located else [])
    )
    request_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO partner_request ({names}) VALUES ({values}) RETURNING id",
        *columns.values(),
    )
    return request_id


async def move(conn: asyncpg.Connection, request_id: uuid.UUID, status: str) -> None:
    await conn.execute("UPDATE partner_request SET status = $2 WHERE id = $1", request_id, status)


# --- the life of a request --------------------------------------------------------------------


async def test_a_request_goes_requested_accepted_en_route_completed(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    req = await request(
        conn, ids, requested_at=datetime(2000, 1, 1, tzinfo=UTC), incident_id=ids.incident
    )
    row = await conn.fetchrow("SELECT * FROM partner_request WHERE id = $1", req)
    assert row is not None
    assert row["status"] == "REQUESTED"
    assert row["requested_at"].year > 2000  # written by the database, not the caller
    assert (row["accepted_at"], row["completed_at"], row["eta"]) == (None, None, None)
    await conn.execute(
        "UPDATE partner_request SET status = 'ACCEPTED', eta = now() + interval '15 minutes' "
        "WHERE id = $1",
        req,
    )
    await move(conn, req, "EN_ROUTE")
    await conn.execute(
        "UPDATE partner_request SET eta = now() + interval '5 minutes' WHERE id = $1", req
    )
    await move(conn, req, "COMPLETED")
    row = await conn.fetchrow("SELECT * FROM partner_request WHERE id = $1", req)
    assert row is not None
    assert row["status"] == "COMPLETED"
    assert row["accepted_at"] is not None
    assert row["completed_at"] is not None


@pytest.mark.parametrize(
    ("path", "refused"),
    [
        ([], "EN_ROUTE"),
        ([], "COMPLETED"),
        (["ACCEPTED"], "COMPLETED"),
        (["ACCEPTED"], "DECLINED"),
        (["ACCEPTED"], "REQUESTED"),
        (["ACCEPTED", "EN_ROUTE"], "ACCEPTED"),
        (["ACCEPTED", "EN_ROUTE", "COMPLETED"], "CANCELLED"),
        (["DECLINED"], "ACCEPTED"),
        (["CANCELLED"], "REQUESTED"),
        (["ACCEPTED", "CANCELLED"], "EN_ROUTE"),
    ],
)
async def test_status_moves_only_forward(
    tenant: tuple[asyncpg.Connection, Ids], path: list[str], refused: str
) -> None:
    conn, ids = tenant
    req = await request(conn, ids)
    for status in path:
        await move(conn, req, status)
    with pytest.raises(REFUSED, match="cannot become"):
        await move(conn, req, refused)


@pytest.mark.parametrize("path", [["CANCELLED"], ["ACCEPTED", "CANCELLED"], ["DECLINED"]])
async def test_cancel_and_decline_end_a_request(
    tenant: tuple[asyncpg.Connection, Ids], path: list[str]
) -> None:
    conn, ids = tenant
    req = await request(conn, ids)
    for status in path:
        await move(conn, req, status)
    assert await conn.fetchval("SELECT status FROM partner_request WHERE id = $1", req) == path[-1]


@pytest.mark.parametrize(
    "start",
    [{"status": "ACCEPTED"}, {"eta": LATER}, {"accepted_at": LATER}],
)
async def test_a_request_starts_as_requested(
    tenant: tuple[asyncpg.Connection, Ids], start: dict[str, Any]
) -> None:
    conn, ids = tenant
    with pytest.raises(REFUSED, match="starts as REQUESTED"):
        await request(conn, ids, **start)


@pytest.mark.parametrize(
    "change",
    [
        "partner_id = gen_random_uuid()",
        "service = 'SECURE_TRANSPORT'",
        "mission_id = gen_random_uuid()",
        "incident_id = NULL",
        "person_id = NULL",
        "place_label = 'Elsewhere'",
        "location = 'SRID=4326;POINT(1 1)'",
        "note = 'changed'",
        "created_by = 'someone else'",
        "created_by_type = 'PLAYBOOK'",
        "requested_at = now() - interval '1 day'",
        "reference = 'REQ-999999'",
    ],
)
async def test_content_is_fixed_once_requested(
    tenant: tuple[asyncpg.Connection, Ids], change: str
) -> None:
    conn, ids = tenant
    req = await request(
        conn,
        ids,
        incident_id=ids.incident,
        person_id=ids.person,
        place_label="Haile Selassie Ave",
        note="Vehicle blocked",
        located=True,
    )
    with pytest.raises(REFUSED, match="content is fixed"):
        await conn.execute(f"UPDATE partner_request SET {change} WHERE id = $1", req)


async def test_a_missing_location_cannot_be_added_later(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    req = await request(conn, ids)
    with pytest.raises(REFUSED, match="content is fixed"):
        await conn.execute(f"UPDATE partner_request SET location = {PT} WHERE id = $1", req)


@pytest.mark.parametrize("column", ["accepted_at", "completed_at"])
async def test_timestamps_are_written_by_the_database(
    tenant: tuple[asyncpg.Connection, Ids], column: str
) -> None:
    conn, ids = tenant
    req = await request(conn, ids)
    await move(conn, req, "ACCEPTED")
    with pytest.raises(REFUSED, match="written by the database"):
        await conn.execute(f"UPDATE partner_request SET {column} = now() WHERE id = $1", req)


async def test_an_eta_only_once_accepted(tenant: tuple[asyncpg.Connection, Ids]) -> None:
    conn, ids = tenant
    eta = "UPDATE partner_request SET eta = now() + interval '1 hour' WHERE id = $1"
    req = await request(conn, ids)
    with pytest.raises(REFUSED, match="ETA is set only once accepted"):
        await conn.execute(eta, req)
    await move(conn, req, "ACCEPTED")
    await conn.execute(eta, req)
    await move(conn, req, "EN_ROUTE")
    await move(conn, req, "COMPLETED")
    with pytest.raises(REFUSED, match="ETA is set only once accepted"):
        await conn.execute(eta, req)


# --- who can be asked, about what --------------------------------------------------------------


async def test_the_partner_must_be_active_offer_the_service_and_cover_the_country(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    with pytest.raises(REFUSED, match="IDLE is not active"):
        await request(conn, ids, partner_id=ids.idle)
    with pytest.raises(REFUSED, match="KES does not offer SECURE_TRANSPORT"):
        await request(conn, ids, service="SECURE_TRANSPORT")
    paris = await mission(conn, "PAR", "FR")
    with pytest.raises(REFUSED, match="KES does not cover FR"):
        await request(conn, ids, mission_id=paris)
    await request(conn, ids, partner_id=ids.sen, service="SECURE_TRANSPORT", mission_id=paris)


async def test_every_reference_is_in_the_requests_tenant(
    db: DbUrls, tenant: tuple[asyncpg.Connection, Ids]
) -> None:
    """Foreign keys ignore RLS: another tenant's rows are refused by the guard."""
    conn, ids = tenant
    other = await create_tenant(db, "Partners B")
    await set_tenant(conn, other)
    mine = await world(conn)
    for column, value, message in [
        ("partner_id", ids.kes, "no such partner"),
        ("mission_id", ids.mission, "no such mission"),
        ("incident_id", ids.incident, "no such incident"),
        ("person_id", ids.person, "no such person"),
    ]:
        foreign: dict[str, Any] = {column: value}
        with pytest.raises(REFUSED, match=message):
            await request(conn, mine, **foreign)


async def test_a_restricted_traveller_cannot_be_named(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    """AS-08, G-5: not while the restricted trip will happen or is under way."""
    conn, ids = tenant

    async def trip(status: str, ends: str) -> None:
        trip_id = uuid.uuid4()
        # As the seed loads trips: the trip and its travellers in one transaction.
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO trip (id, tenant_id, reference, origin, destination, starts_on, "
                f"ends_on, approval_status, restricted) VALUES ($1, current_tenant_id(), $2, 'A', "
                f"'B', current_date - 10, {ends}, $3, true)",
                trip_id,
                f"TRP-{trip_id.hex[:6]}",
                status,
            )
            await conn.execute(
                "INSERT INTO trip_traveller (tenant_id, trip_id, person_id) "
                "VALUES (current_tenant_id(), $1, $2)",
                trip_id,
                ids.person,
            )

    await trip("APPROVED", "current_date - 1")  # over: no longer protected
    await request(conn, ids, person_id=ids.person)
    await trip("PENDING", "current_date + 3")
    with pytest.raises(REFUSED, match="restricted traveller"):
        await request(conn, ids, person_id=ids.person)


# --- grants and CHECKs ---------------------------------------------------------------------


async def test_nothing_is_deleted_and_partners_are_not_edited(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    await request(conn, ids)
    for statement in (
        "DELETE FROM partner_request",
        "DELETE FROM partner",
        "UPDATE partner SET is_active = false",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(statement)


@pytest.mark.parametrize(
    ("services", "coverage", "sla"),
    [
        ([], ["KE"], 30),  # no service
        (["MASSAGE"], ["KE"], 30),  # unknown service
        (["MEDICAL"], [], 30),  # no coverage
        (["MEDICAL"], ["ke"], 30),  # not a country code
        (["MEDICAL"], ["KE"], 0),  # SLA out of range
        (["MEDICAL"], ["KE"], 10081),
    ],
)
async def test_partner_values_are_checked(
    tenant: tuple[asyncpg.Connection, Ids], services: list[str], coverage: list[str], sla: int
) -> None:
    conn, _ = tenant
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
            "VALUES (current_tenant_id(), 'BAD', 'Bad', $1, $2, $3)",
            services,
            coverage,
            sla,
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"note": "x" * 501},
        {"place_label": "x" * 201},
        {"reference": "REQ-X"},
        {"service": "MASSAGE"},
    ],
)
async def test_request_values_are_checked(
    tenant: tuple[asyncpg.Connection, Ids], extra: dict[str, Any]
) -> None:
    conn, ids = tenant
    with pytest.raises((asyncpg.CheckViolationError, REFUSED)):
        await request(conn, ids, **extra)


async def test_references_are_unique_per_tenant(tenant: tuple[asyncpg.Connection, Ids]) -> None:
    conn, ids = tenant
    await request(conn, ids, reference="REQ-551")
    with pytest.raises(asyncpg.UniqueViolationError):
        await request(conn, ids, reference="REQ-551")
