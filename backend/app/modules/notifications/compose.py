"""Mass Notification composer (MN-01..10, MN-12; D-31, Prompt 20).

A user writes a campaign as a DRAFT; nothing is queued until it is sent. Sending goes
through the same outbox as playbook and agent campaigns (service.queue_deliveries):
there is no second sending path, and the dispatcher only sends SENDING campaigns.

- Recipients are resolved from the audience. If any recipient is a citizen, the
  campaign needs a second person: submit puts it in PENDING_APPROVAL, and a different
  user holding DUTY_OFFICER|CONSULAR_OFFICER approves it through approvals.decide().
  Submitting is the first step, so the author and the submitter are listed as
  deciders of another step (plan G-2). Otherwise the author sends it on submit, if
  they hold DUTY_OFFICER|SECURITY_OFFICER.
- Mission scope (plan G-3): the incident's mission; else the single audience mission;
  else none (HQ-level holders only, D-06).
- created_by, created_by_type and submitted_by are set here only, never from a
  request. The database backs every rule (PC-08, PC-10, PC-11, PC-12): content frozen
  once submitted, forward-only status, approval only with SENDING.
- In a pilot (APP_ENV=pilot), a campaign cannot be sent with a translation that is not
  the template's reviewed text, unchanged (MN-06, plan G-11).
- Every action is audited (MN-12).
- The approver approves the audience as defined (missions, person types, or the people
  exposed to an incident), not a fixed list: recipients are resolved again when the
  approval sends it, so someone who joins the audience before then is included.
"""

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.intel.models import Incident
from app.modules.notifications import service, templates
from app.modules.notifications.channels import CHANNELS
from app.modules.notifications.models import MessageTemplate, NotificationCampaign
from app.modules.people.models import Mission
from app.modules.tenancy.service import Actor

KINDS = ("ALERT", "ADVISORY", "CHECKIN")
PERSON_TYPES = ("DIPLOMAT", "LOCAL_STAFF", "DELEGATE", "DEPENDANT", "CONTRACTOR", "CITIZEN")
TRANSLATIONS = ("ar", "fr", "sw")  # D-15: pre-written languages
TEXT_MAX = 2000
REASON_MAX = 500
SMS_SEGMENT = 160

COMPOSERS = "DUTY_OFFICER|SECURITY_OFFICER|CONSULAR_OFFICER|ADMIN"
STAFF_SENDERS = "DUTY_OFFICER|SECURITY_OFFICER"  # send a staff-only campaign themselves
APPROVERS = "DUTY_OFFICER|CONSULAR_OFFICER"  # the second person for citizens (D-31)


class CampaignError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Content:
    """What a draft says and to whom: everything a user may write (no author fields)."""

    kind: str
    message: str
    channels: list[str]
    missions: list[uuid.UUID] = field(default_factory=list)
    person_types: list[str] | None = None
    exposed_to_incident: bool = False
    incident_id: uuid.UUID | None = None
    translations: dict[str, str] = field(default_factory=dict)
    template_id: uuid.UUID | None = None
    # The people on an evacuation's manifest (D-40); set by Evacuation Management only.
    evacuation_id: uuid.UUID | None = None


@dataclass
class Outcome:
    campaign: NotificationCampaign
    events: list[Event]


def _actor(user: CurrentUser) -> Actor:
    return Actor(type="USER", id=str(user.id))


def _event(campaign: NotificationCampaign, kind: str = "CAMPAIGN_UPDATED") -> Event:
    return Event(
        type=kind,
        tenant_id=campaign.tenant_id,
        payload={
            "campaign_id": str(campaign.id),
            "reference": campaign.reference,
            "status": campaign.status,
            "incident_id": str(campaign.incident_id) if campaign.incident_id else None,
        },
        source="notifications.compose",
    )


async def _audit(
    session: AsyncSession,
    user: CurrentUser,
    action: str,
    campaign: NotificationCampaign,
    details: dict[str, Any] | None = None,
) -> None:
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action=f"CAMPAIGN.{action}",
        entity_type="notification_campaign",
        entity_id=campaign.reference,
        details=details or {},
    )


# --- validation ---------------------------------------------------------------------


