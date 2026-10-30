"""Simulated weather feed (WX-01, WX-08; D-35, docs/plan-pilot-wx.md §2).

It plays the part of a weather provider: nothing external is called. It is the only
writer of weather_current. A real provider later replaces conditions() and the
WEATHER_FEED consumer, nothing else.

- tick(): per tenant, every 15 minutes: plausible conditions for every mission from its
  latitude, the season and the local solar hour, with a stable variation per city and
  day (the same moment always gives the same weather), upserted into weather_current.
- feed_handler(): WEATHER_FEED events (the scenario player): one mission's conditions,
  written with source SCENARIO_SOURCE.

Plan G-1: the tick leaves a row alone while its source is the scenario's and it was
written within HOLD, so a storm does not clear itself mid-demo. Neither writer replaces
a row with an older observation. Warnings are not written here: they are RAW_SIGNAL
events of the xWeather source, through the intel pipeline.

Each tick is audited once (WEATHER.REFRESH) and each scenario override once
(WEATHER.OVERRIDE); WEATHER_UPDATED is published after commit.
"""

import hashlib
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.tenancy.service import Actor
from app.modules.weather.models import WeatherCurrent

log = logging.getLogger(__name__)

Now = Callable[[], datetime]

FEED = Actor(type="SYSTEM", id="weather.feed")
SOURCE = "xWeather (simulated)"
SCENARIO_SOURCE = "xWeather (simulated, scenario)"
HOLD = timedelta(hours=6)  # plan G-1
STALE_AFTER = timedelta(minutes=30)  # WX §28 Q2
CONDITIONS = ("CLEAR", "CLOUD", "RAIN", "STORM", "DUST", "FOG", "SNOW")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Conditions:
    temperature_c: Decimal
    condition: str
    wind_kph: int
    gust_kph: int
    rain_mm: Decimal


def _draws(code: str, day: str) -> list[float]:
    """Eight stable numbers in [0, 1) for a city and day, the same in every process
    (hash() is salted per process). A simulation, not a secret: no RNG is needed."""
    digest = hashlib.sha256(f"nexira:weather:{code}:{day}".encode()).digest()
    return [int.from_bytes(digest[i : i + 4], "big") / 2**32 for i in range(0, 32, 4)]


def conditions(code: str, lat: float, lon: float, moment: datetime) -> Conditions:
    """Plausible, deterministic conditions for a city at a moment (UTC)."""
    moment = moment.astimezone(UTC)
    hour = (moment.hour + moment.minute / 60 + lon / 15) % 24  # local solar time
    local_day = (moment + timedelta(hours=lon / 15)).date()
    d = _draws(code, local_day.isoformat())
    # Warmest in local summer (July north, January south) and at 15:00; cooler away
    # from the tropics.
    season = math.cos(2 * math.pi * (local_day.timetuple().tm_yday - 196) / 365)
    season *= 1 if lat >= 0 else -1
    mean = 28 - 0.5 * max(0.0, abs(lat) - 15)
    temperature = (
        mean + 0.2 * abs(lat) * season + 5 * math.cos(2 * math.pi * (hour - 15) / 24) + 6 * d[0] - 3
    )
    temperature = max(-60.0, min(60.0, temperature))
    sky = "CLEAR" if d[1] < 0.5 else "CLOUD" if d[1] < 0.8 else "RAIN"
    foggy = d[2] < 0.15
    if sky == "RAIN" and temperature < 1:
        condition = "SNOW"
    elif foggy and hour < 9 and sky != "RAIN":
        condition = "FOG"
    else:
        condition = sky
    wind = 4 + int(19 * d[3]) + round(6 * max(0.0, math.cos(2 * math.pi * (hour - 15) / 24)))
    rain = {"RAIN": 0.5 + 7.5 * d[4], "SNOW": 0.2 + 2.8 * d[4]}.get(condition, 0.0)
    return Conditions(
        temperature_c=Decimal(str(round(temperature, 1))),
        condition=condition,
        wind_kph=wind,
        gust_kph=round(wind * 1.4),
        rain_mm=Decimal(str(round(rain, 1))),
    )


def _upsert(rows: list[dict[str, Any]], moment: datetime) -> Any:
    """Insert, or replace a row only with a newer observation; the tick (source SOURCE)
    also skips a row held by a scenario (plan G-1)."""
    statement = insert(WeatherCurrent).values(rows)
    excluded = statement.excluded
    current = WeatherCurrent.__table__.c
    held = (current.source == SCENARIO_SOURCE) & (current.observed_at > moment - HOLD)
    return statement.on_conflict_do_update(
        index_elements=[current.tenant_id, current.mission_id],
        set_={
            name: excluded[name]
            for name in (
                "observed_at",
                "temperature_c",
                "condition",
                "wind_kph",
                "gust_kph",
                "rain_mm",
                "source",
            )
        },
        where=(current.observed_at <= excluded.observed_at)
        & ((excluded.source == SCENARIO_SOURCE) | ~held),
    ).returning(current.mission_id)


