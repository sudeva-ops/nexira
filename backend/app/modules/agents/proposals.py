"""Agent proposals: the policy engine's outcome, human decisions and execution
(AGT-01..08, D-12..D-17). Changes need human sign-off (D-29).

- create(): inserts agent_proposal. The database sets effective_level and
  deadline_at (agent_proposal_level trigger) and the approval rows
  (agent_proposal_approvals); this module never computes or writes them. It also
  refuses the insert while agents are paused (D-17) or the agent is disabled.
  - level 0: executed at once (AUTO_EXECUTED);
  - level 1: executed at once with undo_until (D-13, UNDO_WINDOW_S, plan G-17);
  - level 2 and 3: PENDING until every approval step is decided;
  - level 4: advice only; never executed.
- approve() / edit_approve() / reject() / use_alternative(): every check goes
  through approvals.decide() (role, mission scope from the incident, step order,
  one person per step; D-05, D-16).
- Execution happens only when the number of approved steps equals what the level
  requires (1 for level 2, 2 for level 3), not merely when "all rows are
  approved" (PC-05: rows could be deleted). It calls actions.execute(), i.e. the
  same services users call, inside a savepoint: a failure rolls the action back
  and marks the proposal FAILED, audited with the error.
- Execution results are kept in the PROPOSAL.EXECUTE audit row (the table has no
  result column); undo reads them from there.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.agents import actions
from app.modules.agents.models import Agent, AgentProposal, ProposalApproval
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.tenancy.models import Tenant
from app.modules.tenancy.service import Actor

REQUIRED_STEPS = {2: 1, 3: 2}  # D-16
EXPIRER = Actor(type="SYSTEM", id="agents.expiry")


class ProposalError(Exception):
    """A request that conflicts with the proposal's state (409)."""


class AgentsPausedError(ProposalError):
    """D-17: the kill switch is on, or the agent is disabled."""


@dataclass
class Outcome:
    proposal: AgentProposal
    created: bool = True
    events: list[Event] = field(default_factory=list)  # publish after commit


def _event(proposal: AgentProposal, kind: str = "PROPOSAL_UPDATED", **extra: Any) -> Event:
    return Event(
        type=kind,
        tenant_id=proposal.tenant_id,
        payload={
            "proposal_id": str(proposal.id),
            "status": proposal.status,
            "incident_id": str(proposal.incident_id) if proposal.incident_id else None,
            **extra,
        },
        source="agents",
    )


def _agent_actor(agent_code: str) -> Actor:
    return Actor(type="AGENT", id=agent_code)


# --- creation ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposalIn:
    agent_code: str
    proposal_key: str  # idempotency: the same observation twice is one proposal
    action_type: str
    title: str
    proposed_action: str
    action_payload: dict[str, Any]
    incident_id: uuid.UUID | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)  # [{"text", "source"}]
    alternatives: list[dict[str, Any]] = field(default_factory=list)  # D-14
    risk_if_no_action: str | None = None
    confidence: int | None = None
    is_proactive: bool = False


