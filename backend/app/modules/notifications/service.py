"""Notification campaigns and deliveries (Prompts 9 and 10).

Outbox: create_campaign() writes the campaign and one QUEUED notification_delivery
row per recipient and channel, in the caller's transaction (for a playbook step,
the step's own transaction). dispatch() later sends QUEUED rows through the
channel adapter (channels.py) and marks them SENT. A crash between the adapter
call and the update can only repeat a send with the same idempotency key (the
delivery id); it can never create a second delivery.

Audit (plan G-20): CAMPAIGN.CREATE, CAMPAIGN.SEND (counts per channel) and
CAMPAIGN.DISPATCHED once per campaign. Per-delivery receipts are telemetry.
"""

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import Event
from app.modules.notifications.channels import CHANNELS, Recipient, adapter_for
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.people.models import Person
from app.modules.tenancy.service import Actor

DISPATCHER = Actor(type="SYSTEM", id="notifications.dispatcher")
DISPATCH_BATCH = 500

CAMPAIGN_TYPES = ("ALERT", "CHECKIN", "ADVISORY", "TEST")
DEFAULT_ESCALATE_AFTER_S = 600  # D-07


class AudienceError(ValueError):
    pass


class CitizensWithoutApprovalError(ValueError):
    """A user campaign without a second person's approval would reach a citizen (D-31)."""


async def resolve_audience(
    session: AsyncSession, incident_id: uuid.UUID | None, audience: dict[str, Any]
) -> list[uuid.UUID]:
    """Active people an audience spec selects, ordered by id.

    Specs used by PB-07 (plan G-14):
    - {"exposed": true, "person_types": [...]}: exposed to the incident (optional types)
    - {"mission": "incident", "role_titles": [...]}: people of the incident's mission
      with one of these role titles
    Spec used by the composer (MN-02), with or without an incident:
    - {"missions": [mission ids], "person_types": [...]}: people of those missions
    """
    if audience.get("missions"):
        rows = await session.scalars(
            text(
                """
                SELECT p.id FROM person p
                 WHERE p.is_active AND p.mission_id = ANY(CAST(:missions AS uuid[]))
                   AND (CAST(:types AS text[]) IS NULL OR p.person_type = ANY(:types))
                 ORDER BY p.id
                """
            ),
            {
                "missions": [str(m) for m in audience["missions"]],
                "types": audience.get("person_types"),
            },
        )
        return list(rows)
    if incident_id is None:
        raise AudienceError("this audience needs an incident")
    if audience.get("exposed"):
        rows = await session.scalars(
            text(
                """
                SELECT p.id FROM incident_exposure e JOIN person p ON p.id = e.subject_id
                 WHERE e.incident_id = :incident_id AND e.subject_type = 'PERSON' AND p.is_active
                   AND (CAST(:types AS text[]) IS NULL OR p.person_type = ANY(:types))
                 ORDER BY p.id
                """
            ),
            {"incident_id": incident_id, "types": audience.get("person_types")},
        )
        return list(rows)
    if audience.get("mission") == "incident":
        rows = await session.scalars(
            text(
                """
                SELECT p.id FROM incident i JOIN person p ON p.mission_id = i.mission_id
                 WHERE i.id = :incident_id AND p.is_active
                   AND p.role_title = ANY(:titles)
                 ORDER BY p.id
                """
            ),
            {"incident_id": incident_id, "titles": list(audience.get("role_titles") or [])},
        )
        return list(rows)
    raise AudienceError(f"unsupported audience {audience!r}")


@dataclass(frozen=True)
class CampaignIn:
    campaign_type: str
    message: str
    channels: list[str]
    audience: dict[str, Any]
    translations: dict[str, str] | None = None
    escalate_after_s: int = DEFAULT_ESCALATE_AFTER_S


# A demo is running only once a scenario has been played: an IDLE run (created
# when someone opens the presenter bar) does not count.
DEMO_RUNNING = ("PLAYING", "PAUSED")


