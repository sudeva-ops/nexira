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
    # SCHEDULED (armed, PC-24), RUNNING, AWAITING_APPROVAL, COMPLETED, CANCELLED, FAILED,
    # DISARMED
    status: str
    started_by_type: str
    started_by_name: str | None
    proposal_id: uuid.UUID | None
    started_at: datetime
    completed_at: datetime | None
    scheduled_for: datetime | None = None  # an armed run's start, on the hazard clock (G-9)
    steps: list[RunStepOut]


class StartRunIn(BaseModel):
    playbook_code: str
    incident_id: uuid.UUID


class ArmRunIn(BaseModel):
    """HZ-05: arm a playbook for a cyclone forecast, 36 h before landfall (§43 Q4)."""

    playbook_code: str
    incident_id: uuid.UUID


class PermissionsOut(BaseModel):
    """Plan G-07: what the caller may do on an entity, from approvals.can_decide()."""

    entity_type: str
    entity_id: str
    approve_step: list[uuid.UUID] = []  # playbook_run: steps the caller may approve
    decide_proposal: bool = False  # agent_proposal: may decide its next step
    edit_proposal: bool = False  # agent_proposal: may edit-and-approve
    dismiss_proposal: bool = False  # agent_proposal: may dismiss level-4 advice
    undo_proposal: bool = False  # agent_proposal: may undo a level-1 action
    edit_campaign: bool = False  # notification_campaign: may edit the draft (the author)
    submit_campaign: bool = False  # notification_campaign: may submit or send it
    approve_campaign: bool = False  # notification_campaign: may approve or reject (D-31)
    cancel_campaign: bool = False  # notification_campaign: may cancel it
    edit_trip: bool = False  # trip: the requester may edit the draft
    submit_trip: bool = False  # trip: the requester may submit it
    approve_trip: bool = False  # trip: may approve now (D-32; checklist done if HIGH+)
    reject_trip: bool = False  # trip: may reject it with a reason
    check_trip: bool = False  # trip: may tick checklist items
    cancel_trip: bool = False  # trip: may cancel it
    read_documents: bool = False  # documents: may read the list (DX-09)
    act_documents: bool = False  # documents: may renew and send reminders
    read_document_missions: list[uuid.UUID] | None = None  # None: every mission
    act_document_missions: list[uuid.UUID] | None = None  # None: every mission
    arm_playbook: bool = False  # hazards: may arm a playbook for this incident (HZ-10, G-1)
    start_armed: bool = False  # hazards: may start its armed run now
    disarm: bool = False  # hazards: may disarm it
