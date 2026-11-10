from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.modules.aar.schemas import TimelineEntryOut
from app.modules.checkin.schemas import TallyOut

SEVERITY = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]


class WindowOut(BaseModel):
    start: datetime
    end: datetime


class ReplayIncidentOut(BaseModel):
    id: str
    reference: str
    title: str
    severity: SEVERITY
    status: Literal["ACTIVE", "MONITORING", "CLOSED"]
    lon: float
    lat: float
    impact_radius_m: int
    opened_at: datetime
    exercise: bool


class ReplaySignalOut(BaseModel):
    received_at: datetime
    lon: float | None
    lat: float | None
    severity: SEVERITY | None


class AnswerOut(BaseModel):
    at: datetime
    status: Literal["SAFE", "NEED_HELP"]


class ReplayPersonOut(BaseModel):
    """An exposed person as a dot: an index, never a name or an id (RPL-05)."""

    index: int
    lon: float | None
    lat: float | None
    exposed_at: datetime
    personnel: bool
    asked: bool  # a recipient of the check-in
    answers: list[AnswerOut]


class ReplaySiteOut(BaseModel):
    name: str
    lon: float | None
    lat: float | None
    exposed_at: datetime


class ReplayCheckinOut(BaseModel):
    reference: str
    sent_at: datetime | None
    # Each personnel recipient's answers in time order, without who they are (RPL-04, G-3).
    personnel: list[list[AnswerOut]]
    tally_end: TallyOut


class ReplayOut(BaseModel):
    window: WindowOut
    incident: ReplayIncidentOut
    signals: list[ReplaySignalOut]
    people: list[ReplayPersonOut]
    sites: list[ReplaySiteOut]
    trips: int
    checkin: ReplayCheckinOut | None
    timeline: list[TimelineEntryOut]
