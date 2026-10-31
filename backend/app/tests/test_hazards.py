"""Natural hazards (HZ-01..07, HZ-10; D-38; docs/plan-pilot-hz.md): severity and size per
hazard, the newest signal's details, nearest mission, arming / start now / disarm through
the playbook service, armed runs started by the worker on the hazard clock (with the demo
clock, G-9), the ARM_PLAYBOOK proposal and its executor, and GET /api/hazards."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.agents.agents.response_planner import ResponsePlanner
from app.modules.agents.runner import run_agents
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.audit.models import AuditLog
from app.modules.hazards import clock, consumer
from app.modules.hazards import service as hazard_service
from app.modules.intel import exposure, hazards
from app.modules.intel.models import Incident
from app.modules.intel.normalise import normalise
from app.modules.intel.service import Ingested, SourceIn, ensure_sources, ingest_signal
from app.modules.playbooks import service as playbook_service
from app.modules.playbooks.models import PlaybookRun
from app.modules.playbooks.service import StepIn, ensure_playbook
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.conftest import create_tenant
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import KM_LAT

GENERIC = {"Minor": "LOW", "Moderate": "MODERATE", "Major": "HIGH", "Severe": "CRITICAL"}
SOURCES = [
    SourceIn(
        "XWEATHER",
        "xWeather",
        Decimal("0.50"),
        GENERIC,
        {"Flood": "FLOOD", "Tropical cyclone": "TROPICAL_CYCLONE", "Wildfire": "WILDFIRE"},
    ),
    SourceIn("SEISMIC", "Seismic network", Decimal("0.70"), {}, {"Earthquake": "EARTHQUAKE"}),
    SourceIn("AIRQ", "Air-quality network", Decimal("0.60"), {}, {"Air quality": "AIR_QUALITY"}),
]
CATEGORY = {"SEISMIC": "Earthquake", "AIRQ": "Air quality"}
DHAKA = (23.81, 90.41)
ANKARA = (39.93, 32.86)
STEPS = [StepIn(1, "Confirm the warning", "TASK", {"summary": "confirmed"})]


def south(origin: tuple[float, float], km: float) -> tuple[float, float]:
    return (origin[0] - km * KM_LAT, origin[1])


def north(origin: tuple[float, float], km: float) -> tuple[float, float]:
    return (origin[0] + km * KM_LAT, origin[1])


def landfall_point() -> tuple[float, float]:
    return south(DHAKA, 110)


def hz(
    source: str,
    where: tuple[float, float],
    *,
    category: str | None = None,
    hazard: dict[str, Any] | None = None,
    severity: str = "Moderate",
    at: timedelta = timedelta(0),
    place: str = "Dhaka",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_code": source,
        "external_id": str(uuid.uuid4()),
        "title": f"{source} hazard",
        "provider_category": category or CATEGORY[source],
        "provider_severity": severity,
        "lat": where[0],
        "lon": where[1],
        "place_label": place,
        "occurred_at": (datetime.now(UTC) + at).isoformat(),
    }
    if hazard is not None:
        payload["hazard"] = hazard
    return payload


def cyclone(category: int, landfall_in_h: float, **extra: Any) -> dict[str, Any]:
    return hz(
        "XWEATHER",
        landfall_point(),
        category="Tropical cyclone",
        hazard={"cyclone_category": category, "landfall_in_h": landfall_in_h, "track_km": 110},
        **extra,
    )


# --- rules (no database) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("magnitude", "severity", "radius"),
    [
        (4.9, "LOW", 50_000),
        (5.2, "LOW", 100_000),
        (5.5, "MODERATE", 100_000),
        (6.4, "MODERATE", 200_000),
        (6.5, "HIGH", 200_000),
        (7.4, "HIGH", 400_000),
        (7.5, "CRITICAL", 400_000),
    ],
)
def test_an_earthquake_is_sized_by_its_magnitude(
    magnitude: float, severity: str, radius: int
) -> None:
    payload = {"hazard": {"magnitude": magnitude}}
    assert hazards.severity("EARTHQUAKE", payload) == severity
    assert hazards.impact_radius_m("EARTHQUAKE", payload) == radius
    assert hazards.fusion_radius_m("EARTHQUAKE", payload) == radius


@pytest.mark.parametrize(
    ("category", "hazard", "severity"),
    [
        ("TROPICAL_CYCLONE", {"cyclone_category": 1, "landfall_in_h": 60}, "MODERATE"),
        ("TROPICAL_CYCLONE", {"cyclone_category": 2, "landfall_in_h": 60}, "HIGH"),
        ("TROPICAL_CYCLONE", {"cyclone_category": 3, "landfall_in_h": 60}, "CRITICAL"),
        ("AIR_QUALITY", {"aqi": 201}, "MODERATE"),
        ("AIR_QUALITY", {"aqi": 300}, "MODERATE"),
        ("AIR_QUALITY", {"aqi": 301}, "HIGH"),
        ("AIR_QUALITY", {"aqi": 400}, "HIGH"),
        ("AIR_QUALITY", {"aqi": 401}, "CRITICAL"),
        ("WILDFIRE", None, "MODERATE"),
    ],
)
def test_severity_comes_from_the_measure(
    category: str, hazard: dict[str, Any] | None, severity: str
) -> None:
    assert hazards.severity(category, {"hazard": hazard} if hazard else {}) == severity


def test_sizes_and_windows_per_hazard() -> None:
    """§43 Q3 and G-3; Weather and unrest unchanged."""
    sizes = {
        c: (hazards.impact_radius_m(c), hazards.fusion_radius_m(c), hazards.fusion_window_min(c))
        for c in ("TROPICAL_CYCLONE", "AIR_QUALITY", "WILDFIRE", "STORM", "FLOOD", "CIVIL_UNREST")
    }
    assert sizes == {
        "TROPICAL_CYCLONE": (150_000, 150_000, 48 * 60),
        "AIR_QUALITY": (30_000, 30_000, 24 * 60),
        "WILDFIRE": (20_000, 20_000, 24 * 60),
        "STORM": (60_000, 60_000, 60),
        "FLOOD": (25_000, 25_000, 60),
        "CIVIL_UNREST": (5_000, 3_000, 60),
    }


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({}, "no hazard details for EARTHQUAKE"),
        ({"hazard": "M5"}, "no hazard details for EARTHQUAKE"),
        ({"hazard": {"magnitude": 11}}, "invalid hazard details for EARTHQUAKE"),
        ({"hazard": {"magnitude": 5, "felt": True}}, "invalid hazard details for EARTHQUAKE"),
    ],
)
def test_a_measured_hazard_without_a_valid_measure_is_discarded(
    payload: dict[str, Any], reason: str
) -> None:
    """Never guessed: the source's own words are not used for a measured category."""
    result = normalise(
        category_map={"Earthquake": "EARTHQUAKE"},
        severity_map={"Strong": "CRITICAL"},
        provider_category="Earthquake",
        provider_severity="Strong",
        has_location=True,
        payload=payload,
    )
    assert (result.category, result.severity, result.reason) == ("EARTHQUAKE", None, reason)


