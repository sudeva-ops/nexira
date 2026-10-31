import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExposureOut(BaseModel):
    """Counts only, for every role (HZ-10): names stay on People & Sites."""

    staff: int
    people: int
    homes: int  # exposed people located at home (place label "Home…")
    mission_sites: int


class ArmedOut(BaseModel):
    run_id: uuid.UUID
    playbook_code: str
    status: str  # SCHEDULED, RUNNING, ..., DISARMED
    scheduled_for: datetime | None
    starts_in_h: float | None  # on the hazard clock; None once started or disarmed
    forecast_changed: bool  # the latest landfall differs by an hour or more (§43 Q4)


class HazardOut(BaseModel):
    incident_id: uuid.UUID
    reference: str
    title: str
    category: str
    severity: str
    status: str
    place_label: str | None
    lat: float
    lon: float
    impact_radius_m: int
    opened_at: datetime
    updated_at: datetime  # the newest signal
    hazard: dict[str, Any]  # the measure: magnitude, cyclone_category, aqi ...
    landfall_at: datetime | None
    landfall_in_h: float | None
    nearest_mission_code: str | None
    nearest_mission_city: str | None
    nearest_mission_m: int | None
    within_range: bool  # a mission within 300 km (HZ-03)
    exposed: bool  # someone or a site inside the impact radius
    exposure: ExposureOut
    sources: list[str]
    armed: ArmedOut | None
    simulated: bool = True  # D-19


class HazardsOut(BaseModel):
    events: list[HazardOut]
    clock_now: datetime  # the hazard clock (plan-pilot-hz §5)
    demo_advance_h: int
    sources: int  # the simulated sources the module draws on (HZ-09)


class ClimateOut(BaseModel):
    mission_id: uuid.UUID
    mission_code: str
    city: str
    hazards: list[str]
    score_today: int
    score_2050: int
    scenario: str
    source: str
    simulated: bool = True
