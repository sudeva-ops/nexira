import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SegmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="FLIGHT, STAY, MEETING or GROUND")
    title: str = Field(min_length=1, max_length=200)
    place_label: str | None = Field(default=None, max_length=200)
    starts_at: datetime
    ends_at: datetime


class TripIn(BaseModel):
    """A draft trip (JR-01, JR-02). Author, risk and approval fields are never accepted:
    extra fields are refused."""

    model_config = ConfigDict(extra="forbid")

    purpose: str | None = Field(default=None, max_length=200)
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    destination_country: str = Field(min_length=2, max_length=2)
    starts_on: date
    ends_on: date
    travellers: list[uuid.UUID] = Field(min_length=1, max_length=50)
    segments: list[SegmentIn] = Field(default_factory=list, max_length=30)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    done: bool


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class TravellerOut(BaseModel):
    id: uuid.UUID
    full_name: str
    person_type: str


class SegmentOut(BaseModel):
    seq: int
    kind: str
    title: str
    place_label: str | None
    starts_at: datetime
    ends_at: datetime


class CountryRiskOut(BaseModel):
    """JR-03: the destination's breakdown. simulated: D-19."""

    country_code: str
    level: str  # the base level raised to the worst ACTIVE incident in the country
    base_level: str
    security: int | None
    unrest: int | None
    health: int | None
    transport: int | None
    source: str | None
    incident_level: str | None
    incidents: list[str]
    simulated: bool


class TripOut(BaseModel):
    id: uuid.UUID
    reference: str
    purpose: str | None
    origin: str
    destination: str
    destination_country: str | None
    starts_on: date
    ends_on: date
    approval_status: str  # DRAFT, PENDING, APPROVED, CANCELLED (REJECTED: 0001 rows)
    risk_level: str  # submitted risk; for a draft, what submitting would give now
    live_risk: str
    risk_changed: bool  # JR-07: approved, and the live risk is above the approved level
    mission_id: uuid.UUID | None
    requested_by: uuid.UUID | None  # None: a seeded trip
    requested_by_name: str | None
    submitted_at: datetime | None
    approved_by: uuid.UUID | None  # None on an approved trip: LOW, approved on submission
    approved_by_name: str | None
    approved_at: datetime | None
    approved_risk_level: str | None
    rejection_reason: str | None  # the last rejection; kept as history
    checklist: dict[str, bool]  # the four user items and security_approval
    travellers_count: int
    impacted_by: list[str]  # JR-06: ACTIVE incident references
    created_at: datetime


class TripDetailOut(TripOut):
    travellers: list[TravellerOut]
    segments: list[SegmentOut]
    country_risk: CountryRiskOut | None