def test_the_measure_overrides_the_sources_map_and_low_air_quality_is_discarded() -> None:
    def run(hazard: dict[str, Any]) -> tuple[str | None, str | None]:
        r = normalise(
            category_map={"Air quality": "AIR_QUALITY"},
            severity_map={"Hazardous": "CRITICAL"},
            provider_category="Air quality",
            provider_severity="Hazardous",
            has_location=True,
            payload={"hazard": hazard},
        )
        return r.severity, r.reason

    assert run({"aqi": 380}) == ("HIGH", None)
    assert run({"aqi": 200}) == (None, "below threshold")  # G-5


def test_landfall_is_counted_from_the_signals_own_time() -> None:
    at = datetime(2026, 10, 31, 6, tzinfo=UTC)
    payload = {"hazard": {"cyclone_category": 2, "landfall_in_h": 60}}
    assert hazards.landfall_at("TROPICAL_CYCLONE", payload, at) == at + timedelta(hours=60)
    assert hazards.landfall_at("EARTHQUAKE", {"hazard": {"magnitude": 6}}, at) is None


# --- the world ---------------------------------------------------------------------------------


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    dac: uuid.UUID
    ank: uuid.UUID

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def ingest(self, payload: dict[str, Any]) -> Ingested:
        event = Event("RAW_SIGNAL", self.idp.tenant_id, payload, "test")
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await ingest_signal(session, event)
            await session.commit()
        if result.fused is not None:
            async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
                await exposure.compute(session, result.fused.incident_id)
                await session.commit()
        return result

    async def incident(self, payload: dict[str, Any]) -> uuid.UUID:
        fused = (await self.ingest(payload)).fused
        assert fused is not None
        return fused.incident_id

    async def get(self, who: str, url: str) -> Any:
        return await self.client.get(url, headers=self.idp.headers(who))

    async def post(self, who: str, url: str, body: dict[str, Any] | None = None) -> Any:
        return await self.client.post(url, json=body, headers=self.idp.headers(who))

    async def arm(self, who: str, incident_id: uuid.UUID, code: str = "PB-06") -> Any:
        body = {"playbook_code": code, "incident_id": str(incident_id)}
        return await self.post(who, "/api/playbook-runs/arm", body)

    async def runs(self) -> list[tuple[str, datetime | None, str]]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            rows = await session.execute(
                select(
                    PlaybookRun.status, PlaybookRun.scheduled_for, PlaybookRun.started_by_type
                ).order_by(PlaybookRun.started_at)
            )
            return [(r[0], r[1], r[2]) for r in rows]

    async def actions(self, prefix: str) -> list[str]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog.action)
                    .where(AuditLog.action.like(f"{prefix}%"), AuditLog.action != "PLAYBOOK.CREATE")
                    .order_by(AuditLog.id)
                )
            )

    async def demo(self) -> None:
        """A demo scenario running in the tenant, as the presenter bar leaves it."""
        await self.sql(
            "WITH s AS (INSERT INTO scenario (tenant_id, code, name) VALUES "
            "(current_tenant_id(), 'DAC-CYCLONE', 'Cyclone') RETURNING id) "
            "INSERT INTO scenario_run (tenant_id, scenario_id, status, started_at) "
            "SELECT current_tenant_id(), id, 'PLAYING', now() - interval '1 minute' FROM s"
        )

    async def clock(self, hours: object, event_id: uuid.UUID | None = None) -> None:
        event = Event("DEMO_CLOCK", self.idp.tenant_id, {"advance_h": hours}, "test")
        if event_id is not None:
            event = Event(event.type, event.tenant_id, event.payload, "test", id=event_id)
        await consumer.clock_handler(self.idp.engine, self.publisher)(event)

    async def tick(self) -> int:
        return await consumer.tick(self.idp.engine, self.idp.tenant_id, self.publisher)

    async def observe(self, incident_id: uuid.UUID) -> list[Any]:
        event = Event(
            "EXPOSURE_COMPUTED", self.idp.tenant_id, {"incident_id": str(incident_id)}, "t"
        )
        await run_agents(
            self.idp.engine, self.publisher, event, undo_window_s=300, agents=[ResponsePlanner()]
        )
        result = await self.sql(
            "SELECT id, proposal_key, action_type, effective_level, status, action_payload, "
            "is_proactive FROM agent_proposal ORDER BY created_at"
        )
        return list(result)


