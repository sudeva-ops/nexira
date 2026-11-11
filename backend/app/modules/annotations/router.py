"""Map annotations API (ANN-01..ANN-06; D-52). Every role reads them; adding, editing and
withdrawing are checked in app/modules/annotations/service.py through app/core/approvals.py.
Each annotation says whether the caller may change it (can_edit)."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.annotations import service
from app.modules.annotations.models import MapAnnotation
from app.modules.annotations.schemas import (
    AnnotationEdit,
    AnnotationIn,
    AnnotationOut,
    AnnotationsOut,
    WithdrawIn,
)
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/annotations", tags=["annotations"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(e: service.AnnotationError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(
    session: AsyncSession, publisher: Publisher, user: CurrentUser, annotation: MapAnnotation
) -> AnnotationOut:
    annotation_id = annotation.id
    event = service.updated_event(annotation)
    await session.commit()
    try:
        await publisher.publish(event)
    except Exception:
        log.exception("publishing ANNOTATION_UPDATED failed after commit")
    return await service.one(session, user, annotation_id)


@router.get("")
async def list_annotations(
    user: Reader, session: Db, incident_id: uuid.UUID | None = None
) -> AnnotationsOut:
    return await service.listed(session, user, datetime.now(UTC), incident_id)


@router.post("", status_code=201)
async def add(body: AnnotationIn, user: Reader, session: Db, publisher: Pub) -> AnnotationOut:
    try:
        annotation = await service.add(session, user, body, datetime.now(UTC))
    except service.AnnotationError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, annotation)


@router.patch("/{annotation_id}")
async def edit(
    annotation_id: uuid.UUID, body: AnnotationEdit, user: Reader, session: Db, publisher: Pub
) -> AnnotationOut:
    try:
        annotation = await service.edit(session, user, annotation_id, body, datetime.now(UTC))
    except service.AnnotationError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, annotation)


@router.post("/{annotation_id}/withdraw")
async def withdraw(
    annotation_id: uuid.UUID, body: WithdrawIn, user: Reader, session: Db, publisher: Pub
) -> AnnotationOut:
    try:
        annotation = await service.withdraw(session, user, annotation_id, body.reason)
    except service.AnnotationError as e:
        raise _http(e) from None
    return await _done(session, publisher, user, annotation)
