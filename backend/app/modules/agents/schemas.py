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
    exercise: bool = False  # EXR-03: its incident is an exercise's (D-48)
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
    # What the caller may do now, from the same checks the actions enforce (plan G-07):
    can_decide: bool  # approve, edit-and-approve, reject, use an alternative
    can_edit: bool  # edit-and-approve: editable type, and the caller decides step 1
    can_dismiss: bool  # reject level-4 advice
    can_undo: bool  # undo a level-1 action inside its window


class EditApproveIn(BaseModel):
    edited_action: str | None = Field(default=None, max_length=2000)
    edited_payload: dict[str, Any] | None = None


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AlternativeIn(BaseModel):
    index: int = Field(ge=0)


class AgentActionOut(BaseModel):
    """One action type an agent proposes, with its policy (D-12, D-16; TA-09)."""

    action_type: str
    level: int  # the policy floor; 4 (advise only) when there is no policy (D-12)
    approver_roles: list[str]  # one entry per step; '|' separates alternatives
    decision_deadline_s: int | None


class AgentOut(BaseModel):
    code: str
    name: str
    description: str | None
    watches: list[str]  # the event types the agent observes
    actions: list[AgentActionOut]  # what it proposes, and who decides
    autonomy_level: int  # 0 AUTO .. 4 ADVISE_ONLY
    is_enabled: bool
    model_ref: str | None
    proposals_pending: int
    proposals_total: int
    accepted_pct: float | None  # approved / (approved + rejected) by people


class ActivityOut(BaseModel):
    """DQ-06 agent activity log: agents and people acting on proposals. People
    are shown as "Human"; no names."""

    occurred_at: datetime
    actor: str  # an agent's name, "Human" or "System"
    action: str
    proposal_id: uuid.UUID | None
    text: str


class AgentPatch(BaseModel):
    autonomy_level: int | None = Field(default=None, ge=0, le=4)
    is_enabled: bool | None = None


class AgentsStateOut(BaseModel):
    paused: bool
    agents: list[AgentOut]
