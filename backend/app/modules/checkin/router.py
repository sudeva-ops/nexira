"""Safety check-in API (CHK-02, CHK-03, D-28).

- Reading: any user with a role.
- Recording an answer (POST .../respond): staff who handle people in a crisis,
  unscoped or for the incident's mission (D-05). This is also the phone preview
  panel's path; the answer is audited with the recording user as the actor.
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles, user_has_role
from app.core.events import Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.checkin import service
from app.modules.checkin.schemas import (
    CheckinPersonOut,
    EscalatedOut,
    RespondIn,
    ResponseOut,
    SummaryOut,
    TallyOut,
)
from app.modules.notifications.models import NotificationCampaign
from app.modules.tenancy.service import ROLES, Actor

RESPOND_ROLES = (
    "DUTY_OFFICER",
    "SECURITY_OFFICER",
    "CONSULAR_OFFICER",
    "HEAD_OF_MISSION",
    "HQ_CRISIS_DIRECTOR",
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkin", tags=["checkin"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


async def _checkin(session: AsyncSession, campaign_id: uuid.UUID) -> NotificationCampaign:
    campaign = await session.get(NotificationCampaign, campaign_id)
    if campaign is None or campaign.campaign_type != "CHECKIN":
        raise HTTPException(404, "Check-in not found")
    return campaign


def _tally(t: service.Tally) -> TallyOut:
    return TallyOut(
        recipients=t.recipients,
        safe=t.safe,
        need_help=t.need_help,
        pending=t.pending,
        accounted_pct=t.accounted_pct,
    )


@router.get("/{campaign_id}/summary")
async def summary(campaign_id: uuid.UUID, _user: Reader, session: Db) -> SummaryOut:
    """CHK-03: personnel and citizens separately."""
    campaign = await _checkin(session, campaign_id)
    tallies = await service.tally(session, campaign_id)
    return SummaryOut(
        campaign_id=campaign.id,
        reference=campaign.reference,
        incident_id=campaign.incident_id,
        status=campaign.status,
        sent_at=campaign.sent_at,
        escalate_after_s=campaign.escalate_after_s,
        personnel=_tally(tallies["personnel"]),
        citizens=_tally(tallies["citizens"]),
    )


_PEOPLE = text(
    """
    WITH recipients AS (
      SELECT DISTINCT person_id FROM notification_delivery WHERE campaign_id = :campaign_id
    ), escalated AS (
      SELECT DISTINCT details ->> 'person_id' AS person_id FROM audit_log
       WHERE action = 'CHECKIN.ESCALATE' AND entity_id = :reference
    )
    SELECT p.id AS person_id, p.full_name, p.person_type, p.role_title,
           m.code AS mission_code, coalesce(l.status, 'PENDING') AS status,
           l.channel, l.note, l.responded_at,
           (e.person_id IS NOT NULL) AS escalated
      FROM recipients r
      JOIN person p ON p.id = r.person_id
      LEFT JOIN mission m ON m.id = p.mission_id
      LEFT JOIN v_checkin_latest l ON l.campaign_id = :campaign_id AND l.person_id = p.id
      LEFT JOIN escalated e ON e.person_id = p.id::text
     WHERE (CAST(:group AS text) IS NULL
            OR (:group = 'citizens') = (p.person_type = 'CITIZEN'))
       AND (CAST(:status AS text) IS NULL OR coalesce(l.status, 'PENDING') = :status)
     ORDER BY CASE coalesce(l.status, 'PENDING')
                WHEN 'NEED_HELP' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END,
              (p.person_type = 'CITIZEN'), p.full_name
    """
)


@router.get("/{campaign_id}/people")
async def people(
    campaign_id: uuid.UUID,
    _user: Reader,
    session: Db,
    group: Literal["personnel", "citizens"] | None = None,
    status: Annotated[Literal["SAFE", "NEED_HELP", "PENDING"] | None, Query()] = None,
) -> list[CheckinPersonOut]:
    """Recipients with their latest answer: need help first, then pending, then safe.
    Free-text notes are shown only to staff who may record answers."""
    campaign = await _checkin(session, campaign_id)
    show_notes = await user_has_role(session, _user, RESPOND_ROLES)
    rows = await session.execute(
        _PEOPLE,
        {
            "campaign_id": campaign.id,
            "reference": campaign.reference,
            "group": group,
            "status": status,
        },
    )
    return [
        CheckinPersonOut(**{**r._asdict(), "note": r.note if show_notes else None}) for r in rows
    ]


_RESPONSES = text(
    """
    SELECT l.person_id, p.full_name, p.person_type, p.role_title, m.code AS mission_code,
           l.status, l.channel, l.note, l.responded_at, false AS escalated
      FROM v_checkin_latest l
      JOIN person p ON p.id = l.person_id
      LEFT JOIN mission m ON m.id = p.mission_id
     WHERE l.campaign_id = :campaign_id
     ORDER BY l.responded_at DESC, p.full_name
     LIMIT :limit
    """
)


@router.get("/{campaign_id}/responses")
async def responses(
    campaign_id: uuid.UUID,
    _user: Reader,
    session: Db,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[CheckinPersonOut]:
    """The live list: each person's latest answer, newest first."""
    campaign = await _checkin(session, campaign_id)
    show_notes = await user_has_role(session, _user, RESPOND_ROLES)
    rows = await session.execute(_RESPONSES, {"campaign_id": campaign.id, "limit": limit})
    return [
        CheckinPersonOut(**{**r._asdict(), "note": r.note if show_notes else None}) for r in rows
    ]


