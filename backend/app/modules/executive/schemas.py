import uuid
from datetime import date, datetime

from pydantic import BaseModel


class PostureOut(BaseModel):
    level: str  # GUARDED, ELEVATED, SEVERE
    critical_missions: int
    elevated_missions: int  # MODERATE or HIGH


class IncidentRefOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    severity: str


class DetectionOut(BaseModel):
    """First signal received to first campaign sent (§2); no baseline is claimed."""

    median_s: int | None
    incidents: int  # how many incidents of the last 30 days the median covers
    current_s: int | None  # the most severe ACTIVE incident's own time
    current_reference: str | None


class AccountedOut(BaseModel):
    pct: int | None  # None: no ACTIVE incident has a check-in
    answered: int
    asked: int
    incident_references: list[str]


class ReadinessOut(BaseModel):
    mean: int | None
    sites: int


class TrendDayOut(BaseModel):
    day: date
    signals: int
    incidents: int


class RegionOut(BaseModel):
    region: str
    exposure: int  # the mean of its missions' risk points (§3)
    missions: int


class DriverOut(BaseModel):
    kind: str  # INCIDENT, EVACUATION, HEALTH, HAZARD, SUPPLY, FLEET, SHELTER
    label: str
    reference: str | None = None


class AttentionOut(BaseModel):
    mission_id: uuid.UUID
    mission_code: str
    city: str
    risk: str  # display_risk
    personnel: int
    readiness: int | None  # the embassy's score
    drivers: list[DriverOut]


class TimelineEventOut(BaseModel):
    occurred_at: datetime
    event_type: str
    summary: str  # never a person's name (G-11)


class RecentOut(BaseModel):
    reference: str
    title: str
    change: str  # OPENED, CLOSED
    at: datetime


class TimelineOut(BaseModel):
    incident: IncidentRefOut | None  # the most severe ACTIVE incident, if any
    events: list[TimelineEventOut]
    recent: list[RecentOut]  # with no ACTIVE incident: the last 7 days


class OverviewOut(BaseModel):
    """EXE-01, EXE-02: aggregates and references only, never a person's name (EXE-04)."""

    posture: PostureOut
    active_incidents: int
    latest_incident: IncidentRefOut | None
    detection: DetectionOut
    accounted: AccountedOut
    readiness: ReadinessOut
    trend: list[TrendDayOut]
    regions: list[RegionOut]
    attention: list[AttentionOut]
    timeline: TimelineOut
    generated_at: datetime
    simulated: bool = True  # D-19
