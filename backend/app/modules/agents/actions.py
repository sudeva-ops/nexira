"""What an approved agent action does (AGT-05). Changes need human sign-off (D-29).

Each Phase 1 action type has a payload schema and an executor. Executors only
call the service functions a logged-in user's request calls: incident notes,
playbooks.start_run, notifications.create_campaign. Agents never reach channels,
external systems or tables directly (AGENTS.md).

An action type with no entry here can still be proposed: the database makes it
level 4 (advise only) when it has no action_policy row (D-12), and it is never
executed.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.intel import service as intel
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.notifications.channels import CHANNELS
from app.modules.notifications.service import CampaignIn, campaign_queued_event, create_campaign
from app.modules.playbooks import service as playbooks
from app.modules.tenancy.service import Actor


class ActionError(Exception):
    """The action cannot run (bad payload, missing incident, a refused service call)."""


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotePayload(_Payload):
    text: str = Field(min_length=1, max_length=4000)


class StartPlaybookPayload(_Payload):
    playbook_code: str = Field(min_length=1)


class MessagePayload(_Payload):
    """SEND_EXTERNAL_MESSAGE: a citizen advisory (D-15: reviewed templates only)."""

    campaign_type: str = "ADVISORY"
    message: str = Field(min_length=1, max_length=2000)
    translations: dict[str, str] = Field(default_factory=dict)
    channels: list[str] = Field(min_length=1)
    audience: dict[str, Any]


class EvacuationPayload(_Payload):
    route: str = Field(min_length=1)
    note: str | None = None


@dataclass
class Context:
    """Who the action runs for. The agent is the actor; for approved proposals the
    last approver is recorded as the person who let it run."""

    proposal_id: uuid.UUID
    incident_id: uuid.UUID | None
    agent_actor: Actor
    approved_by: uuid.UUID | None
    events: list[Event] = field(default_factory=list)  # published after commit


Executor = Callable[[AsyncSession, Any, Context], Awaitable[dict[str, Any]]]
Undo = Callable[[AsyncSession, dict[str, Any], Context], Awaitable[None]]


async def _incident(session: AsyncSession, ctx: Context) -> Incident:
    if ctx.incident_id is None:
        raise ActionError("this action needs an incident")
    incident = await session.get(Incident, ctx.incident_id)
    if incident is None:
        raise ActionError("incident not found")
    return incident


async def _note(session: AsyncSession, payload: NotePayload, ctx: Context) -> dict[str, Any]:
    # The same service as POST /api/incidents/{id}/notes.
    event = await intel.add_note(
        session, await _incident(session, ctx), payload.text, ctx.agent_actor
    )
    return {"incident_event_id": event.id}


async def _retract_note(session: AsyncSession, result: dict[str, Any], ctx: Context) -> None:
    """D-13: undo marks the entry retracted (the history stays)."""
    event = await session.get(IncidentEvent, int(result["incident_event_id"]))
    if event is None:
        raise ActionError("the note no longer exists")
    event.data = {**event.data, "retracted": True}
    event.summary = f"[Retracted] {event.summary}"
    await session.flush()


async def _start_playbook(
    session: AsyncSession, payload: StartPlaybookPayload, ctx: Context
) -> dict[str, Any]:
    if ctx.incident_id is None:
        raise ActionError("START_PLAYBOOK needs an incident")
    try:
        # The same service as POST /api/playbook-runs.
        run = await playbooks.start_run(
            session,
            playbook_code=payload.playbook_code,
            incident_id=ctx.incident_id,
            actor=ctx.agent_actor,
            started_by=ctx.approved_by,
            started_by_type="AGENT",
            proposal_id=ctx.proposal_id,
        )
    except playbooks.RunNotAllowedError as e:
        raise ActionError(str(e)) from None
    ctx.events.append(playbooks.run_started_event(run))
    return {"run_id": str(run.id), "playbook_code": payload.playbook_code}


async def _send_message(
    session: AsyncSession, payload: MessagePayload, ctx: Context
) -> dict[str, Any]:
    if ctx.incident_id is None:
        raise ActionError("SEND_EXTERNAL_MESSAGE needs an incident")
    try:
        # The same service the playbook engine and users use; simulated channels only.
        campaign, recipients = await create_campaign(
            session,
            incident_id=ctx.incident_id,
            campaign=CampaignIn(
                campaign_type=payload.campaign_type,
                message=payload.message,
                channels=payload.channels,
                audience=payload.audience,
                translations=payload.translations,
            ),
            created_by_type="AGENT",
            created_by=str(ctx.proposal_id),
            actor=ctx.agent_actor,
        )
    except ValueError as e:
        raise ActionError(str(e)) from None
    ctx.events.append(campaign_queued_event(campaign))
    return {
        "campaign_id": str(campaign.id),
        "reference": campaign.reference,
        "recipients": recipients,
    }


async def _start_evacuation(
    session: AsyncSession, payload: EvacuationPayload, ctx: Context
) -> dict[str, Any]:
    """Phase 1 stub: writes an incident event only. No movement order is sent."""
    incident = await _incident(session, ctx)
    text = f"Evacuation ordered via {payload.route} (Phase 1 stub: no message sent)."
    if payload.note:
        text += f" {payload.note}"
    event = await intel.add_note(session, incident, text, ctx.agent_actor)
    return {"incident_event_id": event.id, "route": payload.route, "stub": True}


@dataclass(frozen=True)
class Action:
    payload: type[_Payload]
    execute: Executor
    undo: Undo | None = None


ACTIONS: dict[str, Action] = {
    "LOG_INFO": Action(NotePayload, _note, _retract_note),
    "POST_INTERNAL_NOTE": Action(NotePayload, _note, _retract_note),
    "START_PLAYBOOK": Action(StartPlaybookPayload, _start_playbook),
    "SEND_EXTERNAL_MESSAGE": Action(MessagePayload, _send_message),
    # Test only (scene 5, plan G-16): no Phase 1 agent proposes it.
    "START_EVACUATION": Action(EvacuationPayload, _start_evacuation),
}


def validate(action_type: str, payload: dict[str, Any]) -> _Payload | None:
    """Check a payload against its action type. None for unknown (advise-only) types."""
    action = ACTIONS.get(action_type)
    if action is None:
        return None
    try:
        return action.payload.model_validate(payload)
    except ValidationError as e:
        raise ActionError(f"invalid {action_type} payload: {e.error_count()} errors") from None


def check_edit(action_type: str, original: dict[str, Any], edited: dict[str, Any]) -> None:
    """Plan G-21: an edit must pass the same schema and cannot widen what the
    action reaches. For messages: the same audience, and only channels that were
    already proposed."""
    validate(action_type, edited)
    if action_type == "SEND_EXTERNAL_MESSAGE":
        if edited.get("audience") != original.get("audience"):
            raise ActionError("an edit cannot change the audience")
        if not set(edited.get("channels", [])) <= set(original.get("channels", [])):
            raise ActionError("an edit cannot add channels")
        if not set(edited.get("channels", [])) <= set(CHANNELS):
            raise ActionError("unknown channel")
    if action_type == "START_PLAYBOOK" and edited != original:
        raise ActionError("a START_PLAYBOOK proposal cannot be edited; use an alternative")


async def execute(
    session: AsyncSession, action_type: str, payload: dict[str, Any], ctx: Context
) -> dict[str, Any]:
    action = ACTIONS.get(action_type)
    if action is None:
        raise ActionError(f"{action_type} is advise-only")
    model = action.payload.model_validate(payload)
    return await action.execute(session, model, ctx)


async def undo(
    session: AsyncSession, action_type: str, result: dict[str, Any], ctx: Context
) -> None:
    action = ACTIONS.get(action_type)
    if action is None or action.undo is None:
        raise ActionError(f"{action_type} cannot be undone")
    await action.undo(session, result, ctx)
