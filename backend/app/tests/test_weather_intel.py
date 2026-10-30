"""Weather warnings as intelligence (WX-03, WX-04; plan-pilot-wx.md §3): category-sized
fusion distance and impact radius; unrest keeps 3 km / 5 km (D-23)."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.modules.intel import fusion
from app.modules.intel.models import Incident
from app.modules.intel.service import SourceIn, ensure_sources
from app.tests.conftest import DbUrls
from app.tests.intel_helpers import EPICENTRE, KM_LAT, ingest, intel_tenant, signal

GENERIC = {"Minor": "LOW", "Moderate": "MODERATE", "Major": "HIGH", "Severe": "CRITICAL"}
XWEATHER = SourceIn(
    "XWEATHER",
    "xWeather",
    Decimal("0.50"),
    GENERIC,
    {
        "Flood": "FLOOD",
        "Storm": "STORM",
        "Dust storm": "DUST_STORM",
        "Extreme heat": "EXTREME_HEAT",
    },
)
STORM_DM = SourceIn(
    "DATAMINR_WX",
    "Dataminr",
    Decimal("0.60"),
    {"Critical": "CRITICAL"},
    {"Tropical storm": "STORM"},
)


@pytest.fixture
async def tenant(db: DbUrls, api_engine: AsyncEngine) -> uuid.UUID:
    tenant_id = await intel_tenant(db, api_engine)
    async with tenant_session(tenant_id, api_engine) as session:
        await ensure_sources(session, [XWEATHER, STORM_DM])
        await session.commit()
    return tenant_id


async def incidents(engine: AsyncEngine, tenant: uuid.UUID) -> list[Incident]:
    async with tenant_session(tenant, engine) as session:
        return list(await session.scalars(select(Incident).order_by(Incident.reference)))


def north(km: float) -> tuple[float, float]:
    return (EPICENTRE[0] + km * KM_LAT, EPICENTRE[1])


def test_sizes_follow_the_category() -> None:
    """WX §28 Q4; every other category keeps the Phase 1 sizes."""
    sizes = {
        c: (fusion.fusion_radius_m(c), fusion.impact_radius_m(c)) for c in fusion.WEATHER_SIZES
    }
    assert sizes == {
        "STORM": (60_000, 60_000),
        "FLOOD": (25_000, 25_000),
        "DUST_STORM": (40_000, 40_000),
        "EXTREME_HEAT": (30_000, 30_000),
    }
    for category in ("CIVIL_UNREST", "TRANSPORT_STRIKE", "HEALTH_OUTBREAK"):
        assert (fusion.fusion_radius_m(category), fusion.impact_radius_m(category)) == (
            3_000,
            5_000,
        )


@pytest.mark.parametrize(
    ("category", "km", "joins", "radius"),
    [
        ("Storm", 59, True, 60_000),
        ("Storm", 61, False, 60_000),
        ("Flood", 24, True, 25_000),
        ("Flood", 26, False, 25_000),
        ("Dust storm", 39, True, 40_000),
        ("Dust storm", 41, False, 40_000),
        ("Extreme heat", 29, True, 30_000),
        ("Extreme heat", 31, False, 30_000),
    ],
)
async def test_weather_fuses_and_opens_at_its_own_size(
    api_engine: AsyncEngine, tenant: uuid.UUID, category: str, km: float, joins: bool, radius: int
) -> None:
    await ingest(api_engine, tenant, signal("XWEATHER", "Severe", category=category))
    second = await ingest(
        api_engine,
        tenant,
        signal("XWEATHER", "Major", at=timedelta(minutes=5), where=north(km), category=category),
    )
    assert second.fused is not None
    assert second.fused.created is not joins
    opened = await incidents(api_engine, tenant)
    assert [i.impact_radius_m for i in opened] == [radius] * (1 if joins else 2)


async def test_unrest_keeps_3_km_and_5_km(api_engine: AsyncEngine, tenant: uuid.UUID) -> None:
    await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    apart = await ingest(api_engine, tenant, signal("MAX", "Level 4", where=north(3.1)))
    assert apart.fused is not None
    assert apart.fused.created
    assert [i.impact_radius_m for i in await incidents(api_engine, tenant)] == [5_000, 5_000]


async def test_a_storm_does_not_fuse_with_unrest_or_a_flood(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    await ingest(api_engine, tenant, signal("XWEATHER", "Severe", category="Storm"))
    await ingest(api_engine, tenant, signal("XWEATHER", "Major", category="Flood"))
    await ingest(api_engine, tenant, signal("DATAMINR", "High"))
    assert sorted(i.category for i in await incidents(api_engine, tenant)) == [
        "CIVIL_UNREST",
        "FLOOD",
        "STORM",
    ]


async def test_two_providers_fuse_one_storm_with_both_reliabilities(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    """Plan §5: xWeather and Dataminr about the same storm, 16 km apart."""
    await ingest(api_engine, tenant, signal("XWEATHER", "Severe", category="Storm"))
    await ingest(
        api_engine,
        tenant,
        signal(
            "DATAMINR_WX",
            "Critical",
            at=timedelta(minutes=1),
            where=north(16),
            category="Tropical storm",
        ),
    )
    [storm] = await incidents(api_engine, tenant)
    assert (storm.category, storm.severity, storm.confidence, storm.title) == (
        "STORM",
        "CRITICAL",
        80,  # 1 - 0.5 * 0.4 (D-10)
        "Storm · Nairobi",
    )