async def _mission(idp: Idp, code: str, where: tuple[float, float]) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :code, 'XX', "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
            ),
            {"id": mission_id, "code": code, "lat": where[0], "lon": where[1]},
        )
        await session.execute(
            text(
                "INSERT INTO site (tenant_id, mission_id, site_type, name, location) VALUES "
                "(current_tenant_id(), :m, 'EMBASSY', :name, "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
            ),
            {"m": mission_id, "name": f"{code} chancery", "lat": where[0], "lon": where[1]},
        )
        await session.commit()
    return mission_id


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    dac = await _mission(idp, "DAC", DHAKA)
    ank = await _mission(idp, "ANK", ANKARA)
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "security.dac": [("SECURITY_OFFICER", dac)],
        "security.ank": [("SECURITY_OFFICER", ank)],
        "hom.dac": [("HEAD_OF_MISSION", dac)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        for code in ("PB-06", "PB-01"):
            await ensure_playbook(
                session,
                playbook_id=uuid.uuid4(),
                code=code,
                name="Severe weather" if code == "PB-06" else "Earthquake",
                category="WEATHER",
                trigger_rules={"categories": ["STORM", "FLOOD"], "min_severity": "HIGH"}
                if code == "PB-06"
                else {"categories": ["EARTHQUAKE"], "min_severity": "HIGH"},
                steps=STEPS,
                step_ids=[uuid.uuid4()],
            )
        await ensure_agents(session, [AgentIn("RESPONSE_PLANNER", "Response Planner", "", 2)])
        await ensure_policies(
            session,
            [
                PolicyIn("ARM_PLAYBOOK", 2, ["SECURITY_OFFICER|DUTY_OFFICER"], False, 43_200),
                PolicyIn("START_PLAYBOOK", 2, ["DUTY_OFFICER|SECURITY_OFFICER"], False),
            ],
        )
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, dac, ank)


# --- hazard events through the pipeline ---------------------------------------------------------


async def test_a_distant_earthquake_is_low_listed_with_its_mission_and_not_exposed(
    world: World,
) -> None:
    """HZ-01, HZ-03 (§42): M5.2, 210 km from Ankara: LOW, 100 km radius, out of range."""
    incident_id = await world.incident(
        hz(
            "SEISMIC",
            north(ANKARA, 210),
            hazard={"magnitude": 5.2, "depth_km": 12},
            place="Central Anatolia",
        )
    )
    response = await world.get("viewer", "/api/hazards")
    assert response.status_code == 200
    body = response.json()
    [event] = body["events"]
    assert event["incident_id"] == str(incident_id)
    assert (event["category"], event["severity"], event["impact_radius_m"]) == (
        "EARTHQUAKE",
        "LOW",
        100_000,
    )
    assert event["hazard"] == {"magnitude": 5.2, "depth_km": 12.0}
    assert event["nearest_mission_code"] == "ANK"
    assert 205_000 < event["nearest_mission_m"] < 215_000
    assert (event["within_range"], event["exposed"]) == (True, False)
    assert event["sources"] == ["Seismic network"]
    assert (event["simulated"], body["sources"], body["demo_advance_h"]) == (True, 4, 0)


