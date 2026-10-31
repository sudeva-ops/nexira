"""Migration 0009 (PC-26..29; D-39), checked as nexira_api: health advisories keep what
they are about, move only their level, guidance and status, and a closed one is final;
facilities, entry requirements and readiness counts are seeded reference data in their
own tenant, never changed or deleted; readiness holds counts only, each at most the
mission's staff (docs/plan-pilot-hl.md §2, §5, §12)."""

import json
import uuid
from typing import Any

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
CHECK = asyncpg.CheckViolationError
DENIED = asyncpg.InsufficientPrivilegeError
PT = "'SRID=4326;POINT(36.82 -1.29)'"


async def mission(conn: asyncpg.Connection, code: str = "NBO") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Nairobi', 'KE', {PT})",
        mission_id,
        code,
    )
    return mission_id


async def partner(conn: asyncpg.Connection) -> uuid.UUID:
    partner_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
        "VALUES (current_tenant_id(), 'KES', 'Kestrel', '{MEDICAL}', '{KE}', 15) RETURNING id"
    )
    return partner_id


async def advisory(conn: asyncpg.Connection, **change: Any) -> uuid.UUID:
    columns: dict[str, Any] = {
        "reference": f"HA-{uuid.uuid4().int % 10_000:04d}",
        "external_id": f"who-don:{uuid.uuid4().hex[:8]}",
        "topic": "Cholera",
        "topic_code": "CHOLERA",
        "countries": ["KE"],
        "region_label": "Kenya · Coast & Nairobi counties",
        "level": "MODERATE",
        "guidance": "Water-safety advice for staff.",
        "source": "WHO Disease Outbreak News (simulated)",
        **change,
    }
    names = ", ".join(["tenant_id", "published_at", *columns])
    values = ", ".join(
        ["current_tenant_id()", "now()", *(f"${n}" for n in range(1, len(columns) + 1))]
    )
    advisory_id: uuid.UUID = await conn.fetchval(
        f"INSERT INTO health_advisory ({names}) VALUES ({values}) RETURNING id",
        *columns.values(),
    )
    return advisory_id


async def readiness(conn: asyncpg.Connection, mission_id: uuid.UUID, **change: Any) -> None:
    columns: dict[str, Any] = {
        "staff": 14,
        "blood_type_on_file": 14,
        "insurance_active": 14,
        "trauma_kits": 6,
        "vaccines_offered": json.dumps({"CHOLERA": 9}),
        **change,
    }
    names = ", ".join(["tenant_id", "mission_id", "as_of", *columns])
    values = ", ".join(
        [
            "current_tenant_id()",
            "$1",
            "current_date",
            *(f"${n}" for n in range(2, len(columns) + 2)),
        ]
    )
    await conn.execute(
        f"INSERT INTO mission_health_readiness ({names}) VALUES ({values})",
        mission_id,
        *columns.values(),
    )


@pytest.fixture
async def api_tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Health"))
    return api


@pytest.fixture
async def owner(db: DbUrls, api_tenant: asyncpg.Connection) -> Any:
    """The table owner in the same tenant: the guards hold for it too (defence in depth)."""
    conn = await asyncpg.connect(db.owner_plain)
    await set_tenant(conn, await api_tenant.fetchval("SELECT current_tenant_id()"))
    try:
        yield conn
    finally:
        await conn.close()


# --- PC-26 · health advisories -----------------------------------------------------------------


async def test_a_newer_bulletin_moves_level_guidance_and_status_and_the_database_dates_it(
    api_tenant: asyncpg.Connection,
) -> None:
    conn = api_tenant
    advisory_id = await advisory(conn)
    first = await conn.fetchrow("SELECT * FROM health_advisory WHERE id = $1", advisory_id)
    assert first is not None
    assert first["status"] == "OPEN"
    await conn.execute(
        "UPDATE health_advisory SET level = 'HIGH', guidance = 'Bottled water only.', "
        "updated_at = '2000-01-01' WHERE id = $1",
        advisory_id,
    )
    second = await conn.fetchrow("SELECT * FROM health_advisory WHERE id = $1", advisory_id)
    assert second is not None
    assert (second["level"], second["guidance"]) == ("HIGH", "Bottled water only.")
    assert second["updated_at"] >= first["updated_at"]  # written by the guard, not the caller
    assert second["updated_at"].year > 2000
    await conn.execute("UPDATE health_advisory SET status = 'CLOSED' WHERE id = $1", advisory_id)


