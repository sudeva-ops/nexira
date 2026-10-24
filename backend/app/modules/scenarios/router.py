"""Scenario API (PLT-06). Every command is audited. ADMIN or DUTY_OFFICER."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.approvals import require_roles
from app.core.db import engine_dependency
from app.core.events import Publisher, get_publisher
from app.core.security import CurrentUser, get_db
from app.modules.scenarios import service
from app.modules.scenarios.models import Scenario, ScenarioRun
from app.modules.scenarios.player import Player, Status
from app.modules.scenarios.schemas import ScenarioStateOut, SceneOut

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

Operator = Annotated[CurrentUser, Depends(require_roles("ADMIN", "DUTY_OFFICER"))]
Session = Annotated[AsyncSession, Depends(get_db)]
Players = Annotated[service.PlayerRegistry, Depends(service.get_registry)]
Pub = Annotated[Publisher, Depends(get_publisher)]
Engine = Annotated[AsyncEngine, Depends(engine_dependency)]


def _state(scenario: Scenario, run: ScenarioRun, player: Player) -> ScenarioStateOut:
    scenes = []
    for n in range(player.last_scene + 1):
        events = player.scene_events(n)
        title = next((e.payload.get("name") for e in events if e.event_type == "SCENE_START"), "")
        scenes.append(SceneOut(scene_no=n, name=str(title), events=len(events)))
    return ScenarioStateOut(
        code=player.code,
        name=scenario.name,
        run_id=run.id,
        status=player.status.value,
        current_scene=player.current_scene,
        position=player.position,
        scene_complete=player.scene_complete,
        scenes=scenes,
    )


async def _context(
    code: str,
    user: CurrentUser,
    session: AsyncSession,
    players: service.PlayerRegistry,
    publisher: Publisher,
    engine: AsyncEngine,
) -> tuple[Scenario, ScenarioRun, Player]:
    scenario = await service.get_scenario(session, code)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scenario {code} not found")
    run = await service.active_run(session, scenario.id, user.id)
    player = await service.player_for(
        session, scenario, run, players=players, publisher=publisher, engine=engine
    )
    return scenario, run, player


@router.get("/{code}")
async def get_state(
    code: str, user: Operator, session: Session, players: Players, publisher: Pub, engine: Engine
) -> ScenarioStateOut:
    scenario, run, player = await _context(code, user, session, players, publisher, engine)
    await session.commit()  # persists a newly created run
    return _state(scenario, run, player)


@router.post("/{code}/{command}")
async def command(
    code: str,
    command: Literal["play", "pause", "next", "reset"],
    user: Operator,
    session: Session,
    players: Players,
    publisher: Pub,
    engine: Engine,
) -> ScenarioStateOut:
    scenario, run, player = await _context(code, user, session, players, publisher, engine)
    before = {"status": player.status.value, "scene": player.current_scene}

    if command == "reset":
        run.status = Status.FINISHED.value
        await session.flush()
        run = await service.active_run(session, scenario.id, user.id)
        await player.reset(run.id)
    elif command == "play":
        await player.play()
    elif command == "pause":
        await player.pause()
    else:
        await player.next()

    service.sync_run(run, player)
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action=f"SCENARIO.{command.upper()}",
        entity_type="scenario_run",
        entity_id=str(run.id),
        details={
            "code": code,
            "before": before,
            "after": {"status": player.status.value, "scene": player.current_scene},
        },
    )
    await session.commit()
    return _state(scenario, run, player)
