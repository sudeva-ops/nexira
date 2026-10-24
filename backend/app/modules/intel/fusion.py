"""Fusion of normalised signals into incidents (INC-03, INC-04, D-10, D-11).

A normalised signal joins an ACTIVE incident when all of these hold:
- same norm_category;
- within FUSION_RADIUS_M of incident.location (the first signal's location; it
  never moves);
- occurred_at within FUSION_WINDOW of incident.last_signal_at, either side;
- the source takes part in fusion (checked by the caller, see service.py).
Otherwise it opens a new incident. If several incidents match, it joins the nearest.

Fusion runs under a per-tenant transaction advisory lock, so two signals
handled at the same time cannot both open an incident for the same event.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.intel.models import (
    Incident,
    IncidentEvent,
    IncidentSignal,
    IntelSource,
    RawSignal,
)
from app.modules.intel.normalise import max_severity, severity_rank
from app.modules.tenancy.service import Actor

FUSION_RADIUS_M = 3_000
FUSION_WINDOW_MIN = 60
MAX_CONFIDENCE = 99

CATEGORY_LABELS = {"CIVIL_UNREST": "Civil unrest", "TRANSPORT_STRIKE": "Transport strike"}


def confidence(reliabilities: Iterable[Decimal]) -> int:
    """D-10: confidence = round(100 * (1 - prod(1 - r_i))), capped at 99.

    r_i is intel_source.reliability, counted once per distinct source; the caller
    passes one value per source (the highest, if a source has several). Decimal
    arithmetic with half-up rounding keeps the result exact, so Dataminr 0.60,
    MAX 0.55 and Riskline 0.55 give 1 - 0.40 * 0.45 * 0.45 = 0.919, so 92.
    """
    miss = Decimal(1)
    for r in reliabilities:
        miss *= Decimal(1) - r
    value = (Decimal(100) * (Decimal(1) - miss)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return min(int(value), MAX_CONFIDENCE)


def incident_title(category: str, place_label: str | None) -> str:
    label = CATEGORY_LABELS.get(category, category.replace("_", " ").capitalize())
    return f"{label} · {place_label}" if place_label else label


@dataclass(frozen=True)
class Fused:
    incident_id: uuid.UUID
    reference: str
    created: bool
    confidence: int
    signal_severity: str


def _normalised(signal: RawSignal) -> tuple[str, str]:
    if signal.norm_category is None or signal.norm_severity is None:
        raise ValueError(f"raw_signal {signal.id} is not normalised")
    return signal.norm_category, signal.norm_severity


async def fuse(
    session: AsyncSession, signal: RawSignal, source: IntelSource, actor: Actor
) -> Fused:
    """Link a NORMALISED signal to an incident, opening one if none matches."""
    _normalised(signal)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('nexira:fusion:' || current_tenant_id()))")
    )
    match = await session.scalar(
        select(Incident)
        .join(RawSignal, RawSignal.id == signal.id)
        .where(
            Incident.status == "ACTIVE",
            Incident.category == RawSignal.norm_category,
            func.ST_DWithin(Incident.location, RawSignal.location, FUSION_RADIUS_M),
            func.abs(func.extract("epoch", RawSignal.occurred_at - Incident.last_signal_at))
            <= FUSION_WINDOW_MIN * 60,
        )
        .order_by(func.ST_Distance(Incident.location, RawSignal.location), Incident.opened_at)
        .limit(1)
        .with_for_update(of=Incident)
    )
    if match is None:
        fused = await _open(session, signal, source)
    else:
        fused = await _join(session, match, signal, source)

    await session.execute(
        update(RawSignal).where(RawSignal.id == signal.id).values(norm_status="FUSED")
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="INCIDENT.CREATE" if fused.created else "INCIDENT.FUSE_SIGNAL",
        entity_type="incident",
        entity_id=fused.reference,
        details={
            "signal_id": signal.id,
            "source": source.code,
            "confidence": fused.confidence,
            "signal_severity": fused.signal_severity,
        },
    )
    return fused


async def _open(session: AsyncSession, signal: RawSignal, source: IntelSource) -> Fused:
    category, severity = _normalised(signal)
    value = confidence([source.reliability])
    row = (
        await session.execute(
            insert(Incident)
            .from_select(
                [
                    "tenant_id",
                    "reference",
                    "title",
                    "category",
                    "severity",
                    "signal_severity",
                    "confidence",
                    "location",
                    "place_label",
                    "opened_at",
                    "last_signal_at",
                ],
                select(
                    RawSignal.tenant_id,
                    func.next_reference("INC", True),  # D-18
                    literal(incident_title(category, signal.place_label)),
                    RawSignal.norm_category,
                    RawSignal.norm_severity,  # Prompt 7 may raise severity (D-11 step 3)
                    RawSignal.norm_severity,
                    literal(value),
                    RawSignal.location,
                    RawSignal.place_label,
                    RawSignal.occurred_at,
                    RawSignal.occurred_at,
                ).where(RawSignal.id == signal.id),
            )
            .returning(Incident.id, Incident.reference)
        )
    ).one()
    session.add(IncidentSignal(tenant_id=signal.tenant_id, incident_id=row.id, signal_id=signal.id))
    session.add(
        IncidentEvent(
            tenant_id=signal.tenant_id,
            incident_id=row.id,
            event_type="SIGNAL",
            summary=f"Opened from {source.name}: {signal.provider_severity} → {severity}. "
            f"Confidence {value}%.",
            actor_type="SYSTEM",
            actor_id="intel.fusion",
            occurred_at=signal.occurred_at,
            data=_event_data(signal, source, value),
        )
    )
    await session.flush()
    return Fused(row.id, row.reference, True, value, severity)


async def _join(
    session: AsyncSession, incident: Incident, signal: RawSignal, source: IntelSource
) -> Fused:
    _, severity = _normalised(signal)
    session.add(
        IncidentSignal(tenant_id=signal.tenant_id, incident_id=incident.id, signal_id=signal.id)
    )
    await session.flush()
    per_source = await session.scalars(
        select(func.max(IntelSource.reliability))
        .select_from(IncidentSignal)
        .join(RawSignal, RawSignal.id == IncidentSignal.signal_id)
        .join(IntelSource, IntelSource.id == RawSignal.source_id)
        .where(IncidentSignal.incident_id == incident.id)
        .group_by(IntelSource.id)
    )
    before = incident.confidence
    value = confidence(per_source.all())
    signal_severity = max_severity(incident.signal_severity, severity)
    incident.confidence = value
    incident.signal_severity = signal_severity
    # Keep any raise already applied (D-11 step 3); never below signal severity.
    if severity_rank(signal_severity) > severity_rank(incident.severity):
        incident.severity = signal_severity
    incident.last_signal_at = max(incident.last_signal_at, signal.occurred_at)
    session.add(
        IncidentEvent(
            tenant_id=signal.tenant_id,
            incident_id=incident.id,
            event_type="FUSED",
            summary=f"Fused {source.name}: {signal.provider_severity} → {severity}. "
            f"Confidence {before}% → {value}%.",
            actor_type="SYSTEM",
            actor_id="intel.fusion",
            occurred_at=signal.occurred_at,
            data=_event_data(signal, source, value),
        )
    )
    await session.flush()
    return Fused(incident.id, incident.reference, False, value, signal_severity)


def _event_data(signal: RawSignal, source: IntelSource, value: int) -> dict[str, object]:
    return {
        "signal_id": signal.id,
        "source": source.code,
        "provider_category": signal.provider_category,
        "provider_severity": signal.provider_severity,
        "norm_category": signal.norm_category,
        "norm_severity": signal.norm_severity,
        "confidence": value,
    }
