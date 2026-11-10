"""Incident Replay API (RPL-01; D-51). Every role that reads Incidents may replay one; the
payload holds no person's name or id (RPL-05). A read, so not audited (§103 Q6)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.replay import service
from app.modules.replay.schemas import ReplayOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api", tags=["replay"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/incidents/{incident_id}/replay")
async def replay(incident_id: uuid.UUID, _user: Reader, session: Db) -> ReplayOut:
    found = await service.replay(session, incident_id, datetime.now(UTC))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    return found
