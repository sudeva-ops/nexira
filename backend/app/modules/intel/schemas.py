import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SignalOut(BaseModel):
    id: int
    source_code: str
    source_name: str
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
    sources: list[str]


class IncidentEventOut(BaseModel):
    id: int
    event_type: str
    summary: str
    actor_type: str
    actor_id: str | None
    occurred_at: datetime
    data: dict[str, Any]


class IncidentDetailOut(IncidentOut):
    signals: list[SignalOut]
    timeline: list[IncidentEventOut]
