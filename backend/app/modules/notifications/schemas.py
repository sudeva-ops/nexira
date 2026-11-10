import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CampaignOut(BaseModel):
    id: uuid.UUID
    reference: str
    incident_id: uuid.UUID | None
    exercise: bool = False  # EXR-03: its incident is an exercise's (D-48)
    campaign_type: str  # ALERT, CHECKIN, ADVISORY, TEST
    message: str
    translations: dict[str, str]  # D-15
    channels: list[str]
    audience_filter: dict[str, Any]
    status: str  # DRAFT, PENDING_APPROVAL, SENDING, SENT, CANCELLED
    created_by_type: str
    created_by: str | None
    created_by_name: str | None  # for USER campaigns
    template_id: uuid.UUID | None
    submitted_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_by_name: str | None
    approved_at: datetime | None
    rejection_reason: str | None  # the last rejection; kept as history (D-31)
    created_at: datetime
    sent_at: datetime | None
    escalate_after_s: int
    recipients: int
    deliveries: dict[str, int]  # by status: QUEUED, SENT, DELIVERED, READ, FAILED
    funnel: dict[str, dict[str, int]]  # MN-04: per channel, by status
    simulated: bool  # D-19: Phase 1 channels are simulated


class ComposeIn(BaseModel):
    """A draft (MN-01). Author fields are never accepted: extra fields are refused."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="ALERT, ADVISORY or CHECKIN")
    message: str = Field(max_length=2000)
    channels: list[str] = Field(min_length=1, max_length=5)
    missions: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    person_types: list[str] | None = Field(default=None, max_length=6)
    exposed_to_incident: bool = False
    incident_id: uuid.UUID | None = None
    translations: dict[str, str] = Field(default_factory=dict, max_length=3)
    template_id: uuid.UUID | None = None


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class PreviewOut(BaseModel):
    recipients: int
    by_person_type: dict[str, int]
    by_mission: dict[str, int]


class TemplateOut(BaseModel):
    id: uuid.UUID
    code: str
    kind: str
    mission_id: uuid.UUID | None
    name: str
    texts: dict[str, str]
    reviewed: dict[str, bool]
    is_active: bool


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    kind: str
    mission_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    texts: dict[str, str] = Field(max_length=4)


class TemplatePatch(BaseModel):
    """Changing a text clears its reviewed flag; reviewed can be set only by a reviewer."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    texts: dict[str, str] | None = Field(default=None, max_length=4)
    reviewed: dict[str, bool] | None = Field(default=None, max_length=3)
    is_active: bool | None = None
