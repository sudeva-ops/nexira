"""Read queries for missions, people and sites (OPS-01, PPL-01..04). RLS scopes
every query to the caller's tenant."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.people.schemas import MissionOut, PersonOut, SiteOut

_MISSIONS = text(
    """
    WITH worst AS (
      SELECT DISTINCT ON (mission_id) mission_id, id, reference, severity
        FROM incident
       WHERE status = 'ACTIVE' AND mission_id IS NOT NULL
       ORDER BY mission_id, severity_rank(severity) DESC, opened_at DESC
    ), people AS (
      SELECT mission_id,
             count(*) FILTER (WHERE person_type <> 'CITIZEN') AS personnel,
             count(*) FILTER (WHERE person_type = 'CITIZEN') AS citizens
        FROM person WHERE is_active GROUP BY mission_id
    )
    SELECT m.id, m.code, m.city, m.country_code,
           ST_Y(m.location::geometry) AS lat, ST_X(m.location::geometry) AS lon,
           m.risk_level,
           CASE WHEN w.severity IS NOT NULL
                 AND severity_rank(w.severity) > severity_rank(m.risk_level)
                THEN w.severity ELSE m.risk_level END AS display_risk,
           CASE WHEN severity_rank(w.severity) > severity_rank(m.risk_level)
                THEN w.id END AS incident_id,
           CASE WHEN severity_rank(w.severity) > severity_rank(m.risk_level)
                THEN w.reference END AS incident_reference,
           coalesce(p.personnel, 0) AS personnel, coalesce(p.citizens, 0) AS citizens
      FROM mission m
      LEFT JOIN worst w ON w.mission_id = m.id
      LEFT JOIN people p ON p.mission_id = m.id
     ORDER BY m.code
    """
)


async def list_missions(session: AsyncSession) -> list[MissionOut]:
    return [MissionOut(**r._asdict()) for r in await session.execute(_MISSIONS)]


def _like(q: str | None) -> str | None:
    if not q:
        return None
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# The zone CTE is repeated in the people and sites queries so that each query is
# one literal (no SQL is assembled from strings).
_PEOPLE_PAGE = text(
    """
    WITH zone AS (  -- in an ACTIVE incident's exposure; the most severe incident wins
      SELECT DISTINCT ON (e.subject_id) e.subject_id, i.reference
        FROM incident_exposure e JOIN incident i ON i.id = e.incident_id
       WHERE i.status = 'ACTIVE' AND e.subject_type = :subject_type
       ORDER BY e.subject_id, severity_rank(i.severity) DESC, i.opened_at DESC
    )
    SELECT p.id, p.full_name, p.person_type, p.role_title,
           m.code AS mission_code, l.place_label,
           ST_Y(l.location::geometry) AS lat, ST_X(l.location::geometry) AS lon,
           l.primary_source AS location_source, l.confidence, l.computed_at AS located_at,
           z.subject_id IS NOT NULL AS in_zone, z.reference AS incident_reference
      FROM person p
      LEFT JOIN mission m ON m.id = p.mission_id
      LEFT JOIN person_location_current l ON l.person_id = p.id
      LEFT JOIN zone z ON z.subject_id = p.id
     WHERE p.is_active
       AND (CAST(:q AS text) IS NULL
            OR concat_ws(' ', p.full_name, p.role_title, m.code, m.city, l.place_label) ILIKE :q)
       AND (CAST(:person_type AS text) IS NULL OR p.person_type = :person_type)
       AND (CAST(:mission AS text) IS NULL OR m.code = :mission)
       AND (CAST(:in_zone AS boolean) IS NULL OR (z.subject_id IS NOT NULL) = :in_zone)
     ORDER BY (z.subject_id IS NULL), (p.person_type = 'CITIZEN'), m.code NULLS LAST,
              p.full_name, p.id
     LIMIT :limit OFFSET :offset
    """
)
_PEOPLE_COUNT = text(
    """
    WITH zone AS (  -- in an ACTIVE incident's exposure; the most severe incident wins
      SELECT DISTINCT ON (e.subject_id) e.subject_id, i.reference
        FROM incident_exposure e JOIN incident i ON i.id = e.incident_id
       WHERE i.status = 'ACTIVE' AND e.subject_type = :subject_type
       ORDER BY e.subject_id, severity_rank(i.severity) DESC, i.opened_at DESC
    )
    SELECT count(*)
      FROM person p
      LEFT JOIN mission m ON m.id = p.mission_id
      LEFT JOIN person_location_current l ON l.person_id = p.id
      LEFT JOIN zone z ON z.subject_id = p.id
     WHERE p.is_active
       AND (CAST(:q AS text) IS NULL
            OR concat_ws(' ', p.full_name, p.role_title, m.code, m.city, l.place_label) ILIKE :q)
       AND (CAST(:person_type AS text) IS NULL OR p.person_type = :person_type)
       AND (CAST(:mission AS text) IS NULL OR m.code = :mission)
       AND (CAST(:in_zone AS boolean) IS NULL OR (z.subject_id IS NOT NULL) = :in_zone)
    """
)


async def list_people(
    session: AsyncSession,
    *,
    q: str | None,
    person_type: str | None,
    mission: str | None,
    in_zone: bool | None,
    limit: int,
    offset: int,
) -> tuple[int, list[PersonOut]]:
    """PPL-04: free-text filter across name, role, mission and place. In-zone people
    first, and personnel before citizens."""
    params: dict[str, Any] = {
        "q": _like(q),
        "person_type": person_type,
        "mission": mission,
        "in_zone": in_zone,
        "subject_type": "PERSON",
    }
    total = await session.scalar(_PEOPLE_COUNT, params) or 0
    rows = await session.execute(_PEOPLE_PAGE, {**params, "limit": limit, "offset": offset})
    return total, [PersonOut(**r._asdict()) for r in rows]


_SITES = text(
    """
    WITH zone AS (  -- in an ACTIVE incident's exposure; the most severe incident wins
      SELECT DISTINCT ON (e.subject_id) e.subject_id, i.reference
        FROM incident_exposure e JOIN incident i ON i.id = e.incident_id
       WHERE i.status = 'ACTIVE' AND e.subject_type = :subject_type
       ORDER BY e.subject_id, severity_rank(i.severity) DESC, i.opened_at DESC
    )
    SELECT s.id, s.name, s.site_type, m.code AS mission_code, m.city,
           ST_Y(s.location::geometry) AS lat, ST_X(s.location::geometry) AS lon,
           s.readiness_score, s.last_drill_on,
           z.subject_id IS NOT NULL AS in_zone
      FROM site s
      JOIN mission m ON m.id = s.mission_id
      LEFT JOIN zone z ON z.subject_id = s.id
     WHERE (CAST(:q AS text) IS NULL
            OR concat_ws(' ', s.name, s.site_type, m.code, m.city) ILIKE :q)
       AND (CAST(:mission AS text) IS NULL OR m.code = :mission)
     ORDER BY (z.subject_id IS NULL), m.code, s.site_type, s.name
    """
)


async def list_sites(
    session: AsyncSession, *, q: str | None, mission: str | None
) -> tuple[int, int, list[SiteOut]]:
    """Returns (total, mission property count, sites). In-zone sites first."""
    rows = await session.execute(
        _SITES, {"q": _like(q), "mission": mission, "subject_type": "SITE"}
    )
    sites = [SiteOut(**r._asdict()) for r in rows]
    return len(sites), sum(s.site_type != "HOTEL" for s in sites), sites
