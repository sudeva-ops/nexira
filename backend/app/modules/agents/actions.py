"""What an approved agent action does (AGT-05). Changes need human sign-off (D-29).

Each Phase 1 action type has a payload schema and an executor. Executors only
call the service functions a logged-in user's request calls: incident notes,
playbooks.start_run, notifications.create_campaign, for the Travel & Air agent
(D-34) the trip audience of create_campaign and trips.cancel_by_agent, for the
Compliance agent (D-37) documents.renew_by_agent, and for arming ahead of a cyclone
landfall (D-38) playbooks.arm_run. Agents never
reach channels, external systems or tables directly (AGENTS.md).

An action type with no entry here can still be proposed: the database makes it
level 4 (advise only) when it has no action_policy row (D-12), and it is never
executed.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.events import Event
from app.modules.documents import service as documents
from app.modules.intel import service as intel
from app.modules.intel.models import Incident
from app.modules.notifications.channels import CHANNELS
from app.modules.notifications.service import CampaignIn, campaign_queued_event, create_campaign
from app.modules.playbooks import service as playbooks
from app.modules.tenancy.service import Actor
from app.modules.travel import trips


class ActionError(Exception):
    """The action cannot run (bad payload, missing incident, a refused service call)."""


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotePayload(_Payload):
    text: str = Field(min_length=1, max_length=4000)


class StartPlaybookPayload(_Payload):
    playbook_code: str = Field(min_length=1)


class ArmPlaybookPayload(_Payload):
    """ARM_PLAYBOOK (D-38, HZ-06): start the playbook by itself 36 h before the forecast
    landfall (§43 Q4); fixed in the pilot, so the approvers read what runs."""

    playbook_code: str = Field(min_length=1)
    hours_before_landfall: Literal[36] = 36
    # The forecast landfall the approvers read; arming is refused if it has moved since
    # (review of Prompt 55, M1). Timezone-aware only (review of Prompt 54, L7).
    landfall_at: AwareDatetime


class MessagePayload(_Payload):
    """SEND_EXTERNAL_MESSAGE: a citizen advisory (D-15: reviewed templates only)."""

    campaign_type: str = "ADVISORY"
    message: str = Field(min_length=1, max_length=2000)
    translations: dict[str, str] = Field(default_factory=dict)
    channels: list[str] = Field(min_length=1)
    audience: dict[str, Any]

    @field_validator("audience")
    @classmethod
    def _incident_audiences(cls, audience: dict[str, Any]) -> dict[str, Any]:
        """The trip and document audiences have their own actions, approvers and scope
        (review of Prompt 50, L1)."""
        if "trip_id" in audience or "document_ids" in audience:
            raise ValueError("an advisory cannot name a trip or documents")
        return audience


class EvacuationPayload(_Payload):
    route: str = Field(min_length=1)
    note: str | None = None


class NotifyTravellersPayload(_Payload):
    """NOTIFY_TRAVELLERS (D-34): a staff alert to one trip's travellers."""

    trip_id: uuid.UUID
    message: str = Field(min_length=1, max_length=2000)
    channels: list[str] = Field(default_factory=lambda: ["APP", "SMS"], min_length=1, max_length=5)

    @field_validator("channels")
    @classmethod
    def _known_once(cls, channels: list[str]) -> list[str]:
        """Refused when proposed, not at execution (review of Prompt 34, L1)."""
        if not set(channels) <= set(CHANNELS) or len(set(channels)) != len(channels):
            raise ValueError(f"channels are each of {', '.join(CHANNELS)} at most once")
        return channels


class CancelTripPayload(_Payload):
    """CANCEL_TRIP (D-34): an approved trip that has not started."""

    trip_id: uuid.UUID


class DocumentRenewalPayload(_Payload):
    """START_DOCUMENT_RENEWAL (D-37): urgent renewal of documents at the incident's
    mission, and one reminder to their holders. The reminder is the fixed text the
    proposal quotes (documents.REMINDER), so it is not in the payload."""

    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


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
    """D-13: undo marks the entry retracted (the history stays), through the intel service."""
    try:
        await intel.retract_note(session, int(result["incident_event_id"]), ctx.agent_actor)
    except LookupError:
        raise ActionError("the note no longer exists") from None


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


async def _arm_playbook(
    session: AsyncSession, payload: ArmPlaybookPayload, ctx: Context
) -> dict[str, Any]:
    if ctx.incident_id is None:
        raise ActionError("ARM_PLAYBOOK needs an incident")
    try:
        # The same service as POST /api/playbook-runs/arm.
        armed = await playbooks.arm_run(
            session,
            playbook_code=payload.playbook_code,
            incident_id=ctx.incident_id,
            actor=ctx.agent_actor,
            started_by=ctx.approved_by,
            started_by_type="AGENT",
            proposal_id=ctx.proposal_id,
            hours_before_landfall=payload.hours_before_landfall,
            expected_landfall=payload.landfall_at,
        )
    except playbooks.RunNotAllowedError as e:
        raise ActionError(str(e)) from None
    run = armed.run
    ctx.events.append(
        playbooks.run_started_event(run) if armed.started_now else playbooks.run_armed_event(run)
    )
    return {
        "run_id": str(run.id),
        "playbook_code": payload.playbook_code,
        "status": run.status,
        "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
        "started_now": armed.started_now,
    }


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


