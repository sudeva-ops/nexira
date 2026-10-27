"""Location Confidence Engine (PPL-02, PPL-03, plan G-13).

Turns location_observation rows into person_location_current: one current
location per person, with a confidence from 0 to 100.

Formula (deterministic; the same inputs and as_of give the same result):

    base       = per-source quality (below), capped at 99
    decay      = per-source points lost per hour since observed_at
    confidence = round(max(0, base - decay * age_hours))

The observation with the highest confidence wins; ties go to the most recent.
Observations newer than as_of, or older than MAX_AGE, are ignored. A landing (a FLIGHT
observation, D-33 AT-04) means the person moved: observations from before their latest
landing no longer count, however good they were (a badge at the embassy they flew from). A person
with no usable observation gets no current location (and so is never exposed).

Per-source quality:
    MOBILE_GPS      100 - ceil(raw.accuracy_m / 10)   (default accuracy 20 m -> 98)
    ACCESS_CONTROL  99                                 (badge at a known door)
    CHECKIN         95                                 (the person said where they are)
    FLIGHT          90
    TRAVEL_BOOKING  raw.quality, default 89            (hotel or itinerary on file)
    CALENDAR_HR     raw.quality, default 72            (scheduled, not observed)
    MANUAL          raw.quality, default 60            (registered address)
"""

import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.people.models import LocationObservation
from app.modules.tenancy.service import SYSTEM, Actor

MAX_AGE = timedelta(hours=72)
CAP = 99

DEFAULT_QUALITY = {
    "ACCESS_CONTROL": 99,
    "CHECKIN": 95,
    "FLIGHT": 90,
    "TRAVEL_BOOKING": 89,
    "CALENDAR_HR": 72,
    "MANUAL": 60,
}
DECAY_PER_HOUR = {
    "MOBILE_GPS": 12.0,
    "ACCESS_CONTROL": 6.0,
    "CHECKIN": 4.0,
    "FLIGHT": 6.0,
    "TRAVEL_BOOKING": 0.0,
    "CALENDAR_HR": 0.0,
    "MANUAL": 0.0,
}


# Only these sources report their own quality; the others are fixed per source.
QUALITY_FROM_RAW = {"TRAVEL_BOOKING", "CALENDAR_HR", "MANUAL"}


def base_quality(source: str, raw: dict[str, Any] | None) -> int:
    raw = raw or {}
    if source == "MOBILE_GPS":
        accuracy_m = float(raw.get("accuracy_m", 20))
        return min(CAP, 100 - math.ceil(accuracy_m / 10))
    if source in QUALITY_FROM_RAW:
        return min(CAP, int(raw.get("quality", DEFAULT_QUALITY[source])))
    return DEFAULT_QUALITY[source]


def confidence(
    source: str, raw: dict[str, Any] | None, observed_at: datetime, as_of: datetime
) -> int:
    age_h = max(0.0, (as_of - observed_at).total_seconds() / 3600)
    return max(0, round(base_quality(source, raw) - DECAY_PER_HOUR[source] * age_h))


@dataclass(frozen=True)
class Current:
    person_id: uuid.UUID
    observation_id: int
    source: str
    place_label: str | None
    confidence: int
    observed_at: datetime


def best(observations: list[LocationObservation], as_of: datetime) -> Current | None:
    candidates = [
        Current(
            person_id=o.person_id,
            observation_id=o.id,
            source=o.source,
            place_label=o.place_label,
            confidence=confidence(o.source, o.raw, o.observed_at, as_of),
            observed_at=o.observed_at,
        )
        for o in observations
        if as_of - MAX_AGE <= o.observed_at <= as_of
    ]
    landed = max((c.observed_at for c in candidates if c.source == "FLIGHT"), default=None)
    if landed is not None:
        candidates = [c for c in candidates if c.observed_at >= landed]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c.confidence, c.observed_at, c.observation_id))


async def recompute(
    session: AsyncSession,
    as_of: datetime,
    person_ids: list[uuid.UUID] | None = None,
    actor: Actor = SYSTEM,
) -> int:
    """Recompute person_location_current; return how many rows changed (audited once)."""
    query = select(LocationObservation).where(
        LocationObservation.observed_at.between(as_of - MAX_AGE, as_of)
    )
    if person_ids is not None:
        query = query.where(LocationObservation.person_id.in_(person_ids))
    by_person: dict[uuid.UUID, list[LocationObservation]] = {}
    for obs in await session.scalars(query):
        by_person.setdefault(obs.person_id, []).append(obs)

    rows = [
        {
            "person_id": c.person_id,
            "observation_id": c.observation_id,
            "place_label": c.place_label,
            "confidence": c.confidence,
            "primary_source": c.source,
            "computed_at": as_of,
        }
        for obs in by_person.values()
        if (c := best(obs, as_of)) is not None
    ]
    if not rows:
        return 0
    # Upsert, and count only rows whose values actually changed.
    changed = await session.execute(
        text(
            """
            INSERT INTO person_location_current
                   (person_id, tenant_id, location, place_label, confidence, primary_source,
                    computed_at)
            SELECT r.person_id, current_tenant_id(), o.location, r.place_label, r.confidence,
                   r.primary_source, r.computed_at
              FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(
                     person_id uuid, observation_id bigint, place_label text,
                     confidence smallint, primary_source text, computed_at timestamptz)
              JOIN location_observation o ON o.id = r.observation_id
            ON CONFLICT (person_id) DO UPDATE
               SET location = EXCLUDED.location, place_label = EXCLUDED.place_label,
                   confidence = EXCLUDED.confidence, primary_source = EXCLUDED.primary_source,
                   computed_at = EXCLUDED.computed_at
             WHERE (person_location_current.location, person_location_current.place_label,
                    person_location_current.confidence, person_location_current.primary_source)
                   IS DISTINCT FROM
                   (EXCLUDED.location, EXCLUDED.place_label, EXCLUDED.confidence,
                    EXCLUDED.primary_source)
            RETURNING person_id
            """
        ),
        {"rows": _json(rows)},
    )
    count = len(changed.all())
    if count:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="LOCATION.RECOMPUTE",
            entity_type="person_location_current",
            details={"changed": count, "as_of": as_of.isoformat()},
        )
    return count


def _json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, default=str)