async def test_a_closed_advisory_is_final(
    api_tenant: asyncpg.Connection, owner: asyncpg.Connection
) -> None:
    advisory_id = await advisory(api_tenant)
    await api_tenant.execute(
        "UPDATE health_advisory SET status = 'CLOSED' WHERE id = $1", advisory_id
    )
    for change in ("status = 'OPEN'", "level = 'HIGH'", "guidance = 'x'"):
        for who in (api_tenant, owner):
            with pytest.raises(REFUSED, match="closed advisory is final"):
                await who.execute(f"UPDATE health_advisory SET {change} WHERE id = $1", advisory_id)


@pytest.mark.parametrize(
    "change",
    [
        "topic = 'Dengue'",
        "topic_code = 'DENGUE'",
        "countries = '{BD}'",
        "region_label = 'Elsewhere'",
        "source = 'Other'",
        "published_at = now() - interval '1 day'",
        "external_id = 'other'",
        "reference = 'HA-9999'",
    ],
)
async def test_what_an_advisory_is_about_is_fixed(
    api_tenant: asyncpg.Connection, owner: asyncpg.Connection, change: str
) -> None:
    advisory_id = await advisory(api_tenant)
    with pytest.raises(DENIED):  # not in the column grants
        await api_tenant.execute(f"UPDATE health_advisory SET {change} WHERE id = $1", advisory_id)
    with pytest.raises(REFUSED, match="what it is about is fixed"):
        await owner.execute(f"UPDATE health_advisory SET {change} WHERE id = $1", advisory_id)


async def test_advisories_are_never_deleted(
    api_tenant: asyncpg.Connection, owner: asyncpg.Connection
) -> None:
    advisory_id = await advisory(api_tenant)
    with pytest.raises(DENIED):
        await api_tenant.execute("DELETE FROM health_advisory WHERE id = $1", advisory_id)
    with pytest.raises(REFUSED, match="advisories are kept"):
        await owner.execute("DELETE FROM health_advisory WHERE id = $1", advisory_id)


async def test_an_advisory_starts_open_and_not_in_the_future(
    api_tenant: asyncpg.Connection,
) -> None:
    with pytest.raises(REFUSED, match="starts open"):
        await advisory(api_tenant, status="CLOSED")
    with pytest.raises(REFUSED, match="published in the future"):
        await api_tenant.execute(
            "INSERT INTO health_advisory (tenant_id, reference, external_id, topic, topic_code, "
            "countries, region_label, level, guidance, source, published_at) VALUES "
            "(current_tenant_id(), 'HA-0001', 'x', 'Cholera', 'CHOLERA', '{KE}', 'Kenya', 'LOW', "
            "'g', 's', now() + interval '1 day')"
        )


@pytest.mark.parametrize(
    "change",
    [
        {"level": "SEVERE"},
        {"topic_code": "cholera"},
        {"topic_code": "C"},
        {"countries": []},
        {"countries": ["ke"]},
        {"countries": ["KE", None]},
        {"reference": "HA-1"},
        {"guidance": ""},
        {"guidance": "x" * 501},
    ],
)
async def test_advisory_values_are_checked(
    api_tenant: asyncpg.Connection, change: dict[str, Any]
) -> None:
    with pytest.raises(CHECK):
        await advisory(api_tenant, **change)


async def test_one_advisory_per_feed_id(api_tenant: asyncpg.Connection) -> None:
    await advisory(api_tenant, external_id="who-don:cholera-ke")
    with pytest.raises(asyncpg.UniqueViolationError):
        await advisory(api_tenant, external_id="who-don:cholera-ke")


# --- PC-27 · medical facilities --------------------------------------------------------------


async def facility(conn: asyncpg.Connection, mission_id: uuid.UUID, **change: Any) -> None:
    columns: dict[str, Any] = {
        "mission_id": mission_id,
        "name": "Highland Private Hospital (sample)",
        "capabilities": ["EMERGENCY", "TRAUMA", "ICU"],
        "trauma_level": 1,
        "open_24_7": True,
        **change,
    }
    names = ", ".join(["tenant_id", "location", *columns])
    values = ", ".join(["current_tenant_id()", PT, *(f"${n}" for n in range(1, len(columns) + 1))])
    await conn.execute(
        f"INSERT INTO medical_facility ({names}) VALUES ({values})", *columns.values()
    )


