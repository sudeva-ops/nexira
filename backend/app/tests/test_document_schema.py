"""Migration 0007 (PC-23; D-37), checked as nexira_api: travel documents with their
forward-only renewal, who did each step written only on that step, database-written
times, a later date only when renewed, and holders limited to staff and dependants
(docs/plan-pilot-dx.md §6, G-1)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
PT = "'SRID=4326;POINT(36.8245 -1.2838)'"
VALID = date(2027, 1, 31)


@dataclass
class Ids:
    staff: uuid.UUID
    dependant: uuid.UUID
    citizen: uuid.UUID
    delegate: uuid.UUID


async def person(conn: asyncpg.Connection, mission: uuid.UUID, person_type: str) -> uuid.UUID:
    person_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO person (id, tenant_id, mission_id, person_type, full_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, 'Fictional Person')",
        person_id,
        mission,
        person_type,
    )
    return person_id


async def world(conn: asyncpg.Connection) -> Ids:
    mission = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), 'NBO', 'Nairobi', 'KE', {PT})",
        mission,
    )
    return Ids(
        staff=await person(conn, mission, "DIPLOMAT"),
        dependant=await person(conn, mission, "DEPENDANT"),
        citizen=await person(conn, mission, "CITIZEN"),
        delegate=await person(conn, mission, "DELEGATE"),
    )


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> tuple[asyncpg.Connection, Ids]:
    await set_tenant(api, await create_tenant(db, "Documents"))
    return api, await world(api)


@pytest.fixture
async def owner(db: DbUrls, tenant: tuple[asyncpg.Connection, Ids]) -> Any:
    """The table owner in the same tenant: it may UPDATE any column, so the guard's own
    rules are tested behind the column grant (defence in depth)."""
    conn = await asyncpg.connect(db.owner_plain)
    await set_tenant(conn, await tenant[0].fetchval("SELECT current_tenant_id()"))
    try:
        yield conn
    finally:
        await conn.close()


async def document(
    conn: asyncpg.Connection, holder: uuid.UUID, doc_type: str = "DIPLOMATIC_PASSPORT", **extra: Any
) -> uuid.UUID:
    columns = {
        "person_id": holder,
        "doc_type": doc_type,
        "issuing_country": "JP",
        "valid_until": VALID,
        **extra,
    }
    names = ", ".join(["tenant_id", *columns])
    values = ", ".join(["current_tenant_id()", *(f"${n}" for n in range(1, len(columns) + 1))])
    doc_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO travel_document ({names}) VALUES ({values}) RETURNING id", *columns.values()
    )
    return doc_id


async def step(conn: asyncpg.Connection, doc: uuid.UUID, status: str, **extra: Any) -> None:
    """A renewal step with who did it (and, when renewed, the new date)."""
    who = {
        "REQUESTED": "renewal_requested_by",
        "IN_PROGRESS": "renewal_started_by",
        "RENEWED": "renewed_by",
    }
    values: dict[str, Any] = {"renewal_status": status, who[status]: "consular.officer"}
    if status == "RENEWED":
        values["valid_until"] = date(2037, 1, 31)
    values.update(extra)
    sets = ", ".join(f"{column} = ${n}" for n, column in enumerate(values, start=2))
    await conn.execute(f"UPDATE travel_document SET {sets} WHERE id = $1", doc, *values.values())


async def row(conn: asyncpg.Connection, doc: uuid.UUID) -> asyncpg.Record:
    record = await conn.fetchrow("SELECT * FROM travel_document WHERE id = $1", doc)
    assert record is not None
    return record


# --- the life of a renewal --------------------------------------------------------------------


async def test_a_renewal_goes_requested_in_progress_renewed(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    assert (await row(conn, doc))["renewal_status"] == "NONE"
    await step(conn, doc, "REQUESTED")
    await step(conn, doc, "IN_PROGRESS", renewal_started_by="hom.nairobi")
    await step(conn, doc, "RENEWED")
    r = await row(conn, doc)
    assert r["renewal_status"] == "RENEWED"
    assert (r["renewal_requested_by"], r["renewal_started_by"], r["renewed_by"]) == (
        "consular.officer",
        "hom.nairobi",
        "consular.officer",
    )
    assert r["renewal_requested_at"] <= r["renewal_started_at"] <= r["renewed_at"]
    assert r["valid_until"] == date(2037, 1, 31)


async def test_a_renewal_may_start_without_a_request(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.dependant, "PASSPORT")
    await step(conn, doc, "IN_PROGRESS")
    r = await row(conn, doc)
    assert (r["renewal_status"], r["renewal_requested_at"]) == ("IN_PROGRESS", None)
    assert r["renewal_started_at"] is not None


@pytest.mark.parametrize(
    ("path", "refused"),
    [
        ([], "RENEWED"),  # NONE -> RENEWED skips the renewal
        (["REQUESTED"], "RENEWED"),
        (["REQUESTED", "IN_PROGRESS"], "REQUESTED"),  # never back
        (["IN_PROGRESS", "RENEWED"], "IN_PROGRESS"),  # RENEWED is final (plan G-3)
        (["REQUESTED"], "NONE"),
        (["IN_PROGRESS"], "REQUESTED"),
        (["IN_PROGRESS"], "NONE"),
        (["IN_PROGRESS", "RENEWED"], "NONE"),
    ],
)
async def test_a_renewal_moves_only_forward(
    tenant: tuple[asyncpg.Connection, Ids], owner: asyncpg.Connection, path: list[str], refused: str
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    for status in path:
        await step(conn, doc, status)
    with pytest.raises(REFUSED, match="cannot become"):
        await owner.execute(
            "UPDATE travel_document SET renewal_status = $2 WHERE id = $1", doc, refused
        )


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("REQUESTED", "say who requested"),
        ("IN_PROGRESS", "say who started"),
    ],
)
async def test_each_step_says_who_did_it(
    tenant: tuple[asyncpg.Connection, Ids], status: str, message: str
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(REFUSED, match=message):
        await conn.execute(
            "UPDATE travel_document SET renewal_status = $2 WHERE id = $1", doc, status
        )


async def test_renewing_says_who_and_gives_a_later_date(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    await step(conn, doc, "IN_PROGRESS")
    with pytest.raises(REFUSED, match="say who renewed"):
        await conn.execute(
            "UPDATE travel_document SET renewal_status = 'RENEWED', valid_until = '2037-01-31' "
            "WHERE id = $1",
            doc,
        )
    for until in (VALID, date(2026, 1, 1)):  # the same date, or an earlier one
        with pytest.raises(REFUSED, match="a later date"):
            await step(conn, doc, "RENEWED", valid_until=until)


@pytest.mark.parametrize(
    ("column", "status", "message"),
    [
        ("renewal_requested_by", "IN_PROGRESS", "who requested"),
        ("renewed_by", "IN_PROGRESS", "who renewed"),
        ("renewal_started_by", "REQUESTED", "who started"),
    ],
)
async def test_who_is_written_only_on_its_own_step(
    tenant: tuple[asyncpg.Connection, Ids], column: str, status: str, message: str
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(REFUSED, match=message):
        await step(conn, doc, status, **{column: "someone.else"})


async def test_who_did_a_step_is_frozen_afterwards(tenant: tuple[asyncpg.Connection, Ids]) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    await step(conn, doc, "REQUESTED")
    with pytest.raises(REFUSED, match="who requested"):
        await conn.execute(
            "UPDATE travel_document SET renewal_requested_by = 'x' WHERE id = $1", doc
        )
    await step(conn, doc, "IN_PROGRESS")
    with pytest.raises(REFUSED, match="who started"):
        await conn.execute("UPDATE travel_document SET renewal_started_by = 'x' WHERE id = $1", doc)
    await step(conn, doc, "RENEWED")
    with pytest.raises(REFUSED, match="who renewed"):
        await conn.execute("UPDATE travel_document SET renewed_by = 'x' WHERE id = $1", doc)


@pytest.mark.parametrize("path", [[], ["REQUESTED"], ["IN_PROGRESS"], ["IN_PROGRESS", "RENEWED"]])
async def test_the_date_changes_only_when_renewed(
    tenant: tuple[asyncpg.Connection, Ids], path: list[str]
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    for status in path:
        await step(conn, doc, status)
    with pytest.raises(REFUSED, match="changes only when renewed"):
        await conn.execute(
            "UPDATE travel_document SET valid_until = '2040-01-01' WHERE id = $1", doc
        )


# --- what the app may touch -------------------------------------------------------------------

FIXED = [
    "id = gen_random_uuid()",
    "tenant_id = gen_random_uuid()",
    "person_id = gen_random_uuid()",
    "doc_type = 'VISA'",
    "issuing_country = 'FR'",
    "created_at = now() - interval '1 day'",
]
TIMES = ["renewal_requested_at = now()", "renewal_started_at = now()", "renewed_at = now()"]


@pytest.mark.parametrize("change", [*FIXED, *TIMES, "updated_at = now()"])
async def test_the_app_may_change_only_the_renewal(
    tenant: tuple[asyncpg.Connection, Ids], change: str
) -> None:
    """GRANT UPDATE on the renewal columns only: anything else is refused by privilege."""
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute(f"UPDATE travel_document SET {change} WHERE id = $1", doc)


@pytest.mark.parametrize("change", FIXED[:1] + FIXED[2:])  # tenant_id: RLS refuses it first
async def test_the_document_is_fixed_even_for_the_owner(
    tenant: tuple[asyncpg.Connection, Ids], owner: asyncpg.Connection, change: str
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(REFUSED, match="document itself is fixed"):
        await owner.execute(f"UPDATE travel_document SET {change} WHERE id = $1", doc)


@pytest.mark.parametrize("change", TIMES)
async def test_renewal_times_are_the_databases_even_for_the_owner(
    tenant: tuple[asyncpg.Connection, Ids], owner: asyncpg.Connection, change: str
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(REFUSED, match="written by the database"):
        await owner.execute(f"UPDATE travel_document SET {change} WHERE id = $1", doc)


async def test_created_and_updated_at_are_the_databases(
    tenant: tuple[asyncpg.Connection, Ids], owner: asyncpg.Connection
) -> None:
    conn, ids = tenant
    old = datetime(2000, 1, 1, tzinfo=UTC)
    doc = await document(conn, ids.staff, created_at=old, updated_at=old)
    r = await row(conn, doc)
    assert r["created_at"].year > 2000  # each on its own (review of Prompt 49, M1)
    assert r["updated_at"].year > 2000
    await owner.execute("UPDATE travel_document SET updated_at = '2000-01-01' WHERE id = $1", doc)
    assert (await row(conn, doc))["updated_at"].year > 2000


async def test_nothing_is_deleted(tenant: tuple[asyncpg.Connection, Ids]) -> None:
    conn, ids = tenant
    await document(conn, ids.staff)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await conn.execute("DELETE FROM travel_document")


# --- new documents ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"renewal_status": "REQUESTED", "renewal_requested_by": "x"},
        {"renewal_requested_by": "x"},
        {"renewal_started_by": "x"},
        {"renewed_by": "x"},
        # Forged times on a new document (review of Prompt 49, M2).
        {"renewal_requested_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"renewal_started_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"renewed_at": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
)
async def test_a_document_starts_with_no_renewal(
    tenant: tuple[asyncpg.Connection, Ids], extra: dict[str, Any]
) -> None:
    conn, ids = tenant
    with pytest.raises(REFUSED, match="starts with no renewal"):
        await document(conn, ids.staff, **extra)


@pytest.mark.parametrize("holder", ["citizen", "delegate"])
async def test_citizens_and_delegates_have_no_documents_here(
    tenant: tuple[asyncpg.Connection, Ids], holder: str
) -> None:
    conn, ids = tenant
    with pytest.raises(REFUSED, match="has no documents here"):
        await document(conn, getattr(ids, holder), "PASSPORT")


async def test_the_holder_is_in_the_documents_tenant(
    db: DbUrls, tenant: tuple[asyncpg.Connection, Ids]
) -> None:
    """Foreign keys ignore RLS: a person of another tenant is refused by the guard."""
    conn, _ = tenant
    other = await create_tenant(db, "Other")
    home = await conn.fetchval("SELECT current_tenant_id()")
    await set_tenant(conn, other)
    foreign = (await world(conn)).staff
    await set_tenant(conn, home)
    with pytest.raises(REFUSED, match="no such person"):
        await document(conn, foreign)


async def test_other_tenants_documents_are_invisible(
    db: DbUrls, tenant: tuple[asyncpg.Connection, Ids]
) -> None:
    conn, ids = tenant
    await document(conn, ids.staff)
    await set_tenant(conn, await create_tenant(db, "Elsewhere"))
    assert await conn.fetchval("SELECT count(*) FROM travel_document") == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"doc_type": "DRIVING_LICENCE"},
        {"issuing_country": "jp"},
        {"issuing_country": "J1"},
    ],
)
async def test_document_values_are_checked(
    tenant: tuple[asyncpg.Connection, Ids], extra: dict[str, str]
) -> None:
    conn, ids = tenant
    with pytest.raises(asyncpg.CheckViolationError):
        await document(conn, ids.staff, **extra)


@pytest.mark.parametrize(
    ("path", "status", "column"),
    [
        (["REQUESTED"], "IN_PROGRESS", "renewal_requested_by"),
        (["IN_PROGRESS"], "RENEWED", "renewal_started_by"),
        ([], "IN_PROGRESS", "renewal_requested_by"),
        ([], "REQUESTED", "renewed_by"),
    ],
)
async def test_another_steps_who_cannot_change_during_a_step(
    tenant: tuple[asyncpg.Connection, Ids], path: list[str], status: str, column: str
) -> None:
    """Review of Prompt 49, L5: a step writes its own "by" and nobody else's."""
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    for done in path:
        await step(conn, doc, done)
    with pytest.raises(REFUSED, match="recorded only on that step"):
        await step(conn, doc, status, **{column: "someone.else"})


