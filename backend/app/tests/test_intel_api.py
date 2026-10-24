"""Signals and incidents API (Prompt 6)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.db import tenant_session
from app.modules.intel.service import ensure_sources
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.conftest import DbUrls
from app.tests.intel_helpers import SOURCES, ingest, intel_tenant, signal


@pytest.fixture
async def seeded(idp: Idp) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await session.commit()
    for e in (
        signal("DATAMINR", "High", place="Nairobi CBD"),
        signal(
            "FACTAL",
            "Moderate",
            at=timedelta(seconds=30),
            where=(48.86, 2.35),
            category="Strike",
            place="Paris",
        ),
        signal("MAX", "Level 4", at=timedelta(seconds=45), where=(-1.2990, 36.8150)),
        signal("RISKLINE", "Moderate", at=timedelta(seconds=100), where=(-1.2864, 36.8172)),
        signal("RISKLINE", "Extreme", at=timedelta(seconds=110)),  # unmapped: DISCARDED
    ):
        await ingest(idp.engine, idp.tenant_id, e)
    await idp.user("viewer", [("VIEWER", None)])
    await idp.user("norole")


async def test_incidents_list_and_detail(client: AsyncClient, idp: Idp, seeded: None) -> None:
    h = idp.headers("viewer")
    year = datetime.now(UTC).year
    listed = (await client.get("/api/incidents", headers=h)).json()
    assert [(i["reference"], i["severity"]) for i in listed] == [
        (f"INC-{year}-1042", "HIGH"),  # most severe first
        (f"INC-{year}-1043", "MODERATE"),
    ]
    nbo = listed[0]
    assert (nbo["confidence"], nbo["signal_count"], nbo["category"]) == (92, 3, "CIVIL_UNREST")
    assert nbo["sources"] == ["Dataminr", "MAX Security", "Riskline"]
    assert (round(nbo["lat"], 4), round(nbo["lon"], 4)) == (-1.2841, 36.8233)
    assert nbo["mission_id"] is None  # set by exposure (Prompt 7, D-06)

    detail = (await client.get(f"/api/incidents/{nbo['id']}", headers=h)).json()
    # D-11 step 4: the "Normalised (signal)" column reads HIGH, HIGH, MODERATE.
    assert [
        (s["source_name"], s["provider_severity"], s["norm_severity"]) for s in detail["signals"]
    ] == [
        ("Dataminr", "High", "HIGH"),
        ("MAX Security", "Level 4", "HIGH"),
        ("Riskline", "Moderate", "MODERATE"),
    ]
    assert [e["event_type"] for e in detail["timeline"]] == ["SIGNAL", "FUSED", "FUSED"]
    assert detail["timeline"][-1]["data"]["confidence"] == 92

    closed = (await client.get("/api/incidents?status=CLOSED", headers=h)).json()
    assert closed == []


async def test_signals_feed_and_status_filter(client: AsyncClient, idp: Idp, seeded: None) -> None:
    h = idp.headers("viewer")
    feed = (await client.get("/api/signals", headers=h)).json()
    assert len(feed) == 5
    assert feed[0]["norm_status"] == "DISCARDED"  # newest first
    fused = (await client.get("/api/signals?status=FUSED", headers=h)).json()
    assert len(fused) == 4
    assert {s["incident_reference"] for s in fused} == {
        f"INC-{datetime.now(UTC).year}-1042",
        f"INC-{datetime.now(UTC).year}-1043",
    }
    discarded = (await client.get("/api/signals?status=DISCARDED", headers=h)).json()
    assert [(s["source_code"], s["incident_id"]) for s in discarded] == [("RISKLINE", None)]
    bad = await client.get("/api/signals?status=WHATEVER", headers=h)
    assert bad.status_code == 422


async def test_reading_needs_a_role(client: AsyncClient, idp: Idp, seeded: None) -> None:
    for path in ("/api/signals", "/api/incidents", f"/api/incidents/{uuid.uuid4()}"):
        assert (await client.get(path, headers=idp.headers("norole"))).status_code == 403
        assert (await client.get(path)).status_code == 401


async def test_unknown_or_other_tenants_incident_is_404(
    client: AsyncClient, idp: Idp, db: DbUrls, seeded: None
) -> None:
    other = await intel_tenant(db, idp.engine)
    result = await ingest(idp.engine, other, signal("DATAMINR", "High"))
    assert result.fused is not None
    h = idp.headers("viewer")
    hidden = await client.get(f"/api/incidents/{result.fused.incident_id}", headers=h)
    assert hidden.status_code == 404
    assert (await client.get(f"/api/incidents/{uuid.uuid4()}", headers=h)).status_code == 404
    assert len((await client.get("/api/incidents", headers=h)).json()) == 2
