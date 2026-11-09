"""Predictive Risk (PRD-01..05, D-46; docs/plan-pilot-prd.md §2-§7).

- An explainable index per mission and day: a stated sum of components, capped at 100 (§2).
  It is labelled "illustrative model"; nothing is trained and no accuracy is claimed.
- The snapshot stores today's value (and its components) once a day and keeps it current during
  the day; the day is the database's UTC date, so it agrees with the guard (§3, review L5).
- The 14-day projection and its band are worked out on read and never stored (§4).
- Drivers, rising risk and rule-based actions read the same components (§5, §6). No action
  names a VIP visit (G-1).
- Advisory only: nothing here changes anything outside predictive's own tables (PRD-06).
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import Event
from app.modules.hazards import service as hazards
from app.modules.health_intel import service as health
from app.modules.people.models import Mission
from app.modules.predictive import schemas
from app.modules.predictive.models import MissionEvent, RiskIndex
from app.modules.tenancy.service import Actor

THRESHOLD = 70  # §83 Q4
HORIZON = 14
HISTORY_DAYS = 30
BASELINE = {"LOW": 35, "MODERATE": 50, "HIGH": 65, "CRITICAL": 80}
INCIDENT = {"LOW": 5, "MODERATE": 15, "HIGH": 30, "CRITICAL": 45}
HEALTH = {"LOW": 2, "MODERATE": 4, "HIGH": 7, "CRITICAL": 10}
HAZARD = {"LOW": 3, "MODERATE": 6, "HIGH": 10, "CRITICAL": 15}
STORM = 5
SIGNAL_RADIUS_M = 50_000
SIGNAL_MAX = 10
EVENTS_MAX = 45
EVENT_RAMP = {0: 1.0, 1: 0.75, 2: 0.5}  # days before the start: the share of the weight
INCIDENT_HALF_LIFE_D = 3
TREND_LIMIT = 1.0  # points a day
SNAPSHOT = Actor(type="SYSTEM", id="risk index snapshot")
KEYS = ("baseline", "incidents", "signals", "health", "hazard", "weather", "events")


@dataclass
class Components:
    """One mission's components today, with what each label needs (§2, §5)."""

    mission_id: uuid.UUID
    code: str
    city: str
    risk_level: str
    incident: tuple[str, str, str] | None = None  # reference, title, severity
    signals_7d: int = 0
    signals_norm: float = 0.0
    health: tuple[str, str] | None = None  # level, topic
    hazard: tuple[str, str] | None = None  # severity, title
    storm: bool = False
    events: list[MissionEvent] = field(default_factory=list)  # today and the next HORIZON days

    def points(self, day: date) -> dict[str, int]:
        """Every component's points for `day` as seen today (events by their dates)."""
        return {
            "baseline": BASELINE[self.risk_level],
            "incidents": INCIDENT[self.incident[2]] if self.incident else 0,
            "signals": signal_points(self.signals_7d, self.signals_norm),
            "health": HEALTH[self.health[0]] if self.health else 0,
            "hazard": HAZARD[self.hazard[0]] if self.hazard else 0,
            "weather": STORM if self.storm else 0,
            "events": event_points(self.events, day),
        }


def signal_points(last_7d: int, weekly_norm: float) -> int:
    """2 points per signal above the weekly norm, at most 10 (§2, G-5)."""
    return min(SIGNAL_MAX, max(0, round(2 * (last_7d - weekly_norm))))


def event_points(events: list[MissionEvent], day: date) -> int:
    """The calendar on `day`: a weight in full during the event, 75% the day before and 50% two
    days before; capped at 45 (§2)."""
    total = 0.0
    for e in events:
        if e.starts_on <= day <= e.ends_on:
            total += e.weight
        else:
            share = EVENT_RAMP.get((e.starts_on - day).days)
            if share is not None and (e.starts_on - day).days > 0:
                total += e.weight * share
    return min(EVENTS_MAX, round(total))


def total(points: dict[str, int]) -> int:
    return max(0, min(100, sum(points.values())))


