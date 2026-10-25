"""Playbooks and runs API (PB-01..04).

- Reading: any user with a role.
- Starting a run: DUTY_OFFICER or SECURITY_OFFICER, unscoped or for the
  incident's mission (D-05).
- Approving a gated step: approvals.decide() only (D-16); 403 or 409 otherwise.
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.events import Event, Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.playbooks import queries, service
from app.modules.playbooks.schemas import PlaybookOut, RunOut, StartRunIn
from app.modules.tenancy.service import ROLES, Actor

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["playbooks"])


async def _publish_after_commit(publisher: Publisher, event: Event) -> None:
    """The change is committed; a failed publish must not turn it into an error.
    The worker's resume sweep continues RUNNING runs (WORKER_TENANT_IDS)."""
    try:
        await publisher.publish(event)
    except Exception:
        log.exception("publishing %s failed after commit", event.type)


Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]


@router.get("/playbooks")
async def list_playbooks(_user: Reader, session: Db) -> list[PlaybookOut]:
    return await queries.list_playbooks(session)


@router.get("/playbook-runs")
async def list_runs(
    _user: Reader,
    session: Db,
    incident_id: uuid.UUID | None = None,
    status: Literal["RUNNING", "AWAITING_APPROVAL", "COMPLETED", "CANCELLED", "FAILED"]
    | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    """Newest first."""
    return await queries.list_runs(session, incident_id=incident_id, status=status, limit=limit)


@router.get("/playbook-runs/{run_id}")
async def get_run(run_id: uuid.UUID, _user: Reader, session: Db) -> RunOut:
    run = await queries.get_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


@router.post("/playbook-runs", status_code=status.HTTP_201_CREATED)
async def start_run(body: StartRunIn, user: User, session: Db, publisher: Pub) -> RunOut:
    if not await service.may_start(session, user, body.incident_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    try:
        run = await service.start_run(
            session,
            playbook_code=body.playbook_code,
            incident_id=body.incident_id,
            actor=Actor(type="USER", id=str(user.id)),
            started_by=user.id,
        )
    except service.RunNotAllowedError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    await session.commit()
    await _publish_after_commit(publisher, service.run_started_event(run))
    out = await queries.get_run(session, run.id)
    assert out is not None
    return out


@router.post("/playbook-runs/{run_id}/steps/{step_id}/approve")
async def approve_step(
    run_id: uuid.UUID, step_id: uuid.UUID, user: User, session: Db, publisher: Pub
) -> RunOut:
    try:
        run = await service.approve_step(session, user, run_id, step_id)
    except service.StepNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None
    await session.commit()
    await _publish_after_commit(publisher, service.step_approved_event(run, step_id))
    out = await queries.get_run(session, run.id)
    assert out is not None
    return out
