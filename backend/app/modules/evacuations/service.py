"""Evacuation Management (EV-01..09, D-40; docs/plan-pilot-ev.md).

- Activation needs two people: a Head of Mission (for the mission, or unscoped) and an HQ
  Crisis Director, different people, through app/core/approvals.py (D-05, D-16). From the
  screen one requests and the other confirms (G-1: the confirmer holds the role the
  requester did not use); from a START_EVACUATION proposal its two approvers are the two.
  The database refuses an activator who is also the requester (PC-31).
- Activation locks the manifest (§4), asks the plan's partners (§7, G-4) and prepares the
  movement message, which a third person sends (D-31).
- Check-in, the sequence and stand-down follow §5, §6 and §8. Every change is audited.
- Names are shown only within NAME_READERS' mission scope (G-8); everyone else sees counts.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.agents.models import ProposalApproval
from app.modules.documents import service as documents
from app.modules.evacuations import schemas
from app.modules.evacuations.models import Evacuation, EvacuationManifestEntry, EvacuationPlan
from app.modules.intel.models import Incident
from app.modules.notifications import compose, templates
from app.modules.notifications.models import NotificationCampaign
from app.modules.partners import service as partners
from app.modules.partners.models import Partner, PartnerRequest
from app.modules.people.models import Mission, Person
from app.modules.tenancy.service import Actor

HOM = "HEAD_OF_MISSION"
HQ = "HQ_CRISIS_DIRECTOR"
OTHER_ROLE = {HOM: HQ, HQ: HOM}
CHECKERS = "SECURITY_OFFICER|CONSULAR_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION"  # §53 Q5
ADVANCERS = "SECURITY_OFFICER|DUTY_OFFICER|HEAD_OF_MISSION"  # plan §6
NAME_READERS = (  # plan G-8
    "DUTY_OFFICER|SECURITY_OFFICER|CONSULAR_OFFICER|HQ_CRISIS_DIRECTOR|HEAD_OF_MISSION"
)
CATEGORY = {"DIPLOMAT": "STAFF", "DELEGATE": "DELEGATE", "DEPENDANT": "DEPENDANT"}
CATEGORY_ORDER = ("STAFF", "DELEGATE", "DEPENDANT", "CITIZEN")
LIVE = ("PENDING_ACTIVATION", "ACTIVE")
STEPS = (
    "Decision to evacuate",
    "Manifest confirmed",
    "Assembly at muster point",
    "Convoy departed",
    "Flight departed",
    "Arrival and reception",
)
ASSEMBLY, FLIGHT, ARRIVAL = 3, 5, 6
SEATS_PER_ROW = "ABCD"
MESSAGE_TEMPLATE = "EVACUATION_MOVE"  # kind ALERT (G-7)
CHANNELS = ("SMS", "APP")
SCANNER = "muster-scanner (simulated)"  # G-9
SIMULATED_PROGRESS = Actor(type="SYSTEM", id="evacuation-progress (simulated)")
SCANNER_ACTOR = Actor(type="SYSTEM", id=SCANNER)
REASON_MAX = 500
# What a partner is asked for, by the service it offers, first match (plan §7).
PARTNER_SERVICES = ("EVACUATION", "SECURE_TRANSPORT")


class EvacuationError(Exception):
    """The request cannot be done: status_code 403, 404 or 409."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Outcome:
    evacuation: Evacuation
    events: list[Event] = field(default_factory=list)
    already_active: bool = False  # G-3


def evacuation_event(evacuation: Evacuation, checked_in: int | None = None) -> Event:
    """Ids, status, step and a count only (realtime carries no names)."""
    return Event(
        type="EVACUATION_UPDATED",
        tenant_id=evacuation.tenant_id,
        payload={
            "evacuation_id": str(evacuation.id),
            "reference": evacuation.reference,
            "mission_id": str(evacuation.mission_id),
            "status": evacuation.status,
            "step": evacuation.step,
            "checked_in": checked_in,
        },
        source="evacuations",
    )


async def _audit(
    session: AsyncSession, actor: Actor, action: str, evacuation: Evacuation, details: Any
) -> None:
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action=f"EVACUATION.{action}",
        entity_type="evacuation",
        entity_id=evacuation.reference,
        details=details,
    )


def _user(user: CurrentUser) -> Actor:
    return Actor(type="USER", id=str(user.id))


async def _locked(session: AsyncSession, evacuation_id: uuid.UUID) -> Evacuation:
    evacuation = await session.scalar(
        select(Evacuation).where(Evacuation.id == evacuation_id).with_for_update()
    )
    if evacuation is None:
        raise EvacuationError(404, "Evacuation not found")
    return evacuation


async def plan_for(session: AsyncSession, mission_id: uuid.UUID) -> EvacuationPlan | None:
    plan: EvacuationPlan | None = await session.scalar(
        select(EvacuationPlan).where(EvacuationPlan.mission_id == mission_id)
    )
    return plan


