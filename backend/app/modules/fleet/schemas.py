import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class StateOut(BaseModel):
    """A derived or stored state (plan-pilot-flt §3), with the incident or evacuation it
    comes from."""

    code: str  # MAINTENANCE, BLOCKED, IN_ZONE, ASSIGNED, AVAILABLE, IN_USE
    reference: str | None = None


class AssetOut(BaseModel):
    """An asset as everyone sees it; the driver's name only within the caller's people scope
    (FLT-07, plan §7)."""

    id: uuid.UUID
    code: str
    kind: str  # VEHICLE, EQUIPMENT
    type_label: str
    armoured: bool
    seats: int | None
    mission_id: uuid.UUID
    mission_code: str
    city: str
    location_label: str
    lat: float
    lon: float
    at_site: bool
    fuel_pct: int
    position_at: datetime
    status: str  # stored: AVAILABLE, IN_USE, MAINTENANCE
    status_reason: str | None
    state: StateOut  # the first that applies (§3)
    tags: list[StateOut]  # every derived state that applies, the first included
    available: bool
    driver_assigned: bool
    driver_name: str | None
    source: str
    simulated: bool = True  # D-19


class SuggestionOut(BaseModel):
    partner_id: uuid.UUID
    partner_name: str
    sla_minutes: int


class CapacityOut(BaseModel):
    seats_available: int
    seats_needed: int
    needed_from: str  # EVACUATION (the live manifest) or PEOPLE (the mission's people)
    evacuation_reference: str | None
    shortfall: int
    suggestion: SuggestionOut | None  # only with a shortfall; nothing is requested (§58 Q5)


class MissionFleetOut(BaseModel):
    mission_id: uuid.UUID
    mission_code: str
    city: str
    country_code: str
    vehicles: int
    available: int
    generator_fuel_pct: int | None
    capacity: CapacityOut
    simulated: bool = True


class SummaryOut(BaseModel):
    """Tenant-wide counts every role may see (FLT-06)."""

    vehicles: int
    armoured: int
    average_fuel_pct: int | None
    maintenance_due: int  # overdue or due within 14 days, not done


class MaintenanceOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    asset_code: str
    mission_id: uuid.UUID
    mission_code: str
    task: str
    due_on: date
    done_at: datetime | None
    done_by_type: str | None
    alert: bool  # not done, overdue or due within 14 days (§58 Q6)
    overdue: bool


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern=r"^(AVAILABLE|IN_USE|MAINTENANCE)$")
    reason: str | None = Field(default=None, min_length=1, max_length=300)
