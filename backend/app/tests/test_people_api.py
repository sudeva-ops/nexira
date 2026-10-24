"""Missions, people, sites and the operations summary (OPS-01, OPS-03, PPL-01..04)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.db import tenant_session
from app.modules.intel import exposure
from app.modules.intel.service import ensure_sources
from app.modules.people import location
from app.modules.people.service import (
    ObservationIn,
    PersonIn,
    SiteIn,
    add_observations,
    ensure_mission,
    load_persons,
    load_sites,
)
from app.modules.tenancy.service import ensure_reference_counter
from app.modules.travel.service import ensure_trip
from app.tests.auth_helpers import Idp
from app.tests.intel_helpers import EPICENTRE, KM_LAT, SOURCES, ingest, signal

NOW = datetime.now(UTC)


def north(km: float) -> tuple[float, float]:
    return (EPICENTRE[0] + km * KM_LAT, EPICENTRE[1])


@pytest.fixture
async def world(idp: Idp) -> dict[str, uuid.UUID]:
    """NBO with an embassy and hotel in the zone; CAI (MODERATE baseline) far away."""
    ids = {k: uuid.uuid4() for k in ("emb", "hotel", "cai_emb", "amina", "bram", "cit", "far")}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        nbo = await ensure_mission(
            session,
            code="NBO",
            city="Nairobi",
            country_code="KE",
            lat=EPICENTRE[0],
            lon=EPICENTRE[1],
        )
        cai = await ensure_mission(
            session,
            code="CAI",
            city="Cairo",
            country_code="EG",
            lat=30.04,
            lon=31.24,
            risk_level="MODERATE",
        )
        await load_sites(
            session,
            [
                SiteIn(ids["emb"], nbo, "EMBASSY", "Embassy Nairobi", *north(2), 88),
                SiteIn(ids["hotel"], nbo, "HOTEL", "Hotel Upper Hill", *north(1)),
                SiteIn(ids["cai_emb"], cai, "EMBASSY", "Embassy Cairo", 30.04, 31.24, 75),
            ],
        )
        await load_persons(
            session,
            [
                PersonIn(
                    ids["amina"], nbo, "DIPLOMAT", "Amina Okoro", role_title="First Secretary"
                ),
                PersonIn(ids["bram"], nbo, "DELEGATE", "Bram de Vries", role_title="Trade envoy"),
                PersonIn(ids["cit"], nbo, "CITIZEN", "Carla Mendes"),
                PersonIn(ids["far"], cai, "LOCAL_STAFF", "Omar Said", role_title="Driver"),
            ],
        )
        obs_time = NOW - timedelta(minutes=5)
        await add_observations(
            session,
            [
                ObservationIn(ids["amina"], "ACCESS_CONTROL", *north(2), obs_time, "Embassy"),
                ObservationIn(ids["bram"], "MANUAL", *north(1), obs_time, "Hotel"),
                ObservationIn(ids["cit"], "MANUAL", *north(3), obs_time, "Westlands"),
                ObservationIn(ids["far"], "MANUAL", 30.05, 31.25, obs_time, "Zamalek"),
            ],
        )
        await location.recompute(session, NOW)
        await ensure_trip(
            session,
            trip_id=uuid.uuid4(),
            reference="TRP-1",
            purpose="Trade",
            origin="HQ",
            destination="Nairobi",
            destination_country="KE",
            starts_on=NOW.date() - timedelta(days=1),
            ends_on=NOW.date() + timedelta(days=2),
            traveller_ids=[ids["bram"]],
        )
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await session.commit()
    now_signal = signal("DATAMINR", "High")
    now_signal.payload["occurred_at"] = NOW.isoformat()
    fused = (await ingest(idp.engine, idp.tenant_id, now_signal)).fused
    assert fused is not None
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await exposure.compute(session, fused.incident_id)
        await session.commit()
    await idp.user("viewer", [("VIEWER", None)])
    await idp.user("norole")
    return {**ids, "nbo": nbo, "cai": cai, "incident": fused.incident_id}


async def test_missions_show_display_risk_from_active_incidents(
    client: AsyncClient, idp: Idp, world: dict[str, uuid.UUID]
) -> None:
    missions = (await client.get("/api/missions", headers=idp.headers("viewer"))).json()
    by_code = {m["code"]: m for m in missions}
    nbo, cai = by_code["NBO"], by_code["CAI"]
    # G-22: the stored baseline stays LOW; the display risk follows the CRITICAL incident.
    assert (nbo["risk_level"], nbo["display_risk"], nbo["incident_id"]) == (
        "LOW",
        "CRITICAL",
        str(world["incident"]),
    )
    assert (nbo["personnel"], nbo["citizens"]) == (2, 1)
    assert (cai["risk_level"], cai["display_risk"], cai["incident_id"]) == (
        "MODERATE",
        "MODERATE",
        None,
    )


async def test_people_search_zone_and_paging(
    client: AsyncClient, idp: Idp, world: dict[str, uuid.UUID]
) -> None:
    h = idp.headers("viewer")
    page = (await client.get("/api/people", headers=h)).json()
    assert page["total"] == 4
    names = [p["full_name"] for p in page["items"]]
    assert names[-1] == "Omar Said"  # in-zone people first
    amina = next(p for p in page["items"] if p["full_name"] == "Amina Okoro")
    assert (amina["in_zone"], amina["location_source"], amina["mission_code"]) == (
        True,
        "ACCESS_CONTROL",
        "NBO",
    )
    assert amina["incident_reference"].endswith("-1042")
    assert "email" not in amina  # data minimisation
    assert "phone" not in amina

    async def names_for(**params: str) -> list[str]:
        response = await client.get("/api/people", params=params, headers=h)
        assert response.status_code == 200
        return [p["full_name"] for p in response.json()["items"]]

    assert await names_for(q="envoy") == ["Bram de Vries"]  # role title
    assert await names_for(q="zamalek") == ["Omar Said"]  # place, case-insensitive
    assert await names_for(q="CAI") == ["Omar Said"]  # mission code
    assert await names_for(q="100%") == []  # LIKE wildcards are literal
    assert await names_for(person_type="CITIZEN") == ["Carla Mendes"]
    assert sorted(await names_for(in_zone="false")) == ["Omar Said"]
    assert len(await names_for(mission="NBO")) == 3
    second = (await client.get("/api/people", params={"limit": 2, "offset": 2}, headers=h)).json()
    assert (second["total"], len(second["items"])) == (4, 2)
    past = (await client.get("/api/people", params={"offset": 50}, headers=h)).json()
    assert (past["total"], past["items"]) == (4, [])
    assert (
        await client.get("/api/people", params={"person_type": "ALIEN"}, headers=h)
    ).status_code == 422


async def test_sites_count_mission_property(
    client: AsyncClient, idp: Idp, world: dict[str, uuid.UUID]
) -> None:
    h = idp.headers("viewer")
    sites = (await client.get("/api/sites", headers=h)).json()
    assert (sites["total"], sites["mission_property"]) == (3, 2)  # D-23: no hotels
    first = sites["items"][0]
    assert first["in_zone"] is True
    emb = next(s for s in sites["items"] if s["name"] == "Embassy Nairobi")
    assert (emb["readiness_score"], emb["mission_code"]) == (88, "NBO")
    cairo = (await client.get("/api/sites", params={"q": "cairo"}, headers=h)).json()
    assert [s["name"] for s in cairo["items"]] == ["Embassy Cairo"]


async def test_operations_summary(
    client: AsyncClient, idp: Idp, world: dict[str, uuid.UUID]
) -> None:
    summary = (await client.get("/api/operations/summary", headers=idp.headers("viewer"))).json()
    assert summary == {
        "missions": 2,
        "missions_elevated": 2,  # NBO via the incident, CAI by baseline
        "missions_critical": 1,
        "personnel": 3,
        "personnel_located": 3,
        "avg_location_confidence": summary["avg_location_confidence"],
        "citizens": 1,
        "mission_sites": 2,
        "trips_active": 1,
        "travellers_active": 1,
        "signals_24h": 1,
        "incidents_active": 1,
        "highest_active_severity": "CRITICAL",
    }
    assert 0 < summary["avg_location_confidence"] <= 100


async def test_incident_exposure_has_map_coordinates(
    client: AsyncClient, idp: Idp, world: dict[str, uuid.UUID]
) -> None:
    detail = (
        await client.get(f"/api/incidents/{world['incident']}", headers=idp.headers("viewer"))
    ).json()
    by_name = {e["name"]: e for e in detail["exposure"]}
    assert round(by_name["Amina Okoro"]["lat"], 4) == round(north(2)[0], 4)
    assert by_name["Embassy Nairobi"]["lon"] == pytest.approx(EPICENTRE[1])
    assert (by_name["TRP-1"]["lat"], by_name["TRP-1"]["lon"]) == (None, None)


@pytest.mark.parametrize(
    "path", ["/api/missions", "/api/people", "/api/sites", "/api/operations/summary"]
)
async def test_reading_needs_a_role(
    client: AsyncClient, idp: Idp, world: dict[str, uuid.UUID], path: str
) -> None:
    assert (await client.get(path, headers=idp.headers("norole"))).status_code == 403
    assert (await client.get(path)).status_code == 401