async def demo_running(session: AsyncSession) -> bool:
    """Whether this tenant has a demo scenario run in progress."""
    found = await session.scalar(
        text("SELECT 1 FROM scenario_run WHERE mode = 'DEMO' AND status = ANY(:running) LIMIT 1"),
        {"running": list(DEMO_RUNNING)},
    )
    return found is not None


async def demo_started_at(session: AsyncSession) -> datetime | None:
    """When the running demo scenario run was first played (None if none is running)."""
    started: datetime | None = await session.scalar(
        text(
            """
            SELECT started_at FROM scenario_run
             WHERE mode = 'DEMO' AND status = ANY(:running)
             ORDER BY started_at DESC NULLS LAST
             LIMIT 1
            """
        ),
        {"running": list(DEMO_RUNNING)},
    )
    return started


async def scenario_escalate_after_s(session: AsyncSession) -> int | None:
    """The check-in escalation time while a demo scenario is running
    (SCENARIO_SETTINGS, Prompt 5: 20 s for NBO-CIVIL-UNREST). Otherwise None, and
    the campaign keeps its own value. Pilot tenants have no scenario runs.

    Before the run reaches checkin_clock_scene (scene 4 for NBO-CIVIL-UNREST) it is
    None too: that scene's CHECKIN_CLOCK event starts the clock (checkin.start_clock),
    so a presenter who stays on scene 3 does not see escalation early."""
    value = await session.scalar(
        text(
            """
            SELECT CASE
                     WHEN r.current_scene >= COALESCE((e.payload ->> 'checkin_clock_scene')::int, 0)
                     THEN (e.payload ->> 'checkin_escalate_after_s')::int
                   END
              FROM scenario_run r
              JOIN scenario_event e ON e.scenario_id = r.scenario_id
             WHERE r.mode = 'DEMO' AND r.status = ANY(:running)
               AND e.event_type = 'SCENARIO_SETTINGS'
               AND e.payload ? 'checkin_escalate_after_s'
             ORDER BY r.started_at DESC NULLS LAST
             LIMIT 1
            """
        ),
        {"running": list(DEMO_RUNNING)},
    )
    return int(value) if value is not None else None


async def create_campaign(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    campaign: CampaignIn,
    created_by_type: str,
    created_by: str,
    actor: Actor,
) -> tuple[NotificationCampaign, int]:
    """Create a campaign with an NTF reference (D-18) and queue one delivery per
    recipient and channel (status SENDING). Returns it and the recipient count."""
    if campaign.campaign_type not in CAMPAIGN_TYPES:
        raise ValueError(f"unknown campaign type {campaign.campaign_type}")
    if not campaign.channels or not set(campaign.channels) <= set(CHANNELS):
        raise ValueError(f"unknown channels {campaign.channels}")
    recipients = await resolve_audience(session, incident_id, campaign.audience)
    escalate_after_s = campaign.escalate_after_s
    if campaign.campaign_type == "CHECKIN":
        escalate_after_s = await scenario_escalate_after_s(session) or escalate_after_s
    reference = await session.scalar(text("SELECT next_reference('NTF', false)"))
    row = NotificationCampaign(
        tenant_id=session.info["tenant_id"],
        reference=reference,
        incident_id=incident_id,
        campaign_type=campaign.campaign_type,
        message=campaign.message,
        translations=campaign.translations or {},
        channels=campaign.channels,
        audience_filter={**campaign.audience, "incident_id": str(incident_id)},
        created_by_type=created_by_type,
        created_by=created_by,
        escalate_after_s=escalate_after_s,
        status="SENDING" if recipients else "SENT",
        sent_at=None if recipients else func.now(),  # nothing to send: done now
    )
    session.add(row)
    await session.flush()
    await _insert_deliveries(session, row, recipients)
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="CAMPAIGN.CREATE",
        entity_type="notification_campaign",
        entity_id=row.reference,
        details={
            "campaign_type": row.campaign_type,
            "channels": row.channels,
            "recipients": len(recipients),
            "incident_id": str(incident_id),
            "created_by": f"{created_by_type}:{created_by}",
        },
    )
    await _audit_send(session, row, recipients, actor)
    return row, len(recipients)


