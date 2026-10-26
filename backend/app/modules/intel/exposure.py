"""Exposure of people, sites and trips to an incident (INC-05, D-06, D-11, D-22).

compute() replaces an incident's incident_exposure rows in one transaction, so
readers see either the previous set or the new one (READ COMMITTED):

| Subject | Exposed when (D-22)                                                     |
|---------|-------------------------------------------------------------------------|
| PERSON  | active, with person_location_current within incident.impact_radius_m    |
| SITE    | any site type within the radius                                         |
| TRIP    | PENDING or APPROVED (Journey plan G-3), active on incident.opened_at    |
|         | ::date (UTC, plan G-11), and at least one traveller exposed             |

Distances use ST_DWithin / ST_Distance on geography, backed by the gist indexes
on person_location_current, site and incident.

Then, on the same incident row:
- mission_id = the mission of the nearest exposed site, or NULL when no site is
  exposed (D-06: then only unscoped HQ roles can approve).
- severity = signal_severity, raised one level (at most CRITICAL) when a
  protected site (EMBASSY, CONSULATE, RESIDENCE) is exposed and signal_severity
  >= HIGH (D-11 step 3). An ESCALATED timeline event is written when the raise
  first applies.
"""

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import Event
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.intel.normalise import SEVERITIES, severity_rank
from app.modules.tenancy.service import Actor

EXPOSURE = Actor(type="SYSTEM", id="intel.exposure")
PROTECTED_SITE_TYPES = ("EMBASSY", "CONSULATE", "RESIDENCE")
STAFF_TYPES = ("DIPLOMAT", "LOCAL_STAFF")

_REPLACE = [
    "DELETE FROM incident_exposure WHERE incident_id = :incident_id",
    """
    INSERT INTO incident_exposure
           (tenant_id, incident_id, subject_type, subject_id, distance_m, confidence)
    SELECT i.tenant_id, i.id, 'PERSON', p.id,
           round(ST_Distance(l.location, i.location))::int, l.confidence
      FROM incident i
      JOIN person_location_current l ON ST_DWithin(l.location, i.location, i.impact_radius_m)
      JOIN person p ON p.id = l.person_id AND p.is_active
     WHERE i.id = :incident_id
    """,
    """
    INSERT INTO incident_exposure
           (tenant_id, incident_id, subject_type, subject_id, distance_m, confidence)
    SELECT i.tenant_id, i.id, 'SITE', s.id, round(ST_Distance(s.location, i.location))::int, NULL
      FROM incident i
      JOIN site s ON ST_DWithin(s.location, i.location, i.impact_radius_m)
     WHERE i.id = :incident_id
    """,
    # A trip's distance and confidence are those of its nearest and best-located
    # exposed traveller.
    """
    INSERT INTO incident_exposure
           (tenant_id, incident_id, subject_type, subject_id, distance_m, confidence)
    SELECT i.tenant_id, i.id, 'TRIP', t.id, min(e.distance_m), max(e.confidence)
      FROM incident i
      JOIN trip t ON (i.opened_at AT TIME ZONE 'UTC')::date BETWEEN t.starts_on AND t.ends_on
                 AND t.approval_status IN ('PENDING', 'APPROVED')  -- trips that will happen (G-3)
      JOIN trip_traveller tt ON tt.trip_id = t.id
      JOIN incident_exposure e ON e.incident_id = i.id AND e.subject_type = 'PERSON'
                              AND e.subject_id = tt.person_id
     WHERE i.id = :incident_id
     GROUP BY i.tenant_id, i.id, t.id
    """,
]

_SUMMARY = text(
    """
    SELECT count(*) FILTER (WHERE p.person_type = ANY(:staff)) AS staff,
           count(*) FILTER (WHERE p.person_type = 'DELEGATE') AS delegates,
           count(*) FILTER (WHERE p.person_type = 'CITIZEN') AS citizens,
           count(p.id) AS people,
           count(s.id) AS sites,
           count(s.id) FILTER (WHERE s.site_type <> 'HOTEL') AS mission_sites,
           count(s.id) FILTER (WHERE s.site_type = ANY(:protected)) AS protected_sites,
           count(*) FILTER (WHERE e.subject_type = 'TRIP') AS trips
      FROM incident_exposure e
      LEFT JOIN person p ON e.subject_type = 'PERSON' AND p.id = e.subject_id
      LEFT JOIN site s ON e.subject_type = 'SITE' AND s.id = e.subject_id
     WHERE e.incident_id = :incident_id
    """
)


