"""Evacuation Management API (EV-02..09, D-40). Every role reads plans, evacuations and
counts; names only within the caller's scope (plan-pilot-ev G-8). Every action's role is
checked in the service through app/core/approvals.py; GET /api/me/permissions
?entity_type=evacuation&entity_id=<mission> says which buttons to show."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.documents.service import today_utc
from app.modules.evacuations import service
from app.modules.evacuations.schemas import (
    AdvanceIn,
    EvacuationDetailOut,
    EvacuationOut,
    PlanOut,
    RequestIn,
    StandDownIn,
)
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evacuations", tags=["evacuations"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(e: service.EvacuationError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(session: AsyncSession, publisher: Publisher, events: list[Event]) -> None:
    await session.commit()
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


@router.get("/plans")
async def plans(_user: Reader, session: Db) -> list[PlanOut]:
    return await service.list_plans(session)


@router.get("")
async def evacuations(
    _user: Reader, session: Db, mission_id: uuid.UUID | None = None
) -> list[EvacuationOut]:
    return await service.list_evacuations(session, mission_id, today_utc())


@router.get("/{evacuation_id}")
async def evacuation(evacuation_id: uuid.UUID, user: Reader, session: Db) -> EvacuationDetailOut:
    try:
        return await service.detail(session, user, evacuation_id, today_utc())
    except service.EvacuationError as e:
        raise _http(e) from None


@router.post("", status_code=status.HTTP_201_CREATED)
async def request(body: RequestIn, user: User, session: Db, publisher: Pub) -> EvacuationOut:
    try:
        outcome = await service.request(session, user, body.mission_id)
    except service.EvacuationError as e:
        raise _http(e) from None
    out = await service.describe(session, outcome.evacuation, today_utc())
    await _done(session, publisher, outcome.events)
    return out


@router.post("/{evacuation_id}/confirm")
async def confirm(
    evacuation_id: uuid.UUID, user: User, session: Db, publisher: Pub
) -> EvacuationOut:
    try:
        outcome = await service.confirm(session, user, evacuation_id)
    except service.EvacuationError as e:
        raise _http(e) from None
    out = await service.describe(session, outcome.evacuation, today_utc())
    await _done(session, publisher, outcome.events)
    return out


@router.post("/{evacuation_id}/manifest/{entry_id}/check-in")
async def check_in(
    evacuation_id: uuid.UUID, entry_id: uuid.UUID, user: User, session: Db, publisher: Pub
) -> EvacuationOut:
    try:
        outcome = await service.check_in(session, user, evacuation_id, entry_id)
    except service.EvacuationError as e:
        raise _http(e) from None
    out = await service.describe(session, outcome.evacuation, today_utc())
    await _done(session, publisher, outcome.events)
    return out


@router.post("/{evacuation_id}/advance")
async def advance(
    evacuation_id: uuid.UUID, body: AdvanceIn, user: User, session: Db, publisher: Pub
) -> EvacuationOut:
    try:
        outcome = await service.advance(session, user, evacuation_id, body.step)
    except service.EvacuationError as e:
        raise _http(e) from None
    out = await service.describe(session, outcome.evacuation, today_utc())
    await _done(session, publisher, outcome.events)
    return out


@router.post("/{evacuation_id}/stand-down")
async def stand_down(
    evacuation_id: uuid.UUID, body: StandDownIn, user: User, session: Db, publisher: Pub
) -> EvacuationOut:
    try:
        outcome = await service.stand_down(session, user, evacuation_id, body.reason)
    except service.EvacuationError as e:
        raise _http(e) from None
    out = await service.describe(session, outcome.evacuation, today_utc())
    await _done(session, publisher, outcome.events)
    return out