async def live_for(session: AsyncSession, mission_id: uuid.UUID) -> Evacuation | None:
    live: Evacuation | None = await session.scalar(
        select(Evacuation).where(Evacuation.mission_id == mission_id, Evacuation.status.in_(LIVE))
    )
    return live


async def active_incident(session: AsyncSession, mission_id: uuid.UUID) -> Incident | None:
    """The mission's latest ACTIVE incident: an evacuation needs one (G-6)."""
    incident: Incident | None = await session.scalar(
        select(Incident)
        .where(Incident.mission_id == mission_id, Incident.status == "ACTIVE")
        .order_by(Incident.opened_at.desc())
        .limit(1)
    )
    return incident


def _order(category: str, name: str) -> tuple[int, str]:
    """Manifest order: staff, delegates, dependants, citizens; by name within each."""
    return (CATEGORY_ORDER.index(category), name)


async def _counts(session: AsyncSession, evacuation_id: uuid.UUID) -> int:
    checked: int = (
        await session.scalar(
            select(func.count())
            .select_from(EvacuationManifestEntry)
            .where(
                EvacuationManifestEntry.evacuation_id == evacuation_id,
                EvacuationManifestEntry.status == "CHECKED_IN",
            )
        )
        or 0
    )
    return checked


# --- requesting and confirming (EV-02) ---------------------------------------------------------


async def requester_role(
    session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID
) -> str | None:
    """The role a request is made in: Head of Mission first, for a holder of both."""
    if await approvals.user_has_role(session, user, HOM, mission_id):
        return HOM
    if await approvals.user_has_role(session, user, HQ, None):
        return HQ
    return None


