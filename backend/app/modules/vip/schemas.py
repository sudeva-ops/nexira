import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AccessOut(BaseModel):
    """Whether the caller may see visits at all (VIP-06): the screen and its nav entry."""

    visible: bool


class ReasonOut(BaseModel):
    """One reason for a segment's risk (VIP-02), with the incident it comes from."""

    level: str  # MODERATE or HIGH
    text: str  # "civil unrest 1.2 km away · INC-2026-1043", "600 attendees", ...
    incident_id: uuid.UUID | None = None
    incident_reference: str | None = None


class ChangeOut(BaseModel):
    """A programme change (VIP-05). CLOSED: still pending when the visit became final
    (review of Prompt 78, L4); nobody can decide it any more."""

    id: uuid.UUID
    segment_id: uuid.UUID
    new_starts_at: datetime | None
    new_ends_at: datetime | None
    make_virtual: bool
    reason: str
    proposed_by_name: str
    proposed_at: datetime
    status: str  # PENDING, APPROVED, REJECTED, CLOSED
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None


class SegmentOut(BaseModel):
    id: uuid.UUID
    seq: int
    kind: str
    title: str
    venue_name: str
    starts_at: datetime
    ends_at: datetime | None
    attendees: int | None
    virtual: bool
    status: str  # PLANNED, IN_PROGRESS, COMPLETED
    risk: str  # LOW, MODERATE, HIGH (VIP-02), worked out on this read
    reasons: list[ReasonOut]
    recommendation: str | None  # only for a HIGH segment still planned
    pending_change: ChangeOut | None


class VehicleOut(BaseModel):
    """A vehicle of the detail, with its live Fleet state (plan §4)."""

    code: str
    type_label: str | None
    armoured: bool
    state: str  # the Fleet state; UNKNOWN if the code is not in the register
    available: bool


class MedicalOut(BaseModel):
    facility_name: str | None  # the nearest of the mission not marked Avoid (HL-04)
    facility_distance_m: int | None
    partner_name: str | None  # the active MEDICAL partner covering the country


class DetailOut(BaseModel):
    """Labels and counts only, never names (§63 Q3)."""

    team_lead: str | None
    advance_team: str | None
    team_size: int | None
    medic: bool
    vehicles: list[VehicleOut]
    medical: MedicalOut
    safe_havens: list[str]


class ChecklistItemOut(BaseModel):
    id: uuid.UUID
    label: str
    due_on: date
    done: bool
    done_at: datetime | None
    done_by_name: str | None
    overdue: bool


class KpisOut(BaseModel):
    segments: int
    high: int
    team_size: int | None
    vehicles: int
    medics: int
    venues: int  # distinct venues of segments that are not virtual (plan G-2)
    venues_surveyed: int  # those venues without an open "<venue> venue survey" item


class VisitSummaryOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    mission_id: uuid.UUID
    mission_code: str
    starts_on: date
    ends_on: date
    status: str
    risk: str
    simulated: bool = True  # D-19


class VisitOut(VisitSummaryOut):
    principal_role: str
    trip_id: uuid.UUID | None
    trip_reference: str | None
    country_risk: str | None
    started_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    segments: list[SegmentOut]
    changes: list[ChangeOut]  # every change, newest first
    detail: DetailOut
    checklist: list[ChecklistItemOut]
    kpis: KpisOut
    source: str


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class ChangeIn(BaseModel):
    """A new start (and optionally end), or a virtual alternative, with a reason."""

    model_config = ConfigDict(extra="forbid")

    new_starts_at: datetime | None = None
    new_ends_at: datetime | None = None
    make_virtual: bool = False
    reason: str = Field(min_length=1, max_length=500)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, min_length=1, max_length=500)
