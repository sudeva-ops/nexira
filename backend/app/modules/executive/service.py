"""Executive Overview (EXE-01..04, D-45; docs/plan-pilot-exe.md).

- Every figure is worked out on read from what the other modules hold; nothing is stored and
  no history is seeded (§78 Q3, Q4). The one exception is the trend's days before the first live
  data: illustrative counts, worked out from the date on read and marked ILLUSTRATIVE (GFX-05,
  D-55), as Predictive Risk marks its history.
- The attention drivers come from the modules' own read functions, so each rule lives in one
  place (§4).
- Aggregates and references only: no person's name, in the figures or the timeline (EXE-04,
  G-11). The export is audited (EXE-03).
- Exercise incidents (D-48) are left out of every incident figure: active incidents, posture,
  detection, personnel accounted, evacuations, the trend and the timeline (plan-pilot-exr §4).
  Each query takes them as :leave_out.
"""

import hashlib
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.security import CurrentUser
from app.modules.checkin import service as checkin
from app.modules.executive import schemas
from app.modules.exercises import queries as exercise_queries
from app.modules.fleet import service as fleet
from app.modules.hazards import service as hazards
from app.modules.health_intel import service as health
from app.modules.intel import queries as intel_queries
from app.modules.people.queries import list_missions
from app.modules.people.schemas import MissionOut
from app.modules.supply import service as supply
from app.modules.twin import service as twin

RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
POINTS = {"LOW": 20, "MODERATE": 50, "HIGH": 75, "CRITICAL": 95}  # §3
TREND_DAYS = 30
RECENT_DAYS = 7
TIMELINE_MAX = 12
RECENT_MAX = 8
# The timeline's key events (§5). A check-in entry names the person who needs help, so it is
# shown without the name (G-11); free-text notes and escalations are left out.
TIMELINE_TYPES = ("FUSED", "EXPOSURE", "PLAYBOOK_STEP", "NOTIFICATION", "CHECKIN", "STATUS")
REGION_OF: dict[str, str] = {  # G-2: Türkiye under Europe, Egypt under Africa
    **dict.fromkeys(("EG", "MA", "NG", "KE", "ET", "ZA"), "Africa"),
    **dict.fromkeys(("JO", "IQ", "SA", "OM"), "Middle East"),
    **dict.fromkeys(
        ("PK", "IN", "BD", "CN", "KR", "JP", "PH", "MY", "SG", "ID", "AU"), "Asia-Pacific"
    ),
    **dict.fromkeys(("GB", "FR", "DE", "BE", "CH", "IT", "ES", "RU", "TR"), "Europe"),
    **dict.fromkeys(("US", "CA", "MX", "BR", "AR"), "Americas"),
}
REGIONS = ("Africa", "Middle East", "Asia-Pacific", "Europe", "Americas")
UNMAPPED = "Other"


def region_of(country_code: str) -> str:
    return REGION_OF.get(country_code, UNMAPPED)


def posture(missions: list[MissionOut], active: int) -> schemas.PostureOut:
    """SEVERE with a CRITICAL mission, ELEVATED with a HIGH one or any ACTIVE incident, else
    GUARDED (§78 Q2)."""
    critical = sum(1 for m in missions if m.display_risk == "CRITICAL")
    high = any(m.display_risk == "HIGH" for m in missions)
    elevated = sum(1 for m in missions if m.display_risk in ("MODERATE", "HIGH"))
    level = "SEVERE" if critical else "ELEVATED" if high or active else "GUARDED"
    return schemas.PostureOut(level=level, critical_missions=critical, elevated_missions=elevated)


def regions(missions: list[MissionOut]) -> list[schemas.RegionOut]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for m in missions:
        grouped[region_of(m.country_code)].append(POINTS[m.display_risk])
    order = [*REGIONS, UNMAPPED]
    return [
        schemas.RegionOut(region=r, exposure=round(sum(p) / len(p)), missions=len(p))
        for r in order
        if (p := grouped.get(r))
    ]


_ACTIVE = text(
    """
    SELECT id, reference, title, severity, opened_at FROM incident
     WHERE status = 'ACTIVE' AND NOT id = ANY(CAST(:leave_out AS uuid[]))
     ORDER BY severity_rank(severity) DESC, opened_at DESC, reference DESC
    """
)

_DETECTION = text(
    """
    SELECT i.id,
           extract(epoch FROM (
             (SELECT min(c.sent_at) FROM notification_campaign c
               WHERE c.incident_id = i.id AND c.sent_at IS NOT NULL)
             - (SELECT min(s.received_at) FROM incident_signal x
                  JOIN raw_signal s ON s.id = x.signal_id WHERE x.incident_id = i.id)
           )) AS seconds
      FROM incident i
     WHERE i.opened_at >= :since AND NOT i.id = ANY(CAST(:leave_out AS uuid[]))
    """
)

