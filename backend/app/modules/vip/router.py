"""VIP & Delegation Protection API (VIP-01..06, D-42). Every caller is signed in; who sees a
visit is checked in the service (VIP-06): everyone else gets 404, [] and {visible: false}.
GET /api/me/permissions?entity_type=vip_visit&entity_id=<visit> says which buttons to show.
Nothing is published to realtime (plan-pilot-vip G-3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, get_db
from app.modules.documents.service import today_utc
from app.modules.vip import service
from app.modules.vip.schemas import (
    AccessOut,
    CancelIn,
    ChangeIn,
    DecisionIn,
    VisitOut,
    VisitSummaryOut,
)

router = APIRouter(prefix="/api/vip", tags=["vip"])

User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]


def _http(e: service.VipError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(session: AsyncSession, user: CurrentUser, visit_id: uuid.UUID) -> VisitOut:
    out = await service.visit_out(session, user, visit_id, today_utc())
    await session.commit()
    return out


@router.get("/access")
async def access(user: User, session: Db) -> AccessOut:
    return AccessOut(visible=await service.visible(session, user))


@router.get("/visits")
async def visits(user: User, session: Db) -> list[VisitSummaryOut]:
    return await service.list_visits(session, user)


@router.get("/visits/{visit_id}")
async def visit(visit_id: uuid.UUID, user: User, session: Db) -> VisitOut:
    try:
        return await service.visit_out(session, user, visit_id, today_utc())
    except service.VipError as e:
        raise _http(e) from None


@router.post("/visits/{visit_id}/start")
async def start(visit_id: uuid.UUID, user: User, session: Db) -> VisitOut:
    try:
        found = await service.start(session, user, visit_id)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)


@router.post("/visits/{visit_id}/cancel")
async def cancel(visit_id: uuid.UUID, body: CancelIn, user: User, session: Db) -> VisitOut:
    try:
        found = await service.cancel(session, user, visit_id, body.reason)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)


@router.post("/segments/{segment_id}/progress")
async def progress(segment_id: uuid.UUID, user: User, session: Db) -> VisitOut:
    try:
        found = await service.progress(session, user, segment_id)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)


@router.post("/segments/{segment_id}/changes")
async def propose(segment_id: uuid.UUID, body: ChangeIn, user: User, session: Db) -> VisitOut:
    try:
        found = await service.propose(session, user, segment_id, body)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)


@router.post("/changes/{change_id}/approve")
async def approve(change_id: uuid.UUID, body: DecisionIn, user: User, session: Db) -> VisitOut:
    try:
        found = await service.decide(session, user, change_id, True, body.note)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)


@router.post("/changes/{change_id}/reject")
async def reject(change_id: uuid.UUID, body: DecisionIn, user: User, session: Db) -> VisitOut:
    try:
        found = await service.decide(session, user, change_id, False, body.note)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)


@router.post("/checklist/{item_id}/done")
async def tick(item_id: uuid.UUID, user: User, session: Db) -> VisitOut:
    try:
        found = await service.tick(session, user, item_id)
    except service.VipError as e:
        raise _http(e) from None
    return await _done(session, user, found.id)