async def test_a_cyclone_forecast_exposes_dhaka_and_counts_down(world: World) -> None:
    """HZ-02, HZ-04: Category 2, landfall in 60 h: HIGH, 150 km, the Dhaka mission exposed.
    The chancery is a protected site in the zone, so D-11 step 3 raises it to CRITICAL."""
    incident_id = await world.incident(cyclone(2, 60))
    [event] = (await world.get("viewer", "/api/hazards")).json()["events"]
    assert (event["category"], event["severity"], event["impact_radius_m"]) == (
        "TROPICAL_CYCLONE",
        "CRITICAL",
        150_000,
    )
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert (await session.get_one(Incident, incident_id)).signal_severity == "HIGH"
    assert event["title"] == "Tropical cyclone · Dhaka"
    assert 59.5 <= event["landfall_in_h"] <= 60
    assert (event["nearest_mission_code"], event["exposed"]) == ("DAC", True)
    assert event["exposure"]["mission_sites"] == 1
    assert event["armed"] is None


async def test_a_newer_forecast_hours_later_updates_the_same_incident(world: World) -> None:
    """G-3: forecasts 6 h apart stay one incident; the newest signal's details are shown."""
    first = await world.incident(cyclone(1, 72, at=timedelta(hours=-6)))
    second = await world.incident(cyclone(2, 60))
    assert first == second
    [event] = (await world.get("viewer", "/api/hazards")).json()["events"]
    assert event["hazard"]["cyclone_category"] == 2
    assert event["severity"] == "CRITICAL"  # HIGH, raised by D-11 (the chancery)
    assert 59.5 <= event["landfall_in_h"] <= 60


async def test_a_wildfire_near_a_mission_is_high_and_a_remote_one_is_out_of_range(
    world: World,
) -> None:
    """G-4, HZ-03: MODERATE, raised to HIGH with a mission site inside its 20 km."""
    near = await world.incident(
        hz("XWEATHER", north(ANKARA, 15), category="Wildfire", severity="Severe", place="Ankara")
    )
    far = await world.incident(
        hz("XWEATHER", (-40.0, -120.0), category="Wildfire", severity="Severe", place="Pacific")
    )
    events = {
        e["incident_id"]: e for e in (await world.get("viewer", "/api/hazards")).json()["events"]
    }
    assert events[str(near)]["severity"] == "HIGH"
    assert events[str(far)]["severity"] == "MODERATE"
    assert (events[str(far)]["within_range"], events[str(far)]["exposed"]) == (False, False)
    escalated = await world.sql(
        "SELECT summary FROM incident_event WHERE event_type = 'ESCALATED' AND incident_id = :i",
        i=near,
    )
    assert [r[0] for r in escalated] == [
        "Severity MODERATE → HIGH: wildfire within 20 km of a mission site (plan-pilot-hz G-4)."
    ]


async def test_air_quality_and_a_bad_measure_through_the_pipeline(world: World) -> None:
    assert (await world.ingest(hz("AIRQ", DHAKA, hazard={"aqi": 120}))).outcome == "DISCARDED"
    assert (await world.ingest(hz("SEISMIC", DHAKA))).outcome == "DISCARDED"  # no magnitude
    # 50 km out, so no protected site is in its 30 km (D-11 would raise it).
    incident_id = await world.incident(hz("AIRQ", north(DHAKA, 50), hazard={"aqi": 380}))
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        incident = await session.get_one(Incident, incident_id)
        assert (incident.category, incident.severity, incident.impact_radius_m) == (
            "AIR_QUALITY",
            "HIGH",
            30_000,
        )


async def test_the_hazards_list_has_no_names_for_any_role(world: World) -> None:
    """HZ-10: counts only, never a person."""
    await world.sql(
        "WITH p AS (INSERT INTO person (tenant_id, mission_id, person_type, full_name) VALUES "
        "(current_tenant_id(), :m, 'DIPLOMAT', 'Fictional Rahim') RETURNING id) "
        "INSERT INTO person_location_current (person_id, tenant_id, location, place_label, "
        "confidence, primary_source) SELECT id, current_tenant_id(), "
        "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 'Home · Gulshan', 80, 'HR_HOME' "
        "FROM p",
        m=world.dac,
        lat=DHAKA[0],
        lon=DHAKA[1],
    )
    await world.incident(cyclone(2, 60))
    for who in ("viewer", "duty"):
        response = await world.get(who, "/api/hazards")
        assert "Rahim" not in response.text
        [event] = response.json()["events"]
        assert event["exposure"] == {"staff": 1, "people": 1, "homes": 1, "mission_sites": 1}


