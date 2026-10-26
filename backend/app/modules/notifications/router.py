"""Notification campaigns and templates API (Prompts 10 and 20; MN-01..10, D-31).

- Reading campaigns and templates: any user with a role.
- Composing, the second-person approval and cancelling: notifications/compose.py,
  which checks roles through app/core/approvals.py. Events are published after commit.
- Editing templates: ADMIN or CONSULAR_OFFICER.
"""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.config import Settings, get_settings
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.intel.models import Incident
from app.modules.notifications import compose, templates
from app.modules.notifications.models import (
    MessageTemplate,
    NotificationCampaign,
    NotificationDelivery,
)
from app.modules.notifications.schemas import (
    CampaignOut,
    ComposeIn,
    PreviewOut,
    RejectIn,
    TemplateIn,
    TemplateOut,
    TemplatePatch,
)
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["notifications"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
TemplateEditor = Annotated[CurrentUser, Depends(require_roles("ADMIN", "CONSULAR_OFFICER"))]
Composer = Annotated[
    CurrentUser,
    Depends(require_roles("DUTY_OFFICER", "SECURITY_OFFICER", "CONSULAR_OFFICER", "ADMIN")),
]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]
Config = Annotated[Settings, Depends(get_settings)]


async def campaigns_out(
    session: AsyncSession, campaigns: list[NotificationCampaign]
) -> list[CampaignOut]:
    ids = [c.id for c in campaigns]
    counts: dict[uuid.UUID, dict[str, int]] = {}
    funnel: dict[uuid.UUID, dict[str, dict[str, int]]] = {}
    recipients: dict[uuid.UUID, int] = {}
    names: dict[str, str] = {}
    if ids:
        rows = await session.execute(
            select(
                NotificationDelivery.campaign_id,
                NotificationDelivery.channel,
                NotificationDelivery.status,
                func.count(),
            )
            .where(NotificationDelivery.campaign_id.in_(ids))
            .group_by(
                NotificationDelivery.campaign_id,
                NotificationDelivery.channel,
                NotificationDelivery.status,
            )
        )
        for campaign_id, channel, delivery_status, n in rows:
            by_status = counts.setdefault(campaign_id, {})
            by_status[delivery_status] = by_status.get(delivery_status, 0) + n
            funnel.setdefault(campaign_id, {}).setdefault(channel, {})[delivery_status] = n
        people = await session.execute(
            select(
                NotificationDelivery.campaign_id,
                func.count(func.distinct(NotificationDelivery.person_id)),
            )
            .where(NotificationDelivery.campaign_id.in_(ids))
            .group_by(NotificationDelivery.campaign_id)
        )
        recipients = {campaign_id: n for campaign_id, n in people}
        user_ids = {c.created_by for c in campaigns if c.created_by_type == "USER"} | {
            str(c.approved_by) for c in campaigns if c.approved_by
        }
        if user_ids:
            found = await session.execute(
                select(cast(AppUser.id, Text), AppUser.display_name).where(
                    cast(AppUser.id, Text).in_([u for u in user_ids if u])
                )
            )
            names = {user_id: name for user_id, name in found}
    out = []
    for c in campaigns:
        computed = (
            "recipients",
            "deliveries",
            "funnel",
            "simulated",
            "created_by_name",
            "approved_by_name",
        )
        fields: dict[str, Any] = {
            k: getattr(c, k) for k in CampaignOut.model_fields if k not in computed
        }
        out.append(
            CampaignOut(
                **fields,
                recipients=recipients.get(c.id, 0),
                deliveries=counts.get(c.id, {}),
                funnel=funnel.get(c.id, {}),
                simulated=True,
                created_by_name=names.get(c.created_by or "")
                if c.created_by_type == "USER"
                else None,
                approved_by_name=names.get(str(c.approved_by)) if c.approved_by else None,
            )
        )
    return out


