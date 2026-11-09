"""After-Action Review API (AAR-01..08; D-47). Every role reads the reviews: roles, references
and counts, no names. Starting, deciding, adding, marking done and finalising are checked in
app/modules/aar/reviews.py through app/core/approvals.py; each review says what the caller may
do (can_act, can_finalise). The export is audited (AAR-07)."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.aar import reviews
from app.modules.aar.models import AfterActionReview
from app.modules.aar.schemas import (
    AcceptIn,
    ItemIn,
    RejectIn,
    ReviewOut,
    ReviewsOut,
    StartIn,
)
from app.modules.documents.service import today_utc
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/aar", tags=["aar"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(e: reviews.AarError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(
    session: AsyncSession, publisher: Publisher, user: CurrentUser, review: AfterActionReview
) -> ReviewOut:
    review_id = review.id
    event = reviews.updated_event(review)
    await session.commit()
    try:
        await publisher.publish(event)
    except Exception:
        log.exception("publishing AAR_UPDATED failed after commit")
    return await reviews.detail(session, user, review_id, datetime.now(UTC))


@router.get("")
async def list_reviews(user: Reader, session: Db) -> ReviewsOut:
    return await reviews.list_reviews(session, user)


@router.post("", status_code=201)
async def start(body: StartIn, user: User, session: Db, publisher: Pub) -> ReviewOut:
    try:
        review = await reviews.start(session, user, body.incident_id, datetime.now(UTC))
    except reviews.AarError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, review)


@router.get("/{review_id}")
async def review(review_id: uuid.UUID, user: Reader, session: Db) -> ReviewOut:
    try:
        return await reviews.detail(session, user, review_id, datetime.now(UTC))
    except reviews.AarError as e:
        raise _http(e) from None


@router.post("/{review_id}/items", status_code=201)
async def add(
    review_id: uuid.UUID, body: ItemIn, user: User, session: Db, publisher: Pub
) -> ReviewOut:
    try:
        found = await reviews.add(session, user, review_id, body, today_utc())
    except reviews.AarError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, found)


@router.post("/items/{item_id}/accept")
async def accept(
    item_id: uuid.UUID, body: AcceptIn, user: User, session: Db, publisher: Pub
) -> ReviewOut:
    try:
        found = await reviews.accept(session, user, item_id, body, today_utc())
    except reviews.AarError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, found)


@router.post("/items/{item_id}/reject")
async def reject(
    item_id: uuid.UUID, body: RejectIn, user: User, session: Db, publisher: Pub
) -> ReviewOut:
    try:
        found = await reviews.reject(session, user, item_id, body.reason)
    except reviews.AarError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, found)


@router.post("/items/{item_id}/done")
async def done(item_id: uuid.UUID, user: User, session: Db, publisher: Pub) -> ReviewOut:
    try:
        found = await reviews.done(session, user, item_id)
    except reviews.AarError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, found)


@router.post("/{review_id}/finalise")
async def finalise(review_id: uuid.UUID, user: User, session: Db, publisher: Pub) -> ReviewOut:
    try:
        found = await reviews.finalise(session, user, review_id, datetime.now(UTC))
    except reviews.AarError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, found)


@router.post("/{review_id}/export")
async def export(review_id: uuid.UUID, user: Reader, session: Db) -> ReviewOut:
    try:
        out = await reviews.export(session, user, review_id, datetime.now(UTC))
    except reviews.AarError as e:
        raise _http(e) from None
    await session.commit()
    return out
