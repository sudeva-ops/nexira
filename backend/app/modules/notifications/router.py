"""Notification campaigns read API. Any user with a role."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.notifications.schemas import CampaignOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api", tags=["notifications"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


async def campaigns_out(
    session: AsyncSession, campaigns: list[NotificationCampaign]
) -> list[CampaignOut]:
    ids = [c.id for c in campaigns]
    counts: dict[uuid.UUID, dict[str, int]] = {}
    recipients: dict[uuid.UUID, int] = {}
    if ids:
        rows = await session.execute(
            select(NotificationDelivery.campaign_id, NotificationDelivery.status, func.count())
            .where(NotificationDelivery.campaign_id.in_(ids))
            .group_by(NotificationDelivery.campaign_id, NotificationDelivery.status)
        )
        for campaign_id, delivery_status, n in rows:
            counts.setdefault(campaign_id, {})[delivery_status] = n
        people = await session.execute(
            select(
                NotificationDelivery.campaign_id,
                func.count(func.distinct(NotificationDelivery.person_id)),
            )
            .where(NotificationDelivery.campaign_id.in_(ids))
            .group_by(NotificationDelivery.campaign_id)
        )
        recipients = {campaign_id: n for campaign_id, n in people}
    out = []
    for c in campaigns:
        fields: dict[str, Any] = {
            k: getattr(c, k)
            for k in CampaignOut.model_fields
            if k not in ("recipients", "deliveries", "simulated")
        }
        out.append(
            CampaignOut(
                **fields,
                recipients=recipients.get(c.id, 0),
                deliveries=counts.get(c.id, {}),
                simulated=True,
            )
        )
    return out


@router.get("/campaigns")
async def list_campaigns(
    _user: Reader, session: Db, incident_id: uuid.UUID | None = None
) -> list[CampaignOut]:
    """Newest first."""
    query = select(NotificationCampaign).order_by(NotificationCampaign.created_at.desc()).limit(100)
    if incident_id is not None:
        query = query.where(NotificationCampaign.incident_id == incident_id)
    return await campaigns_out(session, list(await session.scalars(query)))


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: uuid.UUID, _user: Reader, session: Db) -> CampaignOut:
    campaign = await session.get(NotificationCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return (await campaigns_out(session, [campaign]))[0]