async def create(
    session: AsyncSession, spec: ProposalIn, *, undo_window_s: int, now: datetime | None = None
) -> Outcome:
    """Insert a proposal (or return the existing one with the same key) and run it
    at once if the database made it level 0 or 1."""
    actions.validate(spec.action_type, spec.action_payload)
    for alternative in spec.alternatives:
        actions.validate(
            str(alternative.get("action_type")), dict(alternative.get("action_payload") or {})
        )
    agent = await session.scalar(select(Agent).where(Agent.code == spec.agent_code))
    if agent is None:
        raise ProposalError(f"unknown agent {spec.agent_code}")
    try:
        async with session.begin_nested():
            proposal_id = await session.scalar(
                insert(AgentProposal)
                .values(
                    tenant_id=session.info["tenant_id"],
                    agent_id=agent.id,
                    incident_id=spec.incident_id,
                    proposal_key=spec.proposal_key,
                    action_type=spec.action_type,
                    title=spec.title,
                    proposed_action=spec.proposed_action,
                    action_payload=spec.action_payload,
                    evidence=spec.evidence,
                    alternatives=spec.alternatives,
                    risk_if_no_action=spec.risk_if_no_action,
                    confidence=spec.confidence,
                    is_proactive=spec.is_proactive,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "agent_id", "proposal_key"])
                .returning(AgentProposal.id)
            )
    except DBAPIError as e:
        message = str(e.orig)
        if "agents are paused" in message or "is disabled" in message:
            raise AgentsPausedError(
                "Agents are paused" if "paused" in message else "This agent is disabled"
            ) from None
        raise
    if proposal_id is None:
        existing = await session.scalar(
            select(AgentProposal).where(
                AgentProposal.agent_id == agent.id,
                AgentProposal.proposal_key == spec.proposal_key,
            )
        )
        assert existing is not None
        return Outcome(existing, created=False)

    proposal = await session.get_one(AgentProposal, proposal_id, populate_existing=True)
    actor = _agent_actor(spec.agent_code)
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PROPOSAL.CREATE",
        entity_type="agent_proposal",
        entity_id=str(proposal.id),
        details={
            "action_type": proposal.action_type,
            "effective_level": proposal.effective_level,  # as set by the database
            "proposal_key": proposal.proposal_key,
            "incident_id": str(proposal.incident_id) if proposal.incident_id else None,
        },
    )
    outcome = Outcome(
        proposal, events=[_event(proposal, "PROPOSAL_CREATED", agent=spec.agent_code)]
    )
    if proposal.effective_level in (0, 1):
        now = now or datetime.now(UTC)
        await _execute(
            session, proposal, spec.agent_code, approved_by=None, outcome=outcome, now=now
        )
        if proposal.status == "AUTO_EXECUTED" and proposal.effective_level == 1:
            proposal.undo_until = now + timedelta(seconds=undo_window_s)
            await session.flush()
    return outcome


# --- execution ------------------------------------------------------------------------------


async def _execute(
    session: AsyncSession,
    proposal: AgentProposal,
    agent_code: str,
    *,
    approved_by: uuid.UUID | None,
    outcome: Outcome,
    now: datetime,
    final_status: str = "AUTO_EXECUTED",
) -> None:
    payload = (
        proposal.edited_payload if proposal.edited_payload is not None else proposal.action_payload
    )
    ctx = actions.Context(
        proposal_id=proposal.id,
        incident_id=proposal.incident_id,
        agent_actor=_agent_actor(agent_code),
        approved_by=approved_by,
    )
    try:
        async with session.begin_nested():
            result = await actions.execute(session, proposal.action_type, payload, ctx)
    except (actions.ActionError, ValueError) as e:
        proposal.status = "FAILED"
        proposal.decided_at = proposal.decided_at or now
        await session.flush()
        await audit.write(
            session,
            actor_type=ctx.agent_actor.type,
            actor_id=ctx.agent_actor.id,
            action="PROPOSAL.FAIL",
            entity_type="agent_proposal",
            entity_id=str(proposal.id),
            details={
                "error": str(e)[:500],
                "approved_by": str(approved_by) if approved_by else None,
            },
        )
        outcome.events.append(_event(proposal))
        return
    proposal.status = final_status
    proposal.executed_at = now
    if final_status == "AUTO_EXECUTED":
        proposal.decided_at = now
    await session.flush()
    await audit.write(
        session,
        actor_type=ctx.agent_actor.type,
        actor_id=ctx.agent_actor.id,
        action="PROPOSAL.EXECUTE",
        entity_type="agent_proposal",
        entity_id=str(proposal.id),
        details={
            "action_type": proposal.action_type,
            "edited": proposal.edited_payload is not None,
            "approved_by": str(approved_by) if approved_by else None,
            "result": result,
        },
    )
    outcome.events.extend(ctx.events)
    outcome.events.append(_event(proposal))


# --- decisions ------------------------------------------------------------------------------


async def _locked(session: AsyncSession, proposal_id: uuid.UUID) -> AgentProposal:
    proposal = await session.scalar(
        select(AgentProposal).where(AgentProposal.id == proposal_id).with_for_update()
    )
    if proposal is None:
        raise LookupError("Proposal not found")
    return proposal


async def _mission(
    session: AsyncSession, proposal: AgentProposal, lock: bool = True
) -> uuid.UUID | None:
    if proposal.incident_id is None:
        return None  # D-06: unscoped (HQ) holders only
    query = select(Incident.mission_id).where(Incident.id == proposal.incident_id)
    if lock:  # exposure cannot move the incident to another mission mid-decision
        query = query.with_for_update(read=True)
    return await session.scalar(query)


@dataclass
class _Step:
    row: ProposalApproval
    gate: approvals.Gate


