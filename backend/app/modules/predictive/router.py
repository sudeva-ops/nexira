"""Predictive Risk API (PRD-01..05, PRD-07; D-46). Every role reads it: aggregates, mission
references and public calendar events only. Advisory: nothing here changes anything."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.predictive import service
from app.modules.predictive.schemas import MissionOut, OverviewOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/predictive", tags=["predictive"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/overview")
async def overview(_user: Reader, session: Db) -> OverviewOut:
    return await service.overview(session)


@router.get("/missions/{mission_id}")
async def mission(mission_id: uuid.UUID, _user: Reader, session: Db) -> MissionOut:
    try:
        return await service.mission(session, mission_id)
    except service.MissionNotFoundError:
        raise HTTPException(404, "Mission not found") from None
