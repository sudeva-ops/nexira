"""Launching, playing, ending and abandoning an exercise (EXR-01..04, D-48; plan-pilot-exr §2, §6).

- An exercise is a scenario run in EXERCISE mode on the live scenario engine, one running per
  mission (the database's partial unique index). Launching refuses while the template's active
  run is PLAYING, and otherwise finishes that run, as the scenario API's reset does.
- ADMIN or DUTY_OFFICER, for the template's mission, checked through app/core/approvals.py.
- Ending scores the run's incident (the earliest opened at the mission whose signals carry the
  run) and freezes the scores; abandoning keeps no score. Both finish the run.
- Every change is audited through app/core/audit.py; EXERCISE_UPDATED carries the id only.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.approvals import user_has_role
from app.core.events import Event, Publisher
from app.core.security import CurrentUser
from app.modules.exercises import queries, service
from app.modules.exercises.models import Exercise, ExerciseScore
from app.modules.exercises.schemas import (
    ExerciseOut,
    ExerciseSummaryOut,
    RunOut,
    SceneOut,
    ScoreOut,
    TemplateOut,
)
from app.modules.intel import queries as intel_queries
from app.modules.scenarios import service as scenarios
from app.modules.scenarios.models import Scenario, ScenarioRun
from app.modules.scenarios.player import Status

OPERATORS = "ADMIN|DUTY_OFFICER"


class ExerciseError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Engine:
    """What drives the scenario player, as the scenario API has it."""

    players: scenarios.PlayerRegistry
    publisher: Publisher
    engine: AsyncEngine


def updated_event(exercise: Exercise) -> Event:
    return Event(
        type="EXERCISE_UPDATED",
        tenant_id=exercise.tenant_id,
        payload={"exercise_id": str(exercise.id)},
        source="exercises",
    )


async def _audit(
    session: AsyncSession, user: CurrentUser, action: str, exercise: Exercise, **details: Any
) -> None:
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action=action,
        entity_type="exercise",
        entity_id=str(exercise.id),
        details=details,
    )


# --- templates (EXR-01) ------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    scenario_id: uuid.UUID
    code: str
    name: str
    mission_id: uuid.UUID
    mission_code: str
    theme: str


_MISSIONS = text("SELECT id, code FROM mission")


async def templates(session: AsyncSession) -> list[Template]:
    """The scenarios whose scene 0 names a mission of this tenant (plan G-1)."""
    missions = {r.code: r.id for r in await session.execute(_MISSIONS)}
    out = []
    for r in await session.execute(text(queries.TEMPLATES_SQL)):
        block = r.template if isinstance(r.template, dict) else {}
        code = block.get("mission")
        if isinstance(code, str) and code in missions:
            out.append(
                Template(r.id, r.code, r.name, missions[code], code, str(block.get("theme", "")))
            )
    return out


async def templates_out(session: AsyncSession, user: CurrentUser) -> list[TemplateOut]:
    running = set(
        await session.scalars(select(Exercise.mission_id).where(Exercise.status == "RUNNING"))
    )
    out = []
    for t in await templates(session):
        events = await scenarios.load_events(session, t.scenario_id)
        out.append(
            TemplateOut(
                code=t.code,
                name=t.name,
                mission_id=t.mission_id,
                mission_code=t.mission_code,
                theme=t.theme,
                scenes=max((e.scene_no for e in events), default=0),
                running=t.mission_id in running,
                can_launch=await user_has_role(session, user, OPERATORS, t.mission_id),
            )
        )
    return out


# --- reading -----------------------------------------------------------------------------------

_LIST = text(
    """
    SELECT e.id, e.name, e.kind, e.status, e.source, e.mission_id, m.code AS mission_code,
           s.code AS scenario_code, e.incident_id, i.reference AS incident_reference,
           e.overall_score, e.participants, e.started_at, e.ended_at
      FROM exercise e
      JOIN mission m ON m.id = e.mission_id
      LEFT JOIN scenario s ON s.id = e.scenario_id
      LEFT JOIN incident i ON i.id = e.incident_id
     WHERE CAST(:id AS uuid) IS NULL OR e.id = CAST(:id AS uuid)
     ORDER BY e.status = 'RUNNING' DESC, coalesce(e.ended_at, e.started_at) DESC, e.id
    """
)


async def list_exercises(
    session: AsyncSession, exercise_id: uuid.UUID | None = None
) -> list[ExerciseSummaryOut]:
    rows = await session.execute(_LIST, {"id": exercise_id})
    return [ExerciseSummaryOut(**r._mapping) for r in rows]


async def running(session: AsyncSession) -> list[ExerciseSummaryOut]:
    """The banner's (plan §4): every running exercise."""
    return [e for e in await list_exercises(session) if e.status == "RUNNING"]


