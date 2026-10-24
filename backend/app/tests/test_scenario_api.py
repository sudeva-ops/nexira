"""Scenario API: roles, commands, audit, run state (PLT-06, Prompt 5)."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
from httpx import AsyncClient

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.scenarios import service
from app.modules.scenarios.service import EventIn, PlayerRegistry, ensure_scenario
from app.tests.auth_helpers import Idp
from app.tests.conftest import DbUrls, create_tenant, set_tenant
from app.tests.fakes import ListPublisher

CODE = "TEST-SCENARIO"


@pytest.fixture
async def setup(idp: Idp) -> AsyncIterator[tuple[ListPublisher, PlayerRegistry]]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_scenario(
            session,
            code=CODE,
            name="Test",
            description="",
            events=[
                EventIn(0, 0, "SCENE_START", {"name": "Calm"}),
                EventIn(1, 0, "SCENE_START", {"name": "Signals"}),
                EventIn(1, 10, "RAW_SIGNAL", {"external_id": "a", "source_code": "X"}),
                EventIn(1, 20, "RAW_SIGNAL", {"external_id": "b", "source_code": "X"}),
                EventIn(2, 0, "SCENE_START", {"name": "Impact"}),
            ],
        )
        await session.commit()
    await idp.user("duty", [("DUTY_OFFICER", None)])
    await idp.user("admin", [("ADMIN", None)])
    await idp.user("viewer", [("VIEWER", None)])
    await idp.user("hom", [("HEAD_OF_MISSION", None)])
    publisher, players = ListPublisher(), PlayerRegistry()
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[service.get_registry] = lambda: players
    yield publisher, players
    await players.close()


async def _wait(players: PlayerRegistry, idp: Idp) -> None:
    player = players.get(idp.tenant_id, CODE)
    assert player is not None
    await player.wait()
    await asyncio.sleep(0.05)  # let the scene-done callback commit


async def test_only_admin_and_duty_officer_may_operate(
    client: AsyncClient, idp: Idp, setup: tuple[ListPublisher, PlayerRegistry]
) -> None:
    for sub in ("viewer", "hom"):
        response = await client.post(f"/api/scenarios/{CODE}/play", headers=idp.headers(sub))
        assert response.status_code == 403, sub
    for sub in ("duty", "admin"):
        response = await client.get(f"/api/scenarios/{CODE}", headers=idp.headers(sub))
        assert response.status_code == 200, sub


async def test_next_plays_the_scene_and_reset_starts_a_new_run(
    client: AsyncClient, idp: Idp, db: DbUrls, setup: tuple[ListPublisher, PlayerRegistry]
) -> None:
    publisher, players = setup
    h = idp.headers("duty")
    state = (await client.get(f"/api/scenarios/{CODE}", headers=h)).json()
    assert (state["status"], state["current_scene"]) == ("IDLE", 0)
    assert [s["name"] for s in state["scenes"]] == ["Calm", "Signals", "Impact"]
    first_run = state["run_id"]

    state = (await client.post(f"/api/scenarios/{CODE}/next", headers=h)).json()
    assert (state["status"], state["current_scene"]) == ("PLAYING", 1)
    await _wait(players, idp)
    assert [e.type for e in publisher.events] == ["SCENE_START", "RAW_SIGNAL", "RAW_SIGNAL"]
    assert all(e.tenant_id == idp.tenant_id for e in publisher.events)

    state = (await client.get(f"/api/scenarios/{CODE}", headers=h)).json()
    assert (state["status"], state["scene_complete"]) == ("PAUSED", True)

    state = (await client.post(f"/api/scenarios/{CODE}/reset", headers=h)).json()
    assert (state["status"], state["current_scene"], state["position"]) == ("IDLE", 0, 0)
    assert state["run_id"] != first_run

    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, idp.tenant_id)
        runs = {str(r["id"]): r["status"] for r in await conn.fetch("SELECT * FROM scenario_run")}
        actions = [
            r["action"]
            for r in await conn.fetch(
                "SELECT action FROM audit_log WHERE action LIKE 'SCENARIO.%' ORDER BY chain_seq"
            )
        ]
        # The player never writes business tables (Prompt 5).
        assert await conn.fetchval("SELECT count(*) FROM raw_signal") == 0
    finally:
        await conn.close()
    assert runs == {first_run: "FINISHED", state["run_id"]: "IDLE"}
    assert actions == ["SCENARIO.CREATE", "SCENARIO.NEXT", "SCENARIO.RESET"]


async def test_pause_and_play(
    client: AsyncClient, idp: Idp, setup: tuple[ListPublisher, PlayerRegistry]
) -> None:
    h = idp.headers("admin")
    await client.post(f"/api/scenarios/{CODE}/next", headers=h)
    paused = (await client.post(f"/api/scenarios/{CODE}/pause", headers=h)).json()
    assert paused["status"] == "PAUSED"
    played = (await client.post(f"/api/scenarios/{CODE}/play", headers=h)).json()
    assert played["status"] in ("PLAYING", "PAUSED")  # PAUSED if the scene already ended


async def test_unknown_scenario_and_command(
    client: AsyncClient, idp: Idp, setup: tuple[ListPublisher, PlayerRegistry]
) -> None:
    h = idp.headers("duty")
    assert (await client.get("/api/scenarios/NOPE", headers=h)).status_code == 404
    assert (await client.post(f"/api/scenarios/{CODE}/rewind", headers=h)).status_code == 422


async def test_scenarios_are_tenant_scoped(
    idp: Idp, db: DbUrls, setup: tuple[ListPublisher, PlayerRegistry]
) -> None:
    other = await create_tenant(db)
    async with tenant_session(other, idp.engine) as session:
        assert await service.get_scenario(session, CODE) is None
