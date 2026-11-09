"""After-Action Review (D-47; docs/plan-pilot-aar.md §2, §3): the reconstructed timeline and the
response metrics, worked out on read from what the platform recorded. Roles, references and
counts only: a summary that may name a person is never copied (G-1)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.aar.schemas import MetricOut, TimelineEntryOut
from app.modules.checkin import service as checkin
from app.modules.tenancy.service import ROLES

DETECTION_TARGET_S = 5.0  # signal to incident, incident to exposure (requirements §5)
NOTIFICATION_TARGET_S = 120.0  # first signal to first notification (the design; §88 Q8)
GATE_WAIT_S = 300.0  # a decision waiting longer than this is a finding (§88 Q8, G-2)

# Timeline entries whose summaries carry codes, references and counts only.
COPIED = {
    "SIGNAL": "INCIDENT",
    "FUSED": "INCIDENT",
    "ESCALATED": "INCIDENT",
    "EXPOSURE": "INCIDENT",
    "PLAYBOOK_STEP": "PLAYBOOK",
    "STATUS": "STATUS",
    "FLEET": "FLEET",
    "SITE": "SITE",
    "SUPPLY": "SUPPLY",
}


@dataclass(frozen=True)
class Incident:
    id: uuid.UUID
    reference: str
    title: str
    mission_id: uuid.UUID | None
    status: str
    opened_at: datetime
    closed_at: datetime | None
    first_signal_at: datetime | None

    def until(self, now: datetime) -> datetime:
        """The window's end: the review's start, or the incident's closing if earlier."""
        return min(now, self.closed_at) if self.closed_at else now


@dataclass(frozen=True)
class Decision:
    """A person's decision on a proposal or a playbook gate, and how long it waited."""

    title: str
    role: str | None
    raised_at: datetime
    decided_at: datetime

    @property
    def wait_s(self) -> float:
        return (self.decided_at - self.raised_at).total_seconds()


def role_label(code: str | None) -> str:
    return ROLES.get(code or "", "a reviewer")


