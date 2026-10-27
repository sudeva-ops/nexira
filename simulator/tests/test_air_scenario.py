"""NBO-AIR-DIVERSION through the real player and the tracker's feed handler (Prompt 30;
D-33, docs/plan-pilot-air.md G-1..G-3). XW 451 holds near Nairobi, diverts to Mombasa
and lands; its three London travellers are then in Mombasa, and the restricted trip's
flight never exists."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from app.core.db import create_engine, tenant_session
from app.modules.scenarios.player import Player
from app.modules.scenarios.service import get_scenario, load_events
from app.modules.travel import tracker
from app.tests.conftest import DbUrls
from app.tests.fakes import FakeClock, ListPublisher
from sqlalchemy import text

from nexira_sim.scenarios import nbo_air_diversion as air
from nexira_sim.seed.load import seed_all

pytestmark = pytest.mark.asyncio(loop_scope="module")

DAY = date(2026, 10, 20)


class Played:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.flights: list[tuple[str, str, str | None, str]] = []
        self.located: set[str] = set()
        self.events: list[str] = []


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed_all(
            engine,
            owner_dsn=db.owner,
            issuer=f"https://kc.test/realms/air-{tenant_id}",
            scenario_date=DAY,
            tenant_id=tenant_id,
        )
        async with tenant_session(tenant_id, engine) as session:
            scenario = await get_scenario(session, air.CODE)
            assert scenario is not None
            events = await load_events(session, scenario.id)
        clock, stream = FakeClock(), ListPublisher()
        player = Player(
            code=air.CODE,
            tenant_id=tenant_id,
            run_id=uuid.uuid4(),
            events=events,
            publisher=stream,
            clock=clock,
        )
        published = ListPublisher()
        now = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
        feed = tracker.feed_handler(engine, published, now=lambda: now)
        await tracker.tick(engine, tenant_id, published, now=lambda: now)  # creates nothing new
        for _ in range(3):  # scenes 1-3
            await player.next()
            await clock.advance(air.LANDED_AFTER_MS / 1000 + 1)
            for event in stream.events[len(result.events) :]:
                result.events.append(event.type)
                if event.type == "FLIGHT_FEED":
                    now += timedelta(seconds=30)
                    await feed(event)
            async with tenant_session(tenant_id, engine) as session:
                status = await session.scalar(
                    text("SELECT status FROM flight WHERE flight_number = 'XW 451'")
                )
            result.statuses.append(str(status))
        async with tenant_session(tenant_id, engine) as session:
            rows = await session.execute(
                text(
                    "SELECT f.flight_number, f.status, f.diverted_to, t.reference FROM flight f "
                    "JOIN trip_segment s ON s.id = f.trip_segment_id "
                    "JOIN trip t ON t.id = s.trip_id"
                )
            )
            result.flights = [tuple(r) for r in rows]
            located = await session.execute(
                text(
                    "SELECT DISTINCT c.place_label FROM person_location_current c "
                    "JOIN trip_traveller tt ON tt.person_id = c.person_id "
                    "JOIN trip t ON t.id = tt.trip_id WHERE t.reference = 'TRP-8818'"
                )
            )
            result.located = {r[0] for r in located}
    finally:
        await engine.dispose()
    return result


async def test_xw_451_holds_diverts_to_mombasa_and_lands(played: Played) -> None:
    assert played.statuses == ["AIRBORNE", "HOLDING", "LANDED"]
    assert played.events.count("FLIGHT_FEED") == 4


async def test_the_restricted_trips_flight_never_exists(played: Played) -> None:
    # The background flights (TRP-8819, TRP-8820, plan G-4) fly around the seed time, so
    # they may be tracked too; the restricted TRP-8813 never is (D-33).
    by_trip = {
        trip: (number, status, diverted) for number, status, diverted, trip in played.flights
    }
    assert by_trip["TRP-8818"] == ("XW 451", "LANDED", "MBA")
    assert "TRP-8813" not in by_trip
    assert set(by_trip) <= {"TRP-8818", "TRP-8819", "TRP-8820"}


async def test_the_travellers_are_in_mombasa(played: Played) -> None:
    assert played.located == {"Mombasa · Mombasa Moi (landed, XW 451)"}