def trend_slope(values: list[int]) -> float:
    """The least-squares slope of the last 14 days, clamped to ±1 point a day (§4)."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return max(-TREND_LIMIT, min(TREND_LIMIT, num / den if den else 0.0))


def forecast(c: Components, today: date, slope: float) -> list[schemas.ForecastOut]:
    """The 14-day projection and its band (§4); worked out on read, never stored."""
    now = c.points(today)
    out = []
    for d in range(1, HORIZON + 1):
        day = today + timedelta(days=d)
        value = (
            now["baseline"]
            + now["incidents"] * 2 ** (-d / INCIDENT_HALF_LIFE_D)
            + now["signals"] * max(0.0, 1 - d / 7)
            + (now["health"] + now["hazard"] + now["weather"]) * max(0.0, 1 - d / HORIZON)
            + event_points(c.events, day)
            + slope * d * 0.5
        )
        v = max(0, min(100, round(value)))
        band = 3 + 0.9 * d
        out.append(
            schemas.ForecastOut(
                day=day, value=v, low=max(0, round(v - band)), high=min(100, round(v + band))
            )
        )
    return out


# --- reading the components (§2) ---------------------------------------------------------------


async def db_today(session: AsyncSession) -> date:
    """The database's UTC date, as the guard's (review of Prompt 100, L5)."""
    found: date = await session.scalar(text("SELECT (now() AT TIME ZONE 'UTC')::date"))
    return found


_MISSIONS = text("SELECT id, code, city, risk_level FROM mission ORDER BY code")

_INCIDENTS = text(
    """
    SELECT DISTINCT ON (mission_id) mission_id, reference, title, severity FROM incident
     WHERE status = 'ACTIVE' AND mission_id IS NOT NULL
     ORDER BY mission_id, severity_rank(severity) DESC, opened_at DESC
    """
)

_SIGNALS = text(
    """
    SELECT m.id AS mission_id,
           count(*) FILTER (WHERE s.received_at >= now() - interval '7 days') AS last_7d,
           count(*) FILTER (WHERE s.received_at < now() - interval '7 days'
                              AND s.received_at >= now() - interval '37 days') AS before
      FROM mission m
      JOIN raw_signal s ON s.location IS NOT NULL
       AND ST_DWithin(s.location, m.location, :radius)
       AND s.received_at >= now() - interval '37 days'
     GROUP BY m.id
    """
)

_STORMS = text("SELECT mission_id FROM weather_current WHERE condition = 'STORM'")


async def components(session: AsyncSession, today: date) -> dict[uuid.UUID, Components]:
    """Every mission's components today, in a handful of queries."""
    out = {
        r.id: Components(mission_id=r.id, code=r.code, city=r.city, risk_level=r.risk_level)
        for r in await session.execute(_MISSIONS)
    }
    by_code = {c.code: c for c in out.values()}
    for r in await session.execute(_INCIDENTS):
        if r.mission_id in out:
            out[r.mission_id].incident = (r.reference, r.title, r.severity)
    for r in await session.execute(_SIGNALS, {"radius": SIGNAL_RADIUS_M}):
        near = out[r.mission_id]
        near.signals_7d = int(r.last_7d)
        near.signals_norm = int(r.before) / 30 * 7  # the weekly mean of the 30 days before (G-5)
    for advisory in await health.list_advisories(session):
        if advisory.status != "OPEN":
            continue
        for affected in advisory.missions:
            advised = out.get(affected.mission_id)
            if advised is not None and (
                advised.health is None
                or health.RANK[advisory.level] > health.RANK[advised.health[0]]
            ):
                advised.health = (advisory.level, advisory.topic)
    for event in (await hazards.list_hazards(session)).events:
        if event.status == "ACTIVE" and event.within_range:
            nearest = by_code.get(event.nearest_mission_code or "")
            if nearest is not None and (
                nearest.hazard is None or HAZARD[event.severity] > HAZARD[nearest.hazard[0]]
            ):
                nearest.hazard = (event.severity, event.title)
    for r in await session.execute(_STORMS):
        if r.mission_id in out:
            out[r.mission_id].storm = True
    calendar = await session.scalars(
        select(MissionEvent)
        .where(
            MissionEvent.ends_on >= today,
            MissionEvent.starts_on <= today + timedelta(days=HORIZON + 2),
        )
        .order_by(MissionEvent.starts_on, MissionEvent.title)
    )
    for e in calendar:
        if e.mission_id in out:
            out[e.mission_id].events.append(e)
    return out


# --- the snapshot (§3) ---------------------------------------------------------------------------

