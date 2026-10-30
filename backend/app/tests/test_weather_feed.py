"""The simulated weather feed, scenario overrides and GET /api/weather (Prompt 40; WX-01,
WX-08, D-35, docs/plan-pilot-wx.md §2). Time is passed in, so every rule is exact."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event
from app.modules.audit.models import AuditLog
from app.modules.people.models import Mission
from app.modules.weather import feed
from app.modules.weather.models import WeatherCurrent
from app.tests.auth_helpers import Idp
from app.tests.conftest import DbUrls, create_tenant
from app.tests.fakes import ListPublisher

T0 = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
CITIES = [  # (code, city, lat, lon): a spread of the seed's missions
    ("MNL", "Manila", 14.6, 120.98),
    ("MOW", "Moscow", 55.75, 37.6),
    ("RUH", "Riyadh", 24.71, 46.68),
    ("CBR", "Canberra", -35.28, 149.13),
    ("YOW", "Ottawa", 45.42, -75.7),
]
STORM = {
    "mission_code": "MNL",
    "condition": "STORM",
    "temperature_c": 26.0,
    "wind_kph": 110,
    "gust_kph": 150,
    "rain_mm": 60,
}


class Weather:
    def __init__(self, idp: Idp) -> None:
        self.idp = idp
        self.publisher = ListPublisher()

    async def tick(self, at: datetime) -> int:
        return await feed.tick(self.idp.engine, self.idp.tenant_id, self.publisher, now=lambda: at)

    async def feed(self, at: datetime, **payload: Any) -> None:
        handle = feed.feed_handler(self.idp.engine, self.publisher, now=lambda: at)
        await handle(
            Event(type="WEATHER_FEED", tenant_id=self.idp.tenant_id, payload=payload, source="test")
        )

    async def rows(self) -> dict[str, WeatherCurrent]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            rows = await session.execute(
                select(Mission.code, WeatherCurrent).join(
                    Mission, Mission.id == WeatherCurrent.mission_id
                )
            )
            return {code: row for code, row in rows}

    async def audited(self, action: str) -> list[AuditLog]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
                )
            )


@pytest.fixture
async def weather(idp: Idp) -> Weather:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for code, city, lat, lon in CITIES:
            await session.execute(
                text(
                    "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
                    "(current_tenant_id(), :code, :city, 'XX', "
                    "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
                ),
                {"code": code, "city": city, "lat": lat, "lon": lon},
            )
        await session.commit()
    return Weather(idp)


# --- the conditions model ---------------------------------------------------------------------


def test_the_same_moment_gives_the_same_weather() -> None:
    assert feed.conditions("MNL", 14.6, 120.98, T0) == feed.conditions("MNL", 14.6, 120.98, T0)
    week = [feed.conditions("MNL", 14.6, 120.98, T0 + timedelta(days=n)) for n in range(7)]
    assert len({(c.condition, c.wind_kph) for c in week}) > 1  # it varies from day to day


def test_conditions_stay_within_pc20_all_year() -> None:
    """Every hour of a year, every city: the values the schema accepts (PC-20)."""
    for code, _city, lat, lon in CITIES:
        for hours in range(0, 365 * 24, 7):
            c = feed.conditions(code, lat, lon, T0 + timedelta(hours=hours))
            assert -60 <= c.temperature_c <= 60
            assert c.condition in ("CLEAR", "CLOUD", "RAIN", "FOG", "SNOW")
            assert 0 <= c.wind_kph <= c.gust_kph <= 400
            assert 0 <= c.rain_mm <= 1000
            assert (c.rain_mm > 0) is (c.condition in ("RAIN", "SNOW"))


def test_conditions_are_plausible() -> None:
    """Warmer in the tropics, in local summer and in the afternoon."""

    def mean(code: str, lat: float, lon: float, start: datetime, hours: list[int]) -> float:
        days = [start + timedelta(days=d) for d in range(30)]
        values = [
            float(feed.conditions(code, lat, lon, day + timedelta(hours=h)).temperature_c)
            for day in days
            for h in hours
        ]
        return sum(values) / len(values)

    january = datetime(2026, 1, 1, tzinfo=UTC)
    july = datetime(2026, 7, 1, tzinfo=UTC)
    every_hour = list(range(24))
    assert mean("MNL", 14.6, 120.98, january, every_hour) > mean(
        "MOW", 55.75, 37.6, january, every_hour
    )
    assert mean("MOW", 55.75, 37.6, july, every_hour) > mean(
        "MOW", 55.75, 37.6, january, every_hour
    )
    assert mean("CBR", -35.28, 149.13, january, every_hour) > mean(
        "CBR", -35.28, 149.13, july, every_hour
    )
    # Manila is UTC+8 (solar): 07:00 UTC is 15:00 local, 21:00 UTC is 05:00 local.
    assert mean("MNL", 14.6, 120.98, january, [7]) > mean("MNL", 14.6, 120.98, january, [21])
    assert any(
        feed.conditions("MOW", 55.75, 37.6, january + timedelta(days=d)).condition == "SNOW"
        for d in range(60)
    )


# --- the tick ---------------------------------------------------------------------------------


async def test_a_tick_writes_every_mission_once_audited(weather: Weather) -> None:
    assert await weather.tick(T0) == len(CITIES)
    rows = await weather.rows()
    assert sorted(rows) == sorted(code for code, *_ in CITIES)
    manila = rows["MNL"]
    expected = feed.conditions("MNL", 14.6, 120.98, T0)
    assert (manila.observed_at, manila.source, manila.condition, manila.temperature_c) == (
        T0,
        "xWeather (simulated)",
        expected.condition,
        expected.temperature_c,
    )
    [refresh] = await weather.audited("WEATHER.REFRESH")
    assert (refresh.actor_type, refresh.actor_id, refresh.details) == (
        "SYSTEM",
        "weather.feed",
        {"missions": 5, "of": 5},
    )
    assert [e.type for e in weather.publisher.events] == ["WEATHER_UPDATED"]

    later = T0 + timedelta(minutes=15)
    assert await weather.tick(later) == len(CITIES)
    assert (await weather.rows())["MNL"].observed_at == later
    assert len(await weather.audited("WEATHER.REFRESH")) == 2


async def test_an_older_observation_never_replaces_a_newer_one(weather: Weather) -> None:
    await weather.tick(T0)
    assert await weather.tick(T0 - timedelta(minutes=15)) == 0
    assert (await weather.rows())["MNL"].observed_at == T0
    assert len(await weather.audited("WEATHER.REFRESH")) == 1  # nothing written, nothing audited
    assert len(weather.publisher.events) == 1


# --- scenario overrides (WEATHER_FEED, plan G-1) ----------------------------------------------


async def test_an_override_holds_for_6_hours_then_the_cycle_returns(weather: Weather) -> None:
    await weather.tick(T0)
    await weather.feed(T0 + timedelta(minutes=1), **STORM)
    manila = (await weather.rows())["MNL"]
    assert (manila.condition, manila.wind_kph, manila.gust_kph, manila.rain_mm, manila.source) == (
        "STORM",
        110,
        150,
        Decimal("60.0"),
        "xWeather (simulated, scenario)",
    )
    [override] = await weather.audited("WEATHER.OVERRIDE")
    assert (override.entity_id, override.details["condition"]) == ("MNL", "STORM")
    assert weather.publisher.events[-1].type == "WEATHER_UPDATED"

    # The tick within the hold updates every other city and leaves Manila's storm alone.
    assert await weather.tick(T0 + timedelta(hours=6)) == len(CITIES) - 1
    rows = await weather.rows()
    assert rows["MNL"].condition == "STORM"
    assert rows["MOW"].observed_at == T0 + timedelta(hours=6)

    # A later scenario update replaces its own row, and holds again from then.
    await weather.feed(T0 + timedelta(hours=6, minutes=30), **{**STORM, "wind_kph": 130})
    assert (await weather.rows())["MNL"].wind_kph == 130

    back = T0 + timedelta(hours=12, minutes=31)
    assert await weather.tick(back) == len(CITIES)
    manila = (await weather.rows())["MNL"]
    assert (manila.source, manila.observed_at) == ("xWeather (simulated)", back)


@pytest.mark.parametrize(
    "change",
    [
        {"condition": "TORNADO"},
        {"condition": None},
        {"wind_kph": 401},
        {"wind_kph": -1},
        {"wind_kph": "fast"},
        {"wind_kph": True},
        {"gust_kph": 100},  # below the wind
        {"temperature_c": 61},
        {"temperature_c": float("nan")},
        {"rain_mm": 1001},
        {"mission_code": None},
        {"mission_code": "X" * 11},
    ],
)
async def test_a_malformed_feed_is_dropped(weather: Weather, change: dict[str, Any]) -> None:
    await weather.feed(T0, **{**STORM, **change})
    assert await weather.rows() == {}
    assert weather.publisher.events == []
    assert await weather.audited("WEATHER.OVERRIDE") == []


async def test_a_feed_for_an_unknown_or_other_tenants_mission_is_ignored(
    weather: Weather, idp: Idp, db: DbUrls
) -> None:
    """The mission is looked up through the tenant's session (RLS): another tenant's
    mission with that code is invisible, so nothing is written for it."""
    other = await create_tenant(db, "Other")
    async with tenant_session(other, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
                "(current_tenant_id(), 'ZZZ', 'Elsewhere', 'XX', 'SRID=4326;POINT(1 1)')"
            )
        )
        await session.commit()
    await weather.feed(T0, **{**STORM, "mission_code": "ZZZ"})
    assert await weather.rows() == {}
    assert weather.publisher.events == []
    async with tenant_session(other, idp.engine) as session:
        assert (await session.execute(text("SELECT count(*) FROM weather_current"))).scalar() == 0


async def test_gusts_default_to_the_wind_and_rain_to_zero(weather: Weather) -> None:
    await weather.feed(T0, mission_code="MNL", condition="CLOUD", temperature_c=28.54, wind_kph=45)
    manila = (await weather.rows())["MNL"]
    assert (manila.gust_kph, manila.rain_mm, manila.temperature_c) == (
        45,
        Decimal("0.0"),
        Decimal("28.5"),
    )


# --- the API ----------------------------------------------------------------------------------


async def test_every_role_reads_the_weather_with_stale_flagged(
    weather: Weather, idp: Idp, client: AsyncClient
) -> None:
    await idp.user("viewer", [("VIEWER", None)])
    now = datetime.now(UTC)
    await weather.tick(now - timedelta(minutes=31))
    await weather.feed(now, **STORM)
    response = await client.get("/api/weather", headers=idp.headers("viewer"))
    assert response.status_code == 200
    body = {w["mission_code"]: w for w in response.json()}
    assert sorted(body) == sorted(code for code, *_ in CITIES)
    manila = body["MNL"]
    assert {k: manila[k] for k in ("city", "condition", "wind_kph", "gust_kph", "stale")} == {
        "city": "Manila",
        "condition": "STORM",
        "wind_kph": 110,
        "gust_kph": 150,
        "stale": False,
    }
    assert (manila["lat"], manila["lon"]) == pytest.approx((14.6, 120.98))
    assert manila["source"] == "xWeather (simulated, scenario)"
    assert body["MOW"]["stale"] is True  # older than 30 minutes (plan G-6)
    assert (await client.get("/api/weather")).status_code == 401