_TREND = text(
    """
    SELECT d::date AS day,
           (SELECT count(*) FROM raw_signal s
             WHERE s.received_at >= d AND s.received_at < d + interval '1 day'
               AND NOT EXISTS (SELECT 1 FROM incident_signal x WHERE x.signal_id = s.id
                                  AND x.incident_id = ANY(CAST(:leave_out AS uuid[]))))
             AS signals,
           (SELECT count(*) FROM incident i
             WHERE i.opened_at >= d AND i.opened_at < d + interval '1 day'
               AND NOT i.id = ANY(CAST(:leave_out AS uuid[]))) AS incidents
      FROM generate_series(CAST(:first AS timestamptz), CAST(:last AS timestamptz),
                           interval '1 day') AS d
     ORDER BY d
    """
)

_CHECKINS = text(
    """
    SELECT DISTINCT ON (c.incident_id) c.id, i.reference
      FROM notification_campaign c JOIN incident i ON i.id = c.incident_id
     WHERE c.campaign_type = 'CHECKIN' AND i.status = 'ACTIVE'
       AND NOT i.id = ANY(CAST(:leave_out AS uuid[]))
     ORDER BY c.incident_id, c.created_at DESC
    """
)

_READINESS = text(
    "SELECT mission_id, readiness_score FROM site "
    "WHERE site_type = 'EMBASSY' AND readiness_score IS NOT NULL"
)

_EVACUATIONS = text(
    "SELECT mission_id, reference FROM evacuation WHERE status = 'ACTIVE' "
    "AND (incident_id IS NULL OR NOT incident_id = ANY(CAST(:leave_out AS uuid[])))"
)

_TIMELINE = text(
    """
    SELECT occurred_at, event_type, summary FROM incident_event
     WHERE incident_id = :incident AND event_type = ANY(:types)
     ORDER BY occurred_at DESC, id DESC LIMIT :limit
    """
)

_RECENT = text(
    """
    SELECT reference, title, 'OPENED' AS change, opened_at AS at FROM incident
     WHERE opened_at >= :since AND NOT id = ANY(CAST(:leave_out AS uuid[]))
    UNION ALL
    SELECT reference, title, 'CLOSED', closed_at FROM incident
     WHERE closed_at IS NOT NULL AND closed_at >= :since
       AND NOT id = ANY(CAST(:leave_out AS uuid[]))
     ORDER BY at DESC LIMIT :limit
    """
)


def _ref(row: Any) -> schemas.IncidentRefOut:
    return schemas.IncidentRefOut(
        id=row.id, reference=row.reference, title=row.title, severity=row.severity
    )


async def _detection(
    session: AsyncSession, now: datetime, current: Any | None, leave_out: list[uuid.UUID]
) -> schemas.DetectionOut:
    since = now - timedelta(days=TREND_DAYS)
    times = {
        r.id: int(r.seconds)
        for r in await session.execute(_DETECTION, {"since": since, "leave_out": leave_out})
        if r.seconds is not None and r.seconds >= 0
    }
    return schemas.DetectionOut(
        median_s=round(median(times.values())) if times else None,
        incidents=len(times),
        current_s=times.get(current.id) if current else None,
        current_reference=current.reference if current else None,
    )


async def _accounted(session: AsyncSession, leave_out: list[uuid.UUID]) -> schemas.AccountedOut:
    answered = asked = 0
    references: list[str] = []
    for row in await session.execute(_CHECKINS, {"leave_out": leave_out}):
        personnel = (await checkin.tally(session, row.id))["personnel"]
        answered += personnel.safe + personnel.need_help
        asked += personnel.recipients
        references.append(row.reference)
    return schemas.AccountedOut(
        pct=round(100 * answered / asked) if asked else None,
        answered=answered,
        asked=asked,
        incident_references=sorted(references),
    )


def illustrative_day(day: date) -> tuple[int, int]:
    """Signals and incidents for a day before the live data (GFX-05, plan-pilot-gfx G-6): from a
    hash of the date, so every read gives the same counts; quieter at weekends."""
    digest = hashlib.sha256(f"nexira-trend-{day.isoformat()}".encode()).digest()
    weekend = day.weekday() >= 5
    signals = 6 + digest[0] % 25  # 6..30
    incidents = digest[1] % 4  # 0..3
    if weekend:
        signals, incidents = (signals * 3) // 5, incidents // 2
    return signals, incidents


