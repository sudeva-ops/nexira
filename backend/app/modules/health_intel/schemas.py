import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AffectedMissionOut(BaseModel):
    mission_id: uuid.UUID
    code: str
    city: str


class AdvisoryOut(BaseModel):
    id: uuid.UUID
    reference: str
    topic: str
    topic_code: str
    countries: list[str]
    region_label: str
    level: str
    guidance: str
    source: str
    status: str  # OPEN, CLOSED
    published_at: datetime
    updated_at: datetime
    missions: list[AffectedMissionOut]  # HL-02: missions in its countries
    simulated: bool = True  # D-19


class LevelCount(BaseModel):
    level: str
    missions: int


class SummaryOut(BaseModel):
    """HL-08's KPIs. Counts only (D-39)."""

    open_advisories: int
    affecting_missions: int  # open advisories with at least one mission in their countries
    missions_with_advisory: int
    by_level: list[LevelCount]  # highest open level per mission, CRITICAL first
    staff_not_offered: int  # plan-pilot-hl G-3
    vetted_facilities: int
    simulated: bool = True


class RequirementOut(BaseModel):
    country_code: str
    mandatory: str
    recommended: str
    source: str
    simulated: bool = True


class FacilityOut(BaseModel):
    id: uuid.UUID
    name: str
    capabilities: list[str]
    trauma_level: int | None
    open_24_7: bool
    vetted_by: str | None  # the partner's name
    distance_m: int  # from the mission
    avoid: bool  # inside an ACTIVE incident's impact radius (HL-04), computed now
    avoid_incident: str | None  # that incident's reference
    source: str
    simulated: bool = True


class VaccineOut(BaseModel):
    topic_code: str
    offered: int
    open_advisory: bool  # an OPEN advisory of this topic for the mission's country


class ReadinessOut(BaseModel):
    """HL-05: counts only, no person-level data (D-39)."""

    staff: int
    blood_type_on_file: int
    insurance_active: int
    trauma_kits: int
    vaccines: list[VaccineOut]
    as_of: date
    source: str
    simulated: bool = True


class MissionHealthOut(BaseModel):
    mission_id: uuid.UUID
    code: str
    city: str
    country_code: str
    level: str | None  # highest OPEN advisory for its country
    facilities: list[FacilityOut]
    readiness: ReadinessOut | None
    requirement: RequirementOut | None


class CampaignIn(BaseModel):
    """HL-06: who it goes to is fixed (the mission's staff, dependants and citizens)."""

    model_config = ConfigDict(extra="forbid")

    mission_id: uuid.UUID


class CampaignOut(BaseModel):
    campaign_id: uuid.UUID
    reference: str
    status: str  # DRAFT
    template: str | None  # the template code used
