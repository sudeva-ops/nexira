import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StepOut(BaseModel):
    id: uuid.UUID
    seq: int
    name: str
    action_type: str
    requires_approval_role: str | None


class PlaybookOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    version: int
    trigger_rules: dict[str, Any]
    steps: list[StepOut]


class RunStepOut(StepOut):
    status: str  # PENDING, RUNNING, AWAITING_APPROVAL, DONE, SKIPPED, FAILED
    started_at: datetime | None
    completed_at: datetime | None
    approved_by: uuid.UUID | None
    approved_by_name: str | None
    result: dict[str, Any]


class RunOut(BaseModel):
    id: uuid.UUID
    playbook_code: str
    playbook_name: str
    incident_id: uuid.UUID | None
    incident_reference: str | None
    status: str  # RUNNING, AWAITING_APPROVAL, COMPLETED, CANCELLED, FAILED
    started_by_type: str
    started_by_name: str | None
    proposal_id: uuid.UUID | None
    started_at: datetime
    completed_at: datetime | None
    steps: list[RunStepOut]


class StartRunIn(BaseModel):
    playbook_code: str
    incident_id: uuid.UUID


class PermissionsOut(BaseModel):
    """Plan G-07: what the caller may do on an entity, from approvals.can_decide()."""

    entity_type: str
    entity_id: str
    approve_step: list[uuid.UUID] = []  # playbook_run: steps the caller may approve
    decide_proposal: bool = False  # agent_proposal: may decide its next step
