"""A hazard incident's latest details (plan-pilot-hz §3): they live in the payload of
its newest signal, not in a table of their own (requirements-pilot.md §41)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intel import hazards
from app.modules.intel.models import Incident, IncidentSignal, RawSignal


@dataclass(frozen=True)
class Latest:
    hazard: dict[str, Any]  # the newest signal's validated measure ({} if none)
    occurred_at: datetime
    landfall_at: datetime | None  # TROPICAL_CYCLONE only


async def latest(session: AsyncSession, incident: Incident) -> Latest | None:
    signal = await session.scalar(
        select(RawSignal)
        .join(IncidentSignal, IncidentSignal.signal_id == RawSignal.id)
        .where(IncidentSignal.incident_id == incident.id)
        .order_by(RawSignal.occurred_at.desc(), RawSignal.id.desc())
        .limit(1)
    )
    if signal is None:
        return None
    try:
        value = hazards.measure(incident.category, signal.payload)
    except hazards.HazardError:
        value = None
    return Latest(
        hazard=value.model_dump() if value else {},
        occurred_at=signal.occurred_at,
        landfall_at=hazards.landfall_at(incident.category, signal.payload, signal.occurred_at),
    )


async def landfall_of(session: AsyncSession, incident_id: uuid.UUID) -> datetime | None:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        return None
    found = await latest(session, incident)
    return found.landfall_at if found else None
