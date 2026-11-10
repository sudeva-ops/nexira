"""Exercise & Training API (EXR-01..08; D-48). Every role reads. Launching, Next inject, ending
and abandoning are for ADMIN or DUTY_OFFICER at the template's mission, checked in
app/modules/exercises/runs.py through app/core/approvals.py. Every change is audited and
followed by EXERCISE_UPDATED (its id only).

Unlike the scenario API (the presenter bar, demo only, D-21), this runs in every environment:
an exercise uses the live scenario engine (D-48). Next inject is here too, so the screen never
reads a scene's expected result (plan §2)."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.approvals import require_roles
from app.core.db import engine_dependency
from app.core.events import Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.exercises import runs, service
from app.modules.exercises.models import Exercise
from app.modules.exercises.schemas import (
    AbandonIn,
    ExerciseOut,
    ExercisesOut,
    ExerciseSummaryOut,
    KpisOut,
    LaunchIn,
    TemplateOut,
)
from app.modules.scenarios.service import PlayerRegistry, get_registry
from app.modules.tenancy.service import ROLES

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/exercises", tags=["exercises"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Operator = Annotated[CurrentUser, Depends(require_roles("ADMIN", "DUTY_OFFICER"))]
Db = Annotated[AsyncSession, Depends(get_db)]
Players = Annotated[PlayerRegistry, Depends(get_registry)]
Pub = Annotated[Publisher, Depends(get_publisher)]
Engine = Annotated[AsyncEngine, Depends(engine_dependency)]


def _engine(players: PlayerRegistry, publisher: Publisher, engine: AsyncEngine) -> runs.Engine:
    return runs.Engine(players=players, publisher=publisher, engine=engine)


async def _done(
    session: AsyncSession, user: CurrentUser, publisher: Publisher, exercise: Exercise
) -> ExerciseOut:
    exercise_id = exercise.id
    event = runs.updated_event(exercise)
    await session.commit()
    try:
        await publisher.publish(event)
    except Exception:
        log.exception("publishing EXERCISE_UPDATED failed after commit")
    return await runs.detail(session, user, exercise_id)


def _http(e: runs.ExerciseError) -> HTTPException:
    return HTTPException(e.status_code, str(e))


@router.get("")
async def list_exercises(_user: Reader, session: Db) -> ExercisesOut:
    kpis = await service.kpis(session, datetime.now(UTC))
    return ExercisesOut(kpis=KpisOut(**vars(kpis)), exercises=await runs.list_exercises(session))


@router.get("/templates")
async def templates(user: Reader, session: Db) -> list[TemplateOut]:
    return await runs.templates_out(session, user)


@router.get("/running")
async def running(_user: Reader, session: Db) -> list[ExerciseSummaryOut]:
    return await runs.running(session)


@router.get("/{exercise_id}")
async def get_exercise(exercise_id: uuid.UUID, user: Reader, session: Db) -> ExerciseOut:
    try:
        return await runs.detail(session, user, exercise_id)
    except runs.ExerciseError as e:
        raise _http(e) from e


@router.post("", status_code=status.HTTP_201_CREATED)
async def launch(
    body: LaunchIn, user: Operator, session: Db, players: Players, publisher: Pub, engine: Engine
) -> ExerciseOut:
    try:
        exercise = await runs.launch(
            session, user, body.template, body.kind, _engine(players, publisher, engine)
        )
    except runs.ExerciseError as e:
        raise _http(e) from e
    return await _done(session, user, publisher, exercise)


@router.post("/{exercise_id}/next")
async def next_inject(
    exercise_id: uuid.UUID,
    user: Operator,
    session: Db,
    players: Players,
    publisher: Pub,
    engine: Engine,
) -> ExerciseOut:
    try:
        exercise = await runs.next_inject(
            session, user, exercise_id, _engine(players, publisher, engine)
        )
    except runs.ExerciseError as e:
        raise _http(e) from e
    return await _done(session, user, publisher, exercise)


@router.post("/{exercise_id}/end")
async def end(
    exercise_id: uuid.UUID,
    user: Operator,
    session: Db,
    players: Players,
    publisher: Pub,
    engine: Engine,
) -> ExerciseOut:
    try:
        exercise = await runs.end(session, user, exercise_id, _engine(players, publisher, engine))
    except runs.ExerciseError as e:
        raise _http(e) from e
    return await _done(session, user, publisher, exercise)


@router.post("/{exercise_id}/abandon")
async def abandon(
    exercise_id: uuid.UUID,
    body: AbandonIn,
    user: Operator,
    session: Db,
    players: Players,
    publisher: Pub,
    engine: Engine,
) -> ExerciseOut:
    try:
        exercise = await runs.abandon(
            session, user, exercise_id, body.reason, _engine(players, publisher, engine)
        )
    except runs.ExerciseError as e:
        raise _http(e) from e
    return await _done(session, user, publisher, exercise)
