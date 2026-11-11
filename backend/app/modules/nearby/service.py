"""Nearby (NBY-01..04; D-52; docs/plan-pilot-map.md §3): what is within a radius of a point,
from the record, as the person asking (RLS). Worked out on read; nothing is stored; not audited
(§115 Q5). Names only within the caller's people scope (evacuations.name_scope()); a restricted
trip's travellers are never named or listed as travellers (D-33)."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser
from app.modules.evacuations.service import name_scope, sees_names
from app.modules.nearby.schemas import (
    AnnotationOut,
    IncidentOut,
    NamedPersonOut,
    NearbyOut,
    PartnerOut,
    PeopleOut,
    SiteOut,
    TravellersOut,
    VehicleOut,
)

LIMIT = 50  # rows per list; the counts cover everyone in range

# Every query takes the point as :lon, :lat and the radius as :radius, in metres.

# Today's travellers on trips that will happen (Journey plan G-3); a restricted trip's are never
# named or counted as travellers (D-33).
_PEOPLE = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT p.id, p.full_name, p.mission_id, l.confidence, l.place_label,
           CASE WHEN p.person_type IN ('DIPLOMAT', 'LOCAL_STAFF') THEN 'STAFF'
                WHEN p.person_type IN ('DELEGATE', 'CITIZEN') THEN p.person_type
                ELSE 'OTHER' END AS grp,
           round(ST_Distance(l.location, pt.g))::int AS distance_m,
           ST_X(l.location::geometry) AS lon, ST_Y(l.location::geometry) AS lat,
           EXISTS (SELECT 1 FROM trip t JOIN trip_traveller tt ON tt.trip_id = t.id
                    WHERE tt.person_id = p.id AND t.restricted
                      AND (now() AT TIME ZONE 'UTC')::date BETWEEN t.starts_on AND t.ends_on)
             AS restricted
      FROM pt, person p JOIN person_location_current l ON l.person_id = p.id
     WHERE p.is_active AND ST_DWithin(l.location, pt.g, :radius)
     ORDER BY distance_m, p.id
    """
)
_SITES = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT s.id, s.name, s.site_type, m.code AS mission_code,
           round(ST_Distance(s.location, pt.g))::int AS distance_m,
           ST_X(s.location::geometry) AS lon, ST_Y(s.location::geometry) AS lat
      FROM pt, site s JOIN mission m ON m.id = s.mission_id
     WHERE ST_DWithin(s.location, pt.g, :radius)
     ORDER BY distance_m, s.name LIMIT :limit
    """
)
_VEHICLES = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT a.id, a.code, a.type_label, a.status,
           round(ST_Distance(a.location, pt.g))::int AS distance_m,
           ST_X(a.location::geometry) AS lon, ST_Y(a.location::geometry) AS lat
      FROM pt, fleet_asset a
     WHERE a.kind = 'VEHICLE' AND ST_DWithin(a.location, pt.g, :radius)
     ORDER BY distance_m, a.code LIMIT :limit
    """
)
_TRAVELLERS = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT count(DISTINCT tt.person_id) AS people, count(DISTINCT t.id) AS trips
      FROM pt, trip t
      JOIN trip_traveller tt ON tt.trip_id = t.id
      JOIN person_location_current l ON l.person_id = tt.person_id
     WHERE NOT t.restricted AND t.approval_status IN ('PENDING', 'APPROVED')
       AND (now() AT TIME ZONE 'UTC')::date BETWEEN t.starts_on AND t.ends_on
       AND ST_DWithin(l.location, pt.g, :radius)
    """
)
_NEAREST_MISSION = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT m.code, m.country_code FROM pt, mission m
     ORDER BY ST_Distance(m.location, pt.g), m.code LIMIT 1
    """
)
_PARTNERS = text(
    """
    SELECT id, name, services, sla_minutes FROM partner
     WHERE is_active AND CAST(:country AS char(2)) = ANY(coverage)
     ORDER BY sla_minutes, name LIMIT :limit
    """
)
_INCIDENTS = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT i.id, i.reference, i.title, i.severity, i.category,
           round(ST_Distance(i.location, pt.g))::int AS distance_m,
           ST_X(i.location::geometry) AS lon, ST_Y(i.location::geometry) AS lat
      FROM pt, incident i
     WHERE i.status = 'ACTIVE' AND ST_DWithin(i.location, pt.g, :radius)
     ORDER BY distance_m, i.reference LIMIT :limit
    """
)
_ANNOTATIONS = text(
    """
    WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS g)
    SELECT a.id, a.kind, a.symbol, a.label,
           round(ST_Distance(a.shape, pt.g))::int AS distance_m,
           ST_X(ST_Centroid(a.shape::geometry)) AS lon, ST_Y(ST_Centroid(a.shape::geometry)) AS lat
      FROM pt, map_annotation a
     WHERE a.status = 'ACTIVE' AND (a.ends_at IS NULL OR a.ends_at > now())
       AND ST_DWithin(a.shape, pt.g, :radius)
     ORDER BY distance_m, a.created_at LIMIT :limit
    """
)


async def nearby(
    session: AsyncSession, user: CurrentUser, lon: float, lat: float, radius_m: int
) -> NearbyOut:
    params: dict[str, Any] = {"lon": lon, "lat": lat, "radius": radius_m, "limit": LIMIT}
    scope = await name_scope(session, user)
    counts = {"STAFF": 0, "DELEGATE": 0, "CITIZEN": 0, "OTHER": 0}
    confidence: list[int] = []
    named: list[NamedPersonOut] = []
    unnamed = 0
    for p in await session.execute(_PEOPLE, params):
        counts[p.grp] += 1
        confidence.append(p.confidence)
        if not p.restricted and p.mission_id is not None and sees_names(scope, p.mission_id):
            if len(named) < LIMIT:
                named.append(
                    NamedPersonOut(
                        id=p.id,
                        name=p.full_name,
                        group=p.grp,
                        distance_m=p.distance_m,
                        confidence=p.confidence,
                        place_label=p.place_label,
                        lon=p.lon,
                        lat=p.lat,
                    )
                )
        else:
            unnamed += 1
    mission = (await session.execute(_NEAREST_MISSION, params)).one_or_none()
    country = mission.country_code if mission else None
    travellers = (await session.execute(_TRAVELLERS, params)).one()
    partners: list[Any] = []
    if country:
        partners = list(await session.execute(_PARTNERS, {"country": country, "limit": LIMIT}))
    return NearbyOut(
        lon=lon,
        lat=lat,
        radius_m=radius_m,
        country_code=country,
        mission_code=mission.code if mission else None,
        people=PeopleOut(
            staff=counts["STAFF"],
            delegates=counts["DELEGATE"],
            citizens=counts["CITIZEN"],
            others=counts["OTHER"],
            confidence=round(sum(confidence) / len(confidence), 1) if confidence else None,
            named=named,
            unnamed=unnamed,
        ),
        sites=[SiteOut(**r._asdict()) for r in await session.execute(_SITES, params)],
        vehicles=[VehicleOut(**r._asdict()) for r in await session.execute(_VEHICLES, params)],
        travellers=TravellersOut(people=travellers.people, trips=travellers.trips),
        partners=[PartnerOut(**r._asdict()) for r in partners],
        incidents=[IncidentOut(**r._asdict()) for r in await session.execute(_INCIDENTS, params)],
        annotations=[
            AnnotationOut(**r._asdict()) for r in await session.execute(_ANNOTATIONS, params)
        ],
    )