def with_illustrative(days: list[schemas.TrendDayOut], today: date) -> list[schemas.TrendDayOut]:
    """Days before the first one with live data become illustrative; today is always live."""
    first_live = next(
        (i for i, d in enumerate(days) if d.signals or d.incidents or d.day >= today), len(days)
    )
    out = []
    for i, d in enumerate(days):
        if i < first_live:
            signals, incidents = illustrative_day(d.day)
            d = schemas.TrendDayOut(
                day=d.day, signals=signals, incidents=incidents, source="ILLUSTRATIVE"
            )
        out.append(d)
    return out


async def _trend(
    session: AsyncSession, today: date, leave_out: list[uuid.UUID]
) -> list[schemas.TrendDayOut]:
    first = datetime.combine(today - timedelta(days=TREND_DAYS - 1), datetime.min.time(), UTC)
    last = datetime.combine(today, datetime.min.time(), UTC)
    rows = await session.execute(_TREND, {"first": first, "last": last, "leave_out": leave_out})
    live = [schemas.TrendDayOut(day=r.day, signals=r.signals, incidents=r.incidents) for r in rows]
    return with_illustrative(live, today)


async def _drivers(
    session: AsyncSession,
    user: CurrentUser,
    today: date,
    active: list[Any],
    missions: list[MissionOut],
    leave_out: list[uuid.UUID],
) -> dict[uuid.UUID, list[schemas.DriverOut]]:
    """Each mission's drivers from the modules' own read functions (§4)."""
    drivers: dict[uuid.UUID, list[schemas.DriverOut]] = defaultdict(list)
    by_code = {m.code: m.id for m in missions}
    incidents = {
        r.id: r.mission_id
        for r in await session.execute(
            text("SELECT id, mission_id FROM incident WHERE status = 'ACTIVE'")
        )
    }
    for row in active:
        mission_id = incidents.get(row.id)
        if mission_id is not None:
            drivers[mission_id].append(
                schemas.DriverOut(
                    kind="INCIDENT",
                    label=f"{row.title} ({row.severity.lower()})",
                    reference=row.reference,
                )
            )
    seen = {d.reference for found in drivers.values() for d in found}
    for row in await session.execute(_EVACUATIONS, {"leave_out": leave_out}):
        drivers[row.mission_id].append(
            schemas.DriverOut(kind="EVACUATION", label="Evacuation active", reference=row.reference)
        )
    worst: dict[uuid.UUID, Any] = {}
    for advisory in await health.list_advisories(session):
        if advisory.status != "OPEN":
            continue
        for affected in advisory.missions:
            known = worst.get(affected.mission_id)
            if known is None or health.RANK[advisory.level] > health.RANK[known.level]:
                worst[affected.mission_id] = advisory
    for mission_id, advisory in worst.items():
        drivers[mission_id].append(
            schemas.DriverOut(
                kind="HEALTH",
                label=f"Health advisory · {advisory.level} · {advisory.topic}",
                reference=advisory.reference,
            )
        )
    for event in (await hazards.list_hazards(session)).events:
        if (
            event.status != "ACTIVE"
            or not event.within_range
            or event.reference in seen
            or event.incident_id in leave_out
        ):
            continue
        mission_id = by_code.get(event.nearest_mission_code or "")
        if mission_id is not None:
            drivers[mission_id].append(
                schemas.DriverOut(
                    kind="HAZARD",
                    label=f"Natural hazard · {event.title}",
                    reference=event.reference,
                )
            )
    impacted: dict[uuid.UUID, int] = defaultdict(int)
    for s in await supply.list_suppliers(session, user, today):
        if s.impacted and s.mission_id is not None:
            impacted[s.mission_id] += 1
    for mission_id, n in impacted.items():
        drivers[mission_id].append(
            schemas.DriverOut(kind="SUPPLY", label=f"{n} supplier{'s' if n > 1 else ''} impacted")
        )
    unavailable: dict[uuid.UUID, int] = defaultdict(int)
    for a in await fleet.list_assets(session, user):
        if a.kind == "VEHICLE" and any(t.code in ("BLOCKED", "IN_ZONE") for t in a.tags):
            unavailable[a.mission_id] += 1
    for mission_id, n in unavailable.items():
        drivers[mission_id].append(
            schemas.DriverOut(kind="FLEET", label=f"{n} vehicle{'s' if n > 1 else ''} unavailable")
        )
    for m in missions:
        sheltering = await twin.sheltering(session, m.id)
        if sheltering is not None:
            drivers[m.id].append(
                schemas.DriverOut(kind="SHELTER", label="Shelter-in-place", reference=sheltering)
            )
    return drivers


