"""Fleet & Assets API (FLT-01..07, D-41). Every role reads assets, states, capacity and
maintenance; a driver's name only within the caller's people scope (plan-pilot-flt §7).
Status and maintenance are checked in the service through app/core/approvals.py; GET
/api/me/permissions?entity_type=fleet&entity_id=<mission> says which buttons to show."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.documents.service import today_utc
from app.modules.fleet import service
from app.modules.fleet.schemas import (
    AssetOut,
    MaintenanceOut,
    MissionFleetOut,
    StatusIn,
    SummaryOut,
)
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fleet", tags=["fleet"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(e: service.FleetError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(session: AsyncSession, publisher: Publisher, events: list[Event]) -> None:
    await session.commit()
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


@router.get("/assets")
async def assets(user: Reader, session: Db, mission_id: uuid.UUID | None = None) -> list[AssetOut]:
    return await service.list_assets(session, user, mission_id)


@router.get("/summary")
async def summary(_user: Reader, session: Db) -> SummaryOut:
    return await service.summary(session, today_utc())


@router.get("/missions/{mission_id}")
async def mission(mission_id: uuid.UUID, user: Reader, session: Db) -> MissionFleetOut:
    try:
        return await service.mission_fleet(session, user, mission_id)
    except service.FleetError as e:
        raise _http(e) from None


@router.get("/maintenance")
async def maintenance(
    _user: Reader, session: Db, mission_id: uuid.UUID | None = None
) -> list[MaintenanceOut]:
    return await service.maintenance(session, today_utc(), mission_id)


@router.patch("/assets/{asset_id}/status")
async def set_status(
    asset_id: uuid.UUID, body: StatusIn, user: User, session: Db, publisher: Pub
) -> AssetOut:
    try:
        outcome = await service.set_status(session, user, asset_id, body.status, body.reason)
    except service.FleetError as e:
        raise _http(e) from None
    out = (await service.list_assets(session, user, asset_id=asset_id))[0]
    await _done(session, publisher, outcome.events)
    return out


@router.post("/maintenance/{item_id}/done")
async def complete(
    item_id: uuid.UUID, user: User, session: Db, publisher: Pub
) -> list[MaintenanceOut]:
    try:
        outcome = await service.complete(session, user, item_id)
    except service.FleetError as e:
        raise _http(e) from None
    out = [m for m in await service.maintenance(session, today_utc()) if m.id == item_id]
    await _done(session, publisher, outcome.events)
    return out
