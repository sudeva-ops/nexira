"""Incident Replay (RPL-01, RPL-04, RPL-05; D-51; docs/plan-pilot-rpl.md §2): what the platform
recorded about one incident, in one payload, for the browser to play back. Worked out on read;
nothing is stored. No person's name or id leaves here: people are indexed dots.

- The window starts at the first linked signal's received time (G-1) and ends now while the
  incident is ACTIVE; otherwise at the last thing the record holds, or its closing (G-2: A).
- A person shows from the first exposure on the timeline, or their own exposure row if earlier:
  each recompute rewrites `computed_at`, so the row alone would show everyone late.
- People are where they are now; the platform keeps no location history (RPL-02).
- The check-in is the incident's latest, personnel only (G-3); trips are a count, restricted
  ones left out (G-4, D-33)."""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.aar import service as aar
from app.modules.checkin import service as checkin
from app.modules.checkin.schemas import TallyOut
from app.modules.intel.queries import exercise_runs
from app.modules.replay.schemas import (
    AnswerOut,
    ReplayCheckinOut,
    ReplayIncidentOut,
    ReplayOut,
    ReplayPersonOut,
    ReplaySignalOut,
    ReplaySiteOut,
    WindowOut,
)

_INCIDENT = text(
    """
    SELECT i.severity, i.impact_radius_m,
           ST_X(i.location::geometry) AS lon, ST_Y(i.location::geometry) AS lat,
           (SELECT min(occurred_at) FROM incident_event
             WHERE incident_id = i.id AND event_type = 'EXPOSURE') AS first_exposure
      FROM incident i WHERE i.id = :incident
    """
)

_SIGNALS = text(
    """
    SELECT s.received_at, s.norm_severity AS severity,
           ST_X(s.location::geometry) AS lon, ST_Y(s.location::geometry) AS lat
      FROM incident_signal x JOIN raw_signal s ON s.id = x.signal_id
     WHERE x.incident_id = :incident
     ORDER BY s.received_at, s.id
    """
)

_PEOPLE = text(
    """
    SELECT e.subject_id AS person_id, e.computed_at, (p.person_type <> 'CITIZEN') AS personnel,
           ST_X(l.location::geometry) AS lon, ST_Y(l.location::geometry) AS lat
      FROM incident_exposure e
      JOIN person p ON p.id = e.subject_id
      LEFT JOIN person_location_current l ON l.person_id = p.id
     WHERE e.incident_id = :incident AND e.subject_type = 'PERSON'
     ORDER BY e.distance_m, e.subject_id
    """
)

_SITES = text(
    """
    SELECT s.name, e.computed_at,
           ST_X(s.location::geometry) AS lon, ST_Y(s.location::geometry) AS lat
      FROM incident_exposure e JOIN site s ON s.id = e.subject_id
     WHERE e.incident_id = :incident AND e.subject_type = 'SITE'
     ORDER BY e.distance_m, s.name
    """
)

_TRIPS = text(
    """
    SELECT count(*) FROM incident_exposure e JOIN trip t ON t.id = e.subject_id
     WHERE e.incident_id = :incident AND e.subject_type = 'TRIP' AND NOT t.restricted
    """
)

_CAMPAIGN = text(
    """
    SELECT id, reference, sent_at FROM notification_campaign
     WHERE incident_id = :incident AND campaign_type = 'CHECKIN'
     ORDER BY created_at DESC LIMIT 1
    """
)

_RECIPIENTS = text(
    """
    SELECT DISTINCT d.person_id, (p.person_type <> 'CITIZEN') AS personnel
      FROM notification_delivery d JOIN person p ON p.id = d.person_id
     WHERE d.campaign_id = :campaign
    """
)

_ANSWERS = text(
    """
    SELECT person_id, responded_at, status FROM checkin_response
     WHERE campaign_id = :campaign ORDER BY responded_at, id
    """
)


def _end(found: aar.Incident, last: list[datetime | None], now: datetime) -> datetime:
    """G-2 (A): ACTIVE plays to now; otherwise to the last recorded moment or the closing."""
    if found.status == "ACTIVE":
        return now
    moments = [m for m in [*last, found.closed_at] if m is not None]
    return min(now, max(moments)) if moments else now


async def replay(session: AsyncSession, incident_id: uuid.UUID, now: datetime) -> ReplayOut | None:
    found = await aar.incident(session, incident_id)
    if found is None:
        return None
    params: dict[str, Any] = {"incident": incident_id}
    inc = (await session.execute(_INCIDENT, params)).one()
    signals = list(await session.execute(_SIGNALS, params))
    timeline = await aar.timeline(session, found, now)

    def shown_from(computed_at: datetime) -> datetime:
        first: datetime | None = inc.first_exposure
        return min(computed_at, first) if first else computed_at

    campaign = (await session.execute(_CAMPAIGN, params)).one_or_none()
    answers: dict[uuid.UUID, list[AnswerOut]] = defaultdict(list)
    recipients: dict[uuid.UUID, bool] = {}
    out_checkin: ReplayCheckinOut | None = None
    if campaign is not None:
        recipients = {
            r.person_id: r.personnel
            for r in await session.execute(_RECIPIENTS, {"campaign": campaign.id})
        }
        for a in await session.execute(_ANSWERS, {"campaign": campaign.id}):
            answers[a.person_id].append(AnswerOut(at=a.responded_at, status=a.status))
        t = (await checkin.tally(session, campaign.id))["personnel"]
        out_checkin = ReplayCheckinOut(
            reference=campaign.reference,
            sent_at=campaign.sent_at,
            personnel=[answers[p] for p, personnel in sorted(recipients.items()) if personnel],
            tally_end=TallyOut(
                recipients=t.recipients,
                safe=t.safe,
                need_help=t.need_help,
                pending=t.pending,
                accounted_pct=t.accounted_pct,
            ),
        )

    people = [
        ReplayPersonOut(
            index=i,
            lon=p.lon,
            lat=p.lat,
            exposed_at=shown_from(p.computed_at),
            personnel=p.personnel,
            asked=p.person_id in recipients,
            answers=answers.get(p.person_id, []),
        )
        for i, p in enumerate(await session.execute(_PEOPLE, params))
    ]
    last_answer = max((a.at for rows in answers.values() for a in rows), default=None)
    start = found.first_signal_at or found.opened_at
    end = max(start, _end(found, [timeline[-1].at if timeline else None, last_answer], now))
    runs = await exercise_runs(session, [incident_id])
    return ReplayOut(
        window=WindowOut(start=start, end=end),
        incident=ReplayIncidentOut(
            id=str(found.id),
            reference=found.reference,
            title=found.title,
            severity=inc.severity,
            status=found.status,
            lon=inc.lon,
            lat=inc.lat,
            impact_radius_m=inc.impact_radius_m,
            opened_at=found.opened_at,
            exercise=incident_id in runs,
        ),
        signals=[
            ReplaySignalOut(received_at=s.received_at, lon=s.lon, lat=s.lat, severity=s.severity)
            for s in signals
        ],
        people=people,
        sites=[
            ReplaySiteOut(name=s.name, lon=s.lon, lat=s.lat, exposed_at=shown_from(s.computed_at))
            for s in await session.execute(_SITES, params)
        ],
        trips=await session.scalar(_TRIPS, params) or 0,
        checkin=out_checkin,
        timeline=timeline,
    )
