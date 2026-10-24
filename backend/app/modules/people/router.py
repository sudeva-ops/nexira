"""Missions, people and sites read API (OPS-01, PPL-01..04). Any user with a role."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.people import queries
from app.modules.people.schemas import MissionOut, Page, PersonOut, SitesPage
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api", tags=["people"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]
PersonType = Literal["DIPLOMAT", "LOCAL_STAFF", "DEPENDANT", "DELEGATE", "CITIZEN", "CONTRACTOR"]


@router.get("/missions")
async def list_missions(_user: Reader, session: Db) -> list[MissionOut]:
    return await queries.list_missions(session)


@router.get("/people")
async def list_people(
    _user: Reader,
    session: Db,
    q: Annotated[str | None, Query(max_length=100)] = None,
    person_type: PersonType | None = None,
    mission: Annotated[str | None, Query(max_length=10)] = None,
    in_zone: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PersonOut]:
    total, items = await queries.list_people(
        session,
        q=q,
        person_type=person_type,
        mission=mission,
        in_zone=in_zone,
        limit=limit,
        offset=offset,
    )
    return Page[PersonOut](total=total, items=items)


@router.get("/sites")
async def list_sites(
    _user: Reader,
    session: Db,
    q: Annotated[str | None, Query(max_length=100)] = None,
    mission: Annotated[str | None, Query(max_length=10)] = None,
) -> SitesPage:
    total, mission_property, items = await queries.list_sites(session, q=q, mission=mission)
    return SitesPage(total=total, mission_property=mission_property, items=items)
