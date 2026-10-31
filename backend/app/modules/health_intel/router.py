"""Health Intelligence API (HL-01..06, HL-09). Every role reads, counts and no names
(D-39); sending needs a Mass Notification composer (HL-06), with its permission in
GET /api/me/permissions?entity_type=health&entity_id=<mission>. The liveness check stays
at GET /api/health."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, current_user, get_db
from app.modules.health_intel import service
from app.modules.health_intel.schemas import (
    AdvisoryOut,
    CampaignIn,
    CampaignOut,
    MissionHealthOut,
    RequirementOut,
    SummaryOut,
)
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/health", tags=["health"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/advisories")
async def list_advisories(_user: Reader, session: Db) -> list[AdvisoryOut]:
    return await service.list_advisories(session)


@router.get("/summary")
async def summary(_user: Reader, session: Db) -> SummaryOut:
    return await service.summary(session)


@router.get("/requirements")
async def list_requirements(_user: Reader, session: Db) -> list[RequirementOut]:
    return await service.list_requirements(session)


@router.get("/missions/{mission_id}")
async def mission_health(mission_id: uuid.UUID, _user: Reader, session: Db) -> MissionHealthOut:
    try:
        return await service.mission_health(session, mission_id)
    except service.HealthError as e:
        raise HTTPException(e.status_code, str(e)) from None


@router.post("/advisories/{advisory_id}/campaign", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    advisory_id: uuid.UUID, body: CampaignIn, user: User, session: Db
) -> CampaignOut:
    try:
        out = await service.create_campaign(session, user, advisory_id, body.mission_id)
    except service.HealthError as e:
        raise HTTPException(e.status_code, str(e)) from None
    await session.commit()
    return out
