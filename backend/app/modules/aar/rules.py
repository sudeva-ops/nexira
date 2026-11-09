"""The drafting rules (AAR-04; docs/plan-pilot-aar.md §4): each reads the record in the review's
window and drafts one lesson and action when the record shows it. Evidence is references and
counts, never a name (D-47). People decide every draft (AAR-05)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.aar import service
from app.modules.aar.service import GATE_WAIT_S, NOTIFICATION_TARGET_S, Incident, duration
from app.modules.documents.service import PASSPORTS, ready_by

LABEL = "Drafted from the platform record by rules · reviewed by people"  # G-6
CONFIDENCE_FLOOR = 80  # below this a person's location is a finding (G-3)
DOWN = ("FAULT", "OFFLINE")
NOT_NORMAL = ("DELAYED", "AT_RISK", "BLOCKED")


@dataclass(frozen=True)
class Draft:
    rule_code: str
    finding: str
    action: str
    owner_team: str
    priority: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


_EVENTS = text(
    """
    SELECT e.event_type, e.summary, e.data, c.reference AS campaign
      FROM incident_event e
      LEFT JOIN notification_campaign c ON c.id::text = e.data->>'campaign_id'
     WHERE e.incident_id = :incident AND e.occurred_at <= :until
       AND e.event_type IN ('ESCALATION', 'FLEET', 'SITE', 'SUPPLY')
     ORDER BY e.occurred_at, e.id
    """
)

# Staff and delegates in the exposure; citizens are the consular team's, through the check-in.
_CONFIDENCE = text(
    """
    SELECT count(*) AS exposed,
           count(*) FILTER (WHERE e.confidence < :floor) AS low,
           min(e.confidence) FILTER (WHERE e.confidence < :floor) AS lowest
      FROM incident_exposure e JOIN person p ON p.id = e.subject_id
     WHERE e.incident_id = :incident AND e.subject_type = 'PERSON' AND p.person_type <> 'CITIZEN'
    """
)


async def draft(session: AsyncSession, found: Incident, now: datetime) -> list[Draft]:
    """Every rule, in a fixed order; each fires only on evidence in the window."""
    until = found.until(now)
    rows = list(await session.execute(_EVENTS, {"incident": found.id, "until": until}))
    drafts = [
        _checkin_silent(rows),
        await _low_confidence(session, found),
        await _notify_late(session, found, now),
        await _gate_wait(session, found, now),
        _fleet_zone(rows),
        _site_fault(rows),
        _supply_impact(rows),
        await _docs_expiring(session, found, until),
    ]
    return [d for d in drafts if d is not None]


def _checkin_silent(rows: list[Any]) -> Draft | None:
    silent = [r for r in rows if r.event_type == "ESCALATION" and r.data.get("scope") == "person"]
    if not silent:
        return None
    campaigns = sorted({r.campaign for r in silent if r.campaign})
    return Draft(
        "CHECKIN_SILENT",
        f"{_plural(len(silent), 'staff member')} did not answer "
        f"{', '.join(campaigns) or 'the check-in'} and {'was' if len(silent) == 1 else 'were'} "
        "escalated.",
        "Confirm contact details and a second channel for staff who did not answer.",
        "HR",
        "HIGH",
        {"escalated": len(silent), "campaigns": campaigns},
    )


async def _low_confidence(session: AsyncSession, found: Incident) -> Draft | None:
    row = (
        await session.execute(_CONFIDENCE, {"incident": found.id, "floor": CONFIDENCE_FLOOR})
    ).one()
    if not row.low:
        return None
    return Draft(
        "LOW_CONFIDENCE",
        f"{row.low} of {row.exposed} staff and delegates were located below {CONFIDENCE_FLOOR}% "
        f"confidence (lowest {row.lowest}%).",
        "Enable mobile check-in for staff located from calendar or badge data.",
        "SECURITY",
        "HIGH",
        {"low": row.low, "exposed": row.exposed, "lowest": row.lowest, "floor": CONFIDENCE_FLOOR},
    )


async def _notify_late(session: AsyncSession, found: Incident, now: datetime) -> Draft | None:
    metric = next(
        m
        for m in await service.metrics(session, found, now)
        if m.key == "detection_to_notification"
    )
    if metric.value is None or metric.value <= NOTIFICATION_TARGET_S:
        return None
    return Draft(
        "NOTIFY_LATE",
        f"The first notification went out {duration(metric.value)} after the first signal "
        f"(target {duration(NOTIFICATION_TARGET_S)}).",
        "Review the alert template and its approval for a faster first message.",
        "COMMUNICATIONS",
        "MEDIUM",
        {"seconds": metric.value, "target_s": NOTIFICATION_TARGET_S},
    )


async def _gate_wait(session: AsyncSession, found: Incident, now: datetime) -> Draft | None:
    slow = [d for d in await service.decisions(session, found, now) if d.wait_s > GATE_WAIT_S]
    if not slow:
        return None
    worst = max(slow, key=lambda d: d.wait_s)
    return Draft(
        "GATE_WAIT",
        f"{_plural(len(slow), 'decision')} waited longer than {duration(GATE_WAIT_S)}; the "
        f"longest, {worst.title}, waited {duration(worst.wait_s)} for the "
        f"{service.role_label(worst.role)}.",
        f"Name a deputy for the {service.role_label(worst.role)}'s approvals.",
        "MISSION_MANAGEMENT",
        "MEDIUM",
        {
            "decisions": [
                {"title": d.title, "role": d.role, "seconds": round(d.wait_s)} for d in slow
            ]
        },
    )


def _fleet_zone(rows: list[Any]) -> Draft | None:
    codes = sorted(
        {
            r.data["code"]
            for r in rows
            if r.event_type == "FLEET"
            and r.data.get("crossing") == "entered"
            and r.data.get("code")
        }
    )
    if not codes:
        return None
    return Draft(
        "FLEET_ZONE",
        f"{_plural(len(codes), 'vehicle')} entered the impact zone ({', '.join(codes)}).",
        "Add impact-zone alerts to vehicle routing.",
        "FLEET",
        "MEDIUM",
        {"vehicles": codes},
    )


def _site_fault(rows: list[Any]) -> Draft | None:
    # The summary is "<site> · <device>: <STATUS> (...)": site and device names, no person.
    devices = sorted(
        {
            r.summary.split(":")[0]
            for r in rows
            if r.event_type == "SITE" and r.data.get("status") in DOWN
        }
    )
    if not devices:
        return None
    sensors = sorted(
        {
            r.data["sensor"]
            for r in rows
            if r.event_type == "SITE" and r.data.get("status") in DOWN and r.data.get("sensor")
        }
    )
    return Draft(
        "SITE_FAULT",
        f"{_plural(len(devices), 'site device')} failed or went offline: {'; '.join(devices)}.",
        "Fit backup power and a spare for these devices.",
        "FACILITIES",
        "HIGH",
        {"sensors": sensors},
    )


def _supply_impact(rows: list[Any]) -> Draft | None:
    suppliers = sorted(
        {
            r.data["supplier"]
            for r in rows
            if r.event_type == "SUPPLY"
            and r.data.get("supplier")
            and (r.data.get("status") in NOT_NORMAL or r.data.get("mitigation"))
        }
    )
    if not suppliers:
        return None
    return Draft(
        "SUPPLY_IMPACT",
        f"{_plural(len(suppliers), 'supplier')} impacted ({', '.join(suppliers)}).",
        "Confirm backup suppliers and routes in the continuity plan.",
        "LOGISTICS",
        "MEDIUM",
        {"suppliers": suppliers},
    )


_EVACUATIONS = text(
    """
    SELECT id, reference, requested_at FROM evacuation
     WHERE requested_at <= :until
       AND (incident_id = :incident
            OR (mission_id = :mission AND requested_at >= :since))
     ORDER BY requested_at
    """
)

# The people on an evacuation's manifest and their passport-type documents.
_MANIFEST_DOCUMENTS = text(
    """
    SELECT m.person_id, d.doc_type, d.valid_until
      FROM evacuation_manifest m
      JOIN travel_document d ON d.person_id = m.person_id AND d.doc_type = ANY(:passports)
     WHERE m.evacuation_id = :evacuation
    """
)


async def _docs_expiring(session: AsyncSession, found: Incident, until: datetime) -> Draft | None:
    if found.mission_id is None:
        return None
    # Document Expiry's "could block" counts only while the mission is at risk, and a review
    # starts once the incident is over; so the six-month rule is applied to the manifest as it
    # stood on the day the evacuation was requested (review of the Prompt 111 run).
    flagged: dict[str, int] = {}
    found_evacuations = await session.execute(
        _EVACUATIONS,
        {
            "incident": found.id,
            "mission": found.mission_id,
            "since": found.first_signal_at or found.opened_at,
            "until": until,
        },
    )
    for evacuation in found_evacuations:
        on = evacuation.requested_at.date()
        ready: dict[uuid.UUID, bool] = {}
        for row in await session.execute(
            _MANIFEST_DOCUMENTS, {"evacuation": evacuation.id, "passports": list(PASSPORTS)}
        ):
            ready[row.person_id] = ready.get(row.person_id, False) or ready_by(
                row.doc_type, row.valid_until, on
            )
        n = sum(1 for ok in ready.values() if not ok)
        if n:
            flagged[evacuation.reference] = n
    if not flagged:
        return None
    total = sum(flagged.values())
    return Draft(
        "DOCS_EXPIRING",
        f"{_plural(total, 'person', 'people')} on the evacuation list had no passport valid for "
        f"six months ({', '.join(sorted(flagged))}).",
        "Check document validity for the evacuation list every quarter.",
        "CONSULAR",
        "MEDIUM",
        {"people": total, "evacuations": sorted(flagged)},
    )
