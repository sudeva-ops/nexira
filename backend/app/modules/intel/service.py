"""Intelligence services: source definitions (Prompt 4); ingestion,
normalisation and fusion of raw signals (Prompt 6, INC-01..04)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import Event
from app.modules.intel import hazards
from app.modules.intel.fusion import Fused, fuse
from app.modules.intel.models import Incident, IncidentEvent, IntelSource, RawSignal
from app.modules.intel.normalise import normalise
from app.modules.tenancy.service import SYSTEM, Actor

FUSION = Actor(type="SYSTEM", id="intel.fusion")


@dataclass(frozen=True)
class SourceIn:
    code: str
    name: str
    reliability: Decimal  # D-10
    severity_map: dict[str, str] = field(default_factory=dict)
    category_map: dict[str, str] = field(default_factory=dict)
    connector_type: str = "SIMULATED"
    takes_part_in_fusion: bool = True  # D-09: OSINT is False in Phase 1
    is_enabled: bool = True


async def ensure_sources(
    session: AsyncSession, sources: list[SourceIn], actor: Actor = SYSTEM
) -> list[str]:
    """Create sources whose code is new; return the codes created (audited once each)."""
    tenant_id = session.info["tenant_id"]
    created = await session.scalars(
        insert(IntelSource)
        .values(
            [
                {
                    "tenant_id": tenant_id,
                    "code": s.code,
                    "name": s.name,
                    "reliability": s.reliability,
                    "severity_map": s.severity_map,
                    "category_map": s.category_map,
                    "connector_type": s.connector_type,
                    "takes_part_in_fusion": s.takes_part_in_fusion,
                    "is_enabled": s.is_enabled,
                }
                for s in sources
            ]
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(IntelSource.code)
    )
    codes = sorted(created.all())
    for code in codes:
        source = next(s for s in sources if s.code == code)
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="INTEL_SOURCE.CREATE",
            entity_type="intel_source",
            entity_id=code,
            details={
                "reliability": str(source.reliability),
                "takes_part_in_fusion": source.takes_part_in_fusion,
                "is_enabled": source.is_enabled,
            },
        )
    return codes


class RawSignalIn(BaseModel):
    """A RAW_SIGNAL event payload: one provider item in its own terms (INC-01)."""

    source_code: str
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str | None = None
    language: str | None = "en"
    provider_category: str | None = None
    provider_severity: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    place_label: str | None = None
    occurred_at: datetime | None = None  # defaults to the event envelope's time
    # D-38: a natural hazard's measure (hazards.MEASURED); validated by the normaliser.
    hazard: dict[str, Any] | None = None


Outcome = Literal["REJECTED", "DUPLICATE", "DISCARDED", "NORMALISED", "FUSED"]


@dataclass(frozen=True)
class Ingested:
    outcome: Outcome
    signal_id: int | None = None
    fused: Fused | None = None
    reason: str | None = None


async def ingest_signal(session: AsyncSession, event: Event, actor: Actor = FUSION) -> Ingested:
    """Store, normalise and fuse one RAW_SIGNAL event, in the caller's transaction.

    Idempotent: a second event with the same source and external_id is ignored
    (raw_signal is unique on them), so redelivery from the stream is harmless.
    """
    try:
        item = RawSignalIn.model_validate(event.payload)
    except ValidationError as e:
        return await _reject(session, event, actor, f"invalid payload: {e.error_count()} errors")
    source = await session.scalar(select(IntelSource).where(IntelSource.code == item.source_code))
    if source is None:
        return await _reject(session, event, actor, f"unknown source {item.source_code!r}")

    has_location = item.lat is not None and item.lon is not None
    signal_id = await session.scalar(
        insert(RawSignal)
        .values(
            tenant_id=session.info["tenant_id"],
            source_id=source.id,
            external_id=item.external_id,
            title=item.title,
            body=item.body,
            language=item.language,
            provider_category=item.provider_category,
            provider_severity=item.provider_severity,
            location=f"SRID=4326;POINT({item.lon} {item.lat})" if has_location else None,
            place_label=item.place_label,
            occurred_at=item.occurred_at or event.occurred_at,
            payload=event.payload,
        )
        .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
        .returning(RawSignal.id)
    )
    if signal_id is None:
        return Ingested("DUPLICATE")
    signal = await session.get_one(RawSignal, signal_id)

    result = normalise(
        category_map=source.category_map,
        severity_map=source.severity_map,
        provider_category=item.provider_category,
        provider_severity=item.provider_severity,
        has_location=has_location,
        payload=event.payload,
    )
    reason = "source disabled" if not source.is_enabled else result.reason  # D-09
    # The newest signal decides a hazard's details, so a future-dated one would fix them
    # for good (review of Prompt 55, L8).
    if (
        reason is None
        and result.category in hazards.HAZARD_CATEGORIES
        and signal.occurred_at > datetime.now(UTC) + hazards.FUTURE_TOLERANCE
    ):
        reason = "occurred in the future"
    signal.norm_category = result.category
    signal.norm_severity = result.severity
    signal.norm_status = "DISCARDED" if reason else "NORMALISED"
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="RAW_SIGNAL.DISCARD" if reason else "RAW_SIGNAL.NORMALISE",
        entity_type="raw_signal",
        entity_id=str(signal_id),
        details={
            "source": source.code,
            "external_id": item.external_id,
            "provider_category": item.provider_category,
            "provider_severity": item.provider_severity,
            "norm_category": result.category,
            "norm_severity": result.severity,
            **({"reason": reason} if reason else {}),
        },
    )
    if reason:
        return Ingested("DISCARDED", signal_id, reason=reason)
    if not source.takes_part_in_fusion:
        # D-09: such a source neither joins nor opens incidents; the signal stays NORMALISED.
        return Ingested("NORMALISED", signal_id)
    fused = await fuse(session, signal, source, actor)
    return Ingested("FUSED", signal_id, fused)


async def _reject(session: AsyncSession, event: Event, actor: Actor, reason: str) -> Ingested:
    """Nothing can be stored without a known source; the event is audited and dropped."""
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="RAW_SIGNAL.REJECT",
        entity_type="event",
        entity_id=str(event.id),
        details={"reason": reason, "source": event.source},
    )
    return Ingested("REJECTED", reason=reason)


def signal_event(ingested: Ingested, tenant_id: uuid.UUID) -> Event | None:
    """SIGNAL_INGESTED, published after commit for every stored signal (live feed, OPS-02)."""
    if ingested.signal_id is None:
        return None  # rejected or a duplicate: nothing new is stored
    return Event(
        type="SIGNAL_INGESTED",
        tenant_id=tenant_id,
        payload={
            "signal_id": ingested.signal_id,
            "outcome": ingested.outcome,
            "incident_id": str(ingested.fused.incident_id) if ingested.fused else None,
        },
        source="intel.fusion",
    )


def incident_event(ingested: Ingested, tenant_id: uuid.UUID) -> Event | None:
    """The INCIDENT_CREATED / INCIDENT_UPDATED event to publish after commit."""
    if ingested.fused is None:
        return None
    fused = ingested.fused
    return Event(
        type="INCIDENT_CREATED" if fused.created else "INCIDENT_UPDATED",
        tenant_id=tenant_id,
        payload={
            "incident_id": str(fused.incident_id),
            "reference": fused.reference,
            "signal_id": ingested.signal_id,
            "confidence": fused.confidence,
            "signal_severity": fused.signal_severity,
            "change": "signal",
        },
        source="intel.fusion",
    )


async def change_status(
    session: AsyncSession, incident: Incident, status: str, actor: Actor
) -> IncidentEvent:
    """INC-07: set ACTIVE / MONITORING / CLOSED, on the timeline and in the audit log."""
    previous = incident.status
    incident.status = status
    incident.closed_at = func.now() if status == "CLOSED" else None
    event = IncidentEvent(
        tenant_id=incident.tenant_id,
        incident_id=incident.id,
        event_type="STATUS",
        summary=f"Status {previous} → {status}.",
        actor_type=actor.type,
        actor_id=actor.id,
        data={"from": previous, "to": status},
    )
    session.add(event)
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="INCIDENT.STATUS_CHANGE",
        entity_type="incident",
        entity_id=incident.reference,
        details={"from": previous, "to": status},
    )
    return event


async def add_note(
    session: AsyncSession, incident: Incident, note: str, actor: Actor
) -> IncidentEvent:
    """INC-07: a free-text note on the incident timeline."""
    event = IncidentEvent(
        tenant_id=incident.tenant_id,
        incident_id=incident.id,
        event_type="NOTE",
        summary=note,
        actor_type=actor.type,
        actor_id=actor.id,
    )
    session.add(event)
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="INCIDENT.NOTE_ADD",
        entity_type="incident",
        entity_id=incident.reference,
        details={"incident_event_id": event.id, "length": len(note)},
    )
    return event


async def retract_note(session: AsyncSession, event_id: int, actor: Actor) -> IncidentEvent:
    """D-13: undoing a note marks it retracted; the history stays (audited by the caller)."""
    event = await session.get(IncidentEvent, event_id)
    if event is None or event.event_type != "NOTE":
        raise LookupError("note not found")
    event.data = {**event.data, "retracted": True, "retracted_by": f"{actor.type}:{actor.id}"}
    event.summary = f"[Retracted] {event.summary}"
    await session.flush()
    return event