async def test_starting_a_renewal_does_not_move_the_date(
    tenant: tuple[asyncpg.Connection, Ids],
) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(REFUSED, match="changes only when renewed"):
        await step(conn, doc, "IN_PROGRESS", valid_until=date(2040, 1, 1))


@pytest.mark.parametrize("until", ["infinity", "-infinity", "1899-12-31", "2201-01-01"])
async def test_a_document_has_a_real_date(
    tenant: tuple[asyncpg.Connection, Ids], until: str
) -> None:
    """Review of Prompt 49, M3: 'infinity' would never expire, nor ever be renewed."""
    conn, ids = tenant
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "INSERT INTO travel_document (tenant_id, person_id, doc_type, issuing_country, "
            f"valid_until) VALUES (current_tenant_id(), $1, 'PASSPORT', 'JP', '{until}')",
            ids.staff,
        )
    doc = await document(conn, ids.staff)
    await step(conn, doc, "IN_PROGRESS")
    # An earlier date is refused by the guard first (a later date); either way, refused.
    with pytest.raises((asyncpg.CheckViolationError, REFUSED)):
        await conn.execute(
            "UPDATE travel_document SET renewal_status = 'RENEWED', renewed_by = 'x', "
            f"valid_until = '{until}' WHERE id = $1",
            doc,
        )


async def test_who_is_never_empty(tenant: tuple[asyncpg.Connection, Ids]) -> None:
    conn, ids = tenant
    doc = await document(conn, ids.staff)
    with pytest.raises(asyncpg.CheckViolationError):
        await step(conn, doc, "REQUESTED", renewal_requested_by="")
