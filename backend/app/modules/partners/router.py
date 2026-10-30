"""Assistance Partners API (Prompt 45; AS-01..08, D-36).

- Reading partners, coverage, suggestions and requests: any user with a role (plan G-10).
- Requesting, cancelling and completing: partners/service.py, which checks roles through
  app/core/approvals.py. The partner's own moves come only from the worker (adapter).
  Events are published after commit.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.intel.models import Incident
from app.modules.partners import service
from app.modules.partners.models import STATUSES, Partner, PartnerRequest
from app.modules.partners.schemas import (
    CoverageOut,
    PartnerOut,
    RequestIn,
    RequestOut,
    SuggestionOut,
)
from app.modules.people.models import Mission, Person
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["partners"])

LIST_MAX = 200
Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(error: service.PartnerError) -> HTTPException:
    return HTTPException(error.status_code, str(error))


async def _publish(publisher: Publisher, events: list[Event]) -> None:
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


def _name(
    people: dict[uuid.UUID, Person], hidden: set[uuid.UUID], pid: uuid.UUID | None
) -> str | None:
    if pid is None:
        return None
    return "Restricted traveller" if pid in hidden else people[pid].full_name


def _role(
    people: dict[uuid.UUID, Person], hidden: set[uuid.UUID], pid: uuid.UUID | None
) -> str | None:
    if pid is None or pid in hidden:
        return None
    return people[pid].role_title


async def requests_out(session: AsyncSession, rows: list[PartnerRequest]) -> list[RequestOut]:
    if not rows:
        return []
    partners = {
        p.id: p.name
        for p in await session.scalars(
            select(Partner).where(Partner.id.in_({r.partner_id for r in rows}))
        )
    }
    missions = {
        m.id: m.code
        for m in await session.scalars(
            select(Mission).where(Mission.id.in_({r.mission_id for r in rows}))
        )
    }
    incidents = {
        i.id: i.reference
        for i in await session.scalars(
            select(Incident).where(Incident.id.in_({r.incident_id for r in rows if r.incident_id}))
        )
    }
    people = {
        p.id: p
        for p in await session.scalars(
            select(Person).where(Person.id.in_({r.person_id for r in rows if r.person_id}))
        )
    }
    # AS-08: a person who has since become a restricted traveller is not shown (review of
    # Prompt 45, L2).
    hidden = await service.restricted_people(session, set(people))
    return [
        RequestOut(
            id=r.id,
            reference=r.reference,
            partner_id=r.partner_id,
            partner_name=partners[r.partner_id],
            service=r.service,
            mission_id=r.mission_id,
            mission_code=missions[r.mission_id],
            incident_id=r.incident_id,
            incident_reference=incidents.get(r.incident_id) if r.incident_id else None,
            person_id=None if r.person_id in hidden else r.person_id,
            person_name=_name(people, hidden, r.person_id),
            person_role=_role(people, hidden, r.person_id),
            place_label=r.place_label,
            note=r.note,
            status=r.status,
            eta=r.eta,
            created_by_type=r.created_by_type,
            requested_at=r.requested_at,
            accepted_at=r.accepted_at,
            completed_at=r.completed_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/partners")
async def list_partners(_user: Reader, session: Db) -> list[PartnerOut]:
    """AS-01: the directory (fictional partners, simulated)."""
    return [PartnerOut.model_validate(p) for p in await service.list_partners(session)]


@router.get("/partners/coverage")
async def coverage(_user: Reader, session: Db) -> list[CoverageOut]:
    """AS-07: per mission, the services no active partner covers."""
    return [CoverageOut(**c.__dict__) for c in await service.coverage(session)]


@router.get("/partners/suggest")
async def suggest(
    _user: Reader,
    session: Db,
    person_id: uuid.UUID,
    service_: Annotated[str, Query(alias="service")] = service.DEFAULT_SOS_SERVICE,
) -> SuggestionOut:
    """AS-06: who can help this person, shortest SLA first. Suggests only; a person requests."""
    try:
        found = await service.suggest(session, person_id, service_)
    except service.PartnerError as e:
        raise _http(e) from None
    return SuggestionOut(
        person_id=found.person_id,
        service=found.service,
        mission_id=found.mission_id,
        mission_code=found.mission_code,
        country_code=found.country_code,
        partners=[PartnerOut.model_validate(p) for p in found.partners],
    )


@router.get("/partner-requests")
async def list_requests(
    _user: Reader,
    session: Db,
    status_: Annotated[str | None, Query(alias="status")] = None,
    incident_id: uuid.UUID | None = None,
    person_id: uuid.UUID | None = None,
) -> list[RequestOut]:
    if status_ is not None and status_ not in STATUSES:
        raise HTTPException(422, f"status is one of {', '.join(STATUSES)}")
    query = select(PartnerRequest).order_by(PartnerRequest.requested_at.desc()).limit(LIST_MAX)
    if status_ is not None:
        query = query.where(PartnerRequest.status == status_)
    if incident_id is not None:
        query = query.where(PartnerRequest.incident_id == incident_id)
    if person_id is not None:
        query = query.where(PartnerRequest.person_id == person_id)
    return await requests_out(session, list(await session.scalars(query)))


@router.post("/partner-requests", status_code=201)
async def create_request(body: RequestIn, user: Reader, session: Db, publisher: Pub) -> RequestOut:
    try:
        outcome = await service.create_request(
            session, user, service.RequestIn(**body.model_dump())
        )
    except service.PartnerError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    [out] = await requests_out(session, [outcome.request])
    return out


@router.post("/partner-requests/{request_id}/cancel")
async def cancel_request(
    request_id: uuid.UUID, user: Reader, session: Db, publisher: Pub
) -> RequestOut:
    try:
        outcome = await service.cancel(session, user, request_id)
    except service.PartnerError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    [out] = await requests_out(session, [outcome.request])
    return out


@router.post("/partner-requests/{request_id}/complete")
async def complete_request(
    request_id: uuid.UUID, user: Reader, session: Db, publisher: Pub
) -> RequestOut:
    try:
        outcome = await service.complete(session, user, request_id)
    except service.PartnerError as e:
        raise _http(e) from None
    await session.commit()
    await _publish(publisher, outcome.events)
    [out] = await requests_out(session, [outcome.request])
    return out
