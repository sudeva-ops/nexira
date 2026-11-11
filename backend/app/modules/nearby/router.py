"""Nearby API (NBY-01..04; D-52). Every role reads it, under RLS and mission scope; names only
within the caller's people scope. A read, like the exposure on Incidents: not audited (§115 Q5)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.nearby import service
from app.modules.nearby.schemas import NearbyOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/nearby", tags=["nearby"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def nearby(
    user: Reader,
    session: Db,
    lon: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    # NBY-02: 1 to 50 km, 10 by default.
    radius_m: Annotated[int, Query(ge=1_000, le=50_000)] = 10_000,
) -> NearbyOut:
    return await service.nearby(session, user, lon, lat, radius_m)
