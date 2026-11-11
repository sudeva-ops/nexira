"""Site Twin API (TWN-01..06, D-43). Every role reads the twin; a staff name only within the
caller's people scope (plan-pilot-twn §7). The readiness tick is checked in the service through
app/core/approvals.py; GET /api/me/permissions?entity_type=site&entity_id=<site> says whether
to show it."""

import logging
import uuid
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.config import get_settings
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.tenancy.service import ROLES
from app.modules.twin import service
from app.modules.twin.schemas import MovementsOut, SiteSummaryOut, TwinOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sites", tags=["twin"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(e: service.TwinError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(session: AsyncSession, publisher: Publisher, events: list[Event]) -> None:
    await session.commit()
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


@router.get("/twin")
async def sites(_user: Reader, session: Db) -> list[SiteSummaryOut]:
    return await service.list_sites(session)


@router.get("/{site_id}/twin")
async def twin(site_id: uuid.UUID, user: Reader, session: Db) -> TwinOut:
    try:
        return await service.twin(session, user, site_id)
    except service.TwinError as e:
        raise _http(e) from None


@router.get("/{site_id}/twin/movements")
async def movements(site_id: uuid.UUID, _user: Reader, session: Db) -> MovementsOut:
    """TWN-14 (D-53): the last moves and today's figures, by kind and zones only."""
    home = ZoneInfo(get_settings().home_tz)
    since = datetime.now(home).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return await service.movements(session, site_id, since)
    except service.TwinError as e:
        raise _http(e) from None


@router.post("/readiness/{item_id}/done")
async def tick(item_id: uuid.UUID, user: User, session: Db, publisher: Pub) -> TwinOut:
    try:
        outcome = await service.tick(session, user, item_id)
        out = await service.twin(session, user, outcome.site_id)
    except service.TwinError as e:
        raise _http(e) from None
    await _done(session, publisher, outcome.events)
    return out
