"""Read queries for the intel API (tenant-scoped by RLS like every other read)."""

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intel.models import (
    Incident,
    IncidentEvent,
    IncidentSignal,
    IntelSource,
    RawSignal,
)
from app.modules.intel.schemas import IncidentEventOut, IncidentOut, SignalOut


def _signals() -> Select[Any]:
    return (
        select(
            RawSignal,
            IntelSource.code.label("source_code"),
            IntelSource.name.label("source_name"),
            func.ST_Y(func.geometry(RawSignal.location)).label("lat"),
            func.ST_X(func.geometry(RawSignal.location)).label("lon"),
            Incident.id.label("incident_id"),
            Incident.reference.label("incident_reference"),
        )
        .join(IntelSource, IntelSource.id == RawSignal.source_id)
        .outerjoin(IncidentSignal, IncidentSignal.signal_id == RawSignal.id)
        .outerjoin(Incident, Incident.id == IncidentSignal.incident_id)
    )


def _signal_out(row: Any) -> SignalOut:
    s: RawSignal = row.RawSignal
    return SignalOut(
        id=s.id,
        source_code=row.source_code,
        source_name=row.source_name,
        external_id=s.external_id,
        title=s.title,
        provider_category=s.provider_category,
        provider_severity=s.provider_severity,
        norm_category=s.norm_category,
        norm_severity=s.norm_severity,
        norm_status=s.norm_status,
        lat=row.lat,
        lon=row.lon,
        place_label=s.place_label,
        occurred_at=s.occurred_at,
        received_at=s.received_at,
        incident_id=row.incident_id,
        incident_reference=row.incident_reference,
    )


async def list_signals(session: AsyncSession, *, status: str | None, limit: int) -> list[SignalOut]:
    query = _signals().order_by(RawSignal.received_at.desc(), RawSignal.id.desc()).limit(limit)
    if status is not None:
        query = query.where(RawSignal.norm_status == status)
    return [_signal_out(r) for r in await session.execute(query)]


def _incidents() -> Select[Any]:
    linked = (
        select(
            IncidentSignal.incident_id,
            func.count().label("signal_count"),
            func.array_agg(func.distinct(IntelSource.name)).label("sources"),
        )
        .join(RawSignal, RawSignal.id == IncidentSignal.signal_id)
        .join(IntelSource, IntelSource.id == RawSignal.source_id)
        .group_by(IncidentSignal.incident_id)
        .subquery()
    )
    return select(
        Incident,
        func.ST_Y(func.geometry(Incident.location)).label("lat"),
        func.ST_X(func.geometry(Incident.location)).label("lon"),
        func.coalesce(linked.c.signal_count, 0).label("signal_count"),
        linked.c.sources,
    ).outerjoin(linked, linked.c.incident_id == Incident.id)


def _incident_fields(row: Any) -> dict[str, Any]:
    i: Incident = row.Incident
    return {
        "id": i.id,
        "reference": i.reference,
        "title": i.title,
        "category": i.category,
        "severity": i.severity,
        "signal_severity": i.signal_severity,
        "status": i.status,
        "confidence": i.confidence,
        "mission_id": i.mission_id,
        "lat": row.lat,
        "lon": row.lon,
        "impact_radius_m": i.impact_radius_m,
        "place_label": i.place_label,
        "opened_at": i.opened_at,
        "last_signal_at": i.last_signal_at,
        "signal_count": row.signal_count,
        "sources": sorted(row.sources or []),
    }


async def list_incidents(
    session: AsyncSession, *, status: str | None, limit: int
) -> list[IncidentOut]:
    query = (
        _incidents()
        .order_by(
            func.severity_rank(Incident.severity).desc(),
            Incident.opened_at.desc(),
            Incident.reference.desc(),
        )
        .limit(limit)
    )
    if status is not None:
        query = query.where(Incident.status == status)
    return [IncidentOut(**_incident_fields(r)) for r in await session.execute(query)]


async def get_incident(
    session: AsyncSession, incident_id: uuid.UUID
) -> tuple[dict[str, Any], list[SignalOut], list[IncidentEventOut]] | None:
    row = (await session.execute(_incidents().where(Incident.id == incident_id))).one_or_none()
    if row is None:
        return None
    signals = await session.execute(
        _signals().where(IncidentSignal.incident_id == incident_id).order_by(RawSignal.occurred_at)
    )
    events = await session.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.occurred_at, IncidentEvent.id)
    )
    return (
        _incident_fields(row),
        [_signal_out(r) for r in signals],
        [IncidentEventOut.model_validate(e, from_attributes=True) for e in events],
    )
