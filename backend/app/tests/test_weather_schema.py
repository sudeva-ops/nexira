"""Migration 0005 (PC-20; D-35), checked as nexira_api: current conditions per mission,
in range, in the mission's own tenant, keyed to that mission for good, never deleted."""

import uuid

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
PT = "'SRID=4326;POINT(120.98 14.6)'"
UPSERT = (
    "INSERT INTO weather_current (tenant_id, mission_id, observed_at, temperature_c, "
    "condition, wind_kph, gust_kph, rain_mm) VALUES (current_tenant_id(), $1, now(), $2, $3, "
    "$4, $5, $6) ON CONFLICT (tenant_id, mission_id) DO UPDATE SET observed_at = "
    "EXCLUDED.observed_at, temperature_c = EXCLUDED.temperature_c, condition = "
    "EXCLUDED.condition, wind_kph = EXCLUDED.wind_kph, gust_kph = EXCLUDED.gust_kph, "
    "rain_mm = EXCLUDED.rain_mm"
)


async def mission(conn: asyncpg.Connection, code: str = "MNL") -> uuid.UUID:
    mission_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
        f"VALUES ($1, current_tenant_id(), $2, 'Manila', 'PH', {PT})",
        mission_id,
        code,
    )
    return mission_id


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Weather"))
    return api


async def test_one_row_per_mission_kept_current(tenant: asyncpg.Connection) -> None:
    manila = await mission(tenant)
    await tenant.execute(UPSERT, manila, 29.5, "CLOUD", 20, 30, 0)
    await tenant.execute(UPSERT, manila, 27.0, "STORM", 110, 150, 60)
    rows = await tenant.fetch("SELECT condition, wind_kph, source FROM weather_current")
    assert [tuple(r) for r in rows] == [("STORM", 110, "xWeather (simulated)")]


@pytest.mark.parametrize(
    ("temperature", "condition", "wind", "gust", "rain"),
    [
        (61, "CLEAR", 10, 10, 0),  # too hot
        (-61, "CLEAR", 10, 10, 0),  # too cold
        (20, "TORNADO", 10, 10, 0),  # unknown condition
        (20, "CLEAR", 401, 401, 0),  # wind out of range
        (20, "CLEAR", 50, 40, 0),  # gusts below the wind
        (20, "RAIN", 10, 10, 1001),  # rain out of range
        (20, "RAIN", -1, 10, 0),  # negative wind
    ],
)
async def test_values_are_in_range(
    tenant: asyncpg.Connection,
    temperature: float,
    condition: str,
    wind: int,
    gust: int,
    rain: float,
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await tenant.execute(
            UPSERT, await mission(tenant), temperature, condition, wind, gust, rain
        )


async def test_a_row_needs_a_mission_in_its_own_tenant(
    db: DbUrls, tenant: asyncpg.Connection
) -> None:
    manila = await mission(tenant)
    await set_tenant(tenant, await create_tenant(db, "Other"))
    with pytest.raises(REFUSED, match="no such mission"):
        await tenant.execute(UPSERT, manila, 25, "CLEAR", 5, 5, 0)
    with pytest.raises(REFUSED, match="no such mission"):
        await tenant.execute(UPSERT, uuid.uuid4(), 25, "CLEAR", 5, 5, 0)


async def test_a_row_keeps_its_mission(tenant: asyncpg.Connection) -> None:
    manila, other = await mission(tenant), await mission(tenant, "CEB")
    await tenant.execute(UPSERT, manila, 25, "CLEAR", 5, 5, 0)
    with pytest.raises(REFUSED, match="keeps its mission"):
        await tenant.execute("UPDATE weather_current SET mission_id = $1", other)


async def test_rows_are_never_deleted_and_the_source_is_labelled(
    tenant: asyncpg.Connection,
) -> None:
    await tenant.execute(UPSERT, await mission(tenant), 25, "CLEAR", 5, 5, 0)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("DELETE FROM weather_current")
    with pytest.raises(asyncpg.CheckViolationError):
        await tenant.execute("UPDATE weather_current SET source = ''")
    await tenant.execute("UPDATE weather_current SET source = 'xWeather (simulated, scenario)'")