async def _notify_travellers(
    session: AsyncSession, payload: NotifyTravellersPayload, ctx: Context
) -> dict[str, Any]:
    try:
        # The same service as every agent and playbook message; simulated channels only.
        # The trip audience refuses a restricted trip and citizens (plan-pilot-ta G-2).
        campaign, recipients = await create_campaign(
            session,
            incident_id=ctx.incident_id,
            campaign=CampaignIn(
                campaign_type="ALERT",
                message=payload.message,
                channels=payload.channels,
                audience={"trip_id": str(payload.trip_id)},
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


async def _cancel_trip(
    session: AsyncSession, payload: CancelTripPayload, ctx: Context
) -> dict[str, Any]:
    try:
        outcome = await trips.cancel_by_agent(
            session,
            payload.trip_id,
            actor=ctx.agent_actor,
            approved_by=ctx.approved_by,
            proposal_id=ctx.proposal_id,
            home_tz=get_settings().home_tz,
        )
    except trips.TripError as e:
        raise ActionError(str(e)) from None
    ctx.events.extend(outcome.events)
    return {"trip_id": str(outcome.trip.id), "reference": outcome.trip.reference}


async def _start_document_renewal(
    session: AsyncSession, payload: DocumentRenewalPayload, ctx: Context
) -> dict[str, Any]:
    incident = await _incident(session, ctx)
    try:
        # The same step, row update and audit as a person's renewal request, and the same
        # reminders campaign (plan-pilot-dx §4).
        done = await documents.renew_by_agent(
            session,
            payload.document_ids,
            incident_id=incident.id,
            mission_id=incident.mission_id,
            actor=ctx.agent_actor,
            approved_by=ctx.approved_by,
            proposal_id=ctx.proposal_id,
        )
    except documents.DocumentError as e:
        raise ActionError(str(e)) from None
    ctx.events.extend(done.events)
    sent = done.reminders
    return {
        "requested": [str(d) for d in done.requested],
        "skipped": [str(d) for d in done.skipped],  # in renewal or no longer at risk
        "campaign_id": str(sent.campaign.id) if sent else None,
        "reference": sent.campaign.reference if sent else None,
        "recipients": sent.recipients if sent else 0,
    }


ACTIONS: dict[str, Action] = {
    "LOG_INFO": Action(NotePayload, _note, _retract_note),
    "POST_INTERNAL_NOTE": Action(NotePayload, _note, _retract_note),
    "START_PLAYBOOK": Action(StartPlaybookPayload, _start_playbook),
    # Response Planner, natural hazards (D-38). Not undoable: disarming is a person's.
    "ARM_PLAYBOOK": Action(ArmPlaybookPayload, _arm_playbook),
    "SEND_EXTERNAL_MESSAGE": Action(MessagePayload, _send_message),
    # Test only (scene 5, plan G-16): no Phase 1 agent proposes it.
    "START_EVACUATION": Action(EvacuationPayload, _start_evacuation),
    # Travel & Air agent (D-34). ADVISE_REBOOKING has no entry: advice only (level 4).
    "NOTIFY_TRAVELLERS": Action(NotifyTravellersPayload, _notify_travellers),
    "CANCEL_TRIP": Action(CancelTripPayload, _cancel_trip),
    # Compliance agent (D-37). ADVISE_EMERGENCY_DOCUMENTS has no entry: advice only.
    "START_DOCUMENT_RENEWAL": Action(DocumentRenewalPayload, _start_document_renewal),
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


# Action types an approver may edit, and the payload field the edit changes. Others
# (START_PLAYBOOK, ARM_PLAYBOOK, START_EVACUATION, unknown types) cannot be edited: use an
# alternative instead, so what the approvers read is always what runs.
EDITABLE_FIELD = {
    "LOG_INFO": "text",
    "POST_INTERNAL_NOTE": "text",
    "SEND_EXTERNAL_MESSAGE": "message",
}


def editable(action_type: str) -> bool:
    return action_type in EDITABLE_FIELD


def check_edit(action_type: str, original: dict[str, Any], edited: dict[str, Any]) -> None:
    """Plan G-21: an edit must pass the same schema and cannot widen what the
    action reaches. For messages: the same audience, and only channels that were
    already proposed."""
    if not editable(action_type):
        raise ActionError(f"a {action_type} proposal cannot be edited; use an alternative")
    validate(action_type, edited)
    if action_type == "SEND_EXTERNAL_MESSAGE":
        if edited.get("audience") != original.get("audience"):
            raise ActionError("an edit cannot change the audience")
        if edited.get("campaign_type", "ADVISORY") != original.get("campaign_type", "ADVISORY"):
            raise ActionError("an edit cannot change the campaign type")
        if not set(edited.get("channels", [])) <= set(original.get("channels", [])):
            raise ActionError("an edit cannot add channels")
        if not set(edited.get("channels", [])) <= set(CHANNELS):
            raise ActionError("unknown channel")
        # D-15: translations are reviewed templates. An edit may drop a language,
        # never change or add one. The English text may be reworded by the approver.
        original_translations = original.get("translations") or {}
        for lang, text in (edited.get("translations") or {}).items():
            if original_translations.get(lang) != text:
                raise ActionError("an edit cannot change or add reviewed translations (D-15)")
    if action_type in ("START_PLAYBOOK", "START_EVACUATION") and edited != original:
        raise ActionError(f"a {action_type} proposal cannot be edited; use an alternative")


async def execute(
    session: AsyncSession, action_type: str, payload: dict[str, Any], ctx: Context
) -> dict[str, Any]:
    action = ACTIONS.get(action_type)
    if action is None:
        raise ActionError(f"{action_type} is advise-only")
    model = action.payload.model_validate(payload)
    return await action.execute(session, model, ctx)


def can_undo(action_type: str) -> bool:
    action = ACTIONS.get(action_type)
    return action is not None and action.undo is not None


async def undo(
    session: AsyncSession, action_type: str, result: dict[str, Any], ctx: Context
) -> None:
    action = ACTIONS.get(action_type)
    if action is None or action.undo is None:
        raise ActionError(f"{action_type} cannot be undone")
    await action.undo(session, result, ctx)