def timeline_summary(event_type: str, summary: str) -> str:
    """G-11: a check-in entry names the person; the overview says what happened, not who."""
    return "Check-in: a person needs help." if event_type == "CHECKIN" else summary


async def _timeline(
    session: AsyncSession, current: Any | None, now: datetime, leave_out: list[uuid.UUID]
) -> schemas.TimelineOut:
    if current is None:
        since = now - timedelta(days=RECENT_DAYS)
        rows = await session.execute(
            _RECENT, {"since": since, "limit": RECENT_MAX, "leave_out": leave_out}
        )
        recent = [
            schemas.RecentOut(reference=r.reference, title=r.title, change=r.change, at=r.at)
            for r in rows
        ]
        last = None
        if not recent:  # GFX-06: how long it has been quiet, from the last change on record
            row = (
                await session.execute(
                    _RECENT,
                    {"since": datetime.min.replace(tzinfo=UTC), "limit": 1, "leave_out": leave_out},
                )
            ).first()
            if row:
                last = schemas.RecentOut(
                    reference=row.reference, title=row.title, change=row.change, at=row.at
                )
        return schemas.TimelineOut(incident=None, events=[], recent=recent, last=last)
    rows = await session.execute(
        _TIMELINE,
        {"incident": current.id, "types": list(TIMELINE_TYPES), "limit": TIMELINE_MAX},
    )
    events = [
        schemas.TimelineEventOut(
            occurred_at=r.occurred_at,
            event_type=r.event_type,
            summary=timeline_summary(r.event_type, r.summary),
        )
        for r in rows
    ]
    return schemas.TimelineOut(incident=_ref(current), events=events[::-1], recent=[])


async def overview(
    session: AsyncSession, user: CurrentUser, now: datetime | None = None
) -> schemas.OverviewOut:
    now = now or datetime.now(UTC)
    today = now.date()
    leave_out = list(await intel_queries.exercise_runs(session))
    missions = await list_missions(session, leave_out)
    active = list(await session.execute(_ACTIVE, {"leave_out": leave_out}))
    current = active[0] if active else None
    latest = max(active, key=lambda r: r.opened_at) if active else None
    # Each embassy's readiness: its mission's latest exercise, else the seeded value (EXR-07).
    seeded = {r.mission_id: r.readiness_score for r in await session.execute(_READINESS)}
    drills = await exercise_queries.readiness(session)
    readiness = {**seeded, **{m: d.score for m, d in drills.items() if m in seeded}}
    drivers = await _drivers(session, user, today, active, missions, leave_out)
    attention = [
        schemas.AttentionOut(
            mission_id=m.id,
            mission_code=m.code,
            city=m.city,
            risk=m.display_risk,
            personnel=m.personnel,
            readiness=readiness.get(m.id),
            drivers=drivers.get(m.id, []),
        )
        for m in missions
        if RANK[m.display_risk] >= RANK["MODERATE"]
        or any(d.kind == "INCIDENT" for d in drivers.get(m.id, []))
    ]
    attention.sort(key=lambda a: (-RANK[a.risk], -len(a.drivers), a.mission_code))
    scores = list(readiness.values())
    return schemas.OverviewOut(
        posture=posture(missions, len(active)),
        active_incidents=len(active),
        latest_incident=_ref(latest) if latest else None,
        detection=await _detection(session, now, current, leave_out),
        accounted=await _accounted(session, leave_out),
        readiness=schemas.ReadinessOut(
            mean=round(sum(scores) / len(scores)) if scores else None,
            sites=len(scores),
            from_exercises=sum(m in drills for m in readiness),
            illustrative=sum(m not in drills or drills[m].source != "EXERCISE" for m in readiness),
        ),
        trend=await _trend(session, today, leave_out),
        regions=regions(missions),
        attention=attention,
        timeline=await _timeline(session, current, now, leave_out),
        generated_at=now,
    )


async def export(
    session: AsyncSession, user: CurrentUser, now: datetime | None = None
) -> schemas.OverviewOut:
    """EXE-03: the same overview for the briefing, audited with its headline values only."""
    out = await overview(session, user, now)
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="EXECUTIVE.EXPORT",
        entity_type="executive_overview",
        details={
            "posture": out.posture.level,
            "active_incidents": out.active_incidents,
            "personnel_accounted_pct": out.accounted.pct,
            "missions_requiring_attention": len(out.attention),
            "generated_at": out.generated_at.isoformat(),
        },
    )
    return out
