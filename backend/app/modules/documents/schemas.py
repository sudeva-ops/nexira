import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentOut(BaseModel):
    """A row of the register (DX-01..04). Simulated (D-19); never a document number."""

    id: uuid.UUID
    person_id: uuid.UUID
    holder_name: str
    holder_type: str
    mission_id: uuid.UUID | None
    mission_code: str | None
    doc_type: str
    issuing_country: str
    valid_until: date
    days_left: int
    urgency: str  # EXPIRED, CRITICAL, HIGH, MODERATE, OK
    holder_ready: bool
    could_block_evacuation: bool
    renewal_status: str
    renewal_requested_by: str | None
    renewal_requested_at: datetime | None
    renewal_started_by: str | None
    renewal_started_at: datetime | None
    renewed_by: str | None
    renewed_at: datetime | None
    can_act: bool  # the caller may renew it and send a reminder
    simulated: bool = True


class MissionReadinessOut(BaseModel):
    mission_id: uuid.UUID
    code: str
    people: int
    ready: int
    ready_pct: float | None


class SummaryOut(BaseModel):
    """DX-08 KPIs: counts only, no names (DX-09)."""

    tracked: int
    expiring_30: int
    expiring_90: int
    in_renewal_90: int
    could_block: int
    people: int
    ready: int
    ready_pct: float | None
    missions: list[MissionReadinessOut]
    simulated: bool = True


class RenewalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: Literal["REQUESTED", "IN_PROGRESS", "RENEWED"]
    valid_until: date | None = None


class RemindersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class RemindersOut(BaseModel):
    campaign_id: uuid.UUID
    reference: str
    recipients: int
    documents: int
