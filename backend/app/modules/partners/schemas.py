import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PartnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    services: list[str]
    coverage: list[str]
    sla_minutes: int
    hours: str
    is_active: bool
    simulated: bool = True  # D-19


class CoverageOut(BaseModel):
    mission_id: uuid.UUID
    code: str
    city: str
    country_code: str
    missing: list[str]


class SuggestionOut(BaseModel):
    person_id: uuid.UUID
    service: str
    mission_id: uuid.UUID
    mission_code: str
    country_code: str
    partners: list[PartnerOut]


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partner_id: uuid.UUID
    service: str
    mission_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class RequestOut(BaseModel):
    id: uuid.UUID
    reference: str
    partner_id: uuid.UUID
    partner_name: str
    service: str
    mission_id: uuid.UUID
    mission_code: str
    incident_id: uuid.UUID | None
    incident_reference: str | None
    person_id: uuid.UUID | None
    person_name: str | None
    person_role: str | None
    place_label: str | None
    note: str | None
    status: str
    eta: datetime | None
    created_by_type: str
    requested_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