async def queue_deliveries(
    session: AsyncSession,
    campaign: NotificationCampaign,
    actor: Actor,
    recipients: list[uuid.UUID] | None = None,
) -> int:
    """Queue a composed campaign that is now SENDING (MN-01): one QUEUED delivery per
    recipient and channel, through the same outbox as playbook and agent campaigns.
    recipients: the people already resolved by the caller (who decided on them);
    otherwise the audience is resolved now. A user campaign that was not approved by
    a second person never reaches a citizen: that fails closed here (D-31).
    Returns the recipient count."""
    if campaign.status != "SENDING":
        raise ValueError(f"campaign {campaign.reference} is {campaign.status}, not SENDING")
    if recipients is None:
        recipients = await resolve_audience(session, campaign.incident_id, campaign.audience_filter)
    if campaign.created_by_type == "USER" and campaign.approved_by is None and recipients:
        citizen = await session.scalar(
            text(
                "SELECT 1 FROM person WHERE id = ANY(CAST(:ids AS uuid[])) "
                "AND person_type = 'CITIZEN' LIMIT 1"
            ),
            {"ids": [str(p) for p in recipients]},
        )
        if citizen is not None:
            raise CitizensWithoutApprovalError(
                f"campaign {campaign.reference} reaches citizens without approval"
            )
    await _insert_deliveries(session, campaign, recipients)
    await _audit_send(session, campaign, recipients, actor)
    return len(recipients)


async def _insert_deliveries(
    session: AsyncSession, campaign: NotificationCampaign, recipients: list[uuid.UUID]
) -> None:
    if recipients:
        await session.execute(
            insert(NotificationDelivery),
            [
                {
                    "tenant_id": campaign.tenant_id,
                    "campaign_id": campaign.id,
                    "person_id": person_id,
                    "channel": channel,
                }
                for person_id in recipients
                for channel in campaign.channels
            ],
        )


async def _audit_send(
    session: AsyncSession,
    campaign: NotificationCampaign,
    recipients: list[uuid.UUID],
    actor: Actor,
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="CAMPAIGN.SEND",
        entity_type="notification_campaign",
        entity_id=campaign.reference,
        details={
            "recipients": len(recipients),
            "per_channel": {c: len(recipients) for c in campaign.channels},
            "escalate_after_s": campaign.escalate_after_s,
        },
    )


def campaign_queued_event(campaign: NotificationCampaign) -> Event:
    return Event(
        type="CAMPAIGN_QUEUED",
        tenant_id=campaign.tenant_id,
        payload={
            "campaign_id": str(campaign.id),
            "reference": campaign.reference,
            "incident_id": str(campaign.incident_id) if campaign.incident_id else None,
        },
        source="notifications",
    )


@dataclass
class Dispatched:
    sent: Counter[str] = field(default_factory=Counter)  # per channel
    completed: list[NotificationCampaign] = field(default_factory=list)  # now SENT


