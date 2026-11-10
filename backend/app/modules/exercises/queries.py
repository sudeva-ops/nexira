"""Readiness shared with the modules that show it (People & Sites, Site Twin, Executive
Overview), kept apart from the exercises service so they can read it without importing it."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Each mission's latest completed exercise with an overall score (EXR-07, plan §5). The embassy's
# readiness and last drill come from it; the residence keeps its seeded value (plan G-6).
_LATEST = text(
    """
    SELECT DISTINCT ON (e.mission_id) e.mission_id, e.id AS exercise_id, e.name,
           e.overall_score, (e.ended_at AT TIME ZONE 'UTC')::date AS drilled_on, e.source
      FROM exercise e
     WHERE e.status = 'COMPLETED' AND e.overall_score IS NOT NULL
     ORDER BY e.mission_id, e.ended_at DESC, e.id
    """
)


@dataclass(frozen=True)
class Readiness:
    score: int
    drilled_on: date
    exercise_id: uuid.UUID
    name: str
    source: str  # EXERCISE or ILLUSTRATIVE


async def readiness(session: AsyncSession) -> dict[uuid.UUID, Readiness]:
    """By mission. A mission with no completed, scored exercise keeps the seeded site value."""
    return {
        r.mission_id: Readiness(r.overall_score, r.drilled_on, r.exercise_id, r.name, r.source)
        for r in await session.execute(_LATEST)
    }


# A template carries a "template" block on scene 0's SCENE_START marker (plan §2, G-1).
TEMPLATES_SQL = """
    SELECT s.id, s.code, s.name, e.payload -> 'template' AS template
      FROM scenario s
      JOIN scenario_event e ON e.scenario_id = s.id
     WHERE e.scene_no = 0 AND e.event_type = 'SCENE_START' AND e.payload ? 'template'
     ORDER BY s.code
"""
