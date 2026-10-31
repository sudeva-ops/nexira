"""Natural Hazards & Climate API (HZ-09, HZ-10). Every role reads: counts, never names.
Arming is in the playbooks API (POST /api/playbook-runs/arm), with its permissions in
GET /api/me/permissions?entity_type=hazards."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.hazards import service
from app.modules.hazards.schemas import ClimateOut, HazardsOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/hazards", tags=["hazards"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_hazards(_user: Reader, session: Db) -> HazardsOut:
    return await service.list_hazards(session)


@router.get("/climate")
async def list_climate(_user: Reader, session: Db) -> list[ClimateOut]:
    return await service.list_climate(session)
