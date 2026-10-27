import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SegmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="FLIGHT, STAY, MEETING or GROUND")
    title: str = Field(min_length=1, max_length=200)
    place_label: str | None = Field(default=None, max_length=200)
    starts_at: datetime
    ends_at: datetime
    flight_number: str | None = Field(default=None, max_length=8)  # FLIGHT only, e.g. XW 451
    from_airport: str | None = Field(default=None, min_length=3, max_length=3)
    to_airport: str | None = Field(default=None, min_length=3, max_length=3)


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
    restricted: bool = False  # VIP or ministerial: flights never tracked (D-33)


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
    """For a restricted trip, FLIGHT segments are masked for everyone except the
    requester, TRAVEL_DESK, SECURITY_OFFICER and ADMIN (plan G-7): title "Flight
    (restricted)", no place, flight fields or times."""

    seq: int
    kind: str
    title: str
    place_label: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    flight_number: str | None
    from_airport: str | None
    to_airport: str | None
    flight_id: uuid.UUID | None  # set while the flight is tracked (D-33)
    flight_status: str | None


class CountryRiskOut(BaseModel):
    """JR-03: the destination's breakdown. simulated: D-19."""

    country_code: str
    level: str  # the base level raised to the worst ACTIVE incident in the country
    base_level: str  # MODERATE when the country has no simulated level (not rated)
    rated: bool
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
    restricted: bool  # VIP or ministerial (D-33)
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


class FlightOut(BaseModel):
    """A tracked flight (D-33). Positions and statuses are simulated (D-19)."""

    id: uuid.UUID
    flight_number: str
    status: str  # SCHEDULED, DELAYED, AIRBORNE, HOLDING, DIVERTED, LANDED, CANCELLED
    from_airport: str
    from_city: str
    to_airport: str
    to_city: str
    diverted_to: str | None
    diverted_city: str | None
    scheduled_dep: datetime
    scheduled_arr: datetime
    estimated_dep: datetime
    estimated_arr: datetime
    delay_min: int  # estimated arrival against schedule, never negative
    disrupted: bool  # DELAYED, HOLDING, DIVERTED, CANCELLED, or 30 min or more late
    lat: float | None
    lon: float | None
    altitude_ft: int | None
    speed_kt: int | None
    progress: float  # 0..1 of the planned (or diverted) leg
    route: list[tuple[float, float]]  # (lat, lon): origin, destination, diversion airport
    travellers: list[str]
    trip_id: uuid.UUID
    trip_reference: str
    updated_at: datetime
    simulated: bool


class FlightEventOut(BaseModel):
    event_type: str
    occurred_at: datetime
    details: dict[str, Any]


class FlightDetailOut(FlightOut):
    events: list[FlightEventOut]


class AirportOut(BaseModel):
    iata: str
    name: str
    city: str
    country_code: str
