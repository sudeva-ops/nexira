import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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


Team = Literal[
    "SECURITY",
    "HR",
    "FACILITIES",
    "FLEET",
    "CONSULAR",
    "LOGISTICS",
    "COMMUNICATIONS",
    "IT",
    "MISSION_MANAGEMENT",
]
Priority = Literal["HIGH", "MEDIUM", "LOW"]


class ItemOut(BaseModel):
    id: uuid.UUID
    rule_code: str | None  # None for a reviewer's own
    finding: str
    action: str
    owner_team: str
    priority: str
    evidence: dict[str, Any]
    status: str  # DRAFT, ACCEPTED, REJECTED, DONE
    due_on: date | None
    reason: str | None
    decided_at: datetime | None
    done_at: datetime | None


class ReviewOut(BaseModel):
    """A review (AAR-01..07): roles, references and counts; who decided is in the audit log."""

    id: uuid.UUID
    reference: str
    incident_id: uuid.UUID
    incident_reference: str
    incident_title: str
    incident_status: str
    status: str  # DRAFT, FINAL
    started_at: datetime
    finalised_at: datetime | None
    label: str  # how the drafts were made (G-6)
    metrics: list[MetricOut]  # live while a draft, frozen once final
    timeline: list[TimelineEntryOut]
    items: list[ItemOut]
    can_act: bool  # start, decide, add, mark done (§5)
    can_finalise: bool
    simulated: bool = True


class ReviewSummaryOut(BaseModel):
    id: uuid.UUID
    reference: str
    incident_reference: str
    incident_title: str
    status: str
    started_at: datetime
    accepted: int  # ACCEPTED or DONE
    drafts: int
    items: int


class ReadyOut(BaseModel):
    """An incident at MONITORING or CLOSED with no review yet."""

    incident_id: uuid.UUID
    reference: str
    title: str
    status: str
    can_start: bool


class ReviewsOut(BaseModel):
    reviews: list[ReviewSummaryOut]
    ready: list[ReadyOut]


class StartIn(BaseModel):
    incident_id: uuid.UUID


class AcceptIn(BaseModel):
    owner_team: Team
    due_on: date
    finding: str | None = Field(default=None, min_length=1, max_length=500)  # a reword
    action: str | None = Field(default=None, min_length=1, max_length=500)
    priority: Priority | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ItemIn(BaseModel):
    """A reviewer's own lesson and action, accepted when added."""

    finding: str = Field(min_length=1, max_length=500)
    action: str = Field(min_length=1, max_length=500)
    owner_team: Team
    priority: Priority
    due_on: date
