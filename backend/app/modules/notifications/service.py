"""Notification campaigns. Prompt 9: playbook steps create campaigns; delivery
through the simulated channel adapters arrives in Prompt 10."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.notifications.models import NotificationCampaign
from app.modules.tenancy.service import Actor

CAMPAIGN_TYPES = ("ALERT", "CHECKIN", "ADVISORY", "TEST")
CHANNELS = ("APP", "SMS", "WHATSAPP", "VOICE", "EMAIL")
DEFAULT_ESCALATE_AFTER_S = 600  # D-07


class AudienceError(ValueError):
    pass


async def resolve_audience(
    session: AsyncSession, incident_id: uuid.UUID, audience: dict[str, Any]
) -> list[uuid.UUID]:
    """Active people an audience spec selects, ordered by id.

    Specs used by PB-07 (plan G-14):
    - {"exposed": true, "person_types": [...]}: exposed to the incident (optional types)
    - {"mission": "incident", "role_titles": [...]}: people of the incident's mission
      with one of these role titles
    """
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


async def create_campaign(
    session: AsyncSession,
    *,
    incident_id: uuid.UUID,
    campaign: CampaignIn,
    created_by_type: str,
    created_by: str,
    actor: Actor,
) -> tuple[NotificationCampaign, int]:
    """Create a DRAFT campaign with an NTF reference (D-18); return it and the
    number of recipients its audience resolves to now."""
    if campaign.campaign_type not in CAMPAIGN_TYPES:
        raise ValueError(f"unknown campaign type {campaign.campaign_type}")
    if not campaign.channels or not set(campaign.channels) <= set(CHANNELS):
        raise ValueError(f"unknown channels {campaign.channels}")
    recipients = await resolve_audience(session, incident_id, campaign.audience)
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
        escalate_after_s=campaign.escalate_after_s,
    )
    session.add(row)
    await session.flush()
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
    return row, len(recipients)
