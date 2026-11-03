"""Executive Overview API (EXE-01..04, D-45). Every role reads the overview: aggregates and
references only, never a person's name. The export returns the same figures for the print-ready
briefing and is audited (EXE-03); nothing is stored on the server."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.executive import service
from app.modules.executive.schemas import OverviewOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/executive", tags=["executive"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/overview")
async def overview(user: Reader, session: Db) -> OverviewOut:
    return await service.overview(session, user)


@router.post("/export")
async def export(user: Reader, session: Db) -> OverviewOut:
    out = await service.export(session, user)
    await session.commit()
    return out