async def test_a_facility_belongs_to_a_mission_and_partner_of_its_tenant(
    db: DbUrls, api_tenant: asyncpg.Connection
) -> None:
    conn = api_tenant
    own_mission, own_partner = await mission(conn), await partner(conn)
    await facility(conn, own_mission, vetted_by=own_partner)
    # Another tenant's mission and partner, inserted as the owner (foreign keys ignore RLS).
    other = await create_tenant(db, "Other health")
    owner = await asyncpg.connect(db.owner_plain)
    try:
        await set_tenant(owner, other)
        foreign_mission, foreign_partner = await mission(owner, "OTH"), await partner(owner)
    finally:
        await owner.close()
    with pytest.raises(REFUSED, match="no such mission"):
        await facility(conn, foreign_mission)
    with pytest.raises(REFUSED, match="no such partner"):
        await facility(conn, own_mission, vetted_by=foreign_partner)


@pytest.mark.parametrize(
    "change",
    [
        {"capabilities": ["SPA"]},
        {"capabilities": []},
        {"capabilities": ["EMERGENCY", None]},
        {"trauma_level": 4},
        {"name": ""},
    ],
)
async def test_facility_values_are_checked(
    api_tenant: asyncpg.Connection, change: dict[str, Any]
) -> None:
    with pytest.raises(CHECK):
        await facility(api_tenant, await mission(api_tenant), **change)


# --- PC-28 · entry requirements --------------------------------------------------------------


async def test_one_requirement_per_country_with_a_valid_code(
    api_tenant: asyncpg.Connection,
) -> None:
    insert = (
        "INSERT INTO country_health_requirement (tenant_id, country_code, mandatory, recommended) "
        "VALUES (current_tenant_id(), $1, "
        "'Yellow fever certificate if arriving from risk country', "
        "'Hep A · Typhoid · Cholera (optional)')"
    )
    await api_tenant.execute(insert, "KE")
    with pytest.raises(asyncpg.UniqueViolationError):
        await api_tenant.execute(insert, "KE")
    with pytest.raises(CHECK):
        await api_tenant.execute(insert, "ke")


# --- PC-29 · readiness counts ----------------------------------------------------------------


async def test_readiness_holds_counts_for_a_mission_of_its_tenant(
    db: DbUrls, api_tenant: asyncpg.Connection
) -> None:
    await readiness(api_tenant, await mission(api_tenant))
    other = await create_tenant(db, "Other readiness")
    owner = await asyncpg.connect(db.owner_plain)
    try:
        await set_tenant(owner, other)
        foreign = await mission(owner, "OTH")
    finally:
        await owner.close()
    with pytest.raises(REFUSED, match="no such mission"):
        await readiness(api_tenant, foreign)


@pytest.mark.parametrize(
    "change",
    [
        {"blood_type_on_file": 15},
        {"insurance_active": -1},
        {"trauma_kits": -1},
        {"staff": -1, "vaccines_offered": "{}"},  # the guard reads vaccines before CHECKs
    ],
)
async def test_readiness_counts_stay_within_the_staff(
    api_tenant: asyncpg.Connection, change: dict[str, Any]
) -> None:
    with pytest.raises(CHECK):
        await readiness(api_tenant, await mission(api_tenant), **change)


@pytest.mark.parametrize(
    "vaccines",
    [
        {"CHOLERA": 15},  # more than the 14 staff
        {"CHOLERA": -1},
        {"CHOLERA": 2.5},
        {"CHOLERA": "9"},
        {"cholera": 9},
        {f"TOPIC_{n}": 1 for n in range(21)},
        ["CHOLERA"],  # not an object
    ],
)
async def test_each_vaccine_count_is_a_whole_number_up_to_the_staff(
    api_tenant: asyncpg.Connection, owner: asyncpg.Connection, vaccines: object
) -> None:
    for who, code in ((api_tenant, "NBO"), (owner, "NBX")):
        with pytest.raises(REFUSED, match="health readiness"):
            await readiness(who, await mission(who, code), vaccines_offered=json.dumps(vaccines))


# --- grants: seeded reference data -------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    ["medical_facility", "country_health_requirement", "mission_health_readiness"],
)
async def test_seeded_tables_are_never_changed_or_deleted_by_the_app(
    api_tenant: asyncpg.Connection, table: str
) -> None:
    for stmt in (f"UPDATE {table} SET source = source", f"DELETE FROM {table}"):
        with pytest.raises(DENIED):
            await api_tenant.execute(stmt)