def duration(seconds: float | None) -> str:
    """ "45 s", "1m 45s", "1h 05m"; "—" when there is no figure."""
    if seconds is None:
        return "—"
    s = max(0, round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


_INCIDENT = text(
    """
    SELECT i.id, i.reference, i.title, i.mission_id, i.status, i.opened_at, i.closed_at,
           (SELECT min(s.received_at) FROM incident_signal x JOIN raw_signal s ON s.id = x.signal_id
             WHERE x.incident_id = i.id) AS first_signal_at
      FROM incident i WHERE i.id = :id
    """
)


async def incident(session: AsyncSession, incident_id: uuid.UUID) -> Incident | None:
    row = (await session.execute(_INCIDENT, {"id": incident_id})).one_or_none()
    return Incident(**row._mapping) if row else None


_EVENTS = text(
    """
    SELECT e.occurred_at, e.event_type, e.summary, e.data,
           c.reference AS campaign, ps.name AS step_name, ps.requires_approval_role AS step_role
      FROM incident_event e
      LEFT JOIN notification_campaign c ON c.id::text = e.data->>'campaign_id'
      LEFT JOIN playbook_step ps ON ps.id::text = e.data->>'step_id'
     WHERE e.incident_id = :incident AND e.occurred_at <= :until
     ORDER BY e.occurred_at, e.id
    """
)

_PROPOSALS = text(
    """
    SELECT p.id, p.title, p.status, p.created_at, p.decided_at, a.name AS agent
      FROM agent_proposal p JOIN agent a ON a.id = p.agent_id
     WHERE p.incident_id = :incident AND p.created_at <= :until
     ORDER BY p.created_at, p.id
    """
)

# The decider's role among those the step required ("A|B"), so no name is needed.
_APPROVALS = text(
    """
    SELECT pa.proposal_id, pa.decision, pa.decided_at,
           (SELECT r.code FROM user_role ur JOIN role r ON r.id = ur.role_id
             WHERE ur.user_id = pa.decided_by
               AND r.code = ANY(string_to_array(pa.required_role, '|'))
             ORDER BY r.code LIMIT 1) AS role
      FROM proposal_approval pa JOIN agent_proposal p ON p.id = pa.proposal_id
     WHERE p.incident_id = :incident AND pa.decided_by IS NOT NULL AND pa.decided_at <= :until
     ORDER BY pa.decided_at, pa.id
    """
)

_CAMPAIGNS = text(
    """
    SELECT c.reference, c.campaign_type, c.sent_at,
           (SELECT count(DISTINCT d.person_id) FROM notification_delivery d
             WHERE d.campaign_id = c.id) AS recipients
      FROM notification_campaign c
     WHERE c.incident_id = :incident AND c.sent_at IS NOT NULL AND c.sent_at <= :until
     ORDER BY c.sent_at, c.reference
    """
)


def _event_line(row: Any) -> TimelineEntryOut | None:
    data: dict[str, Any] = row.data or {}
    at = row.occurred_at
    if row.event_type in COPIED:
        return TimelineEntryOut(at=at, source=COPIED[row.event_type], text=row.summary)
    campaign = row.campaign or "the check-in"
    if row.event_type == "CHECKIN":
        return TimelineEntryOut(
            at=at, source="CHECKIN", text=f"Check-in {campaign}: a person needs help."
        )
    if row.event_type == "ESCALATION":
        if data.get("scope") == "person":
            line = f"Check-in {campaign}: a staff member did not answer and was escalated."
        elif data.get("scope") == "citizens":
            line = (
                f"Check-in {campaign}: {data.get('count', 0)} citizens did not answer; "
                "escalated to the consular team."
            )
        else:
            line = "A proposal was not decided in time and was escalated."
        return TimelineEntryOut(at=at, source="CHECKIN" if "scope" in data else "AGENT", text=line)
    if row.event_type == "DECISION":
        verb = "approved" if data.get("decision") == "APPROVE" else "rejected"
        step = f"Step {data.get('seq', '?')} · {row.step_name or 'approval'}"
        return TimelineEntryOut(
            at=at, source="DECISION", text=f"{step}: {verb} by the {role_label(row.step_role)}."
        )
    return None  # NOTE (free text) and anything unknown are left out (G-1)


async def timeline(session: AsyncSession, found: Incident, now: datetime) -> list[TimelineEntryOut]:
    """AAR-02: every source in time order, up to the window's end."""
    until = found.until(now)
    params = {"incident": found.id, "until": until}
    lines: list[TimelineEntryOut] = []
    in_playbook: set[str] = set()
    for row in await session.execute(_EVENTS, params):
        if row.event_type == "PLAYBOOK_STEP" and (ref := (row.data or {}).get("reference")):
            in_playbook.add(ref)
        if (line := _event_line(row)) is not None:
            lines.append(line)
    titles: dict[uuid.UUID, str] = {}
    for p in await session.execute(_PROPOSALS, params):
        titles[p.id] = p.title
        said = (
            f"{p.agent} acted automatically under policy: {p.title}."
            if p.status == "AUTO_EXECUTED"
            else f"{p.agent} proposed: {p.title}."
        )
        lines.append(TimelineEntryOut(at=p.created_at, source="AGENT", text=said))
    for a in await session.execute(_APPROVALS, params):
        verb = "approved" if a.decision == "APPROVE" else "rejected"
        title = titles.get(a.proposal_id, "A proposal")
        lines.append(
            TimelineEntryOut(
                at=a.decided_at,
                source="DECISION",
                text=f"{title}: {verb} by the {role_label(a.role)}.",
            )
        )
    for c in await session.execute(_CAMPAIGNS, params):
        if c.reference in in_playbook:
            continue  # already on the timeline as its playbook step
        lines.append(
            TimelineEntryOut(
                at=c.sent_at,
                source="NOTIFICATION",
                text=f"{c.reference} sent: {c.campaign_type.lower()}, {c.recipients} recipients.",
            )
        )
    if found.first_signal_at is not None and found.first_signal_at < found.opened_at:
        lines.append(
            TimelineEntryOut(
                at=found.first_signal_at, source="INCIDENT", text="First signal received."
            )
        )
    return sorted(lines, key=lambda line: line.at)


# --- the metrics (AAR-03) -------------------------------------------------------------------

_FIRST_EXPOSURE = text(
    "SELECT min(occurred_at) FROM incident_event "
    "WHERE incident_id = :incident AND event_type = 'EXPOSURE'"
)

# A gate waits from its AWAITING_APPROVAL step to the DECISION on it (G-2).
_GATES = text(
    """
    SELECT ps.name, ps.requires_approval_role AS role, w.occurred_at AS raised_at,
           d.occurred_at AS decided_at, (d.data->>'seq') AS seq
      FROM incident_event d
      JOIN incident_event w ON w.incident_id = d.incident_id AND w.event_type = 'PLAYBOOK_STEP'
       AND w.data->>'step_id' = d.data->>'step_id' AND w.data->>'run_id' = d.data->>'run_id'
       AND w.data->>'status' = 'AWAITING_APPROVAL'
      LEFT JOIN playbook_step ps ON ps.id::text = d.data->>'step_id'
     WHERE d.incident_id = :incident AND d.event_type = 'DECISION' AND d.occurred_at <= :until
    """
)

_PLAYBOOK = text(
    """
    SELECT started_at, completed_at FROM playbook_run
     WHERE incident_id = :incident AND completed_at IS NOT NULL AND completed_at <= :until
     ORDER BY started_at LIMIT 1
    """
)

_CHECKIN = text(
    """
    SELECT c.id, c.reference, c.sent_at,
           (SELECT max(l.responded_at) FROM v_checkin_latest l JOIN person p ON p.id = l.person_id
             WHERE l.campaign_id = c.id AND p.person_type <> 'CITIZEN') AS last_answer
      FROM notification_campaign c
     WHERE c.incident_id = :incident AND c.campaign_type = 'CHECKIN' AND c.sent_at IS NOT NULL
     ORDER BY c.sent_at DESC LIMIT 1
    """
)

_FIRST_NOTIFICATION = text(
    "SELECT min(sent_at) FROM notification_campaign "
    "WHERE incident_id = :incident AND sent_at IS NOT NULL AND sent_at <= :until"
)


async def decisions(session: AsyncSession, found: Incident, now: datetime) -> list[Decision]:
    """The decisions people made: proposals they approved or rejected, and playbook gates."""
    params = {"incident": found.id, "until": found.until(now)}
    titles = {p.id: p for p in await session.execute(_PROPOSALS, params)}
    out: list[Decision] = []
    for a in await session.execute(_APPROVALS, params):
        p = titles.get(a.proposal_id)
        if p is not None:
            out.append(Decision(p.title, a.role, p.created_at, a.decided_at))
    for g in await session.execute(_GATES, params):
        out.append(
            Decision(f"Step {g.seq} · {g.name or 'approval'}", g.role, g.raised_at, g.decided_at)
        )
    return sorted(out, key=lambda d: d.decided_at)


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    """None without both times. The incident opens in the same transaction that stores its
    first signal, a few milliseconds apart in either order, so a gap under a second is 0."""
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < -1:
        return None
    return round(max(0.0, seconds), 2)


def _timed(key: str, label: str, value: float | None, target: float | None) -> MetricOut:
    met = None if value is None or target is None else value <= target
    return MetricOut(key=key, label=label, value=value, unit="s", target=target, met=met)


async def metrics(session: AsyncSession, found: Incident, now: datetime) -> list[MetricOut]:
    """AAR-03, with each formula as plan §3."""
    params = {"incident": found.id, "until": found.until(now)}
    exposure_at = await session.scalar(_FIRST_EXPOSURE, params)
    notified_at = await session.scalar(_FIRST_NOTIFICATION, params)
    out = [
        _timed(
            "detection_to_incident",
            "Detection → incident",
            _seconds(found.first_signal_at, found.opened_at),
            DETECTION_TARGET_S,
        ),
        _timed(
            "incident_to_exposure",
            "Incident → exposure",
            _seconds(found.opened_at, exposure_at),
            DETECTION_TARGET_S,
        ),
        _timed(
            "detection_to_notification",
            "Detection → first notification",
            _seconds(found.first_signal_at, notified_at),
            NOTIFICATION_TARGET_S,
        ),
    ]
    made = await decisions(session, found, now)
    waits = [d.wait_s for d in made]
    out.append(
        MetricOut(
            key="decision_median",
            label="Decision speed · median",
            value=round(median(waits), 2) if waits else None,
            unit="s",
            target=None,
            met=None,
            detail=f"{len(waits)} decision{'s' if len(waits) != 1 else ''} by people",
        )
    )
    slowest = max(made, key=lambda d: d.wait_s, default=None)
    out.append(
        MetricOut(
            key="decision_slowest",
            label="Decision speed · slowest",
            value=round(slowest.wait_s, 2) if slowest else None,
            unit="s",
            target=GATE_WAIT_S,
            met=None if slowest is None else slowest.wait_s <= GATE_WAIT_S,
            detail=f"{slowest.title} · {role_label(slowest.role)}" if slowest else None,
        )
    )
    out.append(await _accounted(session, found))
    run = (await session.execute(_PLAYBOOK, params)).one_or_none()
    out.append(
        _timed(
            "playbook",
            "Playbook · started → completed",
            _seconds(run.started_at, run.completed_at) if run else None,
            None,
        )
    )
    return out


def half_up(value: float) -> int:
    """Rounds half away from zero, as PostgreSQL's round(numeric) (89.5 → 90), so the figures
    agree with what the database checks (migration 0017); Python's round() rounds half to even."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Answers:
    """The incident's latest check-in and how many mission personnel answered it."""

    campaign_id: uuid.UUID
    reference: str
    sent_at: datetime
    last_answer: datetime | None
    answered: int  # SAFE or NEED HELP
    asked: int


async def checkin_answers(session: AsyncSession, found: Incident) -> Answers | None:
    """Executive Overview's rule (EXE-01) for this incident's check-in."""
    row = (await session.execute(_CHECKIN, {"incident": found.id})).one_or_none()
    if row is None:
        return None
    personnel = (await checkin.tally(session, row.id))["personnel"]
    return Answers(
        row.id,
        row.reference,
        row.sent_at,
        row.last_answer,
        personnel.safe + personnel.need_help,
        personnel.recipients,
    )


async def _accounted(session: AsyncSession, found: Incident) -> MetricOut:
    """Personnel accounted, and how long it took."""
    answers = await checkin_answers(session, found)
    if answers is None:
        return MetricOut(
            key="personnel_accounted",
            label="Personnel accounted",
            value=None,
            unit="%",
            target=None,
            met=None,
        )
    pct = half_up(100 * answers.answered / answers.asked) if answers.asked else None
    took = _seconds(answers.sent_at, answers.last_answer)
    return MetricOut(
        key="personnel_accounted",
        label="Personnel accounted",
        value=pct,
        unit="%",
        target=None,
        met=None,
        detail=f"{answers.answered} of {answers.asked} · {answers.reference}"
        + (f" · in {duration(took)}" if took is not None else ""),
    )
