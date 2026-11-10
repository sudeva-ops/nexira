"""Safety check-in (CHK-01..03, D-07, D-28).

- Every answer is kept in checkin_response; the latest one counts (v_checkin_latest).
- Answers come from the API (a staff user recording it, or the phone preview panel)
  and from simulator events (the person answering on a simulated channel).
- Escalation (plan G-19): when escalate_after_s has passed since the campaign was
  sent, each personnel non-responder gets one ESCALATION incident event and one
  audit row; citizens who have not answered get one aggregate event per campaign.
  Both happen once: the CHECKIN.ESCALATE audit rows (always written, unlike the
  timeline event, which needs an incident) are checked with the campaign locked.
- In a demo, a scene can start the clock (CHECKIN_CLOCK, start_clock): open
  check-ins of the run then escalate a set time after that scene, not after sending.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import Event
from app.modules.audit.models import AuditLog
from app.modules.checkin.models import CheckinResponse
from app.modules.intel.models import IncidentEvent
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.people.models import Person
from app.modules.tenancy.service import Actor

ESCALATOR = Actor(type="SYSTEM", id="checkin.escalation")
OPEN = ("SENDING", "SENT")
Answer = Literal["SAFE", "NEED_HELP"]


class CheckinError(Exception):
    """The answer cannot be recorded (not a check-in, closed, not a recipient)."""


async def open_campaign_for(session: AsyncSession, person_id: uuid.UUID) -> uuid.UUID | None:
    """The newest open CHECKIN campaign this person was sent ("latest_open_checkin")."""
    return await session.scalar(
        select(NotificationCampaign.id)
        .join(NotificationDelivery, NotificationDelivery.campaign_id == NotificationCampaign.id)
        .where(
            NotificationCampaign.campaign_type == "CHECKIN",
            NotificationCampaign.status.in_(OPEN),
            NotificationDelivery.person_id == person_id,
        )
        .order_by(NotificationCampaign.created_at.desc())
        .limit(1)
    )


async def record_response(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    person_id: uuid.UUID,
    status: Answer,
    channel: str | None,
    note: str | None,
    actor: Actor,
    source_event_id: str | None = None,
) -> CheckinResponse:
    """Store one answer (history is kept; the latest counts) and audit it.
    source_event_id: the stream event it came from, recorded for idempotency."""
    campaign = await session.get(NotificationCampaign, campaign_id)
    if campaign is None or campaign.campaign_type != "CHECKIN":
        raise CheckinError("Not a check-in campaign")
    if campaign.status not in OPEN:
        raise CheckinError(f"Check-in {campaign.reference} is {campaign.status}")
    recipient = await session.scalar(
        select(NotificationDelivery.id)
        .where(
            NotificationDelivery.campaign_id == campaign_id,
            NotificationDelivery.person_id == person_id,
        )
        .limit(1)
    )
    if recipient is None:
        raise CheckinError("This person was not sent this check-in")
    response = CheckinResponse(
        tenant_id=campaign.tenant_id,
        campaign_id=campaign_id,
        person_id=person_id,
        status=status,
        channel=channel,
        note=note,
    )
    session.add(response)
    await session.flush()
    if status == "NEED_HELP" and campaign.incident_id is not None:
        person = await session.get_one(Person, person_id)
        session.add(
            IncidentEvent(
                tenant_id=campaign.tenant_id,
                incident_id=campaign.incident_id,
                event_type="CHECKIN",
                summary=f"{person.full_name} needs help ({campaign.reference}"
                f"{', ' + channel if channel else ''}).",
                actor_type=actor.type,
                actor_id=actor.id,
                data={
                    "campaign_id": str(campaign_id),
                    "person_id": str(person_id),
                    "status": status,
                },
            )
        )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="CHECKIN.RESPOND",
        entity_type="notification_campaign",
        entity_id=campaign.reference,
        details={
            "person_id": str(person_id),
            "status": status,
            "channel": channel,
            "response_id": response.id,
            **({"event_id": source_event_id} if source_event_id else {}),
        },
    )
    return response


async def already_recorded(session: AsyncSession, event_id: str) -> bool:
    """Whether a stream event's answer is already stored (redelivery after a crash)."""
    found = await session.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.action == "CHECKIN.RESPOND",
            AuditLog.details["event_id"].as_string() == event_id,
        )
        .limit(1)
    )
    return found is not None