async def _next_step(session: AsyncSession, proposal: AgentProposal, lock: bool = True) -> _Step:
    """The next undecided approval step, as a Gate for approvals.decide(). With
    lock=False it only reads (can_decide, for showing buttons)."""
    if proposal.status != "PENDING":
        raise ProposalError(f"The proposal is {proposal.status}")
    if proposal.effective_level == 4:
        raise ProposalError("Advise-only: this proposal cannot be executed")
    if proposal.effective_level not in REQUIRED_STEPS:
        raise ProposalError("This proposal does not need an approval")
    query = (
        select(ProposalApproval)
        .where(ProposalApproval.proposal_id == proposal.id)
        .order_by(ProposalApproval.step_no)
    )
    rows = list(await session.scalars(query.with_for_update() if lock else query))
    pending = [r for r in rows if r.decision is None]
    if not pending:
        raise ProposalError("No approval step is open")
    row = pending[0]
    earlier = [r for r in rows if r.step_no < row.step_no]
    return _Step(
        row,
        approvals.Gate(
            subject=f"Step {row.step_no} of this proposal",
            required_role=row.required_role,
            mission_id=await _mission(session, proposal, lock),
            decided=False,
            open=all(r.decision == "APPROVE" for r in earlier),
            deciders_of_other_steps=frozenset(r.decided_by for r in rows if r.decided_by),
        ),
    )


async def can_decide(session: AsyncSession, user: CurrentUser, proposal: AgentProposal) -> bool:
    """Plan G-07: whether approve() would accept this user now (the same gate)."""
    try:
        step = await _next_step(session, proposal, lock=False)
    except ProposalError:
        return False
    return (await approvals.can_decide(session, user, step.gate)).allowed


async def _agent_code(session: AsyncSession, proposal: AgentProposal) -> str:
    code = await session.scalar(select(Agent.code).where(Agent.id == proposal.agent_id))
    return code or "UNKNOWN"


async def approve(
    session: AsyncSession,
    user: CurrentUser,
    proposal_id: uuid.UUID,
    *,
    edited_action: str | None = None,
    edited_payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Outcome:
    """Decide the next approval step as APPROVE; execute when the last required
    step is approved. With an edit (edit-and-approve), only the first approver may
    change the action, and the original action_payload stays as it was."""
    now = now or datetime.now(UTC)
    proposal = await _locked(session, proposal_id)
    step = await _next_step(session, proposal)
    await approvals.decide(session, user, step.gate)

    edited = edited_payload is not None or edited_action is not None
    if edited:
        if step.row.step_no != 1:
            raise ProposalError("Only the first approver can edit a proposal")
        if edited_payload is not None:
            try:
                actions.check_edit(proposal.action_type, proposal.action_payload, edited_payload)
            except actions.ActionError as e:
                raise ProposalError(str(e)) from None
            proposal.edited_payload = edited_payload
        if edited_action is not None:
            proposal.edited_action = edited_action

    step.row.decided_by = user.id
    step.row.decision = "APPROVE"
    step.row.decided_at = now
    await session.flush()
    actor = Actor(type="USER", id=str(user.id))
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PROPOSAL.EDIT_APPROVE" if edited else "PROPOSAL.APPROVE",
        entity_type="agent_proposal",
        entity_id=str(proposal.id),
        details={
            "step_no": step.row.step_no,
            "required_role": step.row.required_role,
            **(
                {
                    "original_payload": proposal.action_payload,
                    "edited_payload": proposal.edited_payload,
                    "edited_action": proposal.edited_action,
                }
                if edited
                else {}
            ),
        },
    )
    outcome = Outcome(proposal, events=[])
    approved = await session.scalar(
        select(func.count())
        .select_from(ProposalApproval)
        .where(ProposalApproval.proposal_id == proposal.id, ProposalApproval.decision == "APPROVE")
    )
    if approved == REQUIRED_STEPS[proposal.effective_level]:  # PC-05: count, not "all rows"
        proposal.decided_at = now
        final = (
            "EDITED_APPROVED"
            if proposal.edited_payload is not None or proposal.edited_action
            else "APPROVED"
        )
        await _execute(
            session,
            proposal,
            await _agent_code(session, proposal),
            approved_by=user.id,
            outcome=outcome,
            now=now,
            final_status=final,
        )
    else:
        outcome.events.append(_event(proposal, step_decided=step.row.step_no))
    return outcome


REVIEW_ROLES = "DUTY_OFFICER|SECURITY_OFFICER|HQ_CRISIS_DIRECTOR"  # advice and undo