_UPSERT = text(
    """
    INSERT INTO risk_index (tenant_id, mission_id, day, value, components, source)
    VALUES (current_tenant_id(), :mission, :day, :value, CAST(:components AS jsonb), 'COMPUTED')
    ON CONFLICT (mission_id, day) DO UPDATE
       SET value = EXCLUDED.value, components = EXCLUDED.components
    RETURNING (xmax = 0) AS inserted
    """
)


def updated_event(tenant_id: uuid.UUID, missions: int) -> Event:
    """Counts only (PRD-07); the screen refetches."""
    return Event(
        type="PREDICTIVE_UPDATED",
        tenant_id=tenant_id,
        payload={"missions": missions},
        source="predictive",
    )


async def snapshot(session: AsyncSession, actor: Actor = SNAPSHOT) -> int:
    """Store or refresh today's index for every mission. Audited once per tenant and day, on
    the first insert (G-4). Returns the number of missions written."""
    today = await db_today(session)
    found = await components(session, today)
    inserted = 0
    for c in found.values():
        points = c.points(today)
        row = (
            await session.execute(
                _UPSERT,
                {
                    "mission": c.mission_id,
                    "day": today,
                    "value": total(points),
                    "components": json.dumps(points),
                },
            )
        ).one()
        inserted += int(bool(row.inserted))
    if inserted:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="PREDICTIVE.SNAPSHOT",
            entity_type="risk_index",
            details={"day": today.isoformat(), "missions": inserted},
        )
    return len(found)


# --- the screen's figures (§5, §6) ---------------------------------------------------------------


async def _history(
    session: AsyncSession, today: date, mission_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[RiskIndex]]:
    rows = await session.scalars(
        select(RiskIndex)
        .where(
            RiskIndex.mission_id.in_(mission_ids),
            RiskIndex.day >= today - timedelta(days=HISTORY_DAYS),
            RiskIndex.day < today,
        )
        .order_by(RiskIndex.day)
    )
    out: dict[uuid.UUID, list[RiskIndex]] = defaultdict(list)
    for r in rows:
        out[r.mission_id].append(r)
    return out


def _slope(history: list[RiskIndex]) -> float:
    return trend_slope([r.value for r in history[-HORIZON:]])


def _drivers(c: Components, today: date, history: list[RiskIndex]) -> list[schemas.DriverOut]:
    points = c.points(today)
    week_ago = next((r for r in history if r.day == today - timedelta(days=7)), None)
    before: dict[str, Any] = (
        week_ago.components if week_ago is not None and week_ago.source == "COMPUTED" else {}
    )
    upcoming = [e for e in c.events if e.starts_on <= today + timedelta(days=7)]
    labels = {
        "baseline": f"Baseline · {c.risk_level.lower()} mission risk",
        "incidents": (
            f"{c.incident[1]} {c.incident[0]} ({c.incident[2].lower()})" if c.incident else ""
        ),
        "signals": (f"Signals within 50 km · {c.signals_7d} in 7 days (norm {c.signals_norm:.0f})"),
        "health": f"Health advisory · {c.health[0]} · {c.health[1]}" if c.health else "",
        "hazard": f"Natural hazard · {c.hazard[1]}" if c.hazard else "",
        "weather": "Severe weather · storm",
        "events": (
            f"Scheduled events · {len(upcoming)} in the next 7 days"
            + (f" ({upcoming[0].title})" if upcoming else "")
        ),
    }
    return [
        schemas.DriverOut(
            key=key,
            label=labels[key],
            points=points[key],
            change=points[key] - int(before[key]) if key in before else None,
        )
        for key in KEYS
        if key == "baseline" or points[key]
    ]


def _actions(c: Components, peak: schemas.ForecastOut) -> list[schemas.ActionOut]:
    """Rule-based text, no task (§6, §83 Q6). Never a VIP visit (G-1)."""
    out = []
    if peak.value >= THRESHOLD:
        on_peak = [e for e in c.events if event_points([e], peak.day)]
        if on_peak:
            top = max(on_peak, key=lambda e: e.weight)
            out.append(
                schemas.ActionOut(
                    mission_code=c.code,
                    text=f"Review movements and venues in {c.city} around {top.title} "
                    f"({top.starts_on.isoformat()}).",
                )
            )
        elif c.incident:
            out.append(
                schemas.ActionOut(
                    mission_code=c.code,
                    text=f"Keep {c.city} at Elevated until the forecast stays below "
                    f"{THRESHOLD} for 72 h.",
                )
            )
    if c.hazard:
        out.append(
            schemas.ActionOut(
                mission_code=c.code,
                text=f"Check shelter supplies and the continuity plan for {c.city}.",
            )
        )
    return out


