"""Supply Chain & Third-Party Risk API (SUP-01..06, D-44). Every role reads the register,
routes, statuses, banners and mitigations; the names of who acted only within the caller's
people scope (plan-pilot-sup §6). Mitigations are checked in the service through
app/core/approvals.py; GET /api/me/permissions?entity_type=supplier&entity_id=<supplier> says
which buttons to show. Nothing here contacts a supplier."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.documents.service import today_utc
from app.modules.supply import service
from app.modules.supply.schemas import (
    MitigationIn,
    RouteOut,
    SummaryOut,
    SupplierDetailOut,
    SupplierOut,
)
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/supply", tags=["supply"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


def _http(e: service.SupplyError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


async def _done(session: AsyncSession, publisher: Publisher, events: list[Event]) -> None:
    await session.commit()
    for event in events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)


@router.get("/summary")
async def summary(user: Reader, session: Db) -> SummaryOut:
    return await service.summary(session, user, today_utc())


@router.get("/suppliers")
async def suppliers(
    user: Reader, session: Db, mission_id: uuid.UUID | None = None
) -> list[SupplierOut]:
    return await service.list_suppliers(session, user, today_utc(), mission_id)


@router.get("/suppliers/{supplier_id}")
async def supplier(supplier_id: uuid.UUID, user: Reader, session: Db) -> SupplierDetailOut:
    try:
        return await service.supplier_detail(session, user, today_utc(), supplier_id)
    except service.SupplyError as e:
        raise _http(e) from None


@router.get("/routes")
async def routes(user: Reader, session: Db, mission_id: uuid.UUID | None = None) -> list[RouteOut]:
    return await service.list_routes(session, user, today_utc(), mission_id)


@router.post("/suppliers/{supplier_id}/mitigation", status_code=201)
async def activate(
    supplier_id: uuid.UUID, body: MitigationIn, user: User, session: Db, publisher: Pub
) -> SupplierDetailOut:
    try:
        outcome, _ = await service.activate(session, user, today_utc(), supplier_id, body.note)
    except service.SupplyError as e:
        raise _http(e) from None
    out = await service.supplier_detail(session, user, today_utc(), supplier_id)
    await _done(session, publisher, outcome.events)
    return out


@router.post("/mitigations/{mitigation_id}/stand-down")
async def stand_down(
    mitigation_id: uuid.UUID, user: User, session: Db, publisher: Pub
) -> SupplierDetailOut:
    try:
        outcome, supplier_id = await service.stand_down(session, user, mitigation_id)
    except service.SupplyError as e:
        raise _http(e) from None
    out = await service.supplier_detail(session, user, today_utc(), supplier_id)
    await _done(session, publisher, outcome.events)
    return out