async def _validate(session: AsyncSession, content: Content) -> dict[str, Any]:
    """Check content against the tenant's own rows (RLS) and return the audience spec.
    Never trusts an id: missions, incident and template are read through the session."""
    if content.kind not in KINDS:
        raise CampaignError(422, f"unknown kind {content.kind}")
    if not content.message.strip() or len(content.message) > TEXT_MAX:
        raise CampaignError(422, f"the message must be 1 to {TEXT_MAX} characters")
    if not content.channels or not set(content.channels) <= set(CHANNELS):
        raise CampaignError(422, f"channels must be among {', '.join(CHANNELS)}")
    if len(set(content.channels)) != len(content.channels):
        raise CampaignError(422, "each channel once")
    for lang, translated in content.translations.items():
        if lang not in TRANSLATIONS:
            raise CampaignError(422, f"translations are {', '.join(TRANSLATIONS)} only")
        if not translated.strip() or len(translated) > TEXT_MAX:
            raise CampaignError(422, f"the {lang} text must be 1 to {TEXT_MAX} characters")
    if content.person_types is not None and (
        not content.person_types or not set(content.person_types) <= set(PERSON_TYPES)
    ):
        raise CampaignError(422, f"person types must be among {', '.join(PERSON_TYPES)}")
    if content.incident_id is not None and await session.get(Incident, content.incident_id) is None:
        raise CampaignError(422, "unknown incident")
    if content.template_id is not None:
        template = await session.get(MessageTemplate, content.template_id)
        if template is None or not template.is_active:
            raise CampaignError(422, "unknown template")
    if content.evacuation_id is not None:
        if content.exposed_to_incident or content.missions or content.person_types is not None:
            raise CampaignError(422, "an evacuation message goes to its manifest only")
        found = await session.scalar(
            text("SELECT id FROM evacuation WHERE id = :e"), {"e": content.evacuation_id}
        )
        if found is None:
            raise CampaignError(422, "unknown evacuation")
        return {"evacuation_id": str(content.evacuation_id)}
    if content.exposed_to_incident == bool(content.missions):
        raise CampaignError(422, "choose either missions or the people exposed to an incident")
    if content.exposed_to_incident:
        if content.incident_id is None:
            raise CampaignError(422, "the exposed audience needs an incident")
        spec: dict[str, Any] = {"exposed": True}
    else:
        found = set(
            await session.scalars(select(Mission.id).where(Mission.id.in_(content.missions)))
        )
        if found != set(content.missions):
            raise CampaignError(422, "unknown mission")
        spec = {"missions": sorted(str(m) for m in content.missions)}
    if content.person_types is not None:
        spec["person_types"] = sorted(content.person_types)
    return spec


async def _mission(session: AsyncSession, campaign: NotificationCampaign) -> uuid.UUID | None:
    """The approval and sending scope (plan G-3), from who receives the message: the
    incident's mission for the people exposed to it; the single mission of a missions
    audience; otherwise none (HQ only, D-06). An incident attached to a missions
    audience does not change the scope (review of Prompt 20, finding 1)."""
    if campaign.audience_filter.get("exposed"):
        mission: uuid.UUID | None = await session.scalar(
            select(Incident.mission_id)
            .where(Incident.id == campaign.incident_id)
            .with_for_update(read=True)  # exposure cannot move it mid-decision
        )
        return mission
    if campaign.audience_filter.get("evacuation_id"):
        evacuated: uuid.UUID | None = await session.scalar(
            text("SELECT mission_id FROM evacuation WHERE id = CAST(:e AS uuid)"),
            {"e": campaign.audience_filter["evacuation_id"]},
        )
        return evacuated
    missions = campaign.audience_filter.get("missions") or []
    return uuid.UUID(missions[0]) if len(missions) == 1 else None


async def _locked(session: AsyncSession, campaign_id: uuid.UUID) -> NotificationCampaign:
    campaign = await session.scalar(
        select(NotificationCampaign).where(NotificationCampaign.id == campaign_id).with_for_update()
    )
    if campaign is None:
        raise CampaignError(404, "Campaign not found")
    return campaign