async def overview(session: AsyncSession) -> schemas.OverviewOut:
    today = await db_today(session)
    found = await components(session, today)
    history = await _history(session, today, list(found))
    rising: list[schemas.RisingOut] = []
    actions: list[schemas.ActionOut] = []
    for c in found.values():
        now = total(c.points(today))
        ahead = forecast(c, today, _slope(history.get(c.mission_id, [])))
        peak = max(ahead, key=lambda f: (f.value, -f.day.toordinal()))
        rising.append(
            schemas.RisingOut(
                mission_id=c.mission_id,
                mission_code=c.code,
                city=c.city,
                now=now,
                peak=peak.value,
                peak_day=peak.day,
                change=peak.value - now,
                crosses=peak.value >= THRESHOLD,
            )
        )
        actions.extend(_actions(c, peak))
    # By the rise; with nothing rising, the highest peaks (G-7).
    if any(r.change > 0 for r in rising):
        rising.sort(key=lambda r: (-r.change, -r.peak, r.mission_code))
    else:
        rising.sort(key=lambda r: (-r.peak, r.mission_code))
    return schemas.OverviewOut(
        threshold=THRESHOLD, model=schemas.MODEL_LABEL, rising=rising, actions=actions
    )


@dataclass(frozen=True)
class Outlook:
    """One mission today and ahead, for the Forecast agent (PRD-06)."""

    components: Components
    now: int
    peak: schemas.ForecastOut
    events_at_peak: list[MissionEvent]  # the calendar entries that count on the peak's day


async def outlook(session: AsyncSession, mission_id: uuid.UUID) -> Outlook | None:
    today = await db_today(session)
    c = (await components(session, today)).get(mission_id)
    if c is None:
        return None
    history = (await _history(session, today, [mission_id])).get(mission_id, [])
    ahead = forecast(c, today, _slope(history))
    peak = max(ahead, key=lambda f: (f.value, -f.day.toordinal()))
    return Outlook(
        components=c,
        now=total(c.points(today)),
        peak=peak,
        events_at_peak=[e for e in c.events if event_points([e], peak.day)],
    )


class MissionNotFoundError(Exception):
    pass


async def mission(session: AsyncSession, mission_id: uuid.UUID) -> schemas.MissionOut:
    if await session.get(Mission, mission_id) is None:
        raise MissionNotFoundError
    today = await db_today(session)
    c = (await components(session, today))[mission_id]
    history = (await _history(session, today, [mission_id])).get(mission_id, [])
    now = total(c.points(today))
    return schemas.MissionOut(
        mission_id=c.mission_id,
        mission_code=c.code,
        city=c.city,
        threshold=THRESHOLD,
        model=schemas.MODEL_LABEL,
        now=now,
        history=[
            *(schemas.HistoryOut(day=r.day, value=r.value, source=r.source) for r in history),
            schemas.HistoryOut(day=today, value=now, source="LIVE"),
        ],
        forecast=forecast(c, today, _slope(history)),
        drivers=_drivers(c, today, history),
        events=[
            schemas.EventOut(
                id=e.id,
                kind=e.kind,
                title=e.title,
                place_label=e.place_label,
                starts_on=e.starts_on,
                ends_on=e.ends_on,
                attendance=e.attendance,
                weight=e.weight,
                source=e.source,
            )
            for e in c.events
            if e.starts_on <= today + timedelta(days=HORIZON)
        ],
    )


# --- the calendar and the seed (PRD-01, PRD-05; §3, §7) ----------------------------------------


@dataclass(frozen=True)
class EventIn:
    """A calendar entry; dates are offsets from a day (the seed's date, or today when played)."""

    mission_code: str
    kind: str
    title: str
    starts_in_days: int
    weight: int
    days: int = 1
    place_label: str | None = None
    lat: float | None = None
    lon: float | None = None
    attendance: int | None = None