_MISSIONS = text(
    "SELECT id, code, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lon "
    "FROM mission ORDER BY code"
)


async def refresh(session: AsyncSession, moment: datetime) -> int:
    """Upsert every mission's conditions; return how many rows were written."""
    missions = (await session.execute(_MISSIONS)).all()
    if not missions:
        return 0
    tenant_id = session.info["tenant_id"]
    rows = [
        {
            "tenant_id": tenant_id,
            "mission_id": m.id,
            "observed_at": moment,
            "source": SOURCE,
            **conditions(m.code, m.lat, m.lon, moment).__dict__,
        }
        for m in missions
    ]
    written = len((await session.execute(_upsert(rows, moment))).all())
    if written:
        await audit.write(
            session,
            actor_type=FEED.type,
            actor_id=FEED.id,
            action="WEATHER.REFRESH",
            entity_type="weather_current",
            details={"missions": written, "of": len(missions)},
        )
    return written


def updated_event(tenant_id: uuid.UUID, payload: dict[str, Any]) -> Event:
    return Event(
        type="WEATHER_UPDATED", tenant_id=tenant_id, payload=payload, source="weather.feed"
    )


async def tick(
    engine: AsyncEngine, tenant_id: uuid.UUID, publisher: Publisher, *, now: Now = _utcnow
) -> int:
    moment = now()
    async with tenant_session(tenant_id, engine) as session:
        written = await refresh(session, moment)
        await session.commit()
    if written:
        await publisher.publish(updated_event(tenant_id, {"missions": written}))
    return written


# --- the feed (WEATHER_FEED) ------------------------------------------------------------------


@dataclass(frozen=True)
class Override:
    """A validated WEATHER_FEED payload: one mission's conditions, within PC-20's ranges."""

    mission_code: str
    conditions: Conditions


def _number(
    payload: dict[str, Any], name: str, low: float, high: float, default: float | None
) -> float:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return float(value)


def parse_feed(payload: dict[str, Any]) -> Override | None:
    """None (logged) for anything malformed: a bad feed is dropped, never retried."""
    try:
        code, condition = payload.get("mission_code"), payload.get("condition")
        if not isinstance(code, str) or not 1 <= len(code) <= 10:
            raise ValueError("mission_code is required")
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition {condition!r}")
        wind = round(_number(payload, "wind_kph", 0, 400, None))
        gust = round(_number(payload, "gust_kph", 0, 400, wind))
        if gust < wind:
            raise ValueError("gusts are at least the wind")
        return Override(
            code,
            Conditions(
                temperature_c=Decimal(
                    str(round(_number(payload, "temperature_c", -60, 60, None), 1))
                ),
                condition=str(condition),
                wind_kph=wind,
                gust_kph=gust,
                rain_mm=Decimal(str(round(_number(payload, "rain_mm", 0, 1000, 0), 1))),
            ),
        )
    except ValueError as e:
        log.warning("WEATHER_FEED ignored (%s): %s", e, payload)
        return None


async def apply_feed(
    session: AsyncSession, payload: dict[str, Any], moment: datetime
) -> uuid.UUID | None:
    """Write one override; return the mission's id, or None when nothing was written."""
    override = parse_feed(payload)
    if override is None:
        return None
    mission_id: uuid.UUID | None = await session.scalar(
        text("SELECT id FROM mission WHERE code = :code"), {"code": override.mission_code}
    )
    if mission_id is None:
        log.info("WEATHER_FEED for an unknown mission ignored: %s", override.mission_code)
        return None
    row = {
        "tenant_id": session.info["tenant_id"],
        "mission_id": mission_id,
        "observed_at": moment,
        "source": SCENARIO_SOURCE,
        **override.conditions.__dict__,
    }
    written = len((await session.execute(_upsert([row], moment))).all())
    if not written:
        return None  # a newer observation is already there
    await audit.write(
        session,
        actor_type=FEED.type,
        actor_id=FEED.id,
        action="WEATHER.OVERRIDE",
        entity_type="weather_current",
        entity_id=override.mission_code,
        details={
            "condition": override.conditions.condition,
            "wind_kph": override.conditions.wind_kph,
            "gust_kph": override.conditions.gust_kph,
        },
    )
    return mission_id


def feed_handler(engine: AsyncEngine, publisher: Publisher, now: Now = _utcnow) -> Handler:
    async def handle(event: Event) -> None:
        async with tenant_session(event.tenant_id, engine) as session:
            mission_id = await apply_feed(session, event.payload, now())
            await session.commit()
        if mission_id is not None:
            await publisher.publish(updated_event(event.tenant_id, {"mission_id": str(mission_id)}))

    return handle