def _is_author(user: CurrentUser, campaign: NotificationCampaign) -> bool:
    return campaign.created_by_type == "USER" and campaign.created_by == str(user.id)


async def _author_composing(
    session: AsyncSession, user: CurrentUser, campaign: NotificationCampaign, doing: str
) -> None:
    """The author, still holding a composer role (review of Prompt 20, finding 4)."""
    if not _is_author(user, campaign):
        raise CampaignError(403, f"Only the author {doing}")
    if not await approvals.user_has_role(session, user, COMPOSERS):
        raise CampaignError(
            403, "Composing needs DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER or ADMIN"
        )


# --- drafts ---------------------------------------------------------------------------


async def create_draft(
    session: AsyncSession, user: CurrentUser, content: Content
) -> NotificationCampaign:
    if not await approvals.user_has_role(session, user, COMPOSERS):
        raise CampaignError(
            403, "Composing needs DUTY_OFFICER, SECURITY_OFFICER, CONSULAR_OFFICER or ADMIN"
        )
    spec = await _validate(session, content)
    reference = await session.scalar(text("SELECT next_reference('NTF', false)"))
    campaign = NotificationCampaign(
        tenant_id=session.info["tenant_id"],
        reference=reference,
        incident_id=content.incident_id,
        campaign_type=content.kind,
        message=content.message,
        translations=content.translations,
        channels=content.channels,
        audience_filter=spec,
        created_by_type="USER",
        created_by=str(user.id),  # from the token's user, never from the request
        status="DRAFT",
        template_id=content.template_id,
    )
    session.add(campaign)
    await session.flush()
    await _audit(session, user, "DRAFT", campaign, {"kind": content.kind, "audience": spec})
    return campaign


async def prepare_for_approval(
    session: AsyncSession,
    content: Content,
    *,
    proposal_id: uuid.UUID,
    submitted_by: uuid.UUID,
    actor: Actor,
) -> Outcome:
    """An approved agent proposal's campaign, waiting for a second person (D-31; plan-
    pilot-hl G-2): the agent is the author, the proposal's approver submitted it, and the
    gate lets neither decide. Nothing is queued until someone else approves it."""
    return await _prepared(session, content, "AGENT", str(proposal_id), submitted_by, actor)


async def prepare_for_second_person(
    session: AsyncSession,
    content: Content,
    *,
    author: uuid.UUID,
    submitted_by: uuid.UUID,
    actor: Actor,
) -> Outcome:
    """A campaign two people have already decided on (an evacuation's requester and its
    activator, D-40, plan-pilot-ev §7), waiting for a third: the gate lets neither the
    author nor the submitter approve it (D-31). Nothing is queued until then."""
    return await _prepared(session, content, "USER", str(author), submitted_by, actor)


async def _prepared(
    session: AsyncSession,
    content: Content,
    created_by_type: str,
    created_by: str,
    submitted_by: uuid.UUID,
    actor: Actor,
) -> Outcome:
    spec = await _validate(session, content)
    reference = await session.scalar(text("SELECT next_reference('NTF', false)"))
    campaign = NotificationCampaign(
        tenant_id=session.info["tenant_id"],
        reference=reference,
        incident_id=content.incident_id,
        campaign_type=content.kind,
        message=content.message,
        translations=content.translations,
        channels=content.channels,
        audience_filter=spec,
        created_by_type=created_by_type,
        created_by=created_by,
        status="PENDING_APPROVAL",
        submitted_by=submitted_by,
        template_id=content.template_id,
    )
    session.add(campaign)
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="CAMPAIGN.PREPARE",
        entity_type="notification_campaign",
        entity_id=campaign.reference,
        details={"kind": content.kind, "audience": spec, "submitted_by": str(submitted_by)},
    )
    return Outcome(campaign, [_event(campaign)])