async def reject(
    session: AsyncSession,
    user: CurrentUser,
    proposal_id: uuid.UUID,
    reason: str,
    now: datetime | None = None,
) -> Outcome:
    """Reject (AGT-03). Approvable proposals: whoever could decide the next step.
    Advice (level 4): a reviewer dismisses it. The reason is stored."""
    now = now or datetime.now(UTC)
    proposal = await _locked(session, proposal_id)
    if proposal.status != "PENDING":
        raise ProposalError(f"The proposal is {proposal.status}")
    if proposal.effective_level == 4:
        if not await approvals.user_has_role(
            session, user, REVIEW_ROLES, await _mission(session, proposal)
        ):
            raise approvals.ApprovalDeniedError(approvals.Verdict(False, 403, "Forbidden"))
    else:
        step = await _next_step(session, proposal)
        await approvals.decide(session, user, step.gate)
        step.row.decided_by = user.id
        step.row.decision = "REJECT"
        step.row.decided_at = now
    proposal.status = "REJECTED"
    proposal.rejection_reason = reason
    proposal.decided_at = now
    await session.flush()
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="PROPOSAL.REJECT",
        entity_type="agent_proposal",
        entity_id=str(proposal.id),
        details={"reason": reason},
    )
    return Outcome(proposal, events=[_event(proposal)])


async def use_alternative(
    session: AsyncSession,
    user: CurrentUser,
    proposal_id: uuid.UUID,
    index: int,
    *,
    undo_window_s: int,
) -> Outcome:
    """D-14: the original is SUPERSEDED and the alternative becomes a new proposal
    from the same agent, judged by the policy engine on its own, so it can never
    skip a higher approval level."""
    proposal = await _locked(session, proposal_id)
    if proposal.effective_level == 4:
        if proposal.status != "PENDING":
            raise ProposalError(f"The proposal is {proposal.status}")
        if not await approvals.user_has_role(
            session, user, REVIEW_ROLES, await _mission(session, proposal)
        ):
            raise approvals.ApprovalDeniedError(approvals.Verdict(False, 403, "Forbidden"))
    else:
        step = await _next_step(session, proposal)
        await approvals.decide(session, user, step.gate)
    if not 0 <= index < len(proposal.alternatives):
        raise ProposalError("No such alternative")
    alternative = proposal.alternatives[index]
    agent_code = await _agent_code(session, proposal)
    created = await create(
        session,
        ProposalIn(
            agent_code=agent_code,
            proposal_key=f"{proposal.proposal_key}:alt:{index}",
            action_type=str(alternative["action_type"]),
            title=str(alternative.get("label") or proposal.title),
            proposed_action=str(alternative.get("label") or alternative["action_type"]),
            action_payload=dict(alternative.get("action_payload") or {}),
            incident_id=proposal.incident_id,
            evidence=[
                *proposal.evidence,
                {
                    "text": f"Alternative chosen by a user: {alternative.get('rationale', '')}",
                    "source": "decision",
                },
            ],
            risk_if_no_action=proposal.risk_if_no_action,
            confidence=proposal.confidence,
        ),
        undo_window_s=undo_window_s,
    )
    proposal.status = "SUPERSEDED"
    proposal.superseded_by = created.proposal.id
    proposal.decided_at = datetime.now(UTC)
    await session.flush()
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="PROPOSAL.USE_ALTERNATIVE",
        entity_type="agent_proposal",
        entity_id=str(proposal.id),
        details={"index": index, "new_proposal_id": str(created.proposal.id)},
    )
    created.events.append(_event(proposal))
    return created


async def undo(
    session: AsyncSession, user: CurrentUser, proposal_id: uuid.UUID, now: datetime | None = None
) -> Outcome:
    """D-13: only level 1 proposals, only before undo_until."""
    now = now or datetime.now(UTC)
    proposal = await _locked(session, proposal_id)
    if proposal.status != "AUTO_EXECUTED" or proposal.undo_until is None:
        raise ProposalError("Only actions executed automatically with notice can be undone")
    if now >= proposal.undo_until:
        raise ProposalError("The undo window has closed")
    if not await approvals.user_has_role(
        session, user, REVIEW_ROLES, await _mission(session, proposal)
    ):
        raise approvals.ApprovalDeniedError(approvals.Verdict(False, 403, "Forbidden"))
    executed = await session.scalar(
        select(AuditLog.details)
        .where(
            AuditLog.action == "PROPOSAL.EXECUTE",
            AuditLog.entity_type == "agent_proposal",
            AuditLog.entity_id == str(proposal.id),
        )
        .order_by(AuditLog.chain_seq.desc())
        .limit(1)
    )
    if executed is None:
        raise ProposalError("Nothing to undo")
    ctx = actions.Context(
        proposal_id=proposal.id,
        incident_id=proposal.incident_id,
        agent_actor=_agent_actor(await _agent_code(session, proposal)),
        approved_by=user.id,
    )
    try:
        await actions.undo(session, proposal.action_type, dict(executed.get("result") or {}), ctx)
    except actions.ActionError as e:
        raise ProposalError(str(e)) from None
    proposal.status = "UNDONE"
    await session.flush()
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="PROPOSAL.UNDO",
        entity_type="agent_proposal",
        entity_id=str(proposal.id),
        details={"result": executed.get("result")},
    )
    return Outcome(proposal, events=[_event(proposal)])