def updated_event(campaign: NotificationCampaign, kind: str = "CHECKIN_UPDATED") -> Event:
    return Event(
        type=kind,
        tenant_id=campaign.tenant_id,
        payload={
            "campaign_id": str(campaign.id),
            "reference": campaign.reference,
            "incident_id": str(campaign.incident_id) if campaign.incident_id else None,
        },
        source="checkin",
    )


@dataclass(frozen=True)
class Tally:
    recipients: int
    safe: int
    need_help: int
    pending: int

    @property
    def accounted_pct(self) -> float:
        if not self.recipients:
            return 0.0
        return round(100 * (self.safe + self.need_help) / self.recipients, 1)


_TALLY = text(
    """
    WITH recipients AS (
      SELECT DISTINCT d.person_id, (p.person_type = 'CITIZEN') AS citizen
        FROM notification_delivery d JOIN person p ON p.id = d.person_id
       WHERE d.campaign_id = :campaign_id
    )
    SELECT r.citizen,
           count(*) AS recipients,
           count(*) FILTER (WHERE l.status = 'SAFE') AS safe,
           count(*) FILTER (WHERE l.status = 'NEED_HELP') AS need_help,
           count(*) FILTER (WHERE l.status IS NULL) AS pending
      FROM recipients r
      LEFT JOIN v_checkin_latest l ON l.campaign_id = :campaign_id AND l.person_id = r.person_id
     GROUP BY r.citizen
    """
)


async def tally(session: AsyncSession, campaign_id: uuid.UUID) -> dict[str, Tally]:
    """{"personnel": ..., "citizens": ...}, from the latest answer per person."""
    out = {"personnel": Tally(0, 0, 0, 0), "citizens": Tally(0, 0, 0, 0)}
    for row in await session.execute(_TALLY, {"campaign_id": campaign_id}):
        out["citizens" if row.citizen else "personnel"] = Tally(
            row.recipients, row.safe, row.need_help, row.pending
        )
    return out


_PENDING = text(
    """
    SELECT DISTINCT p.id, p.full_name, (p.person_type = 'CITIZEN') AS citizen
      FROM notification_delivery d
      JOIN person p ON p.id = d.person_id
      LEFT JOIN v_checkin_latest l ON l.campaign_id = d.campaign_id AND l.person_id = d.person_id
     WHERE d.campaign_id = :campaign_id AND l.person_id IS NULL
     ORDER BY p.full_name, p.id
    """
)


@dataclass
class Escalated:
    campaign: NotificationCampaign
    personnel: list[str]  # names, escalated one by one
    citizens: int  # escalated as one aggregate (0 = none this time)


async def escalate_now(session: AsyncSession, campaign_id: uuid.UUID, actor: Actor) -> Escalated:
    """A user escalates non-responders before the timer ("Escalate non-responders",
    Prompt 11). The same once-only rules apply; the user is the actor."""
    campaign = await session.scalar(
        select(NotificationCampaign).where(NotificationCampaign.id == campaign_id).with_for_update()
    )
    if campaign is None or campaign.campaign_type != "CHECKIN":
        raise CheckinError("Not a check-in campaign")
    if campaign.status not in OPEN:
        raise CheckinError(f"Check-in {campaign.reference} is {campaign.status}")
    return await _escalate(session, campaign, actor, reason="by a user")


async def escalate_due(session: AsyncSession, now: datetime) -> list[Escalated]:
    """Escalate non-responders of every open check-in whose time has come (D-07)."""
    campaigns = await session.scalars(
        select(NotificationCampaign)
        .where(
            NotificationCampaign.campaign_type == "CHECKIN",
            NotificationCampaign.status.in_(OPEN),
            NotificationCampaign.sent_at.is_not(None),
        )
        .with_for_update(skip_locked=True)
    )
    done: list[Escalated] = []
    for campaign in list(campaigns):
        sent_at = campaign.sent_at
        if sent_at is None or now < sent_at + timedelta(seconds=campaign.escalate_after_s):
            continue
        result = await _escalate(
            session, campaign, ESCALATOR, reason=f"after {campaign.escalate_after_s} s"
        )
        if result.personnel or result.citizens:
            done.append(result)
    return done


async def for_incidents(
    session: AsyncSession, campaign_id: uuid.UUID, incidents: list[uuid.UUID]
) -> bool:
    """Whether the campaign is a check-in of one of these incidents."""
    found = await session.scalar(
        select(NotificationCampaign.id).where(
            NotificationCampaign.id == campaign_id,
            NotificationCampaign.campaign_type == "CHECKIN",
            NotificationCampaign.incident_id.in_(incidents),
        )
    )
    return found is not None


