"""Exposure and severity escalation (INC-05, D-06, D-11, D-22, Prompt 7)."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.modules.audit.models import AuditLog
from app.modules.intel import exposure
from app.modules.intel.models import Incident, IncidentEvent, IncidentExposure
from app.modules.people import location
from app.modules.people.models import Person
from app.modules.people.service import (
    ObservationIn,
    PersonIn,
    SiteIn,
    add_observations,
    ensure_mission,
    load_persons,
    load_sites,
)
from app.modules.travel.service import ensure_trip
from app.tests.conftest import DbUrls
from app.tests.intel_helpers import EPICENTRE, KM_LAT, T0, ingest, intel_tenant, signal


def north(km: float) -> tuple[float, float]:
    return (EPICENTRE[0] + km * KM_LAT, EPICENTRE[1])


class World:
    """A small mission around the epicentre; distances are along one meridian."""

    def __init__(self, tenant: uuid.UUID) -> None:
        self.tenant = tenant
        self.ids: dict[str, uuid.UUID] = {}

    def id(self, key: str) -> uuid.UUID:
        return self.ids.setdefault(key, uuid.uuid4())

    async def build(self, engine: AsyncEngine, sites: list[tuple[str, str, str, float]]) -> None:
        """sites: (key, mission code, site type, km north of the epicentre)."""
        people = [
            ("diplomat", "DIPLOMAT", 1.0),
            ("local", "LOCAL_STAFF", 4.9),
            ("dependant", "DEPENDANT", 2.0),
            ("delegate", "DELEGATE", 1.5),
            ("citizen_in", "CITIZEN", 3.0),
            ("citizen_out", "CITIZEN", 5.1),  # outside the 5 km radius
            ("inactive", "DIPLOMAT", 1.0),  # deactivated below
        ]
        async with tenant_session(self.tenant, engine) as session:
            for code in sorted({m for _, m, _, _ in sites} | {"NBO"}):
                self.ids[code] = await ensure_mission(
                    session,
                    code=code,
                    city=code,
                    country_code="KE",
                    lat=north(0)[0],
                    lon=north(0)[1],
                )
            await load_sites(
                session,
                [
                    SiteIn(self.id(key), self.ids[m], kind, key, *north(km))
                    for key, m, kind, km in sites
                ],
            )
            await load_persons(
                session,
                [PersonIn(self.id(k), self.ids["NBO"], t, k) for k, t, _ in people],
            )
            await add_observations(
                session,
                [
                    ObservationIn(self.id(k), "MANUAL", *north(km), T0 - timedelta(hours=1), k)
                    for k, _, km in people
                ],
            )
            await location.recompute(session, T0)
            await session.execute(
                update(Person).where(Person.id == self.id("inactive")).values(is_active=False)
            )
            for ref, starts, ends, traveller in [
                ("TRP-IN", date(2026, 10, 19), date(2026, 10, 23), "delegate"),
                ("TRP-PAST", date(2026, 10, 1), date(2026, 10, 5), "diplomat"),
                ("TRP-AWAY", date(2026, 10, 19), date(2026, 10, 23), "citizen_out"),
            ]:
                await ensure_trip(
                    session,
                    trip_id=self.id(ref),
                    reference=ref,
                    purpose="",
                    origin="HQ",
                    destination="Nairobi",
                    destination_country="KE",
                    starts_on=starts,
                    ends_on=ends,
                    traveller_ids=[self.id(traveller)],
                )
            await session.commit()


NBO_SITES = [
    ("embassy", "NBO", "EMBASSY", 2.2),
    ("hotel", "NBO", "HOTEL", 1.5),
    ("residence", "NBO", "RESIDENCE", 3.6),
    ("office", "NBO", "OFFICE", 6.0),  # outside
]


@pytest.fixture
async def tenant(db: DbUrls, api_engine: AsyncEngine) -> uuid.UUID:
    return await intel_tenant(db, api_engine)


async def open_incident(
    engine: AsyncEngine, tenant: uuid.UUID, source: str = "DATAMINR", severity: str = "High"
) -> uuid.UUID:
    result = await ingest(engine, tenant, signal(source, severity))
    assert result.fused is not None
    return result.fused.incident_id


async def compute(
    engine: AsyncEngine, tenant: uuid.UUID, incident_id: uuid.UUID
) -> exposure.Computed | None:
    async with tenant_session(tenant, engine) as session:
        computed = await exposure.compute(session, incident_id)
        await session.commit()
    return computed


async def load(engine: AsyncEngine, tenant: uuid.UUID, incident_id: uuid.UUID) -> Incident:
    async with tenant_session(tenant, engine) as session:
        return await session.get_one(Incident, incident_id)


async def timeline(engine: AsyncEngine, tenant: uuid.UUID, incident_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant, engine) as session:
        rows = await session.scalars(
            select(IncidentEvent.event_type)
            .where(IncidentEvent.incident_id == incident_id)
            .order_by(IncidentEvent.id)
        )
        return list(rows)


@pytest.mark.parametrize(
    ("signal_severity", "protected", "expected"),
    [
        ("HIGH", True, "CRITICAL"),
        ("CRITICAL", True, "CRITICAL"),  # at most CRITICAL
        ("MODERATE", True, "MODERATE"),  # below HIGH: Paris (plan G-12)
        ("LOW", True, "LOW"),
        ("HIGH", False, "HIGH"),
    ],
)
def test_escalation_rule(signal_severity: str, protected: bool, expected: str) -> None:
    assert exposure.escalated_severity(signal_severity, protected) == expected


async def test_exposure_counts_mission_and_escalation(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    world = World(tenant)
    await world.build(api_engine, NBO_SITES)
    incident_id = await open_incident(api_engine, tenant)

    computed = await compute(api_engine, tenant, incident_id)
    assert computed is not None
    assert computed.counts == exposure.Counts(
        staff=2,  # diplomat + local staff at 4.9 km; the inactive diplomat is not counted
        delegates=1,
        citizens=1,  # 3 km in, 5.1 km out
        people=5,  # + the dependant
        sites=3,  # embassy, hotel, residence; the office at 6 km is outside
        mission_sites=2,  # not the hotel (D-23)
        protected_sites=2,
        trips=1,  # TRP-IN only: TRP-PAST is not active, TRP-AWAY's traveller is outside
    )
    assert (computed.mission_id, computed.severity, computed.escalated) == (
        world.ids["NBO"],
        "CRITICAL",
        True,
    )
    incident = await load(api_engine, tenant, incident_id)
    assert (incident.mission_id, incident.signal_severity, incident.severity) == (
        world.ids["NBO"],
        "HIGH",
        "CRITICAL",
    )
    assert await timeline(api_engine, tenant, incident_id) == ["SIGNAL", "EXPOSURE", "ESCALATED"]

    async with tenant_session(tenant, api_engine) as session:
        rows = {
            (r.subject_type, r.subject_id): r
            for r in await session.scalars(
                select(IncidentExposure).where(IncidentExposure.incident_id == incident_id)
            )
        }
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "INCIDENT.EXPOSURE_COMPUTE")
            )
        ).all()
    hotel = rows[("SITE", world.id("hotel"))]
    assert hotel.distance_m is not None
    assert abs(hotel.distance_m - 1500) < 10
    diplomat = rows[("PERSON", world.id("diplomat"))]
    assert diplomat.confidence == 60  # the person's location confidence (MANUAL)
    trip = rows[("TRIP", world.id("TRP-IN"))]
    assert trip.distance_m == rows[("PERSON", world.id("delegate"))].distance_m
    assert [a.details["escalated"] for a in audits] == [True]
    assert audits[0].details["people"] == 5


async def test_recompute_replaces_rows_without_repeating_events(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    world = World(tenant)
    await world.build(api_engine, NBO_SITES)
    incident_id = await open_incident(api_engine, tenant)
    await compute(api_engine, tenant, incident_id)
    again = await compute(api_engine, tenant, incident_id)
    assert again is not None
    assert again.escalated is False  # already raised
    assert await timeline(api_engine, tenant, incident_id) == ["SIGNAL", "EXPOSURE", "ESCALATED"]

    # The diplomat moves out of the zone; the next computation drops them.
    async with tenant_session(tenant, api_engine) as session:
        await add_observations(
            session,
            [ObservationIn(world.id("diplomat"), "MANUAL", *north(8), T0, "moved")],
        )
        await location.recompute(session, T0)
        await session.commit()
    moved = await compute(api_engine, tenant, incident_id)
    assert moved is not None
    assert (moved.counts.staff, moved.counts.people) == (1, 4)
    assert await timeline(api_engine, tenant, incident_id) == [
        "SIGNAL",
        "EXPOSURE",
        "ESCALATED",
        "EXPOSURE",
    ]
    async with tenant_session(tenant, api_engine) as session:
        persons = await session.scalars(
            select(IncidentExposure.subject_id).where(
                IncidentExposure.incident_id == incident_id,
                IncidentExposure.subject_type == "PERSON",
            )
        )
        assert world.id("diplomat") not in set(persons)


async def test_moderate_signal_is_not_escalated(api_engine: AsyncEngine, tenant: uuid.UUID) -> None:
    world = World(tenant)
    await world.build(api_engine, NBO_SITES)
    incident_id = await open_incident(api_engine, tenant, "RISKLINE", "Moderate")
    computed = await compute(api_engine, tenant, incident_id)
    assert computed is not None
    assert (computed.severity, computed.escalated, computed.counts.protected_sites) == (
        "MODERATE",
        False,
        2,
    )
    assert "ESCALATED" not in await timeline(api_engine, tenant, incident_id)


async def test_only_a_hotel_exposed_sets_the_mission_but_does_not_escalate(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    world = World(tenant)
    await world.build(
        api_engine, [("hotel", "NBO", "HOTEL", 1.5), ("embassy", "NBO", "EMBASSY", 7)]
    )
    incident_id = await open_incident(api_engine, tenant)
    computed = await compute(api_engine, tenant, incident_id)
    assert computed is not None
    assert (computed.mission_id, computed.severity) == (world.ids["NBO"], "HIGH")


async def test_no_site_exposed_leaves_no_mission(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    world = World(tenant)
    await world.build(api_engine, [("embassy", "NBO", "EMBASSY", 9)])
    incident_id = await open_incident(api_engine, tenant)
    computed = await compute(api_engine, tenant, incident_id)
    assert computed is not None
    assert (computed.mission_id, computed.counts.sites, computed.severity) == (None, 0, "HIGH")


async def test_the_nearest_exposed_site_decides_the_mission(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    world = World(tenant)
    await world.build(
        api_engine,
        [("nbo_embassy", "NBO", "EMBASSY", 2.2), ("cai_office", "CAI", "OFFICE", 0.5)],
    )
    incident_id = await open_incident(api_engine, tenant)
    computed = await compute(api_engine, tenant, incident_id)
    assert computed is not None
    assert computed.mission_id == world.ids["CAI"]


async def test_inactive_incidents_are_not_computed(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    incident_id = await open_incident(api_engine, tenant)
    async with tenant_session(tenant, api_engine) as session:
        await session.execute(update(Incident).values(status="MONITORING"))
        await session.commit()
    assert await compute(api_engine, tenant, incident_id) is None
    assert await compute(api_engine, tenant, uuid.uuid4()) is None


def test_summary_text() -> None:
    counts = exposure.Counts(14, 3, 212, 229, 3, 2, 2, 1)
    assert counts.summary() == "229 people (14 staff, 3 delegates, 212 citizens), 3 sites, 1 trip"
    one = exposure.Counts(1, 1, 0, 1, 1, 1, 1, 0)
    assert one.summary() == "1 person (1 staff, 1 delegate, 0 citizens), 1 site, 0 trips"
