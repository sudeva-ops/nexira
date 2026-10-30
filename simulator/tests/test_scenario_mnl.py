"""MNL-TROPICAL-STORM (D-35, WX-03..07; docs/plan-pilot-wx.md §5): its content, and scenes
1-3 through the worker's real handlers (weather feed, fusion, exposure, agents, playbook
runs), on the same in-memory bus as the Nairobi agents test. Seeded for today: TRP-8810 is
active on the scenario date and the storm opens today."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents import proposals
from app.modules.agents.models import AgentProposal
from app.modules.intel.models import Incident, IncidentExposure
from app.modules.notifications.models import NotificationCampaign
from app.modules.people.models import Mission
from app.modules.travel import trips
from app.modules.travel.models import Trip
from app.modules.weather import feed
from app.modules.weather.models import WeatherCurrent
from app.tests.conftest import DbUrls
from sqlalchemy import select

from nexira_sim.scenarios import mnl_tropical_storm as mnl
from nexira_sim.seed import data, world
from tests.scene_helpers import seed
from tests.test_agents_nbo import Bus, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-555555555555")
EVENTS = mnl.build_events(world.build(date(2026, 10, 30), TENANT), TENANT)


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2, 3]
    assert mnl.build_events(world.build(date(2026, 10, 30), TENANT), TENANT) == EVENTS


def test_every_signal_maps_through_its_own_source_and_every_feed_parses() -> None:
    sources = {code: (sev, cat) for code, _n, _r, sev, cat, _e, _f in data.SOURCES}
    for e in EVENTS:
        if e.event_type == "RAW_SIGNAL":
            severity_map, category_map = sources[str(e.payload["source_code"])]
            assert str(e.payload["provider_category"]) in category_map, e.payload["external_id"]
            assert str(e.payload["provider_severity"]) in severity_map, e.payload["external_id"]
        elif e.event_type == "WEATHER_FEED":
            assert feed.parse_feed(dict(e.payload)) is not None, e.payload


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    manila: uuid.UUID | None = None
    weather: dict[int, WeatherCurrent] = field(default_factory=dict)
    incidents: dict[int, list[Incident]] = field(default_factory=dict)
    storm_exposure: list[tuple[str, uuid.UUID]] = field(default_factory=list)
    proposals: list[AgentProposal] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    advisory: AgentProposal | None = None
    impacted: list[str] = field(default_factory=list)
    trip: uuid.UUID | None = None
    country_level: str | None = None


def scene(n: int, tenant_id: uuid.UUID) -> list[Event]:
    return [
        Event(e.event_type, tenant_id, dict(e.payload), "scenario")
        for e in mnl.build_events(world.build(date(2026, 10, 30), tenant_id), tenant_id)
        if e.scene_no == n and e.event_type != "SCENE_START"
    ]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed(db, engine, tenant_id, datetime.now(UTC).date())
        bus = Bus(engine)
        on_weather = feed.feed_handler(engine, bus.publisher)

        async def play(n: int) -> None:
            events = scene(n, tenant_id)
            for event in events:
                if event.type == "WEATHER_FEED":
                    await on_weather(event)
            await bus.deliver([e for e in events if e.type == "RAW_SIGNAL"])
            async with tenant_session(tenant_id, engine) as session:
                result.manila = await session.scalar(
                    select(Mission.id).where(Mission.code == "MNL")
                )
                row = await session.get(WeatherCurrent, (tenant_id, result.manila))
                if row is not None:
                    result.weather[n] = row
                result.incidents[n] = list(
                    await session.scalars(select(Incident).order_by(Incident.reference))
                )

        await play(1)
        await play(2)
        async with tenant_session(tenant_id, engine) as session:
            [storm] = result.incidents[2]
            result.storm_exposure = [
                (e.subject_type, e.subject_id)
                for e in await session.scalars(
                    select(IncidentExposure).where(IncidentExposure.incident_id == storm.id)
                )
            ]
            result.proposals = list(
                await session.scalars(select(AgentProposal).order_by(AgentProposal.created_at))
            )
            trip = await session.scalar(select(Trip).where(Trip.reference == "TRP-8810"))
            assert trip is not None
            result.trip = trip.id
            result.impacted = (await trips.impacted_by(session, [trip.id])).get(trip.id, [])
            result.country_level = (await trips.destination_risks(session, {"PH"}))["PH"].level
            pb06 = next(
                p
                for p in result.proposals
                if p.action_type == "START_PLAYBOOK"
                and p.action_payload["playbook_code"] == "PB-06"
            )
            outcome = await proposals.approve(
                session, await user(engine, tenant_id, "duty.officer"), pb06.id
            )
            await session.commit()
        await bus.deliver(outcome.events)
        async with tenant_session(tenant_id, engine) as session:
            result.alerts = list(
                await session.scalars(
                    select(NotificationCampaign.message).where(
                        NotificationCampaign.campaign_type == "ALERT"
                    )
                )
            )
            result.advisory = await session.scalar(
                select(AgentProposal).where(AgentProposal.action_type == "SEND_EXTERNAL_MESSAGE")
            )
        await play(3)
    finally:
        await engine.dispose()
    return result


async def test_scene_1_conditions_worsen(played: Played) -> None:
    building = played.weather[1]
    assert (building.condition, building.wind_kph, building.gust_kph, building.source) == (
        "CLOUD",
        45,
        65,
        "xWeather (simulated, scenario)",
    )
    assert played.incidents[1] == []


async def test_scene_2_one_critical_storm_exposes_the_manila_mission(played: Played) -> None:
    assert played.weather[2].condition == "STORM"
    [storm] = played.incidents[2]
    assert (storm.category, storm.severity, storm.confidence, storm.impact_radius_m) == (
        "STORM",
        "CRITICAL",
        80,  # xWeather 0.50 and Dataminr 0.60 fused (D-10)
        60_000,  # WX-04: 40 km from Manila is inside
    )
    assert storm.mission_id == played.manila
    kinds = {kind for kind, _ in played.storm_exposure}
    assert kinds == {"PERSON", "SITE", "TRIP"}


async def test_scene_2_pb06_is_proposed_and_not_pb07(played: Played) -> None:
    started = [
        p.action_payload["playbook_code"]
        for p in played.proposals
        if p.action_type == "START_PLAYBOOK"
    ]
    assert started == ["PB-06"]
    pb06 = next(p for p in played.proposals if p.action_type == "START_PLAYBOOK")
    assert pb06.title == "Run PB-06 · Severe weather near mission"
    assert pb06.status == "APPROVED"  # by the Duty Officer, in the fixture (WX §27)


async def test_scene_2_the_manila_trip_is_impacted_and_the_country_raised(played: Played) -> None:
    """WX-06: like any incident (JR-03 G-1, JR-06)."""
    [storm] = played.incidents[2]
    assert played.impacted == [storm.reference]
    assert played.country_level == "CRITICAL"
    travel = [
        (p.action_type, p.action_payload.get("trip_id"))
        for p in played.proposals
        if p.action_type in ("NOTIFY_TRAVELLERS", "CANCEL_TRIP", "ADVISE_REBOOKING")
    ]
    assert travel == [("NOTIFY_TRAVELLERS", str(played.trip))]  # started: never a cancel


async def test_pb06_uses_the_manila_words(played: Played) -> None:
    """D-31: the Manila staff alert and advisory; English only until reviewed (D-15)."""
    assert "Tropical storm warning. Stay indoors; avoid Manila Bay and low-lying roads." in (
        played.alerts
    )
    assert "URGENT: Severe weather warning for the mission — security team alert" in played.alerts
    assert played.advisory is not None
    payload = played.advisory.action_payload
    assert payload["message"].startswith("Tropical storm warning for Manila.")
    assert payload["translations"] == {}


async def test_scene_3_flooding_is_a_separate_incident(played: Played) -> None:
    incidents = played.incidents[3]
    assert sorted(i.category for i in incidents) == ["FLOOD", "STORM"]
    flood = next(i for i in incidents if i.category == "FLOOD")
    assert (flood.impact_radius_m, flood.signal_severity, flood.mission_id) == (
        25_000,
        "HIGH",
        played.manila,
    )
    assert flood.severity == "CRITICAL"  # the Manila embassy is inside the radius (D-11)
