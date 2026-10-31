"""Read queries for playbooks and runs (RLS scopes every query)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.intel.models import Incident
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.playbooks.schemas import PlaybookOut, RunOut, RunStepOut, StepOut
from app.modules.tenancy.models import AppUser


def _step(step: PlaybookStep) -> StepOut:
    return StepOut(
        id=step.id,
        seq=step.seq,
        name=step.name,
        action_type=step.action_type,
        requires_approval_role=step.requires_approval_role,
    )


async def list_playbooks(session: AsyncSession) -> list[PlaybookOut]:
    playbooks = list(
        await session.scalars(
            select(Playbook).where(Playbook.is_active).order_by(Playbook.code, Playbook.version)
        )
    )
    steps = await session.scalars(select(PlaybookStep).order_by(PlaybookStep.seq))
    by_playbook: dict[uuid.UUID, list[StepOut]] = {}
    for step in steps:
        by_playbook.setdefault(step.playbook_id, []).append(_step(step))
    return [
        PlaybookOut(
            id=p.id,
            code=p.code,
            name=p.name,
            category=p.category,
            version=p.version,
            trigger_rules=p.trigger_rules,
            steps=by_playbook.get(p.id, []),
        )
        for p in playbooks
    ]


async def _run_out(session: AsyncSession, run: PlaybookRun) -> RunOut:
    playbook = await session.get_one(Playbook, run.playbook_id)
    incident = await session.get(Incident, run.incident_id) if run.incident_id else None
    starter = await session.get(AppUser, run.started_by) if run.started_by else None
    approver = aliased(AppUser)
    rows = await session.execute(
        select(PlaybookRunStep, PlaybookStep, approver.display_name)
        .join(PlaybookStep, PlaybookStep.id == PlaybookRunStep.step_id)
        .outerjoin(approver, approver.id == PlaybookRunStep.approved_by)
        .where(PlaybookRunStep.run_id == run.id)
        .order_by(PlaybookStep.seq)
    )
    return RunOut(
        id=run.id,
        playbook_code=playbook.code,
        playbook_name=playbook.name,
        incident_id=run.incident_id,
        incident_reference=incident.reference if incident else None,
        status=run.status,
        started_by_type=run.started_by_type,
        started_by_name=starter.display_name if starter else None,
        proposal_id=run.proposal_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        scheduled_for=run.scheduled_for,
        steps=[
            RunStepOut(
                **_step(step).model_dump(),
                status=rs.status,
                started_at=rs.started_at,
                completed_at=rs.completed_at,
                approved_by=rs.approved_by,
                approved_by_name=name,
                result=rs.result,
            )
            for rs, step, name in rows
        ],
    )


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> RunOut | None:
    run = await session.get(PlaybookRun, run_id)
    return await _run_out(session, run) if run else None


async def list_runs(
    session: AsyncSession, *, incident_id: uuid.UUID | None, status: str | None, limit: int
) -> list[RunOut]:
    query = select(PlaybookRun).order_by(PlaybookRun.started_at.desc()).limit(limit)
    if incident_id is not None:
        query = query.where(PlaybookRun.incident_id == incident_id)
    if status is not None:
        query = query.where(PlaybookRun.status == status)
    return [await _run_out(session, run) for run in await session.scalars(query)]
