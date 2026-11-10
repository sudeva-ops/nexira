"""Scenario storage, run state and the players that replay them (PLT-06).

Run state lives in scenario_run: at most one active run (IDLE, PLAYING or PAUSED)
per scenario. Reset finishes the active run and starts a new one at scene 0,
so each run's signals get fresh external ids. Business data is never touched
(D-21). The player runs inside the API process; Phase 1 runs one API instance.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.db import tenant_session
from app.core.events import Publisher
from app.modules.scenarios.models import Scenario, ScenarioEvent, ScenarioRun
from app.modules.scenarios.player import Clock, Player, SceneDone, Status
from app.modules.scenarios.player import ScenarioEvent as PlayerEvent
from app.modules.tenancy.service import SYSTEM, Actor

ACTIVE = (Status.IDLE.value, Status.PLAYING.value, Status.PAUSED.value)


@dataclass(frozen=True)
class EventIn:
    scene_no: int
    offset_ms: int
    event_type: str
    payload: dict[str, Any]
    id: uuid.UUID | None = None


async def ensure_scenario(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    description: str,
    events: list[EventIn],
    scenario_id: uuid.UUID | None = None,
    actor: Actor = SYSTEM,
) -> bool:
    """Store a scenario and its events if the code is new. Audited on create."""
    tenant_id = session.info["tenant_id"]
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "code": code,
        "name": name,
        "description": description,
    }
    if scenario_id is not None:
        values["id"] = scenario_id
    created: uuid.UUID | None = await session.scalar(
        insert(Scenario)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["tenant_id", "code"])
        .returning(Scenario.id)
    )
    if created is None:
        return False
    if events:
        await session.execute(
            insert(ScenarioEvent).values(
                [
                    {
                        **({"id": e.id} if e.id else {}),
                        "tenant_id": tenant_id,
                        "scenario_id": created,
                        "scene_no": e.scene_no,
                        "offset_ms": e.offset_ms,
                        "event_type": e.event_type,
                        "payload": e.payload,
                    }
                    for e in events
                ]
            )
        )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="SCENARIO.CREATE",
        entity_type="scenario",
        entity_id=code,
        details={"events": len(events)},
    )
    return True


async def get_scenario(session: AsyncSession, code: str) -> Scenario | None:
    return await session.scalar(select(Scenario).where(Scenario.code == code))


async def load_events(session: AsyncSession, scenario_id: uuid.UUID) -> list[PlayerEvent]:
    rows = await session.scalars(
        select(ScenarioEvent)
        .where(ScenarioEvent.scenario_id == scenario_id)
        .order_by(ScenarioEvent.scene_no, ScenarioEvent.offset_ms)
    )
    return [
        PlayerEvent(
            id=r.id,
            scene_no=r.scene_no,
            offset_ms=r.offset_ms,
            event_type=r.event_type,
            payload=r.payload,
        )
        for r in rows
    ]


async def active_run(
    session: AsyncSession, scenario_id: uuid.UUID, user_id: uuid.UUID | None
) -> ScenarioRun:
    run = await session.scalar(
        select(ScenarioRun).where(
            ScenarioRun.scenario_id == scenario_id, ScenarioRun.status.in_(ACTIVE)
        )
    )
    if run is None:
        run = ScenarioRun(
            tenant_id=session.info["tenant_id"],
            scenario_id=scenario_id,
            mode="DEMO",
            current_scene=0,
            status=Status.IDLE.value,
            started_by=user_id,
        )
        session.add(run)
        await session.flush()
    return run


class PlayerRegistry:
    """One player per (tenant, scenario) in this process."""

    def __init__(self) -> None:
        self._players: dict[tuple[uuid.UUID, str], Player] = {}

    def get(self, tenant_id: uuid.UUID, code: str) -> Player | None:
        return self._players.get((tenant_id, code))

    def put(self, player: Player) -> None:
        self._players[(player.tenant_id, player.code)] = player

    async def close(self) -> None:
        for player in self._players.values():
            await player.pause()
        self._players.clear()


registry = PlayerRegistry()


def get_registry() -> PlayerRegistry:
    """FastAPI dependency; tests override it."""
    return registry


def scene_done_callback(engine: AsyncEngine, tenant_id: uuid.UUID) -> SceneDone:
    """Marks the run PAUSED when a scene finishes playing in the background."""

    async def done(run_id: uuid.UUID, scene_no: int) -> None:
        async with tenant_session(tenant_id, engine) as session:
            await session.execute(
                update(ScenarioRun)
                .where(ScenarioRun.id == run_id, ScenarioRun.status == Status.PLAYING.value)
                .values(status=Status.PAUSED.value, current_scene=scene_no)
            )
            await session.commit()

    return done


async def player_for(
    session: AsyncSession,
    scenario: Scenario,
    run: ScenarioRun,
    *,
    players: PlayerRegistry,
    publisher: Publisher,
    engine: AsyncEngine,
    clock: Clock | None = None,
) -> Player:
    tenant_id: uuid.UUID = session.info["tenant_id"]
    player = players.get(tenant_id, scenario.code)
    if player is None or player.run_id != run.id:
        player = Player(
            code=scenario.code,
            tenant_id=tenant_id,
            run_id=run.id,
            events=await load_events(session, scenario.id),
            publisher=publisher,
            clock=clock,
            current_scene=run.current_scene,
            on_scene_done=scene_done_callback(engine, tenant_id),
            exercise=run.mode == "EXERCISE",
        )
        players.put(player)
    return player


def sync_run(run: ScenarioRun, player: Player) -> None:
    """Copy the player's state onto the run row (the caller commits)."""
    run.status = player.status.value
    run.current_scene = player.current_scene
    if player.status is Status.PLAYING and run.started_at is None:
        run.started_at = datetime.now(UTC)
