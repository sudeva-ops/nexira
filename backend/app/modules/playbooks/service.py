"""Playbook services: definitions (Prompt 4); starting runs and approving gated
steps (Prompt 9). The steps themselves run in engine.py, in the worker."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.intel.models import Incident
from app.modules.playbooks.engine import timeline
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.tenancy.service import SYSTEM, Actor

START_ROLES = "DUTY_OFFICER|SECURITY_OFFICER"  # Prompt 9; agents start runs via approved proposals


@dataclass(frozen=True)
class StepIn:
    seq: int
    name: str
    action_type: str  # NOTIFY, CHECKIN, TASK, PARTNER_REQUEST, APPROVAL_GATE, BRIEFING
    action_config: dict[str, Any] = field(default_factory=dict)
    requires_approval_role: str | None = None  # mission scope from incident.mission_id (D-06)


async def ensure_playbook(
    session: AsyncSession,
    *,
    playbook_id: uuid.UUID,
    code: str,
    name: str,
    category: str,
    trigger_rules: dict[str, Any],
    steps: list[StepIn],
    step_ids: list[uuid.UUID],
    version: int = 1,
    actor: Actor = SYSTEM,
) -> bool:
    """Create a playbook version with its steps if it does not exist. Audited on create."""
    if len(step_ids) != len(steps):
        raise ValueError("one step id per step")
    tenant_id = session.info["tenant_id"]
    created = await session.scalar(
        insert(Playbook)
        .values(
            id=playbook_id,
            tenant_id=tenant_id,
            code=code,
            name=name,
            category=category,
            trigger_rules=trigger_rules,
            version=version,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "code", "version"])
        .returning(Playbook.id)
    )
    if created is None:
        return False
    await session.execute(
        insert(PlaybookStep).values(
            [
                {
                    "id": step_id,
                    "tenant_id": tenant_id,
                    "playbook_id": playbook_id,
                    "seq": s.seq,
                    "name": s.name,
                    "action_type": s.action_type,
                    "action_config": s.action_config,
                    "requires_approval_role": s.requires_approval_role,
                }
                for s, step_id in zip(steps, step_ids, strict=True)
            ]
        )
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.CREATE",
        entity_type="playbook",
        entity_id=str(playbook_id),
        details={"code": code, "version": version, "steps": len(steps)},
    )
    return True


class RunNotAllowedError(Exception):
    """The run cannot be started (unknown playbook, incident not ACTIVE)."""


async def active_playbook(session: AsyncSession, code: str) -> Playbook | None:
    return await session.scalar(
        select(Playbook)
        .where(Playbook.code == code, Playbook.is_active)
        .order_by(Playbook.version.desc())
        .limit(1)
    )


async def start_run(
    session: AsyncSession,
    *,
    playbook_code: str,
    incident_id: uuid.UUID,
    actor: Actor,
    started_by: uuid.UUID | None,
    started_by_type: str = "USER",
    proposal_id: uuid.UUID | None = None,
) -> PlaybookRun:
    """Create a RUNNING run with all steps PENDING. The worker executes it after the
    commit (PLAYBOOK_RUN_STARTED). One live run per playbook and incident: a second
    start hits playbook_run_live_uq and becomes a 409 (app/core/errors.py)."""
    playbook = await active_playbook(session, playbook_code)
    if playbook is None:
        raise RunNotAllowedError(f"No active playbook {playbook_code}")
    incident = await session.get(Incident, incident_id)
    if incident is None or incident.status != "ACTIVE":
        raise RunNotAllowedError("A playbook can only start for an ACTIVE incident")
    run = PlaybookRun(
        tenant_id=session.info["tenant_id"],
        playbook_id=playbook.id,
        incident_id=incident.id,
        started_by_type=started_by_type,
        started_by=started_by,
        proposal_id=proposal_id,
    )
    session.add(run)
    await session.flush()
    steps = await session.scalars(
        select(PlaybookStep)
        .where(PlaybookStep.playbook_id == playbook.id)
        .order_by(PlaybookStep.seq)
    )
    session.add_all(
        PlaybookRunStep(tenant_id=run.tenant_id, run_id=run.id, step_id=step.id) for step in steps
    )
    timeline(
        session,
        run,
        "PLAYBOOK_STEP",
        f"{playbook.code} · {playbook.name} started.",
        {"status": "RUNNING", "playbook": playbook.code},
        actor,
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.START",
        entity_type="playbook_run",
        entity_id=str(run.id),
        details={
            "playbook": playbook.code,
            "version": playbook.version,
            "incident": incident.reference,
            "started_by_type": started_by_type,
            "proposal_id": str(proposal_id) if proposal_id else None,
        },
    )
    await session.flush()
    return run


def run_started_event(run: PlaybookRun) -> Event:
    return Event(
        type="PLAYBOOK_RUN_STARTED",
        tenant_id=run.tenant_id,
        payload={"run_id": str(run.id), "incident_id": str(run.incident_id), "status": run.status},
        source="api",
    )


async def _gate(
    session: AsyncSession, run: PlaybookRun, run_step: PlaybookRunStep, step: PlaybookStep
) -> approvals.Gate:
    """The approval gate for a run step, with the run and its steps locked."""
    playbook = await session.get_one(Playbook, run.playbook_id)
    mission_id = None
    if run.incident_id is not None:
        mission_id = await session.scalar(
            select(Incident.mission_id).where(Incident.id == run.incident_id)
        )
    others = await session.scalars(
        select(PlaybookRunStep.approved_by).where(
            PlaybookRunStep.run_id == run.id,
            PlaybookRunStep.id != run_step.id,
            PlaybookRunStep.approved_by.is_not(None),
        )
    )
    return approvals.Gate(
        subject=f"{playbook.code} step {step.seq}",
        required_role=step.requires_approval_role or "",
        mission_id=mission_id,
        decided=run_step.approved_by is not None or run_step.status in ("DONE", "SKIPPED"),
        open=run.status == "AWAITING_APPROVAL" and run_step.status == "AWAITING_APPROVAL",
        deciders_of_other_steps=frozenset(u for u in others if u is not None),
    )


class StepNotFoundError(LookupError):
    pass


async def _locked_step(
    session: AsyncSession, run_id: uuid.UUID, step_id: uuid.UUID
) -> tuple[PlaybookRun, PlaybookRunStep, PlaybookStep]:
    run = await session.scalar(
        select(PlaybookRun).where(PlaybookRun.id == run_id).with_for_update()
    )
    if run is None:
        raise StepNotFoundError("Run not found")
    row = (
        await session.execute(
            select(PlaybookRunStep, PlaybookStep)
            .join(PlaybookStep, PlaybookStep.id == PlaybookRunStep.step_id)
            .where(PlaybookRunStep.run_id == run.id, PlaybookRunStep.step_id == step_id)
            .with_for_update(of=PlaybookRunStep)
        )
    ).one_or_none()
    if row is None:
        raise StepNotFoundError("Step not found in this run")
    return run, row[0], row[1]


async def approve_step(
    session: AsyncSession, user: CurrentUser, run_id: uuid.UUID, step_id: uuid.UUID
) -> PlaybookRun:
    """PB-03: approve a gated step. Every check is approvals.decide() (D-05, D-16);
    ApprovalDeniedError becomes 403 or 409. The worker continues the run after the
    commit (PLAYBOOK_STEP_APPROVED)."""
    run, run_step, step = await _locked_step(session, run_id, step_id)
    if not step.requires_approval_role:
        raise approvals.ApprovalDeniedError(
            approvals.Verdict(False, 409, f"Step {step.seq} does not need an approval")
        )
    gate = await _gate(session, run, run_step, step)
    await approvals.decide(session, user, gate)

    run_step.approved_by = user.id
    run.status = "RUNNING"
    actor = Actor(type="USER", id=str(user.id))
    roles = await approvals.roles_of(session, user.id)
    held = [
        f"{r.code}{' · ' + r.mission_code if r.mission_code else ''}"
        for r in roles
        if r.code in approvals.parse_role_codes(gate.required_role)
    ]
    timeline(
        session,
        run,
        "DECISION",
        f"Step {step.seq} · {step.name}: approved by {user.display_name} ({', '.join(held)}).",
        {"step_id": str(step.id), "seq": step.seq, "decision": "APPROVE"},
        actor,
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.STEP_APPROVE",
        entity_type="playbook_run",
        entity_id=str(run.id),
        details={
            "seq": step.seq,
            "required_role": gate.required_role,
            "mission_id": str(gate.mission_id) if gate.mission_id else None,
            "held": held,
        },
    )
    await session.flush()
    return run


def step_approved_event(run: PlaybookRun, step_id: uuid.UUID) -> Event:
    return Event(
        type="PLAYBOOK_STEP_APPROVED",
        tenant_id=run.tenant_id,
        payload={
            "run_id": str(run.id),
            "incident_id": str(run.incident_id),
            "step_id": str(step_id),
            "status": run.status,
        },
        source="api",
    )


async def approvable_steps(
    session: AsyncSession, user: CurrentUser, run_id: uuid.UUID
) -> list[uuid.UUID]:
    """Steps of a run this user may approve now (plan G-07), by the same
    approvals.can_decide() that approve_step() enforces."""
    run = await session.get(PlaybookRun, run_id)
    if run is None:
        return []
    rows = (
        await session.execute(
            select(PlaybookRunStep, PlaybookStep)
            .join(PlaybookStep, PlaybookStep.id == PlaybookRunStep.step_id)
            .where(
                PlaybookRunStep.run_id == run.id,
                PlaybookRunStep.status == "AWAITING_APPROVAL",
                PlaybookStep.requires_approval_role.is_not(None),
            )
        )
    ).all()
    allowed = []
    for run_step, step in rows:
        verdict = await approvals.can_decide(
            session, user, await _gate(session, run, run_step, step)
        )
        if verdict.allowed:
            allowed.append(step.id)
    return allowed


async def may_start(session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID) -> bool:
    """Prompt 9: DUTY_OFFICER or SECURITY_OFFICER, unscoped or for the incident's mission."""
    mission_id = await session.scalar(select(Incident.mission_id).where(Incident.id == incident_id))
    return await approvals.user_has_role(session, user, START_ROLES, mission_id)