async def dispatch(
    session: AsyncSession,
    now: datetime,
    campaign_id: uuid.UUID | None = None,
    configured_adapter: str = "simulated",
) -> Dispatched:
    """Send QUEUED deliveries of SENDING campaigns (all, or one) through the channel adapter.

    Rows are claimed FOR UPDATE SKIP LOCKED, so two dispatchers never send the same
    delivery; the caller commits once per batch."""
    result = Dispatched()
    query = (
        select(NotificationDelivery, NotificationCampaign, Person.preferred_lang)
        .join(NotificationCampaign, NotificationCampaign.id == NotificationDelivery.campaign_id)
        .join(Person, Person.id == NotificationDelivery.person_id)
        .where(
            NotificationDelivery.status == "QUEUED",
            # Only a campaign that is being sent: never one pending approval (D-31) or
            # one already finished, whatever deliveries were queued for it.
            NotificationCampaign.status == "SENDING",
        )
        .order_by(NotificationDelivery.id)
        .limit(DISPATCH_BATCH)
        .with_for_update(of=NotificationDelivery, skip_locked=True)
    )
    if campaign_id is not None:
        query = query.where(NotificationDelivery.campaign_id == campaign_id)
    for delivery, campaign, lang in (await session.execute(query)).all():
        adapter = adapter_for(delivery.channel, configured_adapter)
        message = campaign.translations.get(lang or "", campaign.message)
        sent = await adapter.send(
            Recipient(delivery.person_id, lang),
            delivery.channel,
            message,
            idempotency_key=str(delivery.id),
            now=now,
        )
        delivery.status = "SENT"
        delivery.provider_ref = sent.provider_ref
        delivery.updated_at = now
        result.sent[delivery.channel] += 1
    await session.flush()
    result.completed = await complete_campaigns(session, now, configured_adapter)
    return result


async def complete_campaigns(
    session: AsyncSession, now: datetime, configured_adapter: str = "simulated"
) -> list[NotificationCampaign]:
    """Mark SENDING campaigns with no QUEUED delivery left as SENT, each exactly once.

    A single conditional UPDATE decides, so two dispatchers that split a campaign
    cannot both complete it, and the campaign is completed by whichever pass runs
    after the last batch committed (every dispatch and every worker tick sweeps)."""
    rows = await session.scalars(
        update(NotificationCampaign)
        .where(
            NotificationCampaign.status == "SENDING",
            ~select(NotificationDelivery.id)
            .where(
                NotificationDelivery.campaign_id == NotificationCampaign.id,
                NotificationDelivery.status == "QUEUED",
            )
            .exists(),
        )
        .values(status="SENT", sent_at=now)
        .returning(NotificationCampaign)
    )
    completed = list(rows)
    for campaign in completed:
        await audit.write(
            session,
            actor_type=DISPATCHER.type,
            actor_id=DISPATCHER.id,
            action="CAMPAIGN.DISPATCHED",
            entity_type="notification_campaign",
            entity_id=campaign.reference,
            details={"adapter": configured_adapter},
        )
    return completed


@dataclass
class Receipts:
    changed: int  # deliveries moved on
    campaigns: list[NotificationCampaign]  # whose funnel changed, for one event each (MN-09)


async def refresh_receipts(
    session: AsyncSession, now: datetime, configured_adapter: str = "simulated"
) -> Receipts:
    """Move SENT/DELIVERED deliveries on as the adapter reports (telemetry, not
    audited, plan G-20). Returns how many changed, and the campaigns they belong to,
    so the screen's delivery funnel can follow live (one event per campaign)."""
    rows = (
        await session.execute(
            select(NotificationDelivery, NotificationCampaign.sent_at)
            .join(NotificationCampaign, NotificationCampaign.id == NotificationDelivery.campaign_id)
            .where(
                NotificationDelivery.status.in_(("SENT", "DELIVERED")),
                NotificationCampaign.sent_at.is_not(None),
            )
            .with_for_update(of=NotificationDelivery, skip_locked=True)
        )
    ).all()
    changed: dict[str, list[int]] = {}
    campaign_ids: set[uuid.UUID] = set()
    for delivery, sent_at in rows:
        if sent_at is None:
            continue
        adapter = adapter_for(delivery.channel, configured_adapter)
        reported: str = adapter.receipt(delivery.provider_ref or "", sent_at, now)
        if reported != delivery.status:
            changed.setdefault(reported, []).append(delivery.id)
            campaign_ids.add(delivery.campaign_id)
    for new_status, ids in changed.items():
        await session.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.id.in_(ids))
            .values(status=new_status, updated_at=now)
        )
    campaigns = (
        list(
            await session.scalars(
                select(NotificationCampaign).where(NotificationCampaign.id.in_(campaign_ids))
            )
        )
        if campaign_ids
        else []
    )
    return Receipts(sum(len(ids) for ids in changed.values()), campaigns)
