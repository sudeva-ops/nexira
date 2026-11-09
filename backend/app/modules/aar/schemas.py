from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Every line of a review is built from a row's type and data, never from a summary that may
# name a person (plan-pilot-aar §2, G-1).
SOURCES = Literal[
    "INCIDENT",
    "PLAYBOOK",
    "CHECKIN",
    "AGENT",
    "DECISION",
    "STATUS",
    "FLEET",
    "SITE",
    "SUPPLY",
    "NOTIFICATION",
]


class TimelineEntryOut(BaseModel):
    at: datetime
    source: SOURCES
    text: str


class MetricOut(BaseModel):
    """One response metric (AAR-03, plan §3): seconds, or a percentage for personnel accounted;
    None when the record holds no figure."""

    key: str
    label: str
    value: float | None
    unit: Literal["s", "%"]
    target: float | None  # in the same unit; None when there is none
    met: bool | None
    detail: str | None = None
