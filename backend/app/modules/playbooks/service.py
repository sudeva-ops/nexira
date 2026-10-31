"""Playbook services: definitions (Prompt 4); starting runs and approving gated
steps (Prompt 9); arming a run ahead of a forecast landfall (HZ-05, D-38,
plan-pilot-hz §4). The steps themselves run in engine.py, in the worker."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.hazards import clock, forecast
from app.modules.intel import hazards
from app.modules.intel.models import Incident
from app.modules.playbooks.engine import timeline
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.tenancy.service import SYSTEM, Actor

log = logging.getLogger(__name__)

START_ROLES = "DUTY_OFFICER|SECURITY_OFFICER"  # Prompt 9; agents start runs via approved proposals
LIVE = ("SCHEDULED", "RUNNING", "AWAITING_APPROVAL")  # playbook_run_live_uq (G-8)
ARMED = Actor(type="SYSTEM", id="playbook.armed")
ARM_MARGIN = timedelta(seconds=5)
FORECAST_CHANGED = timedelta(hours=1)  # §43 Q4: "forecast changed" from an hour


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


async def retire_older_versions(
    session: AsyncSession, code: str, current: int, actor: Actor = SYSTEM
) -> list[int]:
    """Deactivate every version of a playbook below current, so only one version is
    proposed and started (the Response Planner offers every active playbook). Runs
    already started keep their own version's steps. Audited once per version retired."""
    retired = list(
        await session.scalars(
            update(Playbook)
            .where(Playbook.code == code, Playbook.version < current, Playbook.is_active)
            .values(is_active=False)
            .returning(Playbook.version)
        )
    )
    for version in sorted(retired):
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="PLAYBOOK.RETIRE",
            entity_type="playbook",
            entity_id=f"{code} v{version}",
            details={"code": code, "version": version, "replaced_by": current},
        )
    return sorted(retired)


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
    start hits playbook_run_live_uq and becomes a 409 (app/core/errors.py). If the
    playbook is armed for the incident, the armed run starts now instead (plan §4)."""
    playbook, incident = await _startable(session, playbook_code, incident_id)
    armed = await session.scalar(
        select(PlaybookRun)
        .where(
            PlaybookRun.playbook_id == playbook.id,
            PlaybookRun.incident_id == incident.id,
            PlaybookRun.status == "SCHEDULED",
        )
        .with_for_update()
    )
    if armed is not None:
        return await _start_armed(session, armed, incident, actor, reason="started now")
    run = await _new_run(
        session,
        playbook,
        incident,
        started_by_type=started_by_type,
        started_by=started_by,
        proposal_id=proposal_id,
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


async def _startable(
    session: AsyncSession, playbook_code: str, incident_id: uuid.UUID
) -> tuple[Playbook, Incident]:
    playbook = await active_playbook(session, playbook_code)
    if playbook is None:
        raise RunNotAllowedError(f"No active playbook {playbook_code}")
    incident = await session.get(Incident, incident_id)
    if incident is None or incident.status != "ACTIVE":
        raise RunNotAllowedError("A playbook can only start for an ACTIVE incident")
    return playbook, incident


async def _new_run(
    session: AsyncSession,
    playbook: Playbook,
    incident: Incident,
    *,
    started_by_type: str,
    started_by: uuid.UUID | None,
    proposal_id: uuid.UUID | None,
    status: str = "RUNNING",
    scheduled_for: datetime | None = None,
) -> PlaybookRun:
    """The run row and its PENDING steps, of the playbook's current version."""
    run = PlaybookRun(
        tenant_id=session.info["tenant_id"],
        playbook_id=playbook.id,
        incident_id=incident.id,
        status=status,
        scheduled_for=scheduled_for,
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
    return run


# --- Armed runs (HZ-05, PC-24; plan-pilot-hz §4) ------------------------------------------


@dataclass(frozen=True)
class Armed:
    run: PlaybookRun
    started_now: bool  # the arming time had passed (G-7): the run started at once


async def arm_run(
    session: AsyncSession,
    *,
    playbook_code: str,
    incident_id: uuid.UUID,
    actor: Actor,
    started_by: uuid.UUID | None,
    started_by_type: str = "USER",
    proposal_id: uuid.UUID | None = None,
    hours_before_landfall: int = hazards.LANDFALL_LEAD_H,
    expected_landfall: datetime | None = None,
) -> Armed:
    """Arm a playbook for a cyclone forecast: it starts by itself hours_before_landfall
    before the forecast landfall (§43 Q4), on the hazard clock (G-9). The same function
    for a person and for an approved ARM_PLAYBOOK proposal. If that time has passed,
    the run starts at once (G-7). The time never moves: a newer forecast shows as
    "forecast changed" against the landfall recorded here. An approved proposal passes
    the landfall its approvers read (expected_landfall): if the forecast has moved by an
    hour or more since, nothing is armed (review of Prompt 55, M1)."""
    playbook, incident = await _startable(session, playbook_code, incident_id)
    landfall = await forecast.landfall_of(session, incident.id)
    if incident.category != "TROPICAL_CYCLONE" or landfall is None:
        raise RunNotAllowedError("A playbook can only be armed for a cyclone forecast")
    if expected_landfall is not None and abs(landfall - expected_landfall) >= FORECAST_CHANGED:
        raise RunNotAllowedError(
            f"The forecast changed since the proposal: landfall now {landfall:%d %b %H:%M} UTC"
        )
    live = await session.scalar(
        select(PlaybookRun.status).where(
            PlaybookRun.playbook_id == playbook.id,
            PlaybookRun.incident_id == incident.id,
            PlaybookRun.status.in_(LIVE),
        )
    )
    if live is not None:
        raise RunNotAllowedError(f"{playbook.code} is already {live.lower()} for this incident")
    due = landfall - timedelta(hours=hours_before_landfall)
    now = await clock.hazard_now(session)
    if landfall <= now.now:
        raise RunNotAllowedError("Landfall has passed; start the playbook instead")
    # A margin, so the database's own clock never sees a time already past (review L6).
    if due <= now.now + ARM_MARGIN:
        run = await start_run(
            session,
            playbook_code=playbook_code,
            incident_id=incident.id,
            actor=actor,
            started_by=started_by,
            started_by_type=started_by_type,
            proposal_id=proposal_id,
        )
        timeline(
            session,
            run,
            "PLAYBOOK_STEP",
            f"{playbook.code}: the arming time ({hours_before_landfall} h before landfall) had "
            "passed, so it started at once.",
            {"armed_for_landfall_at": landfall.isoformat(), "late": True},
            actor,
        )
        await session.flush()
        return Armed(run, started_now=True)
    run = await _new_run(
        session,
        playbook,
        incident,
        started_by_type=started_by_type,
        started_by=started_by,
        proposal_id=proposal_id,
        status="SCHEDULED",
        scheduled_for=due,
    )
    timeline(
        session,
        run,
        "PLAYBOOK_STEP",
        f"{playbook.code} · {playbook.name} armed: starts {due:%d %b %H:%M} UTC "
        f"({hours_before_landfall} h before landfall).",
        {
            "status": "SCHEDULED",
            "playbook": playbook.code,
            "scheduled_for": due.isoformat(),
            "armed_for_landfall_at": landfall.isoformat(),
        },
        actor,
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.ARM",
        entity_type="playbook_run",
        entity_id=str(run.id),
        details={
            "playbook": playbook.code,
            "version": playbook.version,
            "incident": incident.reference,
            "scheduled_for": due.isoformat(),
            "landfall_at": landfall.isoformat(),
            "hours_before_landfall": hours_before_landfall,
            "demo_advance_h": now.demo_advance_h,
            "started_by_type": started_by_type,
            "proposal_id": str(proposal_id) if proposal_id else None,
        },
    )
    await session.flush()
    return Armed(run, started_now=False)


async def _start_armed(
    session: AsyncSession,
    run: PlaybookRun,
    incident: Incident,
    actor: Actor,
    *,
    reason: str,
    late_by: timedelta | None = None,
) -> PlaybookRun:
    """SCHEDULED -> RUNNING with the run locked; the database writes started_at (G-2)."""
    playbook = await session.get_one(Playbook, run.playbook_id)
    run.status = "RUNNING"
    late = ""
    if late_by is not None and late_by >= timedelta(minutes=1):
        late = f", {int(late_by.total_seconds() // 60)} min after its time"
    timeline(
        session,
        run,
        "PLAYBOOK_STEP",
        f"{playbook.code} · {playbook.name} started ({reason}{late}).",
        {"status": "RUNNING", "playbook": playbook.code, "armed": True},
        actor,
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.ARMED_START",
        entity_type="playbook_run",
        entity_id=str(run.id),
        details={
            "playbook": playbook.code,
            "incident": incident.reference,
            "reason": reason,
            "scheduled_for": run.scheduled_for.isoformat() if run.scheduled_for else None,
            "late_s": int(late_by.total_seconds()) if late_by else 0,
        },
    )
    await session.flush()
    await session.refresh(run)
    return run


async def _disarm(
    session: AsyncSession, run: PlaybookRun, actor: Actor, *, reason: str
) -> PlaybookRun:
    playbook = await session.get_one(Playbook, run.playbook_id)
    run.status = "DISARMED"
    run.completed_at = func.now()
    timeline(
        session,
        run,
        "PLAYBOOK_STEP",
        f"{playbook.code} · {playbook.name} disarmed ({reason}).",
        {"status": "DISARMED", "playbook": playbook.code},
        actor,
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.DISARM",
        entity_type="playbook_run",
        entity_id=str(run.id),
        details={"playbook": playbook.code, "reason": reason},
    )
    await session.flush()
    await session.refresh(run)
    return run


class RunStateError(Exception):
    """The run is not armed (any more): a 409."""


async def _locked_armed(
    session: AsyncSession, user: CurrentUser, run_id: uuid.UUID
) -> tuple[PlaybookRun, uuid.UUID]:
    """The roles first, unlocked, so nobody without them can hold the row (review of
    Prompt 55, L5); then the run locked FOR UPDATE and checked SCHEDULED, so a person's
    "start now" and the worker never both start it (review of Prompt 54, L7)."""
    incident_id = await session.scalar(
        select(PlaybookRun.incident_id).where(PlaybookRun.id == run_id)
    )
    if incident_id is None:
        raise StepNotFoundError("Run not found")
    if not await may_arm(session, user, incident_id):
        raise PermissionError("Forbidden")
    run = await session.scalar(
        select(PlaybookRun).where(PlaybookRun.id == run_id).with_for_update()
    )
    if run is None or run.incident_id != incident_id:
        raise StepNotFoundError("Run not found")
    if run.status != "SCHEDULED":
        raise RunStateError(f"The run is {run.status.lower()}, not armed")
    return run, incident_id


async def may_arm(session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID) -> bool:
    """G-1: arming, starting an armed run and disarming need START_ROLES, as starting."""
    return await may_start(session, user, incident_id)


@dataclass(frozen=True)
class ArmingPermissions:
    arm: bool = False  # may arm PB-06 (or another playbook) for this cyclone forecast
    start: bool = False  # may start its armed run now
    disarm: bool = False


async def arming_permissions(
    session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID
) -> ArmingPermissions:
    """For the screen (HZ-09, HZ-10): what the endpoints would allow now."""
    incident = await session.get(Incident, incident_id)
    if incident is None or not await may_arm(session, user, incident_id):
        return ArmingPermissions()
    armed = await session.scalar(
        select(PlaybookRun.id)
        .where(PlaybookRun.incident_id == incident_id, PlaybookRun.status == "SCHEDULED")
        .limit(1)
    )
    active = incident.status == "ACTIVE"
    landfall = await forecast.landfall_of(session, incident_id)
    cyclone = incident.category == "TROPICAL_CYCLONE" and landfall is not None
    return ArmingPermissions(
        arm=active and cyclone and armed is None,
        start=active and armed is not None,
        disarm=armed is not None,
    )


async def start_armed_now(
    session: AsyncSession, user: CurrentUser, run_id: uuid.UUID
) -> PlaybookRun:
    run, incident_id = await _locked_armed(session, user, run_id)
    incident = await session.get_one(Incident, incident_id)
    if incident.status != "ACTIVE":
        raise RunStateError("A playbook can only start for an ACTIVE incident")
    return await _start_armed(
        session, run, incident, Actor(type="USER", id=str(user.id)), reason="started now"
    )


async def disarm(session: AsyncSession, user: CurrentUser, run_id: uuid.UUID) -> PlaybookRun:
    run, _ = await _locked_armed(session, user, run_id)
    return await _disarm(
        session, run, Actor(type="USER", id=str(user.id)), reason=f"by {user.display_name}"
    )


async def start_due(session: AsyncSession) -> list[PlaybookRun]:
    """The worker's pass (plan §4): every SCHEDULED run whose time has come starts, late
    if the worker was down; a run whose incident is no longer ACTIVE is disarmed instead.
    SKIP LOCKED: two workers never take the same run.

    The demo clock's advance counts only for runs armed while that demo was running, so a
    scene never brings a real armed run forward (review of Prompt 55, M3). Each run is
    taken in its own savepoint: one that fails is logged and left for the next pass,
    and the others still start (M4)."""
    if not await session.scalar(
        select(PlaybookRun.id).where(PlaybookRun.status == "SCHEDULED").limit(1)
    ):
        return []
    real = datetime.now(UTC)
    now = await clock.hazard_now(session, real)
    demo_since = await clock.demo_since(session)
    in_demo = PlaybookRun.started_at >= demo_since if demo_since else false()
    due = list(
        await session.scalars(
            select(PlaybookRun)
            .where(
                PlaybookRun.status == "SCHEDULED",
                or_(
                    PlaybookRun.scheduled_for <= real,
                    and_(in_demo, PlaybookRun.scheduled_for <= now.now),
                ),
            )
            .order_by(PlaybookRun.scheduled_for)
            .with_for_update(skip_locked=True)
        )
    )
    changed = []
    for run in due:
        try:
            async with session.begin_nested():
                changed.append(await _due_run(session, run, real, now))
        except Exception:
            log.exception("armed run %s could not start; left for the next pass", run.id)
    return changed


async def _due_run(
    session: AsyncSession, run: PlaybookRun, real: datetime, now: clock.HazardTime
) -> PlaybookRun:
    if run.incident_id is None or run.scheduled_for is None:
        raise RunStateError("an armed run has an incident and a time")
    incident = await session.get_one(Incident, run.incident_id)
    if incident.status != "ACTIVE":
        return await _disarm(
            session, run, ARMED, reason=f"incident {incident.status.lower()} at its time"
        )
    # Lateness in real time only: a demo jump is not lateness.
    late_by = real - run.scheduled_for if now.demo_advance_h == 0 else None
    return await _start_armed(
        session,
        run,
        incident,
        ARMED,
        reason=f"{hazards.LANDFALL_LEAD_H} h before landfall",
        late_by=late_by,
    )


def run_armed_event(run: PlaybookRun) -> Event:
    return Event(
        type="PLAYBOOK_RUN_ARMED",
        tenant_id=run.tenant_id,
        payload={"run_id": str(run.id), "incident_id": str(run.incident_id), "status": run.status},
        source="api",
    )


def run_disarmed_event(run: PlaybookRun) -> Event:
    return Event(
        type="PLAYBOOK_RUN_DISARMED",
        tenant_id=run.tenant_id,
        payload={"run_id": str(run.id), "incident_id": str(run.incident_id), "status": run.status},
        source="api",
    )


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
        # FOR SHARE: exposure cannot move the incident to another mission between
        # this check and the commit. Locked after the run, as everywhere else.
        mission_id = await session.scalar(
            select(Incident.mission_id)
            .where(Incident.id == run.incident_id)
            .with_for_update(read=True)
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
        and (r.mission_id is None or r.mission_id == gate.mission_id)
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
