import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OptionOut(BaseModel):
    role: str  # PRIMARY, BACKUP, CONTINGENCY
    kind: str  # CHARTER, COMMERCIAL, ROAD
    label: str
    seats: int | None
    partner_id: uuid.UUID | None
    partner_name: str | None
    covered: bool  # the partner covers the mission's country


class PlanOut(BaseModel):
    id: uuid.UUID
    reference: str
    mission_id: uuid.UUID
    mission_code: str
    city: str
    muster_name: str
    route_label: str
    destination: str
    options: list[OptionOut]
    source: str
    simulated: bool = True  # D-19


class StepOut(BaseModel):
    step: int
    name: str
    at: str | None  # written by the database


class EntryOut(BaseModel):
    """A manifest entry. name and document_flag are None outside the caller's scope (G-8)."""

    id: uuid.UUID
    category: str
    seat: str | None
    status: str  # EXPECTED, CHECKED_IN
    checked_in_at: datetime | None
    name: str | None
    document_flag: bool | None


class PartnerRequestOut(BaseModel):
    reference: str
    partner_name: str
    service: str
    status: str


class EvacuationOut(BaseModel):
    id: uuid.UUID
    reference: str
    plan_reference: str
    mission_id: uuid.UUID
    incident_id: uuid.UUID | None
    proposal_id: uuid.UUID | None
    status: str
    requested_role: str
    requested_by_name: str | None
    requested_at: datetime
    activated_by_name: str | None
    activated_at: datetime | None
    step: int | None
    steps: list[StepOut]
    stood_down_reason: str | None
    counts: dict[str, int]  # by category
    checked_in: int
    seats: int | None  # on the primary option
    documents_flagged: int
    partner_requests: list[PartnerRequestOut]
    message_reference: str | None
    message_status: str | None
    simulated: bool = True


class EvacuationDetailOut(EvacuationOut):
    manifest: list[EntryOut]
    names_shown: bool


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: uuid.UUID


class AdvanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=3, le=6)


class StandDownIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def option_out(option: dict[str, Any], partners: dict[uuid.UUID, Any], country: str) -> OptionOut:
    partner_id = uuid.UUID(str(option["partner_id"])) if option.get("partner_id") else None
    partner = partners.get(partner_id) if partner_id else None
    return OptionOut(
        role=option["role"],
        kind=option["kind"],
        label=option["label"],
        seats=option.get("seats"),
        partner_id=partner_id,
        partner_name=partner.name if partner else None,
        covered=bool(partner and country in partner.coverage),
    )