@dataclass(frozen=True)
class Counts:
    """D-23 shape. 'sites' counts every exposed site; the UI's Sites figure is
    mission_sites (site types other than HOTEL)."""

    staff: int
    delegates: int
    citizens: int
    people: int
    sites: int
    mission_sites: int
    protected_sites: int
    trips: int

    def summary(self) -> str:
        return (
            f"{_n(self.people, 'person', 'people')} ({self.staff} staff, "
            f"{_n(self.delegates, 'delegate')}, {_n(self.citizens, 'citizen')}), "
            f"{_n(self.sites, 'site')}, {_n(self.trips, 'trip')}"
        )


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


@dataclass(frozen=True)
class Computed:
    incident_id: uuid.UUID
    reference: str
    counts: Counts
    mission_id: uuid.UUID | None
    severity: str
    escalated: bool  # the D-11 raise applied in this computation for the first time


def escalated_severity(signal_severity: str, protected_site_exposed: bool) -> str:
    """D-11 step 3."""
    if protected_site_exposed and severity_rank(signal_severity) >= severity_rank("HIGH"):
        return SEVERITIES[min(severity_rank(signal_severity), len(SEVERITIES) - 1)]
    return signal_severity


async def compute(
    session: AsyncSession, incident_id: uuid.UUID, actor: Actor = EXPOSURE
) -> Computed | None:
    """Recompute exposure for an ACTIVE incident; None if it is not ACTIVE or not found."""
    incident = await session.scalar(
        select(Incident).where(Incident.id == incident_id).with_for_update()
    )
    if incident is None or incident.status != "ACTIVE":
        return None
    previous = await exposure_counts(session, incident_id)
    for statement in _REPLACE:
        await session.execute(text(statement), {"incident_id": incident_id})
    counts = await exposure_counts(session, incident_id)

    incident.mission_id = await session.scalar(
        text(
            """
            SELECT s.mission_id
              FROM incident_exposure e JOIN site s ON s.id = e.subject_id
             WHERE e.incident_id = :incident_id AND e.subject_type = 'SITE'
             ORDER BY e.distance_m, s.id
             LIMIT 1
            """
        ),
        {"incident_id": incident_id},
    )
    was_escalated = severity_rank(incident.severity) > severity_rank(incident.signal_severity)
    incident.severity = escalated_severity(incident.signal_severity, counts.protected_sites > 0)
    escalated = incident.severity != incident.signal_severity and not was_escalated

    if counts != previous:
        _timeline(session, incident, "EXPOSURE", f"Exposure: {counts.summary()}.", asdict(counts))
    if escalated:
        _timeline(
            session,
            incident,
            "ESCALATED",
            f"Severity {incident.signal_severity} → {incident.severity}: protected mission "
            "site in the impact zone (D-11).",
            {"from": incident.signal_severity, "to": incident.severity},
        )
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="INCIDENT.EXPOSURE_COMPUTE",
        entity_type="incident",
        entity_id=incident.reference,
        details={
            **asdict(counts),
            "mission_id": str(incident.mission_id) if incident.mission_id else None,
            "severity": incident.severity,
            "escalated": escalated,
        },
    )
    return Computed(
        incident.id, incident.reference, counts, incident.mission_id, incident.severity, escalated
    )


async def exposure_counts(session: AsyncSession, incident_id: uuid.UUID) -> Counts:
    row = await session.execute(
        _SUMMARY,
        {
            "incident_id": incident_id,
            "staff": list(STAFF_TYPES),
            "protected": list(PROTECTED_SITE_TYPES),
        },
    )
    return Counts(**row.one()._asdict())


def _timeline(
    session: AsyncSession,
    incident: Incident,
    event_type: str,
    summary: str,
    data: dict[str, object],
) -> None:
    session.add(
        IncidentEvent(
            tenant_id=incident.tenant_id,
            incident_id=incident.id,
            event_type=event_type,
            summary=summary,
            actor_type="SYSTEM",
            actor_id=EXPOSURE.id,
            data=data,
        )
    )


def exposure_event(computed: Computed, tenant_id: uuid.UUID) -> Event:
    """EXPOSURE_COMPUTED, published after commit (the Response Planner listens, G-15)."""
    return Event(
        type="EXPOSURE_COMPUTED",
        tenant_id=tenant_id,
        payload={
            "incident_id": str(computed.incident_id),
            "reference": computed.reference,
            "mission_id": str(computed.mission_id) if computed.mission_id else None,
            "severity": computed.severity,
            "escalated": computed.escalated,
            "counts": asdict(computed.counts),
        },
        source="intel.exposure",
    )