async def _may_respond(
    session: AsyncSession, user: CurrentUser, campaign: NotificationCampaign
) -> None:
    mission_id = await session.scalar(
        text("SELECT mission_id FROM incident WHERE id = :id"), {"id": campaign.incident_id}
    )
    if not await user_has_role(session, user, RESPOND_ROLES, mission_id):
        raise HTTPException(403, "Forbidden")


@router.post("/{campaign_id}/escalate")
async def escalate(campaign_id: uuid.UUID, user: User, session: Db, publisher: Pub) -> EscalatedOut:
    """Escalate non-responders now (once per person, once for citizens, D-07)."""
    campaign = await _checkin(session, campaign_id)
    await _may_respond(session, user, campaign)
    try:
        result = await service.escalate_now(
            session, campaign.id, Actor(type="USER", id=str(user.id))
        )
    except service.CheckinError as e:
        raise HTTPException(409, str(e)) from None
    await session.commit()
    try:
        await publisher.publish(service.updated_event(campaign, "CHECKIN_ESCALATED"))
    except Exception:
        log.exception("publishing CHECKIN_ESCALATED failed after commit")
    return EscalatedOut(personnel=result.personnel, citizens=result.citizens)


@router.post("/{campaign_id}/respond", status_code=201)
async def respond(
    campaign_id: uuid.UUID, body: RespondIn, user: User, session: Db, publisher: Pub
) -> ResponseOut:
    """CHK-02: record an answer for a recipient (D-28: also the phone preview panel)."""
    campaign = await _checkin(session, campaign_id)
    await _may_respond(session, user, campaign)
    try:
        response = await service.record_response(
            session,
            campaign_id=campaign.id,
            person_id=body.person_id,
            status=body.status,
            channel=body.channel,
            note=body.note,
            actor=Actor(type="USER", id=str(user.id)),
        )
    except service.CheckinError as e:
        raise HTTPException(409, str(e)) from None
    out = ResponseOut.model_validate(response, from_attributes=True)
    await session.commit()
    try:
        await publisher.publish(service.updated_event(campaign))
    except Exception:
        log.exception("publishing CHECKIN_UPDATED failed after commit")
    return out
