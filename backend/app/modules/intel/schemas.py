import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    code: str
    name: str
    simulated: bool  # D-19: shown as "<name> (simulated)", never "Connected"


class SignalOut(BaseModel):
    id: int
    source_code: str
    source_name: str
    source_simulated: bool
    external_id: str
    title: str
    provider_category: str | None
    provider_severity: str | None
    norm_category: str | None
    norm_severity: str | None  # D-11: the "Normalised (signal)" column
    norm_status: str  # NEW, NORMALISED, FUSED, DISCARDED
    lat: float | None
    lon: float | None
    place_label: str | None
    occurred_at: datetime
    received_at: datetime
    incident_id: uuid.UUID | None
    incident_reference: str | None


class IncidentOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    category: str
    severity: str  # the incident's severity (D-11 step 3)
    signal_severity: str  # the highest linked signal (D-11 step 2)
    status: str
    confidence: int | None
    mission_id: uuid.UUID | None
    lat: float
    lon: float
    impact_radius_m: int
    place_label: str | None
    opened_at: datetime
    last_signal_at: datetime
    signal_count: int
    sources: list[SourceRef]


class IncidentEventOut(BaseModel):
    id: int
    event_type: str
    summary: str
    actor_type: str
    actor_id: str | None
    occurred_at: datetime
    data: dict[str, Any]


class ExposureOut(BaseModel):
    subject_type: str  # PERSON, SITE, TRIP
    subject_id: uuid.UUID
    name: str  # person name, site name or trip reference
    kind: str  # person_type, site_type, or "TRIP"
    mission_code: str | None
    lat: float | None  # person: current location; site: its location; trip: none
    lon: float | None
    distance_m: int | None
    confidence: int | None  # person: location confidence; trip: best traveller
    location_source: str | None  # person: primary_source of the current location
    place_label: str | None


class ExposureSummaryOut(BaseModel):
    """D-23 shape; the UI's Sites figure is mission_sites (site types other than HOTEL)."""

    staff: int
    delegates: int
    citizens: int
    people: int
    sites: int
    mission_sites: int
    protected_sites: int
    trips: int


class IncidentDetailOut(IncidentOut):
    mission_code: str | None
    exposure_summary: ExposureSummaryOut
    exposure: list[ExposureOut]
    signals: list[SignalOut]
    timeline: list[IncidentEventOut]


class StatusIn(BaseModel):
    status: Literal["ACTIVE", "MONITORING", "CLOSED"]


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class OperationsSummaryOut(BaseModel):
    """OPS-03 KPI strip, computed from data (D-27)."""

    missions: int
    missions_elevated: int  # display risk MODERATE or above (plan G-22)
    missions_critical: int
    personnel: int  # active people other than citizens
    personnel_located: int
    avg_location_confidence: float | None
    citizens: int
    mission_sites: int  # D-23: site types other than HOTEL
    trips_active: int  # starts_on <= today (UTC) <= ends_on
    travellers_active: int
    signals_24h: int
    incidents_active: int
    highest_active_severity: str | None
