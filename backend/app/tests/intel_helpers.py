"""Shared test data for the intel tests: sources like the seed's, and RAW_SIGNAL events."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event
from app.modules.intel.service import Ingested, SourceIn, ensure_sources, ingest_signal
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.conftest import DbUrls, create_tenant

T0 = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
EPICENTRE = (-1.2841, 36.8233)
KM_LAT = 1 / 110.574  # degrees of latitude per km near the equator (WGS84)

SOURCES = [
    SourceIn(
        "DATAMINR",
        "Dataminr",
        Decimal("0.60"),
        {"High": "HIGH", "Critical": "CRITICAL", "Medium": "MODERATE"},
        {"Protest / Civil Unrest": "CIVIL_UNREST"},
    ),
    SourceIn(
        "MAX",
        "MAX Security",
        Decimal("0.55"),
        {"Level 3": "MODERATE", "Level 4": "HIGH"},
        {"Civil Unrest": "CIVIL_UNREST"},
    ),
    SourceIn(
        "RISKLINE",
        "Riskline",
        Decimal("0.55"),
        {"Moderate": "MODERATE", "High": "HIGH", "Bogus": "SEVERE"},
        {"Unrest": "CIVIL_UNREST"},
    ),
    SourceIn(
        "FACTAL",
        "Factal",
        Decimal("0.50"),
        {"Moderate": "MODERATE"},
        {"Strike": "TRANSPORT_STRIKE", "Unrest": "CIVIL_UNREST"},
    ),
    # D-09: seeded disabled and outside fusion.
    SourceIn(
        "OSINT",
        "NEXIRA OSINT",
        Decimal("0.50"),
        {"Major": "HIGH"},
        {"Unrest": "CIVIL_UNREST"},
        takes_part_in_fusion=False,
        is_enabled=False,
    ),
]
CATEGORY = {
    "DATAMINR": "Protest / Civil Unrest",
    "MAX": "Civil Unrest",
    "RISKLINE": "Unrest",
    "FACTAL": "Unrest",
    "OSINT": "Unrest",
}


def signal(
    source: str,
    severity: str,
    *,
    at: timedelta = timedelta(0),
    where: tuple[float, float] = EPICENTRE,
    category: str | None = None,
    external_id: str | None = None,
    place: str = "Nairobi",
) -> Event:
    lat, lon = where
    return Event(
        type="RAW_SIGNAL",
        tenant_id=uuid.UUID(int=0),  # replaced by ingest()
        payload={
            "source_code": source,
            "external_id": external_id or str(uuid.uuid4()),
            "title": f"{source} report",
            "provider_category": category or CATEGORY[source],
            "provider_severity": severity,
            "lat": lat,
            "lon": lon,
            "place_label": place,
            "occurred_at": (T0 + at).isoformat(),
        },
        source="test",
    )


async def intel_tenant(db: DbUrls, engine: AsyncEngine) -> uuid.UUID:
    """A new tenant with the test sources and the INC series at 1041 (next: 1042)."""
    tenant_id = await create_tenant(db)
    async with tenant_session(tenant_id, engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await session.commit()
    return tenant_id


async def ingest(engine: AsyncEngine, tenant: uuid.UUID, event: Event) -> Ingested:
    event = Event(type=event.type, tenant_id=tenant, payload=event.payload, source=event.source)
    async with tenant_session(tenant, engine) as session:
        result = await ingest_signal(session, event)
        await session.commit()
    return result