async def update_draft(
    session: AsyncSession, user: CurrentUser, campaign_id: uuid.UUID, content: Content
) -> NotificationCampaign:
    campaign = await _locked(session, campaign_id)
    await _author_composing(session, user, campaign, "edits a draft")
    if campaign.status != "DRAFT":
        raise CampaignError(
            409, f"{campaign.reference} is {campaign.status}: only a draft can be edited"
        )
    spec = await _validate(session, content)
    campaign.campaign_type = content.kind
    campaign.message = content.message
    campaign.translations = content.translations
    campaign.channels = content.channels
    campaign.audience_filter = spec
    campaign.incident_id = content.incident_id
    campaign.template_id = content.template_id
    await session.flush()
    await _audit(session, user, "EDIT", campaign, {"kind": content.kind, "audience": spec})
    return campaign


# --- preview and test send --------------------------------------------------------------


@dataclass(frozen=True)
class Preview:
    recipients: int
    by_person_type: dict[str, int]
    by_mission: dict[str, int]


async def preview(session: AsyncSession, campaign: NotificationCampaign) -> Preview:
    """MN-02: who the audience selects now. No side effects."""
    people = await service.resolve_audience(session, campaign.incident_id, campaign.audience_filter)
    rows = (
        await session.execute(
            text(
                """
                SELECT p.person_type, coalesce(m.code, '-') AS mission, count(*) AS n
                  FROM person p LEFT JOIN mission m ON m.id = p.mission_id
                 WHERE p.id = ANY(CAST(:ids AS uuid[]))
                 GROUP BY 1, 2
                """
            ),
            {"ids": [str(p) for p in people]},
        )
    ).all()
    by_type: dict[str, int] = {}
    by_mission: dict[str, int] = {}
    for person_type, mission, n in rows:
        by_type[person_type] = by_type.get(person_type, 0) + n
        by_mission[mission] = by_mission.get(mission, 0) + n
    return Preview(len(people), by_type, by_mission)


def render(campaign: NotificationCampaign) -> dict[str, dict[str, Any]]:
    """MN-08: what each chosen channel would show (simulated channels, D-19)."""
    title = {"ALERT": "Alert", "ADVISORY": "Advisory", "CHECKIN": "Safety check-in"}[
        campaign.campaign_type
    ]
    body = campaign.message
    shown: dict[str, dict[str, Any]] = {
        "APP": {"title": title, "body": body},
        "SMS": {"text": body, "sms_segments": max(1, math.ceil(len(body) / SMS_SEGMENT))},
        "WHATSAPP": {"text": body},
        "EMAIL": {"subject": f"{title} · {campaign.reference}", "body": body},
        "VOICE": {"script": body},
    }
    return {channel: shown[channel] for channel in campaign.channels}


