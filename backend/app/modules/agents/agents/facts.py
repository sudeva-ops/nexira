"""Read-only lookups shared by the agents."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intel.models import Incident, IncidentSignal, IntelSource, RawSignal


async def incident(session: AsyncSession, incident_id: Any) -> Incident | None:
    try:
        return await session.get(Incident, uuid.UUID(str(incident_id)))
    except ValueError:
        return None


async def signal_evidence(session: AsyncSession, incident_id: uuid.UUID) -> list[dict[str, Any]]:
    """AGT-01: evidence with sources, one line per linked signal."""
    rows = await session.execute(
        select(
            IntelSource.name,
            IntelSource.connector_type,
            RawSignal.title,
            RawSignal.provider_severity,
        )
        .join(RawSignal, RawSignal.source_id == IntelSource.id)
        .join(IncidentSignal, IncidentSignal.signal_id == RawSignal.id)
        .where(IncidentSignal.incident_id == incident_id)
        .order_by(RawSignal.occurred_at)
    )
    return [
        {
            "text": f"{title} ({severity})",
            "source": f"{name} (simulated)" if connector == "SIMULATED" else name,
        }
        for name, connector, title, severity in rows
    ]
