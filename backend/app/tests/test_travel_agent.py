"""The Travel & Air agent's triggers (Prompt 35; TA-01..04, TA-07, TA-08; D-34,
docs/plan-pilot-ta.md §2). Events go through the agent runner as the worker sends them;
what comes out is pending proposals, never actions."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.events import Event
from app.modules.agents.agents.travel_air import TravelAir
from app.modules.agents.runner import run_agents
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.people.service import PersonIn, load_persons
from app.modules.travel.service import (
    AirportIn,
    CountryRiskIn,
    SegmentSeed,
    ensure_airports,
    ensure_country_risks,
    ensure_scenario_flight,
    ensure_trip,
)
from app.tests.conftest import DbUrls, create_tenant
from app.tests.fakes import ListPublisher

AGENT = TravelAir()


@dataclass
class World:
    tenant: uuid.UUID
    engine: Any
    mission: uuid.UUID
    people: list[uuid.UUID]
    publisher: ListPublisher

    def today(self) -> Any:
        return datetime.now(ZoneInfo(get_settings().home_tz)).date()

    async def sql(self, query: str, **params: Any) -> Any:
        async with tenant_session(self.tenant, self.engine) as session:
            result = await session.execute(text(query), params)
            rows = result.all() if query.lstrip().upper().startswith("SELECT") else []
            await session.commit()
            return rows

    async def trip(
        self,
        travellers: list[uuid.UUID],
        *,
        starts_in_days: int,
        approved_at: str = "LOW",
        restricted: bool = False,
        flight: bool = False,
    ) -> uuid.UUID:
        trip_id = uuid.uuid4()
        start = self.today() + timedelta(days=starts_in_days)
        departs = datetime.now(UTC) - timedelta(hours=10)
        async with tenant_session(self.tenant, self.engine) as session:
            await ensure_trip(
                session,
                trip_id=trip_id,
                reference=f"TRP-{trip_id.hex[:6]}",
                purpose="Consultations",
                origin="Abu Dhabi",
                destination="Paris",
                destination_country="FR",
                starts_on=start,
                ends_on=start + timedelta(days=3),
                traveller_ids=travellers,
                risk_level=approved_at,
                approval_status="APPROVED",
                restricted=restricted,
                segments=[
                    SegmentSeed(
                        kind="FLIGHT",
                        title="XW 451",
                        starts_at=departs,
                        ends_at=departs + timedelta(hours=7),
                        flight_number="XW 451",
                        from_airport="AUH",
                        to_airport="CDG",
                    )
                ]
                if flight
                else None,
            )
            if flight:
                await ensure_scenario_flight(session, trip_id)
            await session.commit()
        return trip_id

    async def run(self, kind: str, **payload: Any) -> list[tuple[str, str, int, str | None]]:
        """Run the agent on one event; return all its proposals so far."""
        await run_agents(
            self.engine,
            self.publisher,
            Event(type=kind, tenant_id=self.tenant, payload=payload, source="test"),
            undo_window_s=300,
            agents=[AGENT],
        )
        rows = await self.sql(
            "SELECT action_type, proposal_key, effective_level, incident_id::text "
            "FROM agent_proposal ORDER BY created_at, action_type"
        )
        return [tuple(r) for r in rows]

    async def flight_to(self, trip_id: uuid.UUID, *statuses: str, **set_: Any) -> uuid.UUID:
        rows = await self.sql(
            "SELECT f.id FROM flight f JOIN trip_segment s ON s.id = f.trip_segment_id "
            "WHERE s.trip_id = :t",
            t=trip_id,
        )
        flight = uuid.UUID(str(rows[0][0]))
        for status in statuses:
            extra = ", diverted_to = 'MBA'" if status == "DIVERTED" else ""
            await self.sql(f"UPDATE flight SET status = '{status}'{extra} WHERE id = :f", f=flight)
        for column, value in set_.items():
            await self.sql(f"UPDATE flight SET {column} = :v WHERE id = :f", v=value, f=flight)
        return flight

    async def incident(self, severity: str = "CRITICAL", status: str = "ACTIVE") -> uuid.UUID:
        incident = uuid.uuid4()
        await self.sql(
            "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
            "signal_severity, status, mission_id, location, confidence) VALUES (:id, "
            "current_tenant_id(), :ref, 'Protest', 'CIVIL_UNREST', :sev, :sev, :status, :m, "
            "'SRID=4326;POINT(2.35 48.86)', 92)",
            id=incident,
            ref=f"INC-T-{incident.hex[:4]}",
            sev=severity,
            status=status,
            m=self.mission,
        )
        return incident

    async def expose(self, incident: uuid.UUID, person: uuid.UUID) -> None:
        await self.sql(
            "INSERT INTO incident_exposure (tenant_id, incident_id, subject_type, subject_id, "
            "distance_m, confidence) VALUES (current_tenant_id(), :i, 'PERSON', :p, 500, 90)",
            i=incident,
            p=person,
        )


@pytest.fixture
async def world(db: DbUrls, api_engine: Any) -> World:
    tenant = await create_tenant(db, "Travel agent")
    mission = uuid.uuid4()
    people = [uuid.uuid4() for _ in range(6)]
    async with tenant_session(tenant, api_engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
                "VALUES (:id, current_tenant_id(), 'PAR', 'Paris', 'FR', "
                "'SRID=4326;POINT(2.35 48.86)')"
            ),
            {"id": mission},
        )
        await ensure_agents(session, [AgentIn("TRAVEL_AIR", "Travel & Air", "", 2)])
        await ensure_policies(
            session,
            [
                PolicyIn("NOTIFY_TRAVELLERS", 2, ["TRAVEL_DESK|SECURITY_OFFICER"], False, 3600),
                PolicyIn("CANCEL_TRIP", 2, ["SECURITY_OFFICER"], False, 3600),
            ],
        )
        await ensure_airports(
            session,
            [
                AirportIn("AUH", "Abu Dhabi", "Abu Dhabi", "AE", 24.43, 54.65),
                AirportIn("CDG", "Paris Charles de Gaulle", "Paris", "FR", 49.01, 2.55),
                AirportIn("MBA", "Mombasa Moi", "Mombasa", "KE", -4.03, 39.59),
            ],
        )
        await ensure_country_risks(session, [CountryRiskIn("FR", 25, 38, 8, 30, "x")])  # LOW
        await load_persons(
            session,
            [
                PersonIn(p, mission, "DIPLOMAT", f"Fictional Officer {n}")
                for n, p in enumerate(people)
            ],
        )
        await session.commit()
    return World(tenant, api_engine, mission, people, ListPublisher())


# --- flights (TA-01, TA-02, TA-08) -----------------------------------------------------------


async def test_a_holding_flight_gives_one_notify_proposal(world: World) -> None:
    trip_id = await world.trip(world.people[:3], starts_in_days=0, flight=True)
    flight = await world.flight_to(trip_id, "AIRBORNE", "HOLDING")
    proposals = await world.run("FLIGHT_UPDATED", flight_id=str(flight), status="HOLDING")
    assert proposals == [
        ("NOTIFY_TRAVELLERS", f"NOTIFY_TRAVELLERS:flight:{flight}:HOLDING", 2, None)
    ]
    again = await world.run("FLIGHT_UPDATED", flight_id=str(flight), status="HOLDING")
    assert again == proposals  # TA-08: replayed, nothing new
    payload = await world.sql("SELECT action_payload, title FROM agent_proposal")
    assert payload[0][0]["trip_id"] == str(trip_id)
    assert "holding near Paris" in payload[0][1]


async def test_a_diversion_adds_onward_travel_advice(world: World) -> None:
    trip_id = await world.trip(world.people[:3], starts_in_days=0, flight=True)
    flight = await world.flight_to(trip_id, "AIRBORNE", "DIVERTED")
    proposals = await world.run("FLIGHT_UPDATED", flight_id=str(flight), status="DIVERTED")
    assert sorted((a, level) for a, _, level, _ in proposals) == [
        ("ADVISE_REBOOKING", 4),  # advice only (D-12)
        ("NOTIFY_TRAVELLERS", 2),
    ]
    titles = [t for (t,) in await world.sql("SELECT title FROM agent_proposal")]
    assert all("Mombasa" in t for t in titles)


@pytest.mark.parametrize(("late_min", "proposed"), [(45, False), (75, True)])
async def test_only_a_delay_of_an_hour_or_more_is_proposed(
    world: World, late_min: int, proposed: bool
) -> None:
    trip_id = await world.trip(world.people[:2], starts_in_days=0, flight=True)
    flight = await world.flight_to(trip_id, "AIRBORNE")
    await world.sql(
        "UPDATE flight SET estimated_arr = scheduled_arr + make_interval(mins => :m) WHERE id = :f",
        m=late_min,
        f=flight,
    )
    proposals = await world.run("FLIGHT_UPDATED", flight_id=str(flight), status="AIRBORNE")
    assert [k for _, k, _, _ in proposals] == (
        [f"NOTIFY_TRAVELLERS:flight:{flight}:DELAY60"] if proposed else []
    )


async def test_nothing_for_an_ordinary_or_landed_flight(world: World) -> None:
    trip_id = await world.trip(world.people[:2], starts_in_days=0, flight=True)
    flight = await world.flight_to(trip_id, "AIRBORNE")
    assert await world.run("FLIGHT_UPDATED", flight_id=str(flight), status="AIRBORNE") == []
    await world.flight_to(trip_id, "LANDED")
    assert await world.run("FLIGHT_UPDATED", flight_id=str(flight), status="LANDED") == []
    assert await world.run("FLIGHT_UPDATED", flight_id="not-a-uuid") == []


# --- incidents (TA-03, TA-04, TA-07) -----------------------------------------------------------


async def test_an_impacted_trip_gets_a_safety_message_linked_to_the_incident(world: World) -> None:
    trip_id = await world.trip(world.people[:2], starts_in_days=-1, approved_at="CRITICAL")
    incident = await world.incident()
    await world.expose(incident, world.people[0])
    proposals = await world.run("EXPOSURE_COMPUTED", incident_id=str(incident))
    assert proposals == [
        (
            "NOTIFY_TRAVELLERS",
            f"NOTIFY_TRAVELLERS:impacted:{trip_id}:{incident}",
            2,
            str(incident),
        )
    ]


async def test_a_risen_risk_cancels_a_trip_not_started_and_warns_one_under_way(
    world: World,
) -> None:
    later = await world.trip(world.people[:2], starts_in_days=5)  # approved at LOW
    under_way = await world.trip(world.people[2:4], starts_in_days=-1)
    impacted = await world.trip(world.people[4:5], starts_in_days=-1)
    over = await world.trip(world.people[5:6], starts_in_days=-10)  # ended last week
    incident = await world.incident("CRITICAL")
    await world.expose(incident, world.people[4])
    proposals = await world.run("EXPOSURE_COMPUTED", incident_id=str(incident))
    keys = {k for _, k, _, _ in proposals}
    assert keys == {
        f"CANCEL_TRIP:risk:{later}:CRITICAL",
        f"NOTIFY_TRAVELLERS:risk:{under_way}:CRITICAL",
        f"NOTIFY_TRAVELLERS:impacted:{impacted}:{incident}",  # impacted only, not also risk
    }
    assert not any(str(over) in k for k in keys)
    cancel = (
        await world.sql(
            "SELECT alternatives, effective_level FROM agent_proposal "
            "WHERE action_type = 'CANCEL_TRIP'"
        )
    )[0]
    assert cancel[1] == 2
    assert cancel[0][0]["action_type"] == "NOTIFY_TRAVELLERS"  # D-14: notify instead
    assert cancel[0][0]["action_payload"]["trip_id"] == str(later)


@pytest.mark.parametrize(
    ("severity", "approved_at", "expected"),
    [
        ("MODERATE", "LOW", 0),  # the destination is not HIGH or above
        ("HIGH", "HIGH", 0),  # not above what was approved
        ("HIGH", "LOW", 1),
        ("CRITICAL", "HIGH", 1),
    ],
)
async def test_only_a_rise_to_high_or_above_past_the_approval_counts(
    world: World, severity: str, approved_at: str, expected: int
) -> None:
    await world.trip(world.people[:2], starts_in_days=5, approved_at=approved_at)
    incident = await world.incident(severity)
    assert len(await world.run("EXPOSURE_COMPUTED", incident_id=str(incident))) == expected


async def test_a_higher_level_later_is_a_new_proposal(world: World) -> None:
    trip_id = await world.trip(world.people[:2], starts_in_days=5)
    high = await world.incident("HIGH")
    await world.run("EXPOSURE_COMPUTED", incident_id=str(high))
    critical = await world.incident("CRITICAL")
    proposals = await world.run("EXPOSURE_COMPUTED", incident_id=str(critical))
    assert [k for _, k, _, _ in proposals] == [
        f"CANCEL_TRIP:risk:{trip_id}:HIGH",
        f"CANCEL_TRIP:risk:{trip_id}:CRITICAL",
    ]


async def test_nothing_about_restricted_trips_or_closed_incidents(world: World) -> None:
    """TA-07, D-33."""
    await world.trip(world.people[:2], starts_in_days=5, restricted=True)
    impacted = await world.trip(world.people[2:3], starts_in_days=-1, restricted=True)
    incident = await world.incident("CRITICAL")
    await world.expose(incident, world.people[2])
    assert await world.run("EXPOSURE_COMPUTED", incident_id=str(incident)) == []
    closed = await world.incident("CRITICAL", status="MONITORING")
    await world.trip(world.people[3:4], starts_in_days=5)
    assert await world.run("EXPOSURE_COMPUTED", incident_id=str(closed)) == []
    assert impacted


async def test_the_kill_switch_stops_the_agent(db: DbUrls, world: World) -> None:
    """D-17: the database refuses new proposals while agents are paused."""
    await world.trip(world.people[:2], starts_in_days=5)
    admin = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        await admin.execute("UPDATE tenant SET agents_paused = true WHERE id = $1", world.tenant)
    finally:
        await admin.close()
    incident = await world.incident("CRITICAL")
    assert await world.run("EXPOSURE_COMPUTED", incident_id=str(incident)) == []