async def expire_overdue(session: AsyncSession, now: datetime) -> list[Outcome]:
    """AGT-06, plan G-18: PENDING past deadline_at -> EXPIRED, audited, with an
    ESCALATION incident event and a notice for holders of the open step's role."""
    overdue = list(
        await session.scalars(
            select(AgentProposal)
            .where(
                AgentProposal.status == "PENDING",
                AgentProposal.deadline_at.is_not(None),
                AgentProposal.deadline_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    out = []
    for proposal in overdue:
        role = await session.scalar(
            select(ProposalApproval.required_role)
            .where(ProposalApproval.proposal_id == proposal.id, ProposalApproval.decision.is_(None))
            .order_by(ProposalApproval.step_no)
            .limit(1)
        )
        proposal.status = "EXPIRED"
        proposal.decided_at = now
        if proposal.incident_id is not None:
            session.add(
                IncidentEvent(
                    tenant_id=proposal.tenant_id,
                    incident_id=proposal.incident_id,
                    event_type="ESCALATION",
                    summary=f"Proposal not decided in time: {proposal.title}. Escalated to "
                    f"{(role or 'HQ').replace('|', ' or ')}.",
                    actor_type=EXPIRER.type,
                    actor_id=EXPIRER.id,
                    data={"proposal_id": str(proposal.id), "required_role": role},
                )
            )
        await session.flush()
        await audit.write(
            session,
            actor_type=EXPIRER.type,
            actor_id=EXPIRER.id,
            action="PROPOSAL.EXPIRE",
            entity_type="agent_proposal",
            entity_id=str(proposal.id),
            details={
                "deadline_at": proposal.deadline_at.isoformat() if proposal.deadline_at else None,
                "required_role": role,
            },
        )
        out.append(
            Outcome(proposal, events=[_event(proposal, "PROPOSAL_EXPIRED", required_role=role)])
        )
    return out


# --- kill switch and autonomy (D-17, AGT-07, AGT-08; ADMIN only, checked by the router) ----


async def set_paused(session: AsyncSession, user: CurrentUser, paused: bool) -> None:
    await session.execute(
        update(Tenant)
        .where(Tenant.id == session.info["tenant_id"])
        .values(
            agents_paused=paused,
            agents_paused_at=func.now() if paused else None,
            agents_paused_by=user.id if paused else None,
        )
    )
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="AGENTS.PAUSE" if paused else "AGENTS.RESUME",
        entity_type="tenant",
        entity_id=str(session.info["tenant_id"]),
    )


async def agents_paused(session: AsyncSession) -> bool:
    return bool(
        await session.scalar(
            text("SELECT agents_paused FROM tenant WHERE id = current_tenant_id()")
        )
    )


async def update_agent(
    session: AsyncSession,
    user: CurrentUser,
    code: str,
    *,
    autonomy_level: int | None,
    is_enabled: bool | None,
) -> Agent:
    agent = await session.scalar(select(Agent).where(Agent.code == code).with_for_update())
    if agent is None:
        raise LookupError("Agent not found")
    before = {"autonomy_level": agent.autonomy_level, "is_enabled": agent.is_enabled}
    if autonomy_level is not None:
        agent.autonomy_level = autonomy_level
    if is_enabled is not None:
        agent.is_enabled = is_enabled
    await session.flush()
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="AGENT.UPDATE",
        entity_type="agent",
        entity_id=code,
        details={
            "before": before,
            "after": {"autonomy_level": agent.autonomy_level, "is_enabled": agent.is_enabled},
        },
    )
    return agent
