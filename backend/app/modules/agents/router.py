"""Agent proposals and agents API (AGT-01..08). Changes need human sign-off (D-29).

- Reading proposals and agents: any user with a role.
- Deciding: approvals.decide() inside the proposals service (D-05, D-16);
  refusals are 403 or 409 (app/core/errors.py).
- Autonomy, enabling and the kill switch: ADMIN only (AGT-07, AGT-08, D-17).
"""

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.approvals import require_roles
from app.core.config import Settings, get_settings
from app.core.events import Publisher, get_publisher
from app.core.security import CurrentUser, current_user, get_db
from app.modules.agents import proposals
from app.modules.agents.agents import AGENTS
from app.modules.agents.models import ActionPolicy, Agent, AgentProposal, ProposalApproval
from app.modules.agents.schemas import (
    ActivityOut,
    AgentActionOut,
    AgentOut,
    AgentPatch,
    AgentsStateOut,
    AlternativeIn,
    ApprovalStepOut,
    EditApproveIn,
    ProposalOut,
    RejectIn,
)
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["agents"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
# Agents and the kill switch are tenant-wide: an unscoped ADMIN grant only.
Admin = Annotated[CurrentUser, Depends(require_roles("ADMIN", mission_id=None))]
User = Annotated[CurrentUser, Depends(current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Pub = Annotated[Publisher, Depends(get_publisher)]
Config = Annotated[Settings, Depends(get_settings)]
Status = Literal[
    "PENDING",
    "APPROVED",
    "EDITED_APPROVED",
    "REJECTED",
    "AUTO_EXECUTED",
    "UNDONE",
    "EXPIRED",
    "SUPERSEDED",
    "FAILED",
]


async def proposal_out(
    session: AsyncSession, user: CurrentUser, rows: list[AgentProposal]
) -> list[ProposalOut]:
    if not rows:
        return []
    ids = [p.id for p in rows]
    agents = {a.id: a for a in await session.scalars(select(Agent))}
    found = await session.execute(
        select(Incident.id, Incident.reference).where(
            Incident.id.in_([p.incident_id for p in rows if p.incident_id])
        )
    )
    incidents: dict[uuid.UUID, str] = {row.id: row.reference for row in found}
    decider = aliased(AppUser)
    steps: dict[uuid.UUID, list[ApprovalStepOut]] = {}
    for row, name in await session.execute(
        select(ProposalApproval, decider.display_name)
        .outerjoin(decider, decider.id == ProposalApproval.decided_by)
        .where(ProposalApproval.proposal_id.in_(ids))
        .order_by(ProposalApproval.step_no)
    ):
        steps.setdefault(row.proposal_id, []).append(
            ApprovalStepOut(
                step_no=row.step_no,
                required_role=row.required_role,
                decision=row.decision,
                decided_by=row.decided_by,
                decided_by_name=name,
                decided_at=row.decided_at,
            )
        )
    out = []
    for p in rows:
        agent = agents.get(p.agent_id)
        out.append(
            ProposalOut(
                **{k: getattr(p, k) for k in ProposalOut.model_fields if hasattr(p, k)},
                agent_code=agent.code if agent else "UNKNOWN",
                agent_name=agent.name if agent else "Unknown",
                incident_reference=incidents.get(p.incident_id) if p.incident_id else None,
                approvals=steps.get(p.id, []),
                can_decide=await proposals.can_decide(session, user, p),
                can_edit=await proposals.can_edit(session, user, p),
                can_dismiss=await proposals.can_dismiss(session, user, p),
                can_undo=await proposals.can_undo(session, user, p),
            )
        )
    return out


async def _one(session: AsyncSession, user: CurrentUser, proposal_id: uuid.UUID) -> ProposalOut:
    proposal = await session.get(AgentProposal, proposal_id, populate_existing=True)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return (await proposal_out(session, user, [proposal]))[0]


async def _finish(
    session: AsyncSession, user: CurrentUser, publisher: Publisher, outcome: proposals.Outcome
) -> ProposalOut:
    await session.commit()
    for event in outcome.events:
        try:
            await publisher.publish(event)
        except Exception:
            log.exception("publishing %s failed after commit", event.type)
    return await _one(session, user, outcome.proposal.id)


def _conflict(e: Exception) -> HTTPException:
    if isinstance(e, LookupError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return HTTPException(status.HTTP_409_CONFLICT, str(e))


@router.get("/proposals")
async def list_proposals(
    user: Reader,
    session: Db,
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    incident_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ProposalOut]:
    """Newest first. can_decide tells the UI whether to show decision buttons."""
    query = select(AgentProposal).order_by(AgentProposal.created_at.desc()).limit(limit)
    if status_filter is not None:
        query = query.where(AgentProposal.status == status_filter)
    if incident_id is not None:
        query = query.where(AgentProposal.incident_id == incident_id)
    return await proposal_out(session, user, list(await session.scalars(query)))


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: uuid.UUID, user: Reader, session: Db) -> ProposalOut:
    return await _one(session, user, proposal_id)


@router.post("/proposals/{proposal_id}/approve")
async def approve(proposal_id: uuid.UUID, user: User, session: Db, publisher: Pub) -> ProposalOut:
    try:
        outcome = await proposals.approve(session, user, proposal_id)
    except (proposals.ProposalError, LookupError) as e:
        raise _conflict(e) from None
    return await _finish(session, user, publisher, outcome)


@router.post("/proposals/{proposal_id}/edit-approve")
async def edit_approve(
    proposal_id: uuid.UUID, body: EditApproveIn, user: User, session: Db, publisher: Pub
) -> ProposalOut:
    if body.edited_action is None and body.edited_payload is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing edited")
    try:
        outcome = await proposals.approve(
            session,
            user,
            proposal_id,
            edited_action=body.edited_action,
            edited_payload=body.edited_payload,
        )
    except (proposals.ProposalError, LookupError) as e:
        raise _conflict(e) from None
    return await _finish(session, user, publisher, outcome)


@router.post("/proposals/{proposal_id}/reject")
async def reject(
    proposal_id: uuid.UUID, body: RejectIn, user: User, session: Db, publisher: Pub
) -> ProposalOut:
    try:
        outcome = await proposals.reject(session, user, proposal_id, body.reason)
    except (proposals.ProposalError, LookupError) as e:
        raise _conflict(e) from None
    return await _finish(session, user, publisher, outcome)


@router.post("/proposals/{proposal_id}/use-alternative")
async def use_alternative(
    proposal_id: uuid.UUID,
    body: AlternativeIn,
    user: User,
    session: Db,
    publisher: Pub,
    settings: Config,
) -> ProposalOut:
    """Returns the new proposal (D-14)."""
    try:
        outcome = await proposals.use_alternative(
            session, user, proposal_id, body.index, undo_window_s=settings.undo_window_s
        )
    except (proposals.ProposalError, LookupError) as e:
        raise _conflict(e) from None
    return await _finish(session, user, publisher, outcome)


@router.post("/proposals/{proposal_id}/undo")
async def undo(proposal_id: uuid.UUID, user: User, session: Db, publisher: Pub) -> ProposalOut:
    try:
        outcome = await proposals.undo(session, user, proposal_id)
    except (proposals.ProposalError, LookupError) as e:
        raise _conflict(e) from None
    return await _finish(session, user, publisher, outcome)


async def _agents_state(session: AsyncSession) -> AgentsStateOut:
    decided_ok = AgentProposal.status.in_(("APPROVED", "EDITED_APPROVED"))
    counts = {
        agent_id: (pending, total, accepted, rejected)
        for agent_id, pending, total, accepted, rejected in await session.execute(
            select(
                AgentProposal.agent_id,
                func.count().filter(AgentProposal.status == "PENDING"),
                func.count(),
                func.count().filter(decided_ok),
                func.count().filter(AgentProposal.status == "REJECTED"),
            ).group_by(AgentProposal.agent_id)
        )
    }
    watches = {agent.code: sorted(agent.observes) for agent in AGENTS}
    proposes = {agent.code: agent.proposes for agent in AGENTS}
    policies = {p.action_type: p for p in await session.scalars(select(ActionPolicy))}

    def actions(code: str) -> list[AgentActionOut]:
        out = []
        for action_type in proposes.get(code, ()):
            policy = policies.get(action_type)
            out.append(
                AgentActionOut(
                    action_type=action_type,
                    level=policy.min_autonomy_level if policy else 4,
                    approver_roles=list(policy.approver_roles) if policy else [],
                    decision_deadline_s=policy.decision_deadline_s if policy else None,
                )
            )
        return out

    agents = await session.scalars(select(Agent).order_by(Agent.code))
    return AgentsStateOut(
        paused=await proposals.agents_paused(session),
        agents=[
            AgentOut(
                code=a.code,
                name=a.name,
                description=a.description,
                autonomy_level=a.autonomy_level,
                is_enabled=a.is_enabled,
                model_ref=a.model_ref,
                watches=watches.get(a.code, []),
                actions=actions(a.code),
                proposals_pending=counts.get(a.id, (0, 0, 0, 0))[0],
                proposals_total=counts.get(a.id, (0, 0, 0, 0))[1],
                accepted_pct=_pct(*counts.get(a.id, (0, 0, 0, 0))[2:]),
            )
            for a in agents
        ],
    )


def _pct(accepted: int, rejected: int) -> float | None:
    decided = accepted + rejected
    return round(100 * accepted / decided, 1) if decided else None


_ACTIVITY_TEXT = {
    "PROPOSAL.CREATE": "proposed",
    "PROPOSAL.EXECUTE": "executed",
    "PROPOSAL.FAIL": "failed",
    "PROPOSAL.APPROVE": "approved",
    "PROPOSAL.EDIT_APPROVE": "edited and approved",
    "PROPOSAL.REJECT": "rejected",
    "PROPOSAL.USE_ALTERNATIVE": "chose an alternative for",
    "PROPOSAL.UNDO": "undid",
    "PROPOSAL.EXPIRE": "expired",
    "AGENTS.PAUSE": "paused all agents",
    "AGENTS.RESUME": "resumed all agents",
    "AGENT.UPDATE": "changed the autonomy or status of",
}


@router.get("/agents/activity")
async def agent_activity(
    _user: Reader, session: Db, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[ActivityOut]:
    """DQ-06: the latest agent and decision activity, newest first.

    An explicit exception to plan G-06 (unfiltered audit reads are ADMIN-only): it
    reads only the agent and decision actions listed in _ACTIVITY_TEXT and returns
    a fixed projection (agent name, "Human" or "System", a verb, the proposal
    title or agent name), never audit details or user ids."""
    rows = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.action.in_(list(_ACTIVITY_TEXT)))
            .order_by(AuditLog.chain_seq.desc())
            .limit(limit)
        )
    )
    proposal_ids = [
        uuid.UUID(r.entity_id) for r in rows if r.entity_type == "agent_proposal" and r.entity_id
    ]
    titles = dict(
        (
            await session.execute(
                select(AgentProposal.id, AgentProposal.title).where(
                    AgentProposal.id.in_(proposal_ids)
                )
            )
        ).all()
    )
    names = {a.code: a.name for a in await session.scalars(select(Agent))}
    out = []
    for r in rows:
        proposal_id = (
            uuid.UUID(r.entity_id) if r.entity_type == "agent_proposal" and r.entity_id else None
        )
        actor = (
            names.get(r.actor_id or "", r.actor_id or "Agent")
            if r.actor_type == "AGENT"
            else "Human"
            if r.actor_type == "USER"
            else "System"
        )
        verb = _ACTIVITY_TEXT[r.action]
        if r.action == "AGENT.UPDATE":
            verb = f"{verb} {names.get(r.entity_id or '', r.entity_id or 'an agent')}"
        out.append(
            ActivityOut(
                occurred_at=r.occurred_at,
                actor=actor,
                action=r.action,
                proposal_id=proposal_id,
                text=f"{verb} {titles.get(proposal_id, '')}".strip() if proposal_id else verb,
            )
        )
    return out


@router.get("/agents")
async def list_agents(_user: Reader, session: Db) -> AgentsStateOut:
    """The roster (any role may read it; changing it is ADMIN only)."""
    return await _agents_state(session)


@router.patch("/agents/{code}")
async def update_agent(
    code: str, body: AgentPatch, user: Admin, session: Db, publisher: Pub
) -> AgentsStateOut:
    try:
        await proposals.update_agent(
            session, user, code, autonomy_level=body.autonomy_level, is_enabled=body.is_enabled
        )
    except LookupError as e:
        raise _conflict(e) from None
    await session.commit()
    return await _agents_state(session)


@router.post("/agents/pause-all")
async def pause_all(user: Admin, session: Db) -> AgentsStateOut:
    """D-17: new proposals are refused; pending ones can still be decided."""
    await proposals.set_paused(session, user, True)
    await session.commit()
    return await _agents_state(session)


@router.post("/agents/resume-all")
async def resume_all(user: Admin, session: Db) -> AgentsStateOut:
    await proposals.set_paused(session, user, False)
    await session.commit()
    return await _agents_state(session)
