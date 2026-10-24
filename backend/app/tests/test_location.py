"""Location Confidence Engine (PPL-03, plan G-13)."""

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.modules.people import location
from app.modules.people.models import PersonLocationCurrent
from app.modules.people.service import ObservationIn, PersonIn, add_observations, load_persons
from app.tests.conftest import DbUrls, create_tenant, set_tenant

AS_OF = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("source", "raw", "age", "expected"),
    [
        ("MOBILE_GPS", {"accuracy_m": 20}, timedelta(0), 98),
        ("MOBILE_GPS", {"accuracy_m": 90}, timedelta(0), 91),  # Peter Mwangi
        ("MOBILE_GPS", {"accuracy_m": 20}, timedelta(minutes=30), 92),  # 12 points/hour
        ("ACCESS_CONTROL", {}, timedelta(minutes=20), 97),
        ("CALENDAR_HR", None, timedelta(hours=10), 72),  # Hana Takeda: no decay
        ("TRAVEL_BOOKING", {}, timedelta(hours=30), 89),
        ("TRAVEL_BOOKING", {"quality": 92}, timedelta(0), 92),
        ("MANUAL", {}, timedelta(0), 60),
        ("ACCESS_CONTROL", {}, timedelta(hours=20), 0),  # never below zero
        ("CHECKIN", {"quality": 120}, timedelta(0), 95),  # quality only for some sources
        ("MANUAL", {"quality": 150}, timedelta(0), 99),  # capped
    ],
)
def test_confidence_formula(
    source: str, raw: dict[str, object] | None, age: timedelta, expected: int
) -> None:
    assert location.confidence(source, raw, AS_OF - age, AS_OF) == expected


@pytest.fixture
async def tenant(db: DbUrls) -> uuid.UUID:
    return await create_tenant(db)


async def _person(engine: AsyncEngine, tenant: uuid.UUID, obs: list[ObservationIn]) -> None:
    async with tenant_session(tenant, engine) as session:
        await load_persons(
            session,
            [PersonIn(id=obs[0].person_id, mission_id=None, person_type="DIPLOMAT", full_name="P")],
        )
        await add_observations(session, obs)
        await session.commit()


def _obs(pid: uuid.UUID, source: str, age: timedelta, place: str, **raw: object) -> ObservationIn:
    return ObservationIn(pid, source, -1.29, 36.81, AS_OF - age, place, dict(raw))


async def test_best_observation_wins_and_recompute_is_idempotent(
    db: DbUrls, api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    pid = uuid.uuid4()
    await _person(
        api_engine,
        tenant,
        [
            _obs(pid, "CALENDAR_HR", timedelta(minutes=5), "Meeting"),  # 72
            _obs(pid, "MOBILE_GPS", timedelta(minutes=10), "Street", accuracy_m=30),  # 95
            _obs(pid, "ACCESS_CONTROL", timedelta(hours=100), "Old badge"),  # too old
            _obs(pid, "MOBILE_GPS", timedelta(minutes=-30), "Future", accuracy_m=10),  # ignored
        ],
    )
    async with tenant_session(tenant, api_engine) as session:
        assert await location.recompute(session, AS_OF) == 1
        assert await location.recompute(session, AS_OF) == 0  # unchanged, not re-audited
        await session.commit()

    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, tenant)
        row = await conn.fetchrow("SELECT * FROM person_location_current WHERE person_id = $1", pid)
        audits = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE action = 'LOCATION.RECOMPUTE'"
        )
    finally:
        await conn.close()
    assert row is not None
    assert (row["confidence"], row["primary_source"], row["place_label"]) == (
        95,
        "MOBILE_GPS",
        "Street",
    )
    assert row["computed_at"] == AS_OF
    assert audits == 1


async def test_later_as_of_lowers_confidence(api_engine: AsyncEngine, tenant: uuid.UUID) -> None:
    pid = uuid.uuid4()
    await _person(api_engine, tenant, [_obs(pid, "ACCESS_CONTROL", timedelta(0), "Embassy")])
    async with tenant_session(tenant, api_engine) as session:
        await location.recompute(session, AS_OF)
        assert await location.recompute(session, AS_OF + timedelta(hours=1)) == 1
        current = await session.get(PersonLocationCurrent, pid)
        assert current is not None
        assert current.confidence == 93  # 99 - 6 points after one hour


async def test_repeated_observations_are_not_duplicated(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    pid = uuid.uuid4()
    obs = [_obs(pid, "MANUAL", timedelta(0), "Home")]
    await _person(api_engine, tenant, obs)
    async with tenant_session(tenant, api_engine) as session:
        assert await add_observations(session, obs) == 0
