"""Signals and incidents read API (INC-01..04). Any user with a role may read."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.intel import queries
from app.modules.intel.schemas import IncidentDetailOut, IncidentOut, SignalOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api", tags=["intel"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/signals")
async def list_signals(
    _user: Reader,
    session: Db,
    status: Literal["NEW", "NORMALISED", "FUSED", "DISCARDED"] | None = None,
    limit: Limit = 100,
) -> list[SignalOut]:
    """Newest first."""
    return await queries.list_signals(session, status=status, limit=limit)


@router.get("/incidents")
async def list_incidents(
    _user: Reader,
    session: Db,
    status: Literal["ACTIVE", "MONITORING", "CLOSED"] | None = None,
    limit: Limit = 100,
) -> list[IncidentOut]:
    """Most severe first, then newest."""
    return await queries.list_incidents(session, status=status, limit=limit)


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: uuid.UUID, _user: Reader, session: Db) -> IncidentDetailOut:
    found = await queries.get_incident(session, incident_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    fields, signals, timeline = found
    return IncidentDetailOut(**fields, signals=signals, timeline=timeline)
