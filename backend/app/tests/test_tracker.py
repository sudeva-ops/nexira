"""The simulated flight tracker, its feed and the flights API (Prompt 30; AT-01..08, D-33,
docs/plan-pilot-air.md §2-4). Time is passed in, so every transition is exact."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.people.service import PersonIn, load_persons
from app.modules.travel import tracker
from app.modules.travel.models import Flight, FlightEvent, TripSegment
from app.modules.travel.service import (
    AirportIn,
    SegmentSeed,
    ensure_airports,
    ensure_scenario_flight,
    ensure_trip,
)
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

T0 = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
AIRPORTS = [
    AirportIn("AUH", "Abu Dhabi", "Abu Dhabi", "AE", 24.43, 54.65),
    AirportIn("NBO", "Nairobi Jomo Kenyatta", "Nairobi", "KE", -1.32, 36.93),
    AirportIn("MBA", "Mombasa Moi", "Mombasa", "KE", -4.03, 39.59),
    AirportIn("LHR", "London Heathrow", "London", "GB", 51.47, -0.45),
]


@dataclass
class World:
    idp: Idp
    people: list[uuid.UUID]
    users: dict[str, uuid.UUID]
    publisher: ListPublisher

    async def trip(
        self,
        number: str | None = "XW 451",
        departs: timedelta = timedelta(hours=1),
        hours: float = 4,
        status: str = "APPROVED",
        restricted: bool = False,
        scenario: bool = False,
        requested_by: uuid.UUID | None = None,
    ) -> uuid.UUID:
        trip_id = uuid.uuid4()
        start = T0 + departs
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            await ensure_trip(
                session,
                trip_id=trip_id,
                reference=f"TRP-{trip_id.hex[:6]}",
                purpose="Consultations",
                origin="Abu Dhabi",
                destination="Nairobi",
                destination_country="KE",
                starts_on=(start - timedelta(days=1)).date(),
                ends_on=(start + timedelta(days=2)).date(),
                traveller_ids=self.people,
                approval_status=status,
                restricted=restricted,
                requested_by=requested_by,
                segments=[
                    SegmentSeed(
                        kind="FLIGHT",
                        title=number or "Flight",
                        place_label="AUH → NBO",
                        starts_at=start,
                        ends_at=start + timedelta(hours=hours),
                        flight_number=number,
                        from_airport="AUH" if number else None,
                        to_airport="NBO" if number else None,
                    )
                ],
            )
            if scenario:
                await ensure_scenario_flight(session, trip_id)
            await session.commit()
        return trip_id

    async def tick(self, at: datetime) -> tracker.Result:
        return await tracker.tick(
            self.idp.engine, self.idp.tenant_id, self.publisher, now=lambda: at
        )

    async def feed(self, at: datetime, **payload: Any) -> None:
        handle = tracker.feed_handler(self.idp.engine, self.publisher, now=lambda: at)
        await handle(
            Event(
                type="FLIGHT_FEED",
                tenant_id=self.idp.tenant_id,
                payload={"flight_number": "XW 451", "date": "2026-10-27", **payload},
                source="test",
            )
        )

    async def flight(self, trip_id: uuid.UUID) -> Flight:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            flight = await session.scalar(
                select(Flight)
                .join(TripSegment, TripSegment.id == Flight.trip_segment_id)
                .where(TripSegment.trip_id == trip_id)
            )
        assert flight is not None
        return flight

    async def tracked(self, trip_id: uuid.UUID) -> bool:
        rows = await self.sql(
            "SELECT count(*) FROM flight f JOIN trip_segment s ON s.id = f.trip_segment_id "
            "WHERE s.trip_id = :trip",
            trip=trip_id,
        )
        return bool(rows[0][0])

    async def events(self, trip_id: uuid.UUID) -> list[tuple[str, dict[str, Any]]]:
        flight = await self.flight(trip_id)
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            rows = await session.scalars(
                select(FlightEvent)
                .where(FlightEvent.flight_id == flight.id)
                .order_by(FlightEvent.id)
            )
            return [(e.event_type, e.details) for e in rows]

    async def sql(self, query: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(query), params)
            rows = result.all() if query.lstrip().upper().startswith("SELECT") else []
            await session.commit()
            return rows


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    mission = await idp.mission("LON")
    people = [uuid.uuid4() for _ in range(3)]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_airports(session, AIRPORTS)
        await load_persons(
            session,
            [
                PersonIn(p, mission, "DIPLOMAT", f"Fictional Officer {n}")
                for n, p in enumerate(people)
            ],
        )
        await session.commit()
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "desk": [("TRAVEL_DESK", None)],
        "security": [("SECURITY_OFFICER", None)],
        "duty": [("DUTY_OFFICER", None)],
        "admin": [("ADMIN", None)],
        "viewer": [("VIEWER", None)],
    }
    users = {sub: await idp.user(sub, roles) for sub, roles in grants.items()}
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, people, users, publisher)


# --- which flights are tracked (AT-01, AT-05) -----------------------------------------------


async def test_only_approved_unrestricted_flights_due_within_a_day_are_tracked(
    world: World,
) -> None:
    tracked = await world.trip()
    restricted = await world.trip(number="XW 777", restricted=True)
    others = [
        await world.trip(number="XW 101", status="DRAFT"),
        await world.trip(number="XW 102", status="PENDING"),
        await world.trip(number="XW 103", departs=timedelta(hours=30)),  # beyond 24 h
        await world.trip(number="XW 104", departs=timedelta(hours=-6)),  # already due to land
        await world.trip(number=None),  # a flight segment without a flight number
    ]
    await world.tick(T0)
    assert await world.tracked(tracked)
    for trip_id in [restricted, *others]:
        assert not await world.tracked(trip_id)
    # Nothing about the restricted trip's flight anywhere (D-33).
    mentions = await world.sql("SELECT count(*) FROM audit_log WHERE details::text LIKE '%XW 777%'")
    assert mentions[0][0] == 0
    assert all(e.payload.get("flight_number") != "XW 777" for e in world.publisher.events)


async def test_tracking_is_idempotent(world: World) -> None:
    trip_id = await world.trip()
    await world.tick(T0)
    await world.tick(T0 + timedelta(seconds=5))
    rows = await world.sql("SELECT count(*) FROM audit_log WHERE action = 'FLIGHT.TRACK'")
    assert rows[0][0] == 1
    assert await world.tracked(trip_id)


# --- the clock (SIMULATED flights) ------------------------------------------------------------


async def test_a_flight_departs_flies_and_lands_moving_its_travellers(world: World) -> None:
    trip_id = await world.trip(departs=timedelta(hours=1), hours=4)
    await world.tick(T0)
    assert (await world.flight(trip_id)).status == "SCHEDULED"
    await world.tick(T0 + timedelta(hours=1))
    flight = await world.flight(trip_id)
    assert flight.status == "AIRBORNE"
    await world.tick(T0 + timedelta(hours=3))  # half way
    row = (
        await world.sql(
            "SELECT ST_Y(position::geometry), ST_X(position::geometry), altitude_ft, speed_kt "
            "FROM flight WHERE id = :id",
            id=flight.id,
        )
    )[0]
    assert -1.3 < row[0] < 24.4  # between Abu Dhabi and Nairobi
    assert 36.9 < row[1] < 54.7
    assert (row[2], row[3]) == (37_000, 460)
    await world.tick(T0 + timedelta(hours=5))
    assert [e for e, _ in await world.events(trip_id)] == ["DEPARTED", "LANDED"]
    located = await world.sql(
        "SELECT primary_source, place_label FROM person_location_current WHERE person_id = ANY(:p)",
        p=world.people,
    )
    assert len(located) == 3
    assert {(source, label) for source, label in located} == {
        ("FLIGHT", "Nairobi · Nairobi Jomo Kenyatta (landed, XW 451)")
    }
    assert [e.payload["status"] for e in world.publisher.events if e.type == "FLIGHT_UPDATED"] == [
        "SCHEDULED",
        "AIRBORNE",
        "LANDED",
    ]
    assert any(e.type == "FLIGHT_POSITIONS" for e in world.publisher.events)
    actions = await world.sql(
        "SELECT action FROM audit_log WHERE action LIKE 'FLIGHT.%' ORDER BY id"
    )
    assert [a for (a,) in actions] == ["FLIGHT.TRACK", "FLIGHT.DEPARTED", "FLIGHT.LANDED"]


async def test_a_cancelled_trip_cancels_its_flight_only_before_departure(world: World) -> None:
    later = await world.trip(number="XW 200", departs=timedelta(hours=2))
    flying = await world.trip(number="XW 201", departs=timedelta(hours=1))
    await world.tick(T0 + timedelta(hours=1, minutes=5))
    await world.sql(
        "UPDATE trip SET approval_status = 'CANCELLED' WHERE id = ANY(:t)", t=[later, flying]
    )
    await world.tick(T0 + timedelta(hours=1, minutes=10))
    cancelled, in_air = await world.flight(later), await world.flight(flying)
    assert (cancelled.status, in_air.status) == ("CANCELLED", "AIRBORNE")  # never cancelled aloft
    assert await world.events(later) == [("CANCELLED", {"reason": "trip cancelled"})]


# --- the feed (FLIGHT_FEED) -------------------------------------------------------------------


async def test_a_delay_of_30_minutes_or_more_is_recorded(world: World) -> None:
    trip_id = await world.trip(departs=timedelta(hours=3))
    await world.tick(T0)
    await world.feed(T0, delay_min=10)
    flight = await world.flight(trip_id)
    assert (flight.status, await world.events(trip_id)) == ("SCHEDULED", [])
    await world.feed(T0, delay_min=45)
    flight = await world.flight(trip_id)
    assert flight.status == "DELAYED"
    assert flight.estimated_dep - flight.scheduled_dep == timedelta(minutes=45)
    assert await world.events(trip_id) == [("DELAYED", {"minutes": 45})]
    # The clock takes a delayed flight off at its new estimate.
    await world.tick(T0 + timedelta(hours=3, minutes=45))
    flight = await world.flight(trip_id)
    assert flight.status == "AIRBORNE"


async def test_a_scenario_flight_moves_only_through_the_feed(world: World) -> None:
    """Plan G-3: XW 451 holds near Nairobi, diverts to Mombasa and lands there."""
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)  # long past
    await world.tick(T0)
    flight = await world.flight(trip_id)
    assert (flight.status, flight.source) == ("SCHEDULED", "SCENARIO")  # the clock never lands it
    await world.feed(T0, status="AIRBORNE", departed_min_ago=230, arrives_in_min=10)
    await world.tick(T0 + timedelta(minutes=30))  # past the estimate: still in the air
    flight = await world.flight(trip_id)
    assert flight.status == "AIRBORNE"
    await world.feed(T0 + timedelta(minutes=31), status="HOLDING", reason="Arrivals restricted")
    await world.tick(T0 + timedelta(minutes=32))
    near = await world.sql(
        "SELECT ST_Distance(f.position, a.location) FROM flight f, airport a "
        "WHERE f.id = :id AND a.iata = 'NBO'",
        id=flight.id,
    )
    assert 10_000 < near[0][0] < 45_000  # circling about 30 km out
    await world.feed(T0 + timedelta(minutes=40), status="DIVERTED", to="MBA", arrives_in_min=1)
    await world.feed(T0 + timedelta(minutes=41), status="LANDED")
    flight = await world.flight(trip_id)
    assert (flight.status, flight.diverted_to) == ("LANDED", "MBA")
    assert [e for e, _ in await world.events(trip_id)] == [
        "DEPARTED",
        "HOLDING",
        "DIVERTED",
        "LANDED",
    ]
    located = await world.sql(
        "SELECT DISTINCT place_label FROM person_location_current WHERE person_id = ANY(:p)",
        p=world.people,
    )
    assert located == [("Mombasa · Mombasa Moi (landed, XW 451)",)]
    await world.feed(T0 + timedelta(minutes=50), status="HOLDING")  # after landing: ignored
    assert len(await world.events(trip_id)) == 4


async def test_the_feed_ignores_untracked_and_restricted_flights(world: World) -> None:
    await world.trip(number="XW 451", restricted=True)
    await world.tick(T0)
    await world.feed(T0, status="AIRBORNE", arrives_in_min=10)
    assert (await world.sql("SELECT count(*) FROM flight"))[0][0] == 0


async def test_a_landing_near_an_active_incident_recomputes_its_exposure(world: World) -> None:
    """Plan G-5."""
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)
    await world.sql(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        "location, impact_radius_m) VALUES (current_tenant_id(), 'INC-MBA', 'Unrest', "
        "'CIVIL_UNREST', 'HIGH', 'HIGH', 'SRID=4326;POINT(39.6 -4.03)', 5000)"
    )
    await world.tick(T0)
    await world.feed(T0, status="AIRBORNE", arrives_in_min=10)
    await world.feed(T0, status="DIVERTED", to="MBA", arrives_in_min=1)
    await world.feed(T0 + timedelta(minutes=2), status="LANDED")
    assert any(e.type == "EXPOSURE_COMPUTED" for e in world.publisher.events)
    exposed = await world.sql(
        "SELECT count(*) FROM incident_exposure e JOIN incident i ON i.id = e.incident_id "
        "WHERE i.reference = 'INC-MBA' AND e.subject_type = 'PERSON' AND e.subject_id = ANY(:p)",
        p=world.people,
    )
    assert exposed[0][0] == 3
    assert await world.tracked(trip_id)


# --- the flights API (AT-02, AT-03, AT-07) ------------------------------------------------------


async def test_flights_are_listed_with_route_travellers_and_events(
    client: AsyncClient, world: World
) -> None:
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)
    await world.trip(number="XW 777", restricted=True, departs=timedelta(minutes=10))
    await world.tick(T0)
    await world.feed(T0, status="AIRBORNE", arrives_in_min=10)
    await world.feed(T0, status="HOLDING", reason="Arrivals restricted")
    headers = world.idp.headers("viewer")
    listed = (await client.get("/api/flights", headers=headers)).json()
    assert [f["flight_number"] for f in listed] == ["XW 451"]  # never the restricted trip
    flight = listed[0]
    assert (flight["status"], flight["disrupted"], flight["simulated"]) == ("HOLDING", True, True)
    assert (flight["from_city"], flight["to_city"], flight["trip_id"]) == (
        "Abu Dhabi",
        "Nairobi",
        str(trip_id),
    )
    assert sorted(flight["travellers"]) == [f"Fictional Officer {n}" for n in range(3)]
    assert len(flight["route"]) == 2
    assert (await client.get("/api/flights?disrupted=false", headers=headers)).json() == []
    detail = (await client.get(f"/api/flights/{flight['id']}", headers=headers)).json()
    assert [e["event_type"] for e in detail["events"]] == ["DEPARTED", "HOLDING"]
    assert detail["events"][1]["details"] == {"reason": "Arrivals restricted"}
    missing = await client.get(f"/api/flights/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    airports = (await client.get("/api/airports", headers=headers)).json()
    assert [a["iata"] for a in airports] == ["AUH", "LHR", "MBA", "NBO"]


# --- the trip API: flight segments, restricted trips, G-7 -------------------------------------


def plan(world: World, **extra: Any) -> dict[str, Any]:
    start = (T0 + timedelta(days=30)).replace(hour=6)
    segment = {
        "kind": "FLIGHT",
        "title": "XW 451",
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=4)).isoformat(),
        "flight_number": "XW 451",
        "from_airport": "AUH",
        "to_airport": "NBO",
    }
    segment.update(extra.pop("segment", {}))
    return {
        "origin": "Abu Dhabi",
        "destination": "Nairobi",
        "destination_country": "KE",
        "starts_on": start.date().isoformat(),
        "ends_on": (start + timedelta(days=2)).date().isoformat(),
        "travellers": [str(p) for p in world.people],
        "segments": [segment],
        **extra,
    }


@pytest.mark.parametrize(
    ("segment", "message"),
    [
        ({"kind": "STAY"}, "are for FLIGHT segments"),
        ({"to_airport": None}, "needs its number and both airports"),
        ({"flight_number": "not 451!"}, "looks like XW 451"),
        ({"to_airport": "ZZZ"}, "unknown airport ZZZ"),
        ({"to_airport": "AUH"}, "same airport"),
    ],
)
async def test_flight_segments_are_validated(
    client: AsyncClient, world: World, segment: dict[str, Any], message: str
) -> None:
    response = await client.post(
        "/api/trips", json=plan(world, segment=segment), headers=world.idp.headers("desk")
    )
    assert response.status_code == 422
    assert message in response.text


async def test_a_planned_flight_segment_shows_its_tracked_status(
    client: AsyncClient, world: World
) -> None:
    created = await client.post("/api/trips", json=plan(world), headers=world.idp.headers("desk"))
    assert created.status_code == 201
    segment = created.json()["segments"][0]
    assert (segment["flight_number"], segment["from_airport"], segment["flight_status"]) == (
        "XW 451",
        "AUH",
        None,
    )
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)
    shown = (await client.get(f"/api/trips/{trip_id}", headers=world.idp.headers("viewer"))).json()
    assert shown["segments"][0]["flight_status"] == "SCHEDULED"
    assert shown["segments"][0]["flight_id"] is not None


async def test_a_restricted_trips_flight_segments_are_masked_for_most_roles(
    client: AsyncClient, world: World
) -> None:
    """Plan G-7 (approved 2026-10-27)."""
    created = await client.post(
        "/api/trips", json=plan(world, restricted=True), headers=world.idp.headers("duty")
    )
    assert created.status_code == 201
    trip_id = created.json()["id"]
    assert created.json()["restricted"] is True
    for sub in ("duty", "desk", "security", "admin"):  # duty: the requester
        segment = (
            await client.get(f"/api/trips/{trip_id}", headers=world.idp.headers(sub))
        ).json()["segments"][0]
        assert segment["flight_number"] == "XW 451", sub
    viewer = (await client.get(f"/api/trips/{trip_id}", headers=world.idp.headers("viewer"))).json()
    assert viewer["segments"][0] == {
        "seq": 1,
        "kind": "FLIGHT",
        "title": "Flight (restricted)",
        "place_label": None,
        "starts_at": None,
        "ends_at": None,
        "flight_number": None,
        "from_airport": None,
        "to_airport": None,
        "flight_id": None,
        "flight_status": None,
    }
    assert viewer["destination"] == "Nairobi"  # the trip itself stays visible (JR-08)


# --- review of Prompt 30 ---------------------------------------------------------------------


async def test_an_edit_without_restricted_keeps_it(client: AsyncClient, world: World) -> None:
    """M1: an edit never quietly un-restricts a trip."""
    created = await client.post(
        "/api/trips", json=plan(world, restricted=True), headers=world.idp.headers("desk")
    )
    trip_id = created.json()["id"]
    edited = await client.patch(
        f"/api/trips/{trip_id}", json=plan(world), headers=world.idp.headers("desk")
    )
    assert edited.status_code == 200
    assert edited.json()["restricted"] is True
    viewer = (await client.get(f"/api/trips/{trip_id}", headers=world.idp.headers("viewer"))).json()
    assert viewer["segments"][0]["flight_number"] is None


async def test_a_feed_updates_every_tracked_flight_with_that_number(world: World) -> None:
    """M2: two of our trips on the same physical flight."""
    first = await world.trip(departs=timedelta(hours=-10), scenario=True)
    second = await world.trip(departs=timedelta(hours=-10), scenario=True)
    await world.feed(T0, status="AIRBORNE", arrives_in_min=10)
    await world.feed(T0, status="HOLDING", reason="Arrivals restricted")
    assert {(await world.flight(t)).status for t in (first, second)} == {"HOLDING"}


async def test_a_refused_feed_change_leaves_the_flight_as_it_was(world: World) -> None:
    """L1: the transition is checked before anything is written."""
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)
    before = await world.flight(trip_id)
    await world.feed(T0, status="LANDED")
    await world.feed(T0, status="DIVERTED", to="MBA")
    after = await world.flight(trip_id)
    assert (after.status, after.diverted_to, after.position, after.estimated_arr) == (
        "SCHEDULED",
        None,
        before.position,
        before.estimated_arr,
    )
    assert await world.events(trip_id) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"delay_min": -100000},
        {"delay_min": "45"},
        {"delay_min": 10**9},
        {"status": "AIRBORNE", "arrives_in_min": -5},
        {"status": "AIRBORNE", "arrives_in_min": float("nan")},
        {"status": "TELEPORTED"},
        {"status": "DIVERTED"},
    ],
)
async def test_a_malformed_feed_is_dropped(world: World, payload: dict[str, Any]) -> None:
    """L2: bounded, typed; dropped rather than retried."""
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)
    before = await world.flight(trip_id)
    await world.feed(T0, **payload)
    after = await world.flight(trip_id)
    assert (after.status, after.estimated_dep, after.estimated_arr) == (
        before.status,
        before.estimated_dep,
        before.estimated_arr,
    )


async def test_a_delay_in_the_air_moves_only_the_arrival(world: World) -> None:
    """L3."""
    trip_id = await world.trip(departs=timedelta(hours=-1), hours=4)  # left on schedule
    await world.tick(T0)
    departed = (await world.flight(trip_id)).estimated_dep
    await world.feed(T0, delay_min=45, date=(T0 - timedelta(hours=1)).date().isoformat())
    flight = await world.flight(trip_id)
    assert flight.estimated_dep == departed
    assert flight.estimated_arr - flight.scheduled_arr == timedelta(minutes=45)
    assert flight.status == "AIRBORNE"


async def test_a_repeated_feed_records_nothing_new(world: World) -> None:
    """L4: the stream may redeliver."""
    trip_id = await world.trip(departs=timedelta(hours=-10), scenario=True)
    await world.feed(T0, status="AIRBORNE", arrives_in_min=10)
    for _ in range(2):
        await world.feed(T0, status="HOLDING", reason="Arrivals restricted")
        await world.feed(T0, delay_min=45)
    assert [e for e, _ in await world.events(trip_id)] == ["DEPARTED", "HOLDING", "DELAYED"]


async def test_a_large_incident_beyond_100_km_is_recomputed_too(world: World) -> None:
    """L7: the incident's own radius when it is larger than 100 km."""
    await world.trip(departs=timedelta(hours=-10), scenario=True)
    await world.sql(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        "location, impact_radius_m) VALUES (current_tenant_id(), 'INC-WIDE', 'Cyclone', "
        "'NATURAL_HAZARD', 'HIGH', 'HIGH', 'SRID=4326;POINT(41.5 -4.03)', 250000)"
    )
    await world.feed(T0, status="AIRBORNE", arrives_in_min=10)
    await world.feed(T0, status="DIVERTED", to="MBA", arrives_in_min=1)
    await world.feed(T0, status="LANDED")
    assert any(e.type == "EXPOSURE_COMPUTED" for e in world.publisher.events)


async def test_flight_status_filter_is_validated(client: AsyncClient, world: World) -> None:
    """L8."""
    response = await client.get("/api/flights?status=FLYING", headers=world.idp.headers("viewer"))
    assert response.status_code == 422


async def test_a_flight_number_with_a_trailing_newline_is_refused(
    client: AsyncClient, world: World
) -> None:
    """L9: the API check matches the database CHECK."""
    response = await client.post(
        "/api/trips",
        json=plan(world, segment={"flight_number": "XW 451\n"}),
        headers=world.idp.headers("desk"),
    )
    assert response.status_code == 422


async def test_masking_applies_to_action_responses_too(client: AsyncClient, world: World) -> None:
    """G-7 on a checklist tick by a Duty Officer who is not the requester."""
    created = await client.post(
        "/api/trips", json=plan(world, restricted=True), headers=world.idp.headers("desk")
    )
    trip_id = created.json()["id"]
    ticked = await client.post(
        f"/api/trips/{trip_id}/checklist",
        json={"item": "security_briefing", "done": True},
        headers=world.idp.headers("duty"),
    )
    assert ticked.status_code == 200
    assert ticked.json()["segments"][0]["title"] == "Flight (restricted)"