async def test_send(
    session: AsyncSession, user: CurrentUser, campaign_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    """Send to self: a preview per channel, audited, with no deliveries (plan G-7)."""
    campaign = await _locked(session, campaign_id)
    await _author_composing(session, user, campaign, "sends a test to themselves")
    shown = render(campaign)
    await _audit(session, user, "TEST_SEND", campaign, {"channels": list(shown)})
    return shown


# --- submit, approve, reject, cancel ------------------------------------------------------


async def _has_citizens(session: AsyncSession, people: list[uuid.UUID]) -> bool:
    """From the people actually selected, not from the requested types."""
    found = await session.scalar(
        text(
            "SELECT 1 FROM person WHERE id = ANY(CAST(:ids AS uuid[])) "
            "AND person_type = 'CITIZEN' LIMIT 1"
        ),
        {"ids": [str(p) for p in people]},
    )
    return found is not None


async def _check_translations(
    session: AsyncSession, campaign: NotificationCampaign, app_env: str
) -> None:
    """MN-06 in a pilot: each translation must be its template's reviewed text, unchanged."""
    if app_env != "pilot" or not campaign.translations:
        return
    expected: templates.Resolved | None = None
    if campaign.template_id is not None:
        template = await session.get(MessageTemplate, campaign.template_id)
        if template is not None:
            expected = await templates.resolve(
                session, template.code, await _mission(session, campaign)
            )
    for lang, translated in sorted(campaign.translations.items()):
        if (
            expected is None
            or not expected.reviewed.get(lang)
            or expected.texts.get(lang) != translated
        ):
            raise CampaignError(
                409, f"The {lang} text is not a reviewed translation (D-15): remove it first"
            )


async def _evacuation_deciders(
    session: AsyncSession, campaign: NotificationCampaign
) -> set[uuid.UUID]:
    """The two people who activated the evacuation behind a movement message: neither
    sends it, even after a rejection and a re-submit by one of them (D-31, D-40; review of
    Prompt 67, M2)."""
    if not campaign.audience_filter.get("evacuation_id"):
        return set()
    row = (
        await session.execute(
            text("SELECT requested_by, activated_by FROM evacuation WHERE id = CAST(:e AS uuid)"),
            {"e": campaign.audience_filter["evacuation_id"]},
        )
    ).first()
    return {u for u in (row or ()) if u is not None}


async def _proposal_deciders(
    session: AsyncSession, campaign: NotificationCampaign
) -> set[uuid.UUID]:
    """Everyone who decided a step of the proposal behind an agent's campaign (created_by
    is the proposal id): with a two-step policy, both are the first step here (review of
    Prompt 61, M1)."""
    if campaign.created_by_type != "AGENT" or campaign.created_by is None:
        return set()
    try:
        proposal_id = uuid.UUID(campaign.created_by)
    except ValueError:
        return set()
    rows = await session.scalars(
        text(
            "SELECT decided_by FROM proposal_approval "
            "WHERE proposal_id = :p AND decided_by IS NOT NULL"
        ),
        {"p": proposal_id},
    )
    return set(rows)


async def gate(session: AsyncSession, campaign: NotificationCampaign) -> approvals.Gate:
    """The second-person step of a campaign that reaches citizens (D-31)."""
    others = {uuid.UUID(campaign.created_by)} if campaign.created_by_type == "USER" else set()
    if campaign.submitted_by is not None:
        others.add(campaign.submitted_by)
    others |= await _proposal_deciders(session, campaign)
    others |= await _evacuation_deciders(session, campaign)
    return approvals.Gate(
        subject=f"Campaign {campaign.reference}",
        required_role=APPROVERS,
        mission_id=await _mission(session, campaign),
        decided=campaign.approved_by is not None,
        open=campaign.status == "PENDING_APPROVAL",
        # Composing and submitting are the first step (plan G-2): their user cannot
        # decide the second.
        deciders_of_other_steps=frozenset(others),
    )


async def submit(
    session: AsyncSession, user: CurrentUser, campaign_id: uuid.UUID, app_env: str
) -> Outcome:
    campaign = await _locked(session, campaign_id)
    await _author_composing(session, user, campaign, "submits a campaign")
    if campaign.status != "DRAFT":
        raise CampaignError(409, f"{campaign.reference} is {campaign.status}")
    # Resolved once: the same list decides whether a second person is needed and is
    # what gets queued, so nobody added in between is sent to (review, finding 2).
    recipients = await service.resolve_audience(
        session, campaign.incident_id, campaign.audience_filter
    )
    if await _has_citizens(session, recipients):
        # Said now rather than by the approver's refusal later (MN-06).
        await _check_translations(session, campaign, app_env)
        campaign.status = "PENDING_APPROVAL"
        campaign.submitted_by = user.id
        await session.flush()
        await _audit(session, user, "SUBMIT", campaign, {"needs_approval": True})
        return Outcome(campaign, [_event(campaign)])
    # Staff only: the author sends it, within the campaign's scope.
    if not await approvals.user_has_role(
        session, user, STAFF_SENDERS, await _mission(session, campaign)
    ):
        raise CampaignError(
            403, "Sending to staff needs DUTY_OFFICER or SECURITY_OFFICER for this scope"
        )
    await _check_translations(session, campaign, app_env)
    campaign.status = "SENDING"
    campaign.submitted_by = user.id
    await session.flush()
    await _audit(session, user, "SUBMIT", campaign, {"needs_approval": False})
    try:
        await service.queue_deliveries(session, campaign, _actor(user), recipients=recipients)
    except service.CitizensWithoutApprovalError:
        # Someone in the list became a citizen since the check: nothing is sent.
        raise CampaignError(
            409, "The audience now includes citizens: submit again for a second person"
        ) from None
    return Outcome(campaign, [_event(campaign, "CAMPAIGN_QUEUED")])


async def approve(
    session: AsyncSession, user: CurrentUser, campaign_id: uuid.UUID, app_env: str
) -> Outcome:
    campaign = await _locked(session, campaign_id)
    await approvals.decide(session, user, await gate(session, campaign))
    await _check_translations(session, campaign, app_env)
    # One UPDATE: the approver and SENDING together; the database sets approved_at.
    campaign.approved_by = user.id
    campaign.status = "SENDING"
    await session.flush()
    await session.refresh(campaign, ["approved_at"])
    await _audit(session, user, "APPROVE", campaign)
    await service.queue_deliveries(session, campaign, _actor(user))
    return Outcome(campaign, [_event(campaign, "CAMPAIGN_QUEUED")])


async def reject(
    session: AsyncSession, user: CurrentUser, campaign_id: uuid.UUID, reason: str
) -> Outcome:
    if not reason.strip() or len(reason) > REASON_MAX:
        raise CampaignError(422, f"a reason of 1 to {REASON_MAX} characters is needed")
    campaign = await _locked(session, campaign_id)
    await approvals.decide(session, user, await gate(session, campaign))
    campaign.status = "DRAFT"  # back to the author, who may edit and submit again
    campaign.rejection_reason = reason
    await session.flush()
    await _audit(session, user, "REJECT", campaign, {"reason": reason})
    return Outcome(campaign, [_event(campaign)])


async def _may_cancel(
    session: AsyncSession, user: CurrentUser, campaign: NotificationCampaign
) -> bool:
    """The author or an ADMIN; for an agent's campaign, which has no author, also an
    approver for its scope, so a rejected one is not stuck (review of Prompt 61, L7)."""
    if _is_author(user, campaign) or await approvals.user_has_role(session, user, "ADMIN"):
        return True
    return campaign.created_by_type == "AGENT" and await approvals.user_has_role(
        session, user, APPROVERS, await _mission(session, campaign)
    )


async def cancel(session: AsyncSession, user: CurrentUser, campaign_id: uuid.UUID) -> Outcome:
    campaign = await _locked(session, campaign_id)
    if not await _may_cancel(session, user, campaign):
        raise CampaignError(
            403,
            "Only the author, an approver of an agent's campaign or an ADMIN cancels a campaign",
        )
    if campaign.status not in ("DRAFT", "PENDING_APPROVAL"):
        raise CampaignError(
            409, f"{campaign.reference} is {campaign.status}: it cannot be cancelled"
        )
    campaign.status = "CANCELLED"
    await session.flush()
    await _audit(session, user, "CANCEL", campaign)
    return Outcome(campaign, [_event(campaign)])


async def withdraw(session: AsyncSession, campaign_id: uuid.UUID, actor: Actor) -> Outcome | None:
    """Cancel a campaign whose reason is gone (a stood-down evacuation, D-40), if it has
    not been sent; None if it already was."""
    campaign = await _locked(session, campaign_id)
    if campaign.status not in ("DRAFT", "PENDING_APPROVAL"):
        return None
    campaign.status = "CANCELLED"
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="CAMPAIGN.CANCEL",
        entity_type="notification_campaign",
        entity_id=campaign.reference,
        details={"reason": "withdrawn"},
    )
    return Outcome(campaign, [_event(campaign)])


# --- permissions (plan G-07) -----------------------------------------------------------


@dataclass(frozen=True)
class Permissions:
    edit: bool
    submit: bool
    approve: bool
    cancel: bool


async def permissions(
    session: AsyncSession, user: CurrentUser, campaign: NotificationCampaign
) -> Permissions:
    author = _is_author(user, campaign)
    draft = campaign.status == "DRAFT"
    may_approve = False
    if campaign.status == "PENDING_APPROVAL":
        verdict = await approvals.can_decide(session, user, await gate(session, campaign))
        may_approve = verdict.allowed
    may_cancel = campaign.status in ("DRAFT", "PENDING_APPROVAL") and await _may_cancel(
        session, user, campaign
    )
    # As enforced by _author_composing: the author, still holding a composer role.
    composing = author and draft and await approvals.user_has_role(session, user, COMPOSERS)
    return Permissions(edit=composing, submit=composing, approve=may_approve, cancel=may_cancel)
