import uuid
from datetime import date, datetime

from pydantic import BaseModel


class MissionOut(BaseModel):
    id: uuid.UUID
    code: str
    city: str
    country_code: str
    lat: float
    lon: float
    risk_level: str  # the stored baseline (plan G-22)
    display_risk: str  # max(risk_level, highest ACTIVE incident severity for the mission)
    incident_id: uuid.UUID | None  # that incident, when it raises the display risk
    incident_reference: str | None
    personnel: int  # active people other than citizens
    citizens: int


class PersonOut(BaseModel):
    """List view. Phone and email are left out on purpose (data minimisation)."""

    id: uuid.UUID
    full_name: str
    person_type: str
    role_title: str | None
    mission_code: str | None
    place_label: str | None
    lat: float | None
    lon: float | None
    location_source: str | None
    confidence: int | None
    located_at: datetime | None
    in_zone: bool  # exposed to an ACTIVE incident
    incident_reference: str | None


class SiteOut(BaseModel):
    id: uuid.UUID
    name: str
    site_type: str
    mission_code: str
    city: str
    lat: float
    lon: float
    readiness_score: int | None
    last_drill_on: date | None
    in_zone: bool


class Page[T](BaseModel):
    total: int
    items: list[T]


class SitesPage(Page[SiteOut]):
    mission_property: int  # D-23: site types other than HOTEL, within the filter
