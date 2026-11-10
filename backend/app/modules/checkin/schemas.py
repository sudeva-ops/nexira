import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TallyOut(BaseModel):
    recipients: int
    safe: int
    need_help: int
    pending: int
    accounted_pct: float


class SummaryOut(BaseModel):
    campaign_id: uuid.UUID
    reference: str
    incident_id: uuid.UUID | None
    exercise: bool = False  # EXR-03: its incident is an exercise's (D-48)
    status: str
    sent_at: datetime | None
    escalate_after_s: int
    personnel: TallyOut
    citizens: TallyOut


class CheckinPersonOut(BaseModel):
    person_id: uuid.UUID
    full_name: str
    person_type: str
    role_title: str | None
    mission_code: str | None
    status: Literal["SAFE", "NEED_HELP", "PENDING"]
    channel: str | None
    note: str | None
    responded_at: datetime | None
    escalated: bool


class EscalatedOut(BaseModel):
    personnel: list[str]
    citizens: int


class RespondIn(BaseModel):
    person_id: uuid.UUID
    status: Literal["SAFE", "NEED_HELP"]
    channel: Literal["APP", "SMS", "WHATSAPP", "VOICE", "EMAIL"] | None = "APP"
    note: str | None = Field(default=None, max_length=1000)


class ResponseOut(BaseModel):
    id: int
    campaign_id: uuid.UUID
    person_id: uuid.UUID
    status: str
    channel: str | None
    responded_at: datetime