@router.get("/campaigns")
async def list_campaigns(
    _user: Reader,
    session: Db,
    incident_id: uuid.UUID | None = None,
    kind: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    mission_id: uuid.UUID | None = None,
) -> list[CampaignOut]:
    """Newest first (MN-10): every campaign, from playbooks, agents and users."""
    query = select(NotificationCampaign).order_by(NotificationCampaign.created_at.desc()).limit(100)
    if incident_id is not None:
        query = query.where(NotificationCampaign.incident_id == incident_id)
    if kind is not None:
        query = query.where(NotificationCampaign.campaign_type == kind)
    if status_ is not None:
        query = query.where(NotificationCampaign.status == status_)
    if mission_id is not None:
        query = query.where(
            or_(
                NotificationCampaign.incident_id.in_(
                    select(Incident.id).where(Incident.mission_id == mission_id)
                ),
                NotificationCampaign.audience_filter["missions"].contains([str(mission_id)]),
            )
        )
    return await campaigns_out(session, list(await session.scalars(query)))


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: uuid.UUID, _user: Reader, session: Db) -> CampaignOut:
    campaign = await session.get(NotificationCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return (await campaigns_out(session, [campaign]))[0]


# --- composing (Prompt 20) ------------------------------------------------------------


def _content(body: ComposeIn) -> compose.Content:
    return compose.Content(
        kind=body.kind,
        message=body.message,
        channels=body.channels,
        missions=body.missions,
        person_types=body.person_types,
        exposed_to_incident=body.exposed_to_incident,
        incident_id=body.incident_id,
        translations=body.translations,
        template_id=body.template_id,
    )


def _http(error: compose.CampaignError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


async def _one(session: AsyncSession, campaign: NotificationCampaign) -> CampaignOut:
    return (await campaigns_out(session, [campaign]))[0]


@router.post("/campaigns", status_code=201)
async def create_campaign(body: ComposeIn, user: Reader, session: Db) -> CampaignOut:
    try:
        campaign = await compose.create_draft(session, user, _content(body))
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    return await _one(session, campaign)


@router.patch("/campaigns/{campaign_id}")
async def edit_campaign(
    campaign_id: uuid.UUID, body: ComposeIn, user: Reader, session: Db
) -> CampaignOut:
    try:
        campaign = await compose.update_draft(session, user, campaign_id, _content(body))
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    return await _one(session, campaign)


@router.post("/campaigns/{campaign_id}/preview")
async def preview_campaign(campaign_id: uuid.UUID, _user: Composer, session: Db) -> PreviewOut:
    campaign = await session.get(NotificationCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    shown = await compose.preview(session, campaign)
    return PreviewOut(
        recipients=shown.recipients,
        by_person_type=shown.by_person_type,
        by_mission=shown.by_mission,
    )


@router.post("/campaigns/{campaign_id}/test-send")
async def test_send_campaign(
    campaign_id: uuid.UUID, user: Reader, session: Db
) -> dict[str, dict[str, Any]]:
    try:
        shown = await compose.test_send(session, user, campaign_id)
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    return shown


@router.post("/campaigns/{campaign_id}/submit")
async def submit_campaign(
    campaign_id: uuid.UUID, user: Reader, session: Db, publisher: Pub, settings: Config
) -> CampaignOut:
    try:
        outcome = await compose.submit(session, user, campaign_id, settings.app_env)
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await _one(session, outcome.campaign)


@router.post("/campaigns/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: uuid.UUID, user: Reader, session: Db, publisher: Pub, settings: Config
) -> CampaignOut:
    try:
        outcome = await compose.approve(session, user, campaign_id, settings.app_env)
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await _one(session, outcome.campaign)


@router.post("/campaigns/{campaign_id}/reject")
async def reject_campaign(
    campaign_id: uuid.UUID, body: RejectIn, user: Reader, session: Db, publisher: Pub
) -> CampaignOut:
    try:
        outcome = await compose.reject(session, user, campaign_id, body.reason)
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await _one(session, outcome.campaign)


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(
    campaign_id: uuid.UUID, user: Reader, session: Db, publisher: Pub
) -> CampaignOut:
    try:
        outcome = await compose.cancel(session, user, campaign_id)
    except compose.CampaignError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await _one(session, outcome.campaign)


# --- templates (MN-03) -------------------------------------------------------------------


def _template_out(t: MessageTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id,
        code=t.code,
        kind=t.kind,
        mission_id=t.mission_id,
        name=t.name,
        texts=t.texts,
        reviewed=t.reviewed,
        is_active=t.is_active,
    )


@router.get("/templates")
async def list_templates(_user: Reader, session: Db) -> list[TemplateOut]:
    rows = await session.scalars(
        select(MessageTemplate).order_by(MessageTemplate.code, MessageTemplate.mission_id)
    )
    return [_template_out(t) for t in rows]


@router.post("/templates", status_code=201)
async def create_template(body: TemplateIn, user: TemplateEditor, session: Db) -> TemplateOut:
    try:
        template = await templates.create_template(
            session,
            user,
            code=body.code,
            kind=body.kind,
            mission_id=body.mission_id,
            name=body.name,
            texts=body.texts,
        )
    except templates.TemplateScopeError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from None
    except templates.TemplateError as e:
        raise HTTPException(422, str(e)) from None
    await session.commit()
    return _template_out(template)


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: uuid.UUID, body: TemplatePatch, user: TemplateEditor, session: Db
) -> TemplateOut:
    try:
        template = await templates.update_template(
            session,
            user,
            template_id,
            name=body.name,
            texts=body.texts,
            reviewed=body.reviewed,
            is_active=body.is_active,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found") from None
    except templates.TemplateScopeError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from None
    except templates.TemplateError as e:
        raise HTTPException(422, str(e)) from None
    await session.commit()
    return _template_out(template)