async def test_the_climate_list_is_sorted_by_2050_and_needs_a_role(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        rows = [
            {"mission_id": world.dac, "hazards": ["FLOOD", "TROPICAL_CYCLONE"], "score_today": 71,
             "score_2050": 86, "scenario": "Illustrative 2050"},
            {"mission_id": world.ank, "hazards": ["EARTHQUAKE"], "score_today": 52,
             "score_2050": 58, "scenario": "Illustrative 2050"},
        ]  # fmt: skip
        assert await hazard_service.ensure_climate(session, rows) == 2
        assert await hazard_service.ensure_climate(session, rows) == 0  # seeded once
        await session.commit()
    climate = (await world.get("viewer", "/api/hazards/climate")).json()
    assert [(c["mission_code"], c["score_2050"]) for c in climate] == [("DAC", 86), ("ANK", 58)]
    assert climate[0]["source"] == "Illustrative climate model (simulated)"
    assert (await world.client.get("/api/hazards/climate")).status_code == 401


# --- arming, start now, disarm (HZ-05, HZ-10, G-1) ----------------------------------------------


async def test_a_duty_officer_arms_pb06_36_h_before_landfall(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    response = await world.arm("duty", incident_id)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "SCHEDULED"
    starts = datetime.fromisoformat(run["scheduled_for"])
    assert timedelta(hours=23, minutes=55) < starts - datetime.now(UTC) <= timedelta(hours=24)
    assert [e.type for e in world.publisher.events] == ["PLAYBOOK_RUN_ARMED"]
    assert await world.actions("PLAYBOOK.") == ["PLAYBOOK.ARM"]
    [event] = (await world.get("viewer", "/api/hazards")).json()["events"]
    armed = event["armed"]
    assert (armed["playbook_code"], armed["status"], armed["forecast_changed"]) == (
        "PB-06",
        "SCHEDULED",
        False,
    )
    assert 23.9 <= armed["starts_in_h"] <= 24
    # The engine leaves an armed run alone until it starts.
    assert await world.tick() == 0
    assert [r[0] for r in await world.runs()] == ["SCHEDULED"]


@pytest.mark.parametrize(
    ("who", "code"),
    [("viewer", 403), ("hom.dac", 403), ("security.ank", 403), ("security.dac", 201)],
)
async def test_who_may_arm_is_who_may_start(world: World, who: str, code: int) -> None:
    """G-1: Security and Duty Officers, unscoped or for the incident's mission; a Head of
    Mission does not arm."""
    incident_id = await world.incident(cyclone(2, 60))
    assert (await world.arm(who, incident_id)).status_code == code


async def test_arming_twice_or_for_another_hazard_is_refused(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    assert (await world.arm("duty", incident_id)).status_code == 201
    again = await world.arm("security", incident_id)
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "PB-06 is already scheduled for this incident",
    )
    quake = await world.incident(hz("SEISMIC", DHAKA, hazard={"magnitude": 6.8}))
    refused = await world.arm("duty", quake)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "A playbook can only be armed for a cyclone forecast",
    )


async def test_arming_after_the_time_has_passed_starts_at_once(world: World) -> None:
    """G-7: landfall in 30 h, so 36 h before it is already past."""
    incident_id = await world.incident(cyclone(2, 30))
    response = await world.arm("duty", incident_id)
    assert (response.status_code, response.json()["status"]) == (201, "RUNNING")
    assert [e.type for e in world.publisher.events] == ["PLAYBOOK_RUN_STARTED"]
    assert await world.actions("PLAYBOOK.") == ["PLAYBOOK.START"]
    late = await world.sql(
        "SELECT summary FROM incident_event WHERE data->>'late' = 'true' AND incident_id = :i",
        i=incident_id,
    )
    assert [r[0] for r in late] == [
        "PB-06: the arming time (36 h before landfall) had passed, so it started at once."
    ]


async def test_start_now_and_disarm(world: World) -> None:
    first = await world.incident(cyclone(2, 60))
    run = (await world.arm("duty", first)).json()
    assert (
        await world.post("viewer", f"/api/playbook-runs/{run['id']}/start-now")
    ).status_code == 403
    started = await world.post("security", f"/api/playbook-runs/{run['id']}/start-now")
    assert (started.status_code, started.json()["status"]) == (200, "RUNNING")
    assert datetime.fromisoformat(started.json()["started_at"]) > datetime.fromisoformat(
        run["started_at"]
    )  # G-2: the database's start, not the arming time
    again = await world.post("security", f"/api/playbook-runs/{run['id']}/start-now")
    assert again.status_code == 409  # only one start (review of Prompt 54, L7)
    assert (await world.post("duty", f"/api/playbook-runs/{run['id']}/disarm")).status_code == 409

    second = await world.incident(
        hz("XWEATHER", south(ANKARA, 50), category="Tropical cyclone", place="Ankara",
           hazard={"cyclone_category": 3, "landfall_in_h": 80})
    )  # fmt: skip
    armed = (await world.arm("duty", second)).json()
    assert (
        await world.post("hom.dac", f"/api/playbook-runs/{armed['id']}/disarm")
    ).status_code == 403
    disarmed = await world.post("duty", f"/api/playbook-runs/{armed['id']}/disarm")
    assert (disarmed.status_code, disarmed.json()["status"]) == (200, "DISARMED")
    late = await world.post("duty", f"/api/playbook-runs/{armed['id']}/start-now")
    assert late.status_code == 409
    assert await world.actions("PLAYBOOK.") == [
        "PLAYBOOK.ARM",
        "PLAYBOOK.ARMED_START",
        "PLAYBOOK.ARM",
        "PLAYBOOK.DISARM",
    ]
    # Disarmed, it may be armed again (it no longer counts as live).
    assert (await world.arm("duty", second)).status_code == 201


async def test_starting_an_armed_playbook_the_usual_way_starts_the_armed_run(
    world: World,
) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    armed = (await world.arm("duty", incident_id)).json()
    body = {"playbook_code": "PB-06", "incident_id": str(incident_id)}
    started = await world.post("security", "/api/playbook-runs", body)
    assert (started.status_code, started.json()["id"]) == (201, armed["id"])
    assert [r[0] for r in await world.runs()] == ["RUNNING"]


async def test_arming_permissions_follow_the_endpoints(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    url = f"/api/me/permissions?entity_type=hazards&entity_id={incident_id}"

    async def flags(who: str) -> tuple[bool, bool, bool]:
        p = (await world.get(who, url)).json()
        return p["arm_playbook"], p["start_armed"], p["disarm"]

    assert await flags("viewer") == (False, False, False)
    assert await flags("hom.dac") == (False, False, False)
    assert await flags("duty") == (True, False, False)
    await world.arm("duty", incident_id)
    assert await flags("security.dac") == (False, True, True)
    assert await flags("viewer") == (False, False, False)


# --- the worker and the demo clock (plan §4, §5) -------------------------------------------------


async def _set_status(world: World, incident_id: uuid.UUID, status: str) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        await session.execute(
            update(Incident).where(Incident.id == incident_id).values(status=status)
        )
        await session.commit()


async def test_the_demo_clock_brings_the_armed_run_due_and_the_worker_starts_it(
    world: World,
) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    await world.arm("duty", incident_id)
    await world.demo()
    await world.clock(12)
    assert [r[0] for r in await world.runs()] == ["SCHEDULED"]  # 48 h to landfall: not yet
    event_id = uuid.uuid4()
    await world.clock(12, event_id)
    assert [r[0] for r in await world.runs()] == ["RUNNING"]
    await world.clock(12, event_id)  # a redelivered event changes nothing
    [event] = (await world.get("viewer", "/api/hazards")).json()["events"]
    assert event["armed"]["status"] == "RUNNING"
    assert 35.5 <= event["landfall_in_h"] <= 36
    body = (await world.get("viewer", "/api/hazards")).json()
    assert body["demo_advance_h"] == 24
    assert await world.actions("SCENARIO.CLOCK") == ["SCENARIO.CLOCK_ADVANCE"] * 2
    assert await world.actions("PLAYBOOK.ARMED") == ["PLAYBOOK.ARMED_START"]
    assert "PLAYBOOK_RUN_STARTED" in [e.type for e in world.publisher.events]
    started = await world.sql(
        "SELECT actor_type, actor_id, details FROM audit_log WHERE action = 'PLAYBOOK.ARMED_START'"
    )
    [(actor_type, actor_id, details)] = list(started)
    assert (actor_type, actor_id, details["reason"]) == (
        "SYSTEM",
        "playbook.armed",
        "36 h before landfall",
    )


@pytest.mark.parametrize("hours", [24, 0, -3, 73, "24", True])
async def test_the_demo_clock_needs_a_running_demo_and_a_sane_value(
    world: World, hours: object
) -> None:
    """Outside a demo, or with a bad value, it is refused and audited; nothing starts."""
    incident_id = await world.incident(cyclone(2, 60))
    await world.arm("duty", incident_id)
    if hours != 24:
        await world.demo()
    await world.clock(hours)
    assert [r[0] for r in await world.runs()] == ["SCHEDULED"]
    assert await world.actions("SCENARIO.CLOCK") == ["SCENARIO.CLOCK_REJECT"]


async def test_a_run_due_while_its_incident_is_not_active_is_disarmed(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    await world.arm("duty", incident_id)
    await _set_status(world, incident_id, "MONITORING")
    await world.demo()
    await world.clock(24)
    assert [r[0] for r in await world.runs()] == ["DISARMED"]
    reason = await world.sql(
        "SELECT details->>'reason' FROM audit_log WHERE action = 'PLAYBOOK.DISARM'"
    )
    assert [r[0] for r in reason] == ["incident monitoring at its time"]
    assert "PLAYBOOK_RUN_DISARMED" in [e.type for e in world.publisher.events]


async def test_a_run_that_came_due_while_the_worker_was_down_starts_late(world: World) -> None:
    """The clock moved 25 h with no worker pass; the next pass starts it. A demo jump is
    not lateness, so no "min after its time" (review of Prompt 55)."""
    incident_id = await world.incident(cyclone(2, 60))
    await world.arm("duty", incident_id)
    await world.demo()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        event = Event("DEMO_CLOCK", world.idp.tenant_id, {"advance_h": 25}, "test")
        assert await clock.advance(session, event) == 25  # no start_due: the worker is down
        await session.commit()
    assert [r[0] for r in await world.runs()] == ["SCHEDULED"]
    assert await world.tick() == 1
    assert [r[0] for r in await world.runs()] == ["RUNNING"]
    summary = await world.sql(
        "SELECT summary FROM incident_event WHERE data->>'armed' = 'true' AND incident_id = :i",
        i=incident_id,
    )
    assert [r[0] for r in summary] == ["PB-06 · Severe weather started (36 h before landfall)."]
    assert await world.tick() == 0  # nothing left to start


# --- the Response Planner proposes arming (HZ-06) ------------------------------------------


async def test_the_planner_proposes_arming_pb06_and_approving_it_arms(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    [proposal] = await world.observe(incident_id)
    _id, key, action, level, status, payload, proactive = proposal
    assert key == f"ARM_PLAYBOOK:{incident_id}:PB-06"
    assert (action, level, status, proactive) == ("ARM_PLAYBOOK", 2, "PENDING", True)
    assert set(payload) == {"playbook_code", "hours_before_landfall", "landfall_at"}
    assert (payload["playbook_code"], payload["hours_before_landfall"]) == ("PB-06", 36)
    assert len(await world.observe(incident_id)) == 1  # one open proposal per incident
    assert (await world.post("viewer", f"/api/proposals/{_id}/approve")).status_code == 403
    approved = await world.post("security", f"/api/proposals/{_id}/approve")
    assert approved.status_code == 200, approved.text
    [(state, scheduled, by)] = await world.runs()
    assert (state, by) == ("SCHEDULED", "AGENT")
    assert scheduled is not None
    assert "PROPOSAL.EXECUTE" in await world.actions("PROPOSAL.")
    assert "PLAYBOOK_RUN_ARMED" in [e.type for e in world.publisher.events]


@pytest.mark.parametrize(
    ("category", "landfall_h", "where"),
    [
        (1, 60, None),  # MODERATE
        (2, 30, None),  # 36 h or less to landfall
        (2, 60, (10.0, 60.0)),  # no mission within the radius
    ],
)
async def test_the_planner_does_not_propose_arming_outside_its_rule(
    world: World, category: int, landfall_h: float, where: tuple[float, float] | None
) -> None:
    payload = cyclone(category, landfall_h)
    if where is not None:
        payload["lat"], payload["lon"] = where
    incident_id = await world.incident(payload)
    assert await world.observe(incident_id) == []


async def test_the_planner_does_not_propose_once_a_person_armed_it(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    await world.arm("duty", incident_id)
    assert await world.observe(incident_id) == []


async def test_the_planner_proposes_pb01_for_a_high_earthquake_near_a_mission(
    world: World,
) -> None:
    """HZ-07: PB-01's trigger is an ordinary START_PLAYBOOK rule."""
    incident_id = await world.incident(
        hz("SEISMIC", north(ANKARA, 30), hazard={"magnitude": 6.8}, place="Ankara")
    )
    [proposal] = await world.observe(incident_id)
    assert proposal[1:3] == (f"START_PLAYBOOK:{incident_id}:PB-01", "START_PLAYBOOK")


# --- review of Prompt 55 ------------------------------------------------------------------------


async def test_approving_after_the_forecast_moved_arms_nothing(world: World) -> None:
    """M1: the executor arms against the landfall the approvers read."""
    incident_id = await world.incident(cyclone(2, 60))
    [proposal] = await world.observe(incident_id)
    await world.incident(cyclone(2, 50))  # a newer forecast: landfall 10 h earlier
    response = await world.post("security", f"/api/proposals/{proposal[0]}/approve")
    assert (response.status_code, response.json()["status"]) == (200, "FAILED")
    assert await world.runs() == []
    errors = await world.sql(
        "SELECT details->>'error' FROM audit_log WHERE action = 'PROPOSAL.FAIL'"
    )
    [(error,)] = list(errors)
    assert error.startswith("The forecast changed since the proposal: landfall now")


async def test_an_arming_proposal_cannot_be_edited(world: World) -> None:
    """What the approvers read is what runs: no edit-and-approve for ARM_PLAYBOOK."""
    incident_id = await world.incident(cyclone(2, 60))
    [proposal] = await world.observe(incident_id)
    edited = {**proposal[5], "playbook_code": "PB-01"}
    response = await world.post(
        "security", f"/api/proposals/{proposal[0]}/edit-approve", {"edited_payload": edited}
    )
    assert response.status_code == 409, response.text
    assert "cannot be edited" in response.json()["detail"]
    assert await world.runs() == []


async def test_two_overlapping_deliveries_of_one_clock_event_advance_once(world: World) -> None:
    """M2: the per-tenant lock serialises them; the second finds the first's row."""
    await world.demo()
    event_id = uuid.uuid4()
    await asyncio.gather(world.clock(24, event_id), world.clock(24, event_id))
    assert (await world.get("viewer", "/api/hazards")).json()["demo_advance_h"] == 24
    assert await world.actions("SCENARIO.CLOCK") == ["SCENARIO.CLOCK_ADVANCE"]


async def test_the_demo_clock_never_brings_a_real_armed_run_forward(world: World) -> None:
    """M3: armed before the demo started, it waits for its real time."""
    incident_id = await world.incident(cyclone(2, 60))
    await world.arm("duty", incident_id)
    await world.sql(
        "WITH s AS (INSERT INTO scenario (tenant_id, code, name) VALUES "
        "(current_tenant_id(), 'DAC-CYCLONE', 'Cyclone') RETURNING id) "
        "INSERT INTO scenario_run (tenant_id, scenario_id, status, started_at) "
        "SELECT current_tenant_id(), id, 'PLAYING', now() + interval '1 second' FROM s"
    )
    await asyncio.sleep(1.1)
    await world.clock(48)
    assert [r[0] for r in await world.runs()] == ["SCHEDULED"]


async def test_one_run_that_fails_does_not_stop_the_others(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4: each due run in its own savepoint."""
    first = await world.incident(cyclone(2, 60))
    second = await world.incident(
        hz("XWEATHER", south(ANKARA, 50), category="Tropical cyclone", place="Ankara",
           hazard={"cyclone_category": 2, "landfall_in_h": 61})
    )  # fmt: skip
    bad = (await world.arm("duty", first)).json()["id"]
    await world.arm("duty", second)
    real = playbook_service._start_armed

    async def flaky(session: Any, run: PlaybookRun, *args: Any, **kwargs: Any) -> PlaybookRun:
        if str(run.id) == bad:
            raise RuntimeError("boom")
        return await real(session, run, *args, **kwargs)

    monkeypatch.setattr(playbook_service, "_start_armed", flaky)
    await world.demo()
    await world.clock(26)
    assert sorted(r[0] for r in await world.runs()) == ["RUNNING", "SCHEDULED"]
    assert await world.actions("SCENARIO.CLOCK") == ["SCENARIO.CLOCK_ADVANCE"]  # kept
    monkeypatch.setattr(playbook_service, "_start_armed", real)
    assert await world.tick() == 1  # the next pass takes it
    assert [r[0] for r in await world.runs()] == ["RUNNING", "RUNNING"]


@pytest.mark.parametrize("action", ["start-now", "disarm"])
async def test_start_now_and_disarm_are_scoped_to_the_incidents_mission(
    world: World, action: str
) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    run = (await world.arm("duty", incident_id)).json()
    url = f"/api/playbook-runs/{run['id']}/{action}"
    assert (await world.post("security.ank", url)).status_code == 403
    assert (await world.post("viewer", url)).status_code == 403
    assert (await world.post("security.dac", url)).status_code == 200
    unknown = f"/api/playbook-runs/{uuid.uuid4()}/{action}"
    assert (await world.post("viewer", unknown)).status_code == 404


async def test_a_newer_forecast_shows_forecast_changed_without_moving_the_time(
    world: World,
) -> None:
    incident_id = await world.incident(cyclone(2, 60))
    run = (await world.arm("duty", incident_id)).json()
    await world.incident(cyclone(3, 54))
    [event] = (await world.get("viewer", "/api/hazards")).json()["events"]
    assert event["armed"]["forecast_changed"] is True
    assert event["armed"]["scheduled_for"] == run["scheduled_for"]


async def test_a_future_dated_hazard_signal_is_discarded(world: World) -> None:
    """L8: it would otherwise stay the newest signal for good."""
    result = await world.ingest(cyclone(2, 60, at=timedelta(hours=3)))
    assert (result.outcome, result.reason) == ("DISCARDED", "occurred in the future")


async def test_arming_after_landfall_is_refused(world: World) -> None:
    incident_id = await world.incident(cyclone(2, 1, at=timedelta(hours=-2)))
    response = await world.arm("duty", incident_id)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "Landfall has passed; start the playbook instead",
    )


async def test_hazards_and_the_clock_stay_in_their_tenant(
    world: World, db: Any, api_engine: AsyncEngine
) -> None:
    other = Idp(issuer="https://kc.test/other", tenant_id=await create_tenant(db, "Other"),
                engine=api_engine)  # fmt: skip
    await world.incident(cyclone(2, 60))
    await world.demo()
    await world.clock(24)
    async with tenant_session(other.tenant_id, api_engine) as session:
        listed = await hazard_service.list_hazards(session)
    assert (listed.events, listed.demo_advance_h) == ([], 0)
