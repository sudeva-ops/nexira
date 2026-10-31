"""Document Expiry API (Prompt 50; DX-01..05, DX-08, DX-09; D-37).

- The list: documents/service.py checks the role and its mission scope (§2); a Viewer
  gets 403 and reads the summary only.
- Renewal steps and reminders: documents/service.py, which checks roles through
  app/core/approvals.py. Events are published after commit.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.documents import service
from app.modules.documents.models import DOC_TYPES
from app.modules.documents.schemas import (
    DocumentOut,
    MissionReadinessOut,
    RemindersIn,
    RemindersOut,
    RenewalIn,
    SummaryOut,
)
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["documents"])

User = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(error: service.DocumentError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


def _pct(ready: int, people: int) -> float | None:
    return round(100 * ready / people, 1) if people else None


def _out(row: service.Row, act: service.Scope | None) -> DocumentOut:
    d = row.document
    return DocumentOut(
        id=d.id,
        person_id=d.person_id,
        holder_name=row.holder_name,
        holder_type=row.holder_type,
        mission_id=row.mission_id,
        mission_code=row.mission_code,
        doc_type=d.doc_type,
        issuing_country=d.issuing_country,
        valid_until=d.valid_until,
        days_left=row.days_left,
        urgency=row.urgency,
        holder_ready=row.holder_ready,
        could_block_evacuation=row.could_block,
        renewal_status=d.renewal_status,
        renewal_requested_by=d.renewal_requested_by,
        renewal_requested_at=d.renewal_requested_at,
        renewal_started_by=d.renewal_started_by,
        renewal_started_at=d.renewal_started_at,
        renewed_by=d.renewed_by,
        renewed_at=d.renewed_at,
        can_act=act is not None and act.covers(row.mission_id),
    )


@router.get("/documents")
async def list_documents(
    user: User,
    session: Db,
    mission_id: uuid.UUID | None = None,
    doc_type: str | None = None,
    urgency: str | None = None,
    limit: Annotated[int, Query(ge=1, le=service.LIST_MAX)] = 200,
) -> list[DocumentOut]:
    """DX-01..03: most urgent first, within the caller's scope (DX-09)."""
    if doc_type is not None and doc_type not in DOC_TYPES:
        raise HTTPException(422, f"doc_type is one of {', '.join(DOC_TYPES)}")
    if urgency is not None and urgency not in service.URGENCIES:
        raise HTTPException(422, f"urgency is one of {', '.join(service.URGENCIES)}")
    try:
        listing = await service.list_documents(
            session, user, service.Filters(mission_id, doc_type, urgency, limit)
        )
    except service.DocumentError as e:
        raise _http(e) from None
    return [_out(r, listing.act) for r in listing.rows]


@router.get("/documents/summary")
async def documents_summary(user: User, session: Db) -> SummaryOut:
    """DX-08: the KPIs, for every role (a Head of Mission's cover their mission)."""
    s = await service.summary(session, user)
    return SummaryOut(
        tracked=s.tracked,
        expiring_30=s.expiring_30,
        expiring_90=s.expiring_90,
        in_renewal_90=s.in_renewal_90,
        could_block=s.could_block,
        people=s.people,
        ready=s.ready,
        ready_pct=_pct(s.ready, s.people),
        missions=[
            MissionReadinessOut(
                mission_id=m.mission_id,
                code=m.code,
                people=m.people,
                ready=m.ready,
                ready_pct=_pct(m.ready, m.people),
            )
            for m in s.missions
        ],
    )


async def _row(session: AsyncSession, user: CurrentUser, outcome: service.Outcome) -> DocumentOut:
    """The document as the list shows it, to the caller who just changed it."""
    rows = await service.register(session, service.today_utc(), outcome.mission_id)
    [row] = [r for r in rows if r.document.id == outcome.document.id]
    return _out(row, await service.act_scope(session, user))


@router.post("/documents/{document_id}/renewal")
async def renew(
    document_id: uuid.UUID, body: RenewalIn, user: User, session: Db, publisher: Pub
) -> DocumentOut:
    """DX-04: one step on: REQUESTED, IN_PROGRESS, or RENEWED with the new date."""
    try:
        outcome = await service.renew(session, user, document_id, body.step, body.valid_until)
    except service.DocumentError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    return await _row(session, user, outcome)


@router.post("/documents/reminders", status_code=201)
async def reminders(body: RemindersIn, user: User, session: Db, publisher: Pub) -> RemindersOut:
    """DX-05: one staff campaign to the holders (simulated channels)."""
    try:
        sent = await service.send_reminders(session, user, body.document_ids)
    except service.DocumentError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, sent.events)
    return RemindersOut(
        campaign_id=sent.campaign.id,
        reference=sent.campaign.reference,
        recipients=sent.recipients,
        documents=sent.documents,
    )
