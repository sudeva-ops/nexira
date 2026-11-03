import uuid
from datetime import date

from pydantic import BaseModel

MODEL_LABEL = "Illustrative model · a projection, not a prediction"  # D-46


class DriverOut(BaseModel):
    key: str  # baseline, incidents, signals, health, hazard, weather, events
    label: str
    points: int
    change: int | None  # against 7 days ago; None when that day has no computed components


class HistoryOut(BaseModel):
    day: date
    value: int
    source: str  # COMPUTED, ILLUSTRATIVE, or LIVE for today's figure worked out on read


class ForecastOut(BaseModel):
    day: date
    value: int
    low: int
    high: int


class EventOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    place_label: str | None
    starts_on: date
    ends_on: date
    attendance: int | None
    weight: int
    source: str


class RisingOut(BaseModel):
    mission_id: uuid.UUID
    mission_code: str
    city: str
    now: int
    peak: int
    peak_day: date
    change: int
    crosses: bool  # the peak reaches the elevated threshold


class ActionOut(BaseModel):
    mission_code: str
    text: str  # never names a VIP visit (plan-pilot-prd §6, G-1)


class OverviewOut(BaseModel):
    threshold: int
    model: str
    rising: list[RisingOut]
    actions: list[ActionOut]
    simulated: bool = True


class MissionOut(BaseModel):
    mission_id: uuid.UUID
    mission_code: str
    city: str
    threshold: int
    model: str
    now: int
    history: list[HistoryOut]  # 30 days before today, then today's live figure
    forecast: list[ForecastOut]  # 14 days after today
    drivers: list[DriverOut]
    events: list[EventOut]  # today and the next 14 days
    simulated: bool = True