async def request(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID) -> Outcome:
    """The screen's Activate: the first of two people (plan §3)."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise EvacuationError(404, "Mission not found")
    role = await requester_role(session, user, mission.id)
    if role is None:
        raise EvacuationError(
            403,
            "Activating an evacuation needs HEAD_OF_MISSION for this mission or HQ_CRISIS_DIRECTOR",
        )
    plan = await plan_for(session, mission.id)
    if plan is None:
        raise EvacuationError(409, f"{mission.city} has no evacuation plan")
    incident = await active_incident(session, mission.id)
    if incident is None:
        raise EvacuationError(409, f"{mission.city} has no active incident")
    if await live_for(session, mission.id) is not None:
        raise EvacuationError(409, f"{plan.reference} already has a live evacuation")
    evacuation = Evacuation(
        tenant_id=session.info["tenant_id"],
        reference=await session.scalar(text("SELECT next_reference('EVN', false)")),
        plan_id=plan.id,
        mission_id=mission.id,
        incident_id=incident.id,
        requested_by=user.id,
        requested_role=role,
    )
    session.add(evacuation)
    await session.flush()
    await session.refresh(evacuation)
    await _audit(
        session,
        _user(user),
        "REQUEST",
        evacuation,
        {"plan": plan.reference, "incident": incident.reference, "role": role},
    )
    return Outcome(evacuation, [evacuation_event(evacuation)])


def _confirm_gate(evacuation: Evacuation) -> approvals.Gate:
    return approvals.Gate(
        subject=f"{evacuation.reference} activation",
        required_role=OTHER_ROLE[evacuation.requested_role],
        mission_id=evacuation.mission_id,
        decided=evacuation.status != "PENDING_ACTIVATION",
        open=evacuation.status == "PENDING_ACTIVATION",
        deciders_of_other_steps=frozenset({evacuation.requested_by}),
    )


async def confirm(session: AsyncSession, user: CurrentUser, evacuation_id: uuid.UUID) -> Outcome:
    """The second person (D-40). The confirmer holds the other role (G-1)."""
    evacuation = await _locked(session, evacuation_id)
    try:
        await approvals.decide(session, user, _confirm_gate(evacuation))
    except approvals.ApprovalDeniedError as e:
        raise EvacuationError(e.verdict.status_code, e.verdict.reason) from None
    return await _activate(session, evacuation, user.id, _user(user), proposal_id=None)


async def activate_from_proposal(
    session: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    incident_id: uuid.UUID,
    approved_by: uuid.UUID | None,
    actor: Actor,
) -> Outcome:
    """START_EVACUATION's executor (plan §3). approvals.py has already had both steps
    decided by different people; step 1 is the requester, the last approver the activator.
    A live ACTIVE evacuation is returned as it is (G-3); a pending screen request for the
    same mission is stood down by the activator, superseded by the proposal."""
    incident = await session.get(Incident, incident_id)
    if incident is None or incident.mission_id is None:
        raise EvacuationError(409, "the incident has no mission to evacuate")
    if incident.status != "ACTIVE":
        raise EvacuationError(409, f"{incident.reference} is no longer active (G-6)")
    first = await session.scalar(
        select(ProposalApproval.decided_by).where(
            ProposalApproval.proposal_id == proposal_id, ProposalApproval.step_no == 1
        )
    )
    if first is None or approved_by is None or first == approved_by:
        raise EvacuationError(409, "an evacuation needs two people's approval (D-40)")
    # The policy names the roles; check them here too, whatever a tenant's policy says
    # (review of Prompt 67, L6).
    if not (
        await approvals.user_has_role(session, first, HOM, incident.mission_id)
        and await approvals.user_has_role(session, approved_by, HQ, None)
    ):
        raise EvacuationError(
            403, "an evacuation needs a Head of Mission and an HQ Crisis Director (D-40)"
        )
    plan = await plan_for(session, incident.mission_id)
    if plan is None:
        raise EvacuationError(409, "the mission has no evacuation plan")
    live = await session.scalar(
        select(Evacuation)
        .where(Evacuation.mission_id == incident.mission_id, Evacuation.status.in_(LIVE))
        .with_for_update()
    )
    events: list[Event] = []
    if live is not None and live.status == "ACTIVE":
        await _audit(session, actor, "ALREADY_ACTIVE", live, {"proposal": str(proposal_id)})
        return Outcome(live, [], already_active=True)
    if live is not None:
        live.status = "STOOD_DOWN"
        live.stood_down_by = approved_by
        live.stood_down_reason = f"Superseded by an approved evacuation proposal ({proposal_id})"
        await session.flush()
        await session.refresh(live)
        await _audit(session, actor, "STAND_DOWN", live, {"reason": live.stood_down_reason})
        events.append(evacuation_event(live))
    evacuation = Evacuation(
        tenant_id=session.info["tenant_id"],
        reference=await session.scalar(text("SELECT next_reference('EVN', false)")),
        plan_id=plan.id,
        mission_id=plan.mission_id,
        incident_id=incident.id,
        proposal_id=proposal_id,
        requested_by=first,
        requested_role=HOM,  # the policy's step 1
    )
    session.add(evacuation)
    await session.flush()
    await session.refresh(evacuation)
    await _audit(
        session,
        actor,
        "REQUEST",
        evacuation,
        {"plan": plan.reference, "incident": incident.reference, "proposal": str(proposal_id)},
    )
    outcome = await _activate(session, evacuation, approved_by, actor, proposal_id=proposal_id)
    outcome.events[:0] = events
    return outcome


# --- activation: manifest, partners, message (EV-03, EV-06) ------------------------------------

_CITIZENS_FROM_CHECKIN = text(
    """
    SELECT DISTINCT d.person_id FROM notification_delivery d
      JOIN person p ON p.id = d.person_id
     WHERE d.campaign_id = :campaign AND p.person_type = 'CITIZEN' AND p.is_active
       AND p.mission_id = :mission
       AND NOT EXISTS (SELECT 1 FROM v_checkin_latest l
                        WHERE l.campaign_id = :campaign AND l.person_id = d.person_id
                          AND l.status = 'SAFE')
    """
)
_CITIZENS_EXPOSED = text(
    """
    SELECT p.id FROM incident_exposure e JOIN person p ON p.id = e.subject_id
     WHERE e.incident_id = :incident AND e.subject_type = 'PERSON'
       AND p.person_type = 'CITIZEN' AND p.is_active AND p.mission_id = :mission
    """
)


async def _citizens(session: AsyncSession, evacuation: Evacuation) -> list[uuid.UUID]:
    """Citizens who have not confirmed safe in the incident's latest check-in; with no
    check-in, the citizens exposed to the incident (§4, G-6)."""
    if evacuation.incident_id is None:
        return []
    # A check-in that was sent: a draft or cancelled one asked no one (review of Prompt 67, L4).
    checkin = await session.scalar(
        select(NotificationCampaign.id)
        .where(
            NotificationCampaign.incident_id == evacuation.incident_id,
            NotificationCampaign.campaign_type == "CHECKIN",
            NotificationCampaign.status.in_(("SENDING", "SENT")),
        )
        .order_by(NotificationCampaign.created_at.desc())
        .limit(1)
    )
    params = {"mission": evacuation.mission_id}
    if checkin is not None:
        rows = await session.scalars(_CITIZENS_FROM_CHECKIN, {**params, "campaign": checkin})
    else:
        rows = await session.scalars(
            _CITIZENS_EXPOSED, {**params, "incident": evacuation.incident_id}
        )
    return list(rows)


async def _build_manifest(session: AsyncSession, evacuation: Evacuation) -> dict[str, int]:
    """In the activating transaction (PC-32): mission people by type, and citizens."""
    citizens = await _citizens(session, evacuation)
    people = await session.scalars(
        select(Person)
        .where(
            Person.mission_id == evacuation.mission_id,
            Person.is_active,
            Person.person_type.in_(tuple(CATEGORY)) | Person.id.in_(citizens),
        )
        .order_by(Person.full_name, Person.id)
    )
    rows = [
        EvacuationManifestEntry(
            tenant_id=evacuation.tenant_id,
            evacuation_id=evacuation.id,
            person_id=p.id,
            category=CATEGORY.get(p.person_type, "CITIZEN"),
        )
        for p in people
        if p.person_type in CATEGORY or p.person_type == "CITIZEN"
    ]
    session.add_all(rows)
    await session.flush()
    counts = {c: 0 for c in CATEGORY_ORDER}
    for r in rows:
        counts[r.category] += 1
    return counts


def _summary(evacuation: Evacuation, plan: EvacuationPlan, mission: Mission, count: int) -> str:
    """What a partner is told (AS-08): no names."""
    return (
        f"{evacuation.reference} · {count} people · muster {plan.muster_name} · "
        f"{plan.route_label} · {plan.destination} (simulated)"
    )[:500]


async def _ask_partners(
    session: AsyncSession,
    evacuation: Evacuation,
    plan: EvacuationPlan,
    mission: Mission,
    count: int,
    activator: uuid.UUID,
    actor: Actor,
) -> tuple[list[str], list[Event]]:
    asked: list[str] = []
    events: list[Event] = []
    for option in plan.options:
        partner_id = option.get("partner_id")
        if not partner_id:
            continue
        partner = await session.get(Partner, uuid.UUID(str(partner_id)))
        if partner is None or not partner.is_active:
            continue
        service = next((s for s in PARTNER_SERVICES if s in partner.services), None)
        if service is None or mission.country_code not in partner.coverage:
            continue
        outcome = await partners.request_for_evacuation(
            session,
            partner=partner,
            service=service,
            mission_id=mission.id,
            incident_id=evacuation.incident_id,
            note=_summary(evacuation, plan, mission, count),
            activator=activator,
            actor=actor,
        )
        asked.append(outcome.request.reference)
        events.extend(outcome.events)
    return asked, events


async def _prepare_message(
    session: AsyncSession,
    evacuation: Evacuation,
    activator: uuid.UUID,
    actor: Actor,
    proposal_id: uuid.UUID | None,
) -> compose.Outcome | None:
    """The movement message, PENDING_APPROVAL: a third person sends it (D-31, plan §7). None
    if the tenant has no EVACUATION_MOVE template (the evacuation still goes ahead)."""
    resolved = await templates.resolve(session, MESSAGE_TEMPLATE, evacuation.mission_id)
    if resolved is None:
        return None
    texts = dict(resolved.texts)
    content = compose.Content(
        kind="ALERT",
        message=texts.pop("en"),
        channels=list(CHANNELS),
        incident_id=evacuation.incident_id,
        translations=texts,
        template_id=resolved.template_id,
        evacuation_id=evacuation.id,
    )
    if proposal_id is not None:
        return await compose.prepare_for_approval(
            session, content, proposal_id=proposal_id, submitted_by=activator, actor=actor
        )
    return await compose.prepare_for_second_person(
        session, content, author=evacuation.requested_by, submitted_by=activator, actor=actor
    )


async def _activate(
    session: AsyncSession,
    evacuation: Evacuation,
    activator: uuid.UUID,
    actor: Actor,
    *,
    proposal_id: uuid.UUID | None,
) -> Outcome:
    if evacuation.requested_by == activator:
        raise EvacuationError(403, "The requester cannot also activate (D-40)")
    evacuation.status = "ACTIVE"
    evacuation.activated_by = activator
    evacuation.step = 2
    await session.flush()
    await session.refresh(evacuation)  # the guard writes the times
    plan = await session.get_one(EvacuationPlan, evacuation.plan_id)
    mission = await session.get_one(Mission, evacuation.mission_id)
    counts = await _build_manifest(session, evacuation)
    total = sum(counts.values())
    asked, events = await _ask_partners(session, evacuation, plan, mission, total, activator, actor)
    message = await _prepare_message(session, evacuation, activator, actor, proposal_id)
    if message is not None:
        events.extend(message.events)
    await _audit(
        session,
        actor,
        "ACTIVATE",
        evacuation,
        {
            "plan": plan.reference,
            "activated_by": str(activator),
            "manifest": counts,
            "partner_requests": asked,
            "message": message.campaign.reference if message else None,
        },
    )
    return Outcome(evacuation, [evacuation_event(evacuation, 0), *events])


# --- check-in and seats (EV-04) ----------------------------------------------------------------


def seat_label(index: int) -> str:
    """0 -> 1A, 3 -> 1D, 4 -> 2A."""
    return f"{index // len(SEATS_PER_ROW) + 1}{SEATS_PER_ROW[index % len(SEATS_PER_ROW)]}"


async def _next_seat(session: AsyncSession, evacuation: Evacuation) -> str | None:
    """The primary option's next free seat, or None when it has no seats left (G-10). The
    evacuation row is locked by the caller, so two check-ins never take one seat."""
    plan = await session.get_one(EvacuationPlan, evacuation.plan_id)
    seats = plan.options[0].get("seats") if plan.options else None
    if not isinstance(seats, int):
        return None
    used: int = (
        await session.scalar(
            select(func.count())
            .select_from(EvacuationManifestEntry)
            .where(
                EvacuationManifestEntry.evacuation_id == evacuation.id,
                EvacuationManifestEntry.seat.is_not(None),
            )
        )
        or 0
    )
    return seat_label(used) if used < seats else None


async def _check_in(
    session: AsyncSession,
    evacuation: Evacuation,
    entry: EvacuationManifestEntry,
    by_type: str,
    by: str,
) -> None:
    entry.seat = await _next_seat(session, evacuation)
    entry.status = "CHECKED_IN"
    entry.checked_in_by_type = by_type
    entry.checked_in_by = by
    await session.flush()


async def _after_check_in(
    session: AsyncSession, evacuation: Evacuation, actor: Actor, checked: int
) -> list[Event]:
    """Assembly is reached when everyone on the manifest is checked in (plan §6)."""
    expected = await session.scalar(
        select(func.count())
        .select_from(EvacuationManifestEntry)
        .where(
            EvacuationManifestEntry.evacuation_id == evacuation.id,
            EvacuationManifestEntry.status == "EXPECTED",
        )
    )
    if expected == 0 and evacuation.step == ASSEMBLY - 1:
        await _move_step(session, evacuation, ASSEMBLY, actor)
    return [evacuation_event(evacuation, checked)]


def _active(evacuation: Evacuation) -> None:
    if evacuation.status != "ACTIVE":
        raise EvacuationError(
            409, f"{evacuation.reference} is {evacuation.status.lower().replace('_', ' ')}"
        )


async def check_in(
    session: AsyncSession, user: CurrentUser, evacuation_id: uuid.UUID, entry_id: uuid.UUID
) -> Outcome:
    evacuation = await _locked(session, evacuation_id)
    if not await approvals.user_has_role(session, user, CHECKERS, evacuation.mission_id):
        raise EvacuationError(
            403,
            "Checking in needs SECURITY_OFFICER, CONSULAR_OFFICER, DUTY_OFFICER or "
            "HEAD_OF_MISSION for this mission",
        )
    _active(evacuation)
    entry = await session.scalar(
        select(EvacuationManifestEntry).where(
            EvacuationManifestEntry.id == entry_id,
            EvacuationManifestEntry.evacuation_id == evacuation.id,
        )
    )
    if entry is None:
        raise EvacuationError(404, "Not on this manifest")
    if entry.status == "CHECKED_IN":
        raise EvacuationError(409, "Already checked in")
    await _check_in(session, evacuation, entry, "USER", str(user.id))
    await _audit(
        session,
        _user(user),
        "CHECK_IN",
        evacuation,
        {"entry": str(entry.id), "category": entry.category, "seat": entry.seat},
    )
    checked = await _counts(session, evacuation.id)
    return Outcome(evacuation, await _after_check_in(session, evacuation, _user(user), checked))


async def scan(session: AsyncSession, mission_code: str, count: int) -> Outcome | None:
    """The simulated muster-point scanner (G-9): the next `count` people expected, in
    manifest order. None if the mission has no ACTIVE evacuation."""
    mission = await session.scalar(select(Mission).where(Mission.code == mission_code))
    if mission is None:
        return None
    live = await live_for(session, mission.id)
    if live is None or live.status != "ACTIVE":
        return None
    evacuation = await _locked(session, live.id)
    if evacuation.status != "ACTIVE":
        return None
    result = await session.execute(
        select(EvacuationManifestEntry, Person.full_name)
        .join(Person, Person.id == EvacuationManifestEntry.person_id)
        .where(
            EvacuationManifestEntry.evacuation_id == evacuation.id,
            EvacuationManifestEntry.status == "EXPECTED",
        )
    )
    expected = list(result.all())
    expected.sort(key=lambda r: _order(r[0].category, r[1]))
    rows = [entry for entry, _name in expected[: max(0, count)]]
    if not rows:
        return Outcome(evacuation, [])
    actor = SCANNER_ACTOR
    for entry in rows:
        await _check_in(session, evacuation, entry, "SCANNER", SCANNER)
    await _audit(session, actor, "CHECK_IN", evacuation, {"scanned": len(rows)})
    checked = await _counts(session, evacuation.id)
    return Outcome(evacuation, await _after_check_in(session, evacuation, actor, checked))


# --- the sequence (EV-05) ----------------------------------------------------------------------


async def _move_step(
    session: AsyncSession, evacuation: Evacuation, step: int, actor: Actor
) -> list[Event]:
    events: list[Event] = []
    evacuation.step = step
    if step == ARRIVAL:
        evacuation.status = "COMPLETED"
    await session.flush()
    await session.refresh(evacuation)
    await _audit(session, actor, "STEP", evacuation, {"step": step, "name": STEPS[step - 1]})
    if step == ARRIVAL:
        for request in await _requests(session, evacuation):
            moved = await partners.move_for_evacuation(session, request, "COMPLETED", actor)
            if moved is not None:
                events.extend(moved.events)
        # A movement message still unsent after arrival has nothing left to say (L5).
        events.extend(await _withdraw_messages(session, evacuation, actor))
    return events


async def _withdraw_messages(
    session: AsyncSession, evacuation: Evacuation, actor: Actor
) -> list[Event]:
    events: list[Event] = []
    campaigns = await session.scalars(
        select(NotificationCampaign.id).where(
            NotificationCampaign.audience_filter["evacuation_id"].astext == str(evacuation.id)
        )
    )
    for campaign_id in list(campaigns):
        withdrawn = await compose.withdraw(session, campaign_id, actor)
        if withdrawn is not None:
            events.extend(withdrawn.events)
    return events


async def _advance(
    session: AsyncSession, evacuation: Evacuation, step: int, actor: Actor
) -> Outcome:
    _active(evacuation)
    if evacuation.step is None or step != evacuation.step + 1:
        raise EvacuationError(409, f"The next step is {(evacuation.step or 0) + 1}")
    events = await _move_step(session, evacuation, step, actor)
    checked = await _counts(session, evacuation.id)
    return Outcome(evacuation, [evacuation_event(evacuation, checked), *events])


async def advance(
    session: AsyncSession, user: CurrentUser, evacuation_id: uuid.UUID, step: int
) -> Outcome:
    evacuation = await _locked(session, evacuation_id)
    if not await approvals.user_has_role(session, user, ADVANCERS, evacuation.mission_id):
        raise EvacuationError(
            403,
            "Moving the sequence needs SECURITY_OFFICER, DUTY_OFFICER or HEAD_OF_MISSION "
            "for this mission",
        )
    return await _advance(session, evacuation, step, _user(user))


async def progress(session: AsyncSession, mission_code: str, step: int) -> Outcome | None:
    """The scenario's simulated progress (G-2): moves steps only. None if there is no
    ACTIVE evacuation at the mission, or it is not at the step before."""
    mission = await session.scalar(select(Mission).where(Mission.code == mission_code))
    live = await live_for(session, mission.id) if mission else None
    if live is None or live.status != "ACTIVE":
        return None
    evacuation = await _locked(session, live.id)
    if evacuation.status != "ACTIVE" or evacuation.step != step - 1:
        return None
    return await _advance(session, evacuation, step, SIMULATED_PROGRESS)


# --- stand down (EV-07) ------------------------------------------------------------------------


def _made_by_activation(evacuation: Evacuation) -> Any:
    """The partner requests the activation made: the activator's, written in the activating
    transaction (the database's requested_at equals activated_at there), naming the
    evacuation. A person cannot write those times, so a crafted note is not enough (review
    of Prompt 67, M3)."""
    return (
        (PartnerRequest.mission_id == evacuation.mission_id)
        & (PartnerRequest.created_by_type == "USER")
        & (PartnerRequest.created_by == str(evacuation.activated_by))
        & (PartnerRequest.requested_at == evacuation.activated_at)
        & PartnerRequest.note.startswith(f"{evacuation.reference} · ")
    )


async def _requests(session: AsyncSession, evacuation: Evacuation) -> list[PartnerRequest]:
    if evacuation.activated_at is None:
        return []
    return list(
        await session.scalars(
            select(PartnerRequest).where(_made_by_activation(evacuation)).with_for_update()
        )
    )


async def may_stand_down(session: AsyncSession, user: CurrentUser, evacuation: Evacuation) -> bool:
    if evacuation.status == "PENDING_ACTIVATION":
        if user.id == evacuation.requested_by:
            return True
        return (await approvals.can_decide(session, user, _confirm_gate(evacuation))).allowed
    return (
        evacuation.status == "ACTIVE"
        and (evacuation.step or 0) < FLIGHT
        and await approvals.user_has_role(session, user, HQ, None)
    )


async def stand_down(
    session: AsyncSession, user: CurrentUser, evacuation_id: uuid.UUID, reason: str
) -> Outcome:
    evacuation = await _locked(session, evacuation_id)
    reason = reason.strip()
    if not 1 <= len(reason) <= REASON_MAX:
        raise EvacuationError(422, f"A reason of 1 to {REASON_MAX} characters")
    if evacuation.status not in LIVE:
        raise EvacuationError(409, f"{evacuation.reference} is already final")
    if evacuation.status == "ACTIVE" and (evacuation.step or 0) >= FLIGHT:
        raise EvacuationError(409, "The flight has departed; it can no longer be stood down")
    if not await may_stand_down(session, user, evacuation):
        raise EvacuationError(
            403,
            "Standing down needs HQ_CRISIS_DIRECTOR (or, for a request, its requester "
            "or the person who may confirm it)",
        )
    actor = _user(user)
    evacuation.status = "STOOD_DOWN"
    evacuation.stood_down_by = user.id
    evacuation.stood_down_reason = reason
    await session.flush()
    await session.refresh(evacuation)
    events: list[Event] = []
    for request in await _requests(session, evacuation):
        moved = await partners.move_for_evacuation(session, request, "CANCELLED", actor)
        if moved is not None:
            events.extend(moved.events)
    events.extend(await _withdraw_messages(session, evacuation, actor))
    await _audit(session, actor, "STAND_DOWN", evacuation, {"reason": reason})
    return Outcome(evacuation, [evacuation_event(evacuation), *events])


# --- reads (EV-08, EV-09) ----------------------------------------------------------------------


@dataclass(frozen=True)
class EntryView:
    id: uuid.UUID
    category: str | None  # with the name and seat, only within the name scope (G-8, plan §9)
    seat: str | None
    status: str
    checked_in_at: Any
    name: str | None  # None outside the caller's name scope (G-8)
    document_flag: bool | None


async def name_scope(session: AsyncSession, user: CurrentUser) -> documents.Scope | None:
    """The missions whose names the caller may see: the union of their NAME_READERS
    grants (as Document Expiry's, plan-pilot-dx G-7); None if they hold none."""
    codes = approvals.parse_role_codes(NAME_READERS)
    grants = [g for g in await approvals.roles_of(session, user.id) if g.code in codes]
    if not grants:
        return None
    if any(g.mission_id is None for g in grants):
        return documents.Scope(None)
    return documents.Scope(frozenset(g.mission_id for g in grants if g.mission_id is not None))


def sees_names(scope: documents.Scope | None, mission_id: uuid.UUID) -> bool:
    return scope is not None and (scope.missions is None or mission_id in scope.missions)


async def manifest(
    session: AsyncSession, user: CurrentUser, evacuation: Evacuation, today: date
) -> list[EntryView]:
    names = sees_names(await name_scope(session, user), evacuation.mission_id)
    flagged: set[uuid.UUID] = set()
    if names:
        flagged = {
            r.document.person_id
            for r in await documents.at_risk(session, evacuation.mission_id, today)
        }
    result = await session.execute(
        select(EvacuationManifestEntry, Person.full_name)
        .join(Person, Person.id == EvacuationManifestEntry.person_id)
        .where(EvacuationManifestEntry.evacuation_id == evacuation.id)
    )
    rows = list(result.all())
    rows.sort(key=lambda r: _order(r[0].category, r[1]))
    return [
        EntryView(
            id=e.id,
            category=e.category if names else None,
            seat=e.seat if names else None,
            status=e.status,
            checked_in_at=e.checked_in_at,
            name=full_name if names else None,
            document_flag=(e.person_id in flagged) if names else None,
        )
        for e, full_name in rows
    ]


async def documents_flagged(session: AsyncSession, evacuation: Evacuation, today: date) -> int:
    """A count every role may see (the KPI): manifest people whose documents could block."""
    at_risk = {
        r.document.person_id for r in await documents.at_risk(session, evacuation.mission_id, today)
    }
    people = await session.scalars(
        select(EvacuationManifestEntry.person_id).where(
            EvacuationManifestEntry.evacuation_id == evacuation.id
        )
    )
    return len(at_risk & set(people))


@dataclass(frozen=True)
class Permissions:
    activate: bool = False
    confirm: bool = False
    check_in: bool = False
    advance: bool = False
    stand_down: bool = False


async def permissions(
    session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID
) -> Permissions:
    """For the screen (GET /api/me/permissions?entity_type=evacuation), from the same
    checks the endpoints make."""
    mission = await session.get(Mission, mission_id)
    if mission is None:
        return Permissions()
    live = await live_for(session, mission.id)
    if live is None:
        may_request = (
            await requester_role(session, user, mission.id) is not None
            and await plan_for(session, mission.id) is not None
            and await active_incident(session, mission.id) is not None
        )
        return Permissions(activate=may_request)
    if live.status == "PENDING_ACTIVATION":
        verdict = await approvals.can_decide(session, user, _confirm_gate(live))
        return Permissions(
            confirm=verdict.allowed, stand_down=await may_stand_down(session, user, live)
        )
    return Permissions(
        check_in=await approvals.user_has_role(session, user, CHECKERS, mission.id),
        advance=await approvals.user_has_role(session, user, ADVANCERS, mission.id),
        stand_down=await may_stand_down(session, user, live),
    )


# --- views for the API (EV-08) -------------------------------------------------------------------


async def _partners(session: AsyncSession) -> dict[uuid.UUID, Partner]:
    return {p.id: p for p in await session.scalars(select(Partner))}


async def list_plans(session: AsyncSession) -> list[schemas.PlanOut]:
    partner_rows = await _partners(session)
    rows = await session.execute(
        select(EvacuationPlan, Mission)
        .join(Mission, Mission.id == EvacuationPlan.mission_id)
        .order_by(Mission.code)
    )
    return [
        schemas.PlanOut(
            id=plan.id,
            reference=plan.reference,
            mission_id=mission.id,
            mission_code=mission.code,
            city=mission.city,
            muster_name=plan.muster_name,
            route_label=plan.route_label,
            destination=plan.destination,
            options=[
                schemas.option_out(o, partner_rows, mission.country_code) for o in plan.options
            ],
            source=plan.source,
        )
        for plan, mission in rows
    ]


async def _display_name(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    name: str | None = await session.scalar(
        text("SELECT display_name FROM app_user WHERE id = :u"), {"u": user_id}
    )
    return name


async def describe(
    session: AsyncSession, evacuation: Evacuation, today: date
) -> schemas.EvacuationOut:
    """Counts, steps, partners and the message: what every role may see (EV-09)."""
    plan = await session.get_one(EvacuationPlan, evacuation.plan_id)
    counts = {c: 0 for c in CATEGORY_ORDER}
    for category, n in await session.execute(
        select(EvacuationManifestEntry.category, func.count())
        .where(EvacuationManifestEntry.evacuation_id == evacuation.id)
        .group_by(EvacuationManifestEntry.category)
    ):
        counts[category] = n
    partner_rows = await _partners(session)
    requests = [
        schemas.PartnerRequestOut(
            reference=r.reference,
            partner_name=partner_rows[r.partner_id].name if r.partner_id in partner_rows else "—",
            service=r.service,
            status=r.status,
        )
        for r in (
            await session.scalars(
                select(PartnerRequest)
                .where(_made_by_activation(evacuation))
                .order_by(PartnerRequest.reference)
            )
            if evacuation.activated_at is not None
            else []
        )
    ]
    message = await session.scalar(
        select(NotificationCampaign)
        .where(NotificationCampaign.audience_filter["evacuation_id"].astext == str(evacuation.id))
        .order_by(NotificationCampaign.created_at.desc())
        .limit(1)
    )
    seats = plan.options[0].get("seats") if plan.options else None
    return schemas.EvacuationOut(
        id=evacuation.id,
        reference=evacuation.reference,
        plan_reference=plan.reference,
        mission_id=evacuation.mission_id,
        incident_id=evacuation.incident_id,
        proposal_id=evacuation.proposal_id,
        status=evacuation.status,
        requested_role=evacuation.requested_role,
        requested_by_name=await _display_name(session, evacuation.requested_by),
        requested_at=evacuation.requested_at,
        activated_by_name=await _display_name(session, evacuation.activated_by),
        activated_at=evacuation.activated_at,
        step=evacuation.step,
        steps=[
            schemas.StepOut(step=n, name=name, at=evacuation.step_times.get(str(n)))
            for n, name in enumerate(STEPS, start=1)
        ],
        stood_down_reason=evacuation.stood_down_reason,
        counts=counts,
        checked_in=await _counts(session, evacuation.id),
        seats=seats if isinstance(seats, int) else None,
        documents_flagged=await documents_flagged(session, evacuation, today),
        partner_requests=requests,
        message_reference=message.reference if message else None,
        message_status=message.status if message else None,
    )


async def list_evacuations(
    session: AsyncSession, mission_id: uuid.UUID | None, today: date
) -> list[schemas.EvacuationOut]:
    query = select(Evacuation).order_by(Evacuation.created_at.desc())
    if mission_id is not None:
        query = query.where(Evacuation.mission_id == mission_id)
    return [await describe(session, e, today) for e in await session.scalars(query.limit(50))]


async def detail(
    session: AsyncSession, user: CurrentUser, evacuation_id: uuid.UUID, today: date
) -> schemas.EvacuationDetailOut:
    evacuation = await session.get(Evacuation, evacuation_id)
    if evacuation is None:
        raise EvacuationError(404, "Evacuation not found")
    base = await describe(session, evacuation, today)
    entries = await manifest(session, user, evacuation, today)
    return schemas.EvacuationDetailOut(
        **base.model_dump(),
        manifest=[schemas.EntryOut(**vars(e)) for e in entries],
        names_shown=sees_names(await name_scope(session, user), evacuation.mission_id),
    )