async def start_clock(
    session: AsyncSession,
    *,
    escalate_in_s: int,
    since: datetime | None,
    now: datetime,
    actor: Actor,
    incidents: list[uuid.UUID] | None = None,
) -> list[NotificationCampaign]:
    """A demo scene starts the check-in clock: each open check-in created since the
    run started escalates escalate_in_s from now (escalate_after_s still counts from
    sent_at, D-07). Once per campaign: the CHECKIN.CLOCK_START audit rows are checked
    with the campaigns locked, so a redelivered event changes nothing."""
    query = (
        select(NotificationCampaign)
        .where(
            NotificationCampaign.campaign_type == "CHECKIN",
            NotificationCampaign.status.in_(OPEN),
        )
        .with_for_update()
    )
    if since is not None:
        query = query.where(NotificationCampaign.created_at >= since)
    if incidents is not None:  # an exercise times its own incidents' check-ins only
        query = query.where(NotificationCampaign.incident_id.in_(incidents))
    campaigns = list(await session.scalars(query))
    started = set(
        await session.scalars(
            select(AuditLog.entity_id).where(
                AuditLog.action == "CHECKIN.CLOCK_START",
                AuditLog.entity_type == "notification_campaign",
            )
        )
    )
    changed: list[NotificationCampaign] = []
    for campaign in campaigns:
        if campaign.reference in started:
            continue
        elapsed = 0
        if campaign.sent_at is not None:
            elapsed = max(0, math.ceil((now - campaign.sent_at).total_seconds()))
        before = campaign.escalate_after_s
        campaign.escalate_after_s = elapsed + escalate_in_s
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="CHECKIN.CLOCK_START",
            entity_type="notification_campaign",
            entity_id=campaign.reference,
            details={"before": before, "after": campaign.escalate_after_s},
        )
        changed.append(campaign)
    await session.flush()
    return changed


async def _escalate(
    session: AsyncSession, campaign: NotificationCampaign, actor: Actor, reason: str
) -> Escalated:
    previous = await session.scalars(
        select(AuditLog.details).where(
            AuditLog.action == "CHECKIN.ESCALATE",
            AuditLog.entity_type == "notification_campaign",
            AuditLog.entity_id == campaign.reference,
        )
    )
    escalated_people: set[str] = set()
    citizens_done = False
    for data in previous:
        if data.get("scope") == "citizens":
            citizens_done = True
        elif data.get("person_id"):
            escalated_people.add(str(data["person_id"]))

    pending = (await session.execute(_PENDING, {"campaign_id": campaign.id})).all()
    result = Escalated(campaign, [], 0)
    for person_id, name, citizen in pending:
        if citizen or str(person_id) in escalated_people:
            continue
        _event(
            session,
            campaign,
            f"{name} has not answered {campaign.reference}: escalated {reason}.",
            {"scope": "person", "person_id": str(person_id)},
            actor,
        )
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="CHECKIN.ESCALATE",
            entity_type="notification_campaign",
            entity_id=campaign.reference,
            details={"scope": "person", "person_id": str(person_id)},
        )
        result.personnel.append(name)
    silent_citizens = sum(1 for _, _, citizen in pending if citizen)
    if silent_citizens and not citizens_done:
        _event(
            session,
            campaign,
            f"{silent_citizens} citizens have not answered {campaign.reference}: "
            f"escalated to the consular team {reason}.",
            {"scope": "citizens", "count": silent_citizens},
            actor,
        )
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="CHECKIN.ESCALATE",
            entity_type="notification_campaign",
            entity_id=campaign.reference,
            details={"scope": "citizens", "count": silent_citizens},
        )
        result.citizens = silent_citizens
    await session.flush()
    return result


def _event(
    session: AsyncSession,
    campaign: NotificationCampaign,
    summary: str,
    data: dict[str, object],
    actor: Actor,
) -> None:
    if campaign.incident_id is None:
        return
    session.add(
        IncidentEvent(
            tenant_id=campaign.tenant_id,
            incident_id=campaign.incident_id,
            event_type="ESCALATION",  # D-07 (plan G-25)
            summary=summary,
            actor_type=actor.type,
            actor_id=actor.id,
            data={"campaign_id": str(campaign.id), **data},
        )
    )