async def _run_out(session: AsyncSession, run: ScenarioRun) -> RunOut:
    events = await scenarios.load_events(session, run.scenario_id)
    scenes = [
        SceneOut(scene_no=e.scene_no, name=str(e.payload.get("name", "")))
        for e in events
        if e.event_type == "SCENE_START"
    ]
    return RunOut(status=run.status, current_scene=run.current_scene, scenes=scenes)


async def detail(session: AsyncSession, user: CurrentUser, exercise_id: uuid.UUID) -> ExerciseOut:
    found = await list_exercises(session, exercise_id)
    if not found:
        raise ExerciseError(404, "Exercise not found")
    summary = found[0]
    exercise = await session.get_one(Exercise, exercise_id, populate_existing=True)
    scores = {
        s.dimension: s
        for s in await session.scalars(
            select(ExerciseScore).where(ExerciseScore.exercise_id == exercise_id)
        )
    }
    run = None
    if exercise.status == "RUNNING" and exercise.scenario_run_id is not None:
        run = await _run_out(session, await session.get_one(ScenarioRun, exercise.scenario_run_id))
    return ExerciseOut(
        **summary.model_dump(),
        reason=exercise.reason,
        scores=[
            ScoreOut(dimension=d, score=scores[d].score, measured=scores[d].measured)
            for d in service.DIMENSIONS
            if d in scores
        ],
        run=run,
        can_act=exercise.status == "RUNNING"
        and await user_has_role(session, user, OPERATORS, exercise.mission_id),
    )


# --- launching (EXR-02) ------------------------------------------------------------------------


async def launch(
    session: AsyncSession, user: CurrentUser, code: str, kind: str, engine: Engine
) -> Exercise:
    template = next((t for t in await templates(session) if t.code == code), None)
    if template is None:
        raise ExerciseError(404, f"No exercise template {code}")
    if not await user_has_role(session, user, OPERATORS, template.mission_id):
        raise ExerciseError(403, "Forbidden")
    if await session.scalar(
        select(Exercise.id).where(
            Exercise.mission_id == template.mission_id, Exercise.status == "RUNNING"
        )
    ):
        raise ExerciseError(409, f"{template.mission_code} already has an exercise running")
    tenant_id: uuid.UUID = session.info["tenant_id"]
    active = await session.scalar(
        select(ScenarioRun)
        .where(
            ScenarioRun.scenario_id == template.scenario_id,
            ScenarioRun.status.in_(scenarios.ACTIVE),
        )
        .with_for_update()
    )
    player = engine.players.get(tenant_id, code)
    playing = player is not None and player.status is Status.PLAYING
    if active is not None and (active.status == Status.PLAYING.value or playing):
        raise ExerciseError(409, f"{code} is playing; pause it first")
    finished = None
    if active is not None:
        if active.mode == "EXERCISE":
            raise ExerciseError(409, f"{code} is already running as an exercise")
        active.status = Status.FINISHED.value
        finished = str(active.id)
        await session.flush()
    run = ScenarioRun(
        tenant_id=tenant_id,
        scenario_id=template.scenario_id,
        mode="EXERCISE",
        current_scene=0,
        status=Status.IDLE.value,
        started_by=user.id,
    )
    session.add(run)
    await session.flush()
    exercise = Exercise(
        tenant_id=tenant_id,
        mission_id=template.mission_id,
        scenario_id=template.scenario_id,
        scenario_run_id=run.id,
        name=template.name,
        kind=kind,
        started_by=user.id,
    )
    session.add(exercise)
    try:
        await session.flush()
    except IntegrityError as e:  # a launch at the same time for the same mission
        raise ExerciseError(409, f"{template.mission_code} already has an exercise running") from e
    await _audit(
        session,
        user,
        "EXERCISE.START",
        exercise,
        template=code,
        kind=kind,
        mission=template.mission_code,
        run=str(run.id),
        finished_run=finished,
    )
    return exercise


# --- playing, ending, abandoning (EXR-02, EXR-04) ------------------------------------------------


