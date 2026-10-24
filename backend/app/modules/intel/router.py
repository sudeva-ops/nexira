"""Signals and incidents API (INC-01..07).

Reading: any user with a role. Changing status and adding notes (INC-07): the
roles below, held unscoped or for the incident's mission (D-05). Before exposure
has set incident.mission_id, only unscoped holders qualify (D-06).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles, user_has_role
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.intel import queries, service
from app.modules.intel.models import Incident
from app.modules.intel.schemas import (
    IncidentDetailOut,
    IncidentEventOut,
    IncidentOut,
    NoteIn,
    OperationsSummaryOut,
    SignalOut,
    StatusIn,
)
from app.modules.tenancy.service import ROLES, Actor

STATUS_ROLES = ("DUTY_OFFICER", "SECURITY_OFFICER", "HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR")
NOTE_ROLES = (*STATUS_ROLES, "CONSULAR_OFFICER", "TRAVEL_DESK")

router = APIRouter(prefix="/api", tags=["intel"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]
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


@router.get("/operations/summary")
async def operations_summary(_user: Reader, session: Db) -> OperationsSummaryOut:
    """OPS-03: the Global Operations KPI strip (D-27)."""
    return await queries.operations_summary(session)


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: uuid.UUID, _user: Reader, session: Db) -> IncidentDetailOut:
    found = await queries.get_incident(session, incident_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    fields, exposure, signals, timeline = found
    return IncidentDetailOut(**fields, exposure=exposure, signals=signals, timeline=timeline)


async def _writable(
    session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID, roles: tuple[str, ...]
) -> Incident:
    incident = await session.scalar(
        select(Incident).where(Incident.id == incident_id).with_for_update()
    )
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    if not await user_has_role(session, user, roles, mission_id=incident.mission_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return incident


@router.patch("/incidents/{incident_id}/status")
async def change_status(
    incident_id: uuid.UUID, body: StatusIn, user: User, session: Db, publisher: Pub
) -> IncidentEventOut:
    incident = await _writable(session, user, incident_id, STATUS_ROLES)
    if incident.status == body.status:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Incident is already {body.status}")
    event = await service.change_status(
        session, incident, body.status, Actor(type="USER", id=str(user.id))
    )
    out = IncidentEventOut.model_validate(event, from_attributes=True)
    await session.commit()
    await publisher.publish(
        Event(
            type="INCIDENT_UPDATED",  # exposure recomputes if the incident is ACTIVE again
            tenant_id=user.tenant_id,
            payload={
                "incident_id": str(incident_id),
                "reference": incident.reference,
                "change": "status",
                "status": body.status,
            },
            source="api",
        )
    )
    return out


@router.post("/incidents/{incident_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_note(
    incident_id: uuid.UUID, body: NoteIn, user: User, session: Db, publisher: Pub
) -> IncidentEventOut:
    incident = await _writable(session, user, incident_id, NOTE_ROLES)
    event = await service.add_note(
        session, incident, body.text, Actor(type="USER", id=str(user.id))
    )
    out = IncidentEventOut.model_validate(event, from_attributes=True)
    await session.commit()
    await publisher.publish(
        Event(
            type="INCIDENT_NOTE_ADDED",
            tenant_id=user.tenant_id,
            payload={"incident_id": str(incident_id), "incident_event_id": event.id},
            source="api",
        )
    )
    return out