_INSERT_EVENT = text(
    """
    INSERT INTO mission_event (tenant_id, mission_id, kind, title, place_label, location,
                               starts_on, ends_on, attendance, weight)
    VALUES (current_tenant_id(), :mission, :kind, :title, :place,
            CASE WHEN CAST(:lat AS float8) IS NULL THEN NULL
                 ELSE ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography END,
            :starts, :ends, :attendance, :weight)
    RETURNING id
    """
)


async def add_event(
    session: AsyncSession,
    e: EventIn,
    from_day: date,
    actor: Actor = SNAPSHOT,
    *,
    audited: bool = True,
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Add a calendar entry (fixed once added, PC-47). None for an unknown mission or when the
    same entry is already there (a replay). Returns (event id, mission id); audited."""
    mission_id = await session.scalar(select(Mission.id).where(Mission.code == e.mission_code))
    if mission_id is None:
        return None
    starts = from_day + timedelta(days=e.starts_in_days)
    exists = await session.scalar(
        select(MissionEvent.id).where(
            MissionEvent.mission_id == mission_id,
            MissionEvent.title == e.title,
            MissionEvent.starts_on == starts,
        )
    )
    if exists is not None:
        return None
    event_id: uuid.UUID = (
        await session.execute(
            _INSERT_EVENT,
            {
                "mission": mission_id,
                "kind": e.kind,
                "title": e.title,
                "place": e.place_label,
                "lat": e.lat,
                "lon": e.lon,
                "starts": starts,
                "ends": starts + timedelta(days=e.days - 1),
                "attendance": e.attendance,
                "weight": e.weight,
            },
        )
    ).scalar_one()
    if audited:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="PREDICTIVE.EVENT",
            entity_type="mission_event",
            entity_id=str(event_id),
            details={"mission": e.mission_code, "kind": e.kind, "starts_on": starts.isoformat()},
        )
    return event_id, mission_id


def event_added(tenant_id: uuid.UUID, event_id: uuid.UUID, mission_id: uuid.UUID) -> Event:
    """For the Forecast agent (PRD-06) and the screen; ids only."""
    return Event(
        type="MISSION_EVENT_ADDED",
        tenant_id=tenant_id,
        payload={"event_id": str(event_id), "mission_id": str(mission_id)},
        source="predictive",
    )


async def ensure_calendar(
    session: AsyncSession, events: list[EventIn], from_day: date, actor: Actor = SNAPSHOT
) -> int:
    """Seed the calendar relative to the scenario date; existing entries are kept (§7). Audited
    once for the batch, as the other bulk loads (G-20)."""
    added = 0
    for e in events:
        added += int(await add_event(session, e, from_day, actor, audited=False) is not None)
    if added:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="PREDICTIVE.CALENDAR_SEED",
            entity_type="mission_event",
            details={"events": added, "from": from_day.isoformat()},
        )
    return added


_HISTORY = text(
    """
    INSERT INTO risk_index (tenant_id, mission_id, day, value, components, source)
    VALUES (current_tenant_id(), :mission, :day, :value, CAST(:components AS jsonb),
            'ILLUSTRATIVE')
    ON CONFLICT (mission_id, day) DO NOTHING
    RETURNING id
    """
)


async def ensure_history(
    session: AsyncSession, until: date, days: int = HISTORY_DAYS, actor: Actor = SNAPSHOT
) -> int:
    """The labelled illustrative history (§3, G-3): each mission's baseline with a seeded wobble
    of up to ±4 that fades into the day before `until`, so the line meets today without a jump.
    Deterministic; days already there are kept. Audited once."""
    added = 0
    for r in await session.execute(_MISSIONS):
        base = BASELINE[r.risk_level]
        seed = sum(ord(ch) for ch in r.code)
        for d in range(days, 0, -1):
            wobble = ((seed * 7 + d * 13) % 9 - 4) * min(1.0, d / 10)
            value = max(0, min(100, round(base + wobble)))
            row = await session.scalar(
                _HISTORY,
                {
                    "mission": r.id,
                    "day": until - timedelta(days=d),
                    "value": value,
                    "components": json.dumps({"illustrative": value}),
                },
            )
            added += int(row is not None)
    if added:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="PREDICTIVE.HISTORY",
            entity_type="risk_index",
            details={"rows": added, "until": until.isoformat(), "source": "ILLUSTRATIVE"},
        )
    return added