async def _running(session: AsyncSession, user: CurrentUser, exercise_id: uuid.UUID) -> Exercise:
    exercise = await session.scalar(
        select(Exercise).where(Exercise.id == exercise_id).with_for_update()
    )
    if exercise is None:
        raise ExerciseError(404, "Exercise not found")
    if not await user_has_role(session, user, OPERATORS, exercise.mission_id):
        raise ExerciseError(403, "Forbidden")
    if exercise.status != "RUNNING" or exercise.scenario_run_id is None:
        raise ExerciseError(409, "The exercise has ended")
    return exercise


async def _run(session: AsyncSession, exercise: Exercise) -> tuple[Scenario, ScenarioRun]:
    run = await session.scalar(
        select(ScenarioRun).where(ScenarioRun.id == exercise.scenario_run_id).with_for_update()
    )
    scenario = await session.get(Scenario, exercise.scenario_id)
    if run is None or scenario is None:
        raise ExerciseError(404, "The exercise's run is missing")
    return scenario, run


async def next_inject(
    session: AsyncSession, user: CurrentUser, exercise_id: uuid.UUID, engine: Engine
) -> Exercise:
    """The next scene, as the scenario API's next, audited the same way (SCENARIO.NEXT)."""
    exercise = await _running(session, user, exercise_id)
    scenario, run = await _run(session, exercise)
    if run.status == Status.FINISHED.value:
        raise ExerciseError(409, "Every inject has been played; end the exercise")
    player = await scenarios.player_for(
        session,
        scenario,
        run,
        players=engine.players,
        publisher=engine.publisher,
        engine=engine.engine,
    )
    before = {"status": player.status.value, "scene": player.current_scene}
    await player.next()
    scenarios.sync_run(run, player)
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="SCENARIO.NEXT",
        entity_type="scenario_run",
        entity_id=str(run.id),
        details={
            "code": scenario.code,
            "exercise_id": str(exercise.id),
            "before": before,
            "after": {"status": player.status.value, "scene": player.current_scene},
        },
    )
    return exercise


async def _stop(scenario: Scenario, run: ScenarioRun, engine: Engine) -> None:
    """Finish the run and stop its player, so nothing more is injected."""
    player = engine.players.get(run.tenant_id, scenario.code)
    if player is not None and player.run_id == run.id:
        await player.pause()
    run.status = Status.FINISHED.value


_AT_MISSION = text(
    "SELECT id FROM incident WHERE mission_id = :mission ORDER BY opened_at, reference"
)


_REFERENCE = text("SELECT reference FROM incident WHERE id = :i")


async def incident_of(session: AsyncSession, exercise: Exercise) -> uuid.UUID | None:
    """The run's incident: the earliest opened at the mission from the run's signals (§2)."""
    ids = list(await session.scalars(_AT_MISSION, {"mission": exercise.mission_id}))
    runs = await intel_queries.exercise_runs(session, ids)
    return next((i for i in ids if runs.get(i) == exercise.scenario_run_id), None)


async def end(
    session: AsyncSession, user: CurrentUser, exercise_id: uuid.UUID, engine: Engine
) -> Exercise:
    """EXR-04: score the run's incident up to now and freeze it. Without an incident every
    score is "—" and there is no overall score (plan §6)."""
    exercise = await _running(session, user, exercise_id)
    scenario, run = await _run(session, exercise)
    await _stop(scenario, run, engine)
    now: datetime = await session.scalar(text("SELECT now()"))  # the guard's ended_at
    incident = await incident_of(session, exercise)
    scored = await service.score(session, incident, now)
    exercise.status = "COMPLETED"
    exercise.incident_id = incident
    exercise.overall_score = scored.overall
    exercise.participants = scored.participants
    exercise.ended_by = user.id
    await session.flush()
    await service.write_scores(session, exercise.id, scored.scores)
    reference = await session.scalar(_REFERENCE, {"i": incident})
    await _audit(
        session,
        user,
        "EXERCISE.END",
        exercise,
        overall=scored.overall,
        incident=reference,
        participants=scored.participants,
        scores={s.dimension: s.score for s in scored.scores},
    )
    return exercise


async def abandon(
    session: AsyncSession, user: CurrentUser, exercise_id: uuid.UUID, reason: str, engine: Engine
) -> Exercise:
    """EXR-04: no score; the reason is kept."""
    exercise = await _running(session, user, exercise_id)
    scenario, run = await _run(session, exercise)
    await _stop(scenario, run, engine)
    exercise.status = "ABANDONED"
    exercise.reason = reason
    exercise.ended_by = user.id
    await session.flush()
    await _audit(session, user, "EXERCISE.ABANDON", exercise, reason=reason)
    return exercise
