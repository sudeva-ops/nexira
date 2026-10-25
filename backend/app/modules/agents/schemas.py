import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApprovalStepOut(BaseModel):
    step_no: int
    required_role: str
    decision: str | None
    decided_by: uuid.UUID | None
    decided_by_name: str | None
    decided_at: datetime | None


class ProposalOut(BaseModel):
    id: uuid.UUID
    agent_code: str
    agent_name: str
    incident_id: uuid.UUID | None
    incident_reference: str | None
    proposal_key: str
    action_type: str
    title: str
    proposed_action: str
    action_payload: dict[str, Any]
    evidence: list[dict[str, Any]]
    alternatives: list[dict[str, Any]]
    risk_if_no_action: str | None
    confidence: int | None
    is_proactive: bool
    effective_level: int  # set by the database (D-12)
    status: str
    superseded_by: uuid.UUID | None
    edited_action: str | None
    edited_payload: dict[str, Any] | None
    rejection_reason: str | None
    deadline_at: datetime | None
    undo_until: datetime | None
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None
    approvals: list[ApprovalStepOut]
    can_decide: bool  # the caller may decide the next step now (approvals.can_decide)


class EditApproveIn(BaseModel):
    edited_action: str | None = Field(default=None, max_length=2000)
    edited_payload: dict[str, Any] | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AlternativeIn(BaseModel):
    index: int = Field(ge=0)


class AgentOut(BaseModel):
    code: str
    name: str
    description: str | None
    autonomy_level: int  # 0 AUTO .. 4 ADVISE_ONLY
    is_enabled: bool
    model_ref: str | None
    proposals_pending: int
    proposals_total: int


class AgentPatch(BaseModel):
    autonomy_level: int | None = Field(default=None, ge=0, le=4)
    is_enabled: bool | None = None


class AgentsStateOut(BaseModel):
    paused: bool
    agents: list[AgentOut]
