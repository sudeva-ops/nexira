"""Playbook engine and API (PB-02..04, D-05, D-16, Prompt 9).

A synthetic playbook keeps these tests independent of seed data; PB-07 itself
runs on the full seed in simulator/tests/test_playbook_pb07.py.
"""

import asyncio
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.intel.service import ensure_sources
from app.modules.people.models import Mission
from app.modules.playbooks import engine
from app.modules.playbooks.models import Playbook, PlaybookRun, PlaybookRunStep, PlaybookStep
from app.modules.playbooks.service import StepIn, ensure_playbook
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import SOURCES, ingest, signal

BROKEN = [
    StepIn(1, "Notify nobody", "NOTIFY", {"audience": {"unknown": True}, "message": "x"}),
]
GATED = [
    StepIn(1, "Confirm incident", "TASK", {"summary": "confirmed"}),
    StepIn(2, "Partner standby", "PARTNER_REQUEST", {"partner": "Kestrel Medical"}),
    StepIn(3, "Approve route", "APPROVAL_GATE", {}, "HEAD_OF_MISSION"),
    StepIn(4, "Brief leadership", "BRIEFING", {"recipient": "Minister's office"}),
]
TWO_GATES = [
    StepIn(1, "First approval", "APPROVAL_GATE", {}, "HEAD_OF_MISSION|HQ_CRISIS_DIRECTOR"),
    StepIn(2, "Second approval", "APPROVAL_GATE", {}, "HQ_CRISIS_DIRECTOR"),
]


@dataclass
class World:
    incident_id: uuid.UUID
    nbo: uuid.UUID
    publisher: ListPublisher
    step_ids: dict[str, list[uuid.UUID]]


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo, cai = await idp.mission("NBO"), await idp.mission("CAI")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "sec": [("SECURITY_OFFICER", None)],
        "viewer": [("VIEWER", None)],
        "hq": [("HQ_CRISIS_DIRECTOR", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "dual": [("HEAD_OF_MISSION", nbo), ("HQ_CRISIS_DIRECTOR", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    step_ids = {
        "PB-T": [uuid.uuid4() for _ in GATED],
        "PB-2G": [uuid.uuid4() for _ in TWO_GATES],
        "PB-X": [uuid.uuid4() for _ in BROKEN],
    }
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        for code, steps in (("PB-T", GATED), ("PB-2G", TWO_GATES), ("PB-X", BROKEN)):
            await ensure_playbook(
                session,
                playbook_id=uuid.uuid4(),
                code=code,
                name=f"Test {code}",
                category="CIVIL_UNREST",
                trigger_rules={},
                steps=steps,
                step_ids=step_ids[code],
            )
        await session.commit()
    fused = (await ingest(idp.engine, idp.tenant_id, signal("DATAMINR", "High"))).fused
    assert fused is not None
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Incident).values(mission_id=nbo))  # as exposure would
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(fused.incident_id, nbo, publisher, step_ids)


async def start(
    client: AsyncClient, idp: Idp, w: World, sub: str = "duty", code: str = "PB-T"
) -> Response:
    return await client.post(
        "/api/playbook-runs",
        json={"playbook_code": code, "incident_id": str(w.incident_id)},
        headers=idp.headers(sub),
    )


async def run_until_stop(idp: Idp, w: World, run_id: uuid.UUID) -> str | None:
    return await engine.advance(idp.engine, idp.tenant_id, run_id, w.publisher)


def approve_url(run_id: str, step_id: uuid.UUID) -> str:
    return f"/api/playbook-runs/{run_id}/steps/{step_id}/approve"


async def counts(idp: Idp, run_id: uuid.UUID) -> dict[str, int]:
    """Timeline and audit rows per DONE step, to prove nothing ran twice."""
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        timeline = await session.scalars(
            select(IncidentEvent.data).where(IncidentEvent.event_type == "PLAYBOOK_STEP")
        )
        audits = await session.scalars(
            select(AuditLog.details).where(
                AuditLog.action == "PLAYBOOK.STEP_DONE", AuditLog.entity_id == str(run_id)
            )
        )
        found = Counter(
            f"timeline:{d['seq']}"
            for d in timeline
            if d.get("run_id") == str(run_id) and d.get("status") == "DONE"
        )
        found.update(f"audit:{d['seq']}" for d in audits)
    return dict(found)


async def test_only_duty_or_security_officers_start_runs(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    for sub in ("viewer", "hom.nbo", "hq"):
        assert (await start(client, idp, world, sub)).status_code == 403, sub
    response = await start(client, idp, world, "sec")
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "RUNNING"
    assert [s["status"] for s in run["steps"]] == ["PENDING"] * 4
    assert [e.type for e in world.publisher.events] == ["PLAYBOOK_RUN_STARTED"]
    # One live run per playbook and incident: the unique index becomes 409 (plan G-08).
    assert (await start(client, idp, world, "duty")).status_code == 409
    assert (await start(client, idp, world, "duty", "PB-NOPE")).status_code == 409


async def test_run_pauses_at_the_gate_and_the_right_approver_completes_it(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    run = (await start(client, idp, world)).json()
    run_id = uuid.UUID(run["id"])
    assert await run_until_stop(idp, world, run_id) == "AWAITING_APPROVAL"
    state = (await client.get(f"/api/playbook-runs/{run_id}", headers=idp.headers("viewer"))).json()
    assert state["status"] == "AWAITING_APPROVAL"
    assert [s["status"] for s in state["steps"]] == ["DONE", "DONE", "AWAITING_APPROVAL", "PENDING"]
    assert all(s["started_at"] and s["completed_at"] for s in state["steps"][:2])
    assert state["steps"][1]["result"]["simulated"] is True

    gate = world.step_ids["PB-T"][2]
    # PB-03: the Duty Officer cannot approve; nor can the Cairo Head of Mission (D-05).
    for sub in ("duty", "hom.cai", "viewer"):
        response = await client.post(approve_url(run["id"], gate), headers=idp.headers(sub))
        assert response.status_code == 403, sub
    perms = await client.get(
        "/api/me/permissions",
        params={"entity_type": "playbook_run", "entity_id": run["id"]},
        headers=idp.headers("hom.nbo"),
    )
    assert perms.json()["approve_step"] == [str(gate)]
    duty_perms = await client.get(
        "/api/me/permissions",
        params={"entity_type": "playbook_run", "entity_id": run["id"]},
        headers=idp.headers("duty"),
    )
    assert duty_perms.json()["approve_step"] == []

    approved = await client.post(approve_url(run["id"], gate), headers=idp.headers("hom.nbo"))
    assert approved.status_code == 200
    assert approved.json()["status"] == "RUNNING"
    again = await client.post(approve_url(run["id"], gate), headers=idp.headers("hom.nbo"))
    assert again.status_code == 409
    assert await run_until_stop(idp, world, run_id) == "RUN_COMPLETED"

    final = (await client.get(f"/api/playbook-runs/{run_id}", headers=idp.headers("viewer"))).json()
    assert final["status"] == "COMPLETED"
    assert [s["status"] for s in final["steps"]] == ["DONE"] * 4
    assert final["steps"][2]["approved_by_name"] == "User hom.nbo"
    assert "Situation report" in final["steps"][3]["result"]["report"]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        actions = list(
            await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.action.like("PLAYBOOK.%"), AuditLog.entity_id == str(run_id))
                .order_by(AuditLog.chain_seq)
            )
        )
        decisions = list(
            await session.scalars(
                select(IncidentEvent.summary).where(IncidentEvent.event_type == "DECISION")
            )
        )
    assert actions == [
        "PLAYBOOK.START",
        "PLAYBOOK.STEP_DONE",
        "PLAYBOOK.STEP_DONE",
        "PLAYBOOK.STEP_AWAIT_APPROVAL",
        "PLAYBOOK.STEP_APPROVE",
        "PLAYBOOK.STEP_DONE",
        "PLAYBOOK.STEP_DONE",
        "PLAYBOOK.COMPLETE",
    ]
    assert decisions == [
        "Step 3 · Approve route: approved by User hom.nbo (HEAD_OF_MISSION · NBO)."
    ]
    types = [e.type for e in world.publisher.events]
    assert types.count("PLAYBOOK_STEP") == 5  # 4 done + 1 awaiting
    assert "PLAYBOOK_STEP_APPROVED" in types
    assert types[-1] == "PLAYBOOK_RUN_UPDATED"


async def test_only_an_open_gate_can_be_approved(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    run = (await start(client, idp, world)).json()
    gate = world.step_ids["PB-T"][2]
    # Not reached yet: 409, even for the right person.
    early = await client.post(approve_url(run["id"], gate), headers=idp.headers("hom.nbo"))
    assert early.status_code == 409
    not_gated = await client.post(
        approve_url(run["id"], world.step_ids["PB-T"][0]), headers=idp.headers("hom.nbo")
    )
    assert not_gated.status_code == 409
    missing = await client.post(
        approve_url(run["id"], uuid.uuid4()), headers=idp.headers("hom.nbo")
    )
    assert missing.status_code == 404


async def test_without_a_mission_only_hq_roles_approve(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Incident).values(mission_id=None))
        await session.commit()
    run = (await start(client, idp, world, code="PB-2G")).json()
    await run_until_stop(idp, world, uuid.UUID(run["id"]))
    first = world.step_ids["PB-2G"][0]
    response = await client.post(approve_url(run["id"], first), headers=idp.headers("hom.nbo"))
    assert response.status_code == 403  # D-06
    assert (
        await client.post(approve_url(run["id"], first), headers=idp.headers("hq"))
    ).status_code == 200


async def test_the_same_person_cannot_fill_two_gates(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    run = (await start(client, idp, world, code="PB-2G")).json()
    run_id = uuid.UUID(run["id"])
    first, second = world.step_ids["PB-2G"]
    await run_until_stop(idp, world, run_id)
    assert (
        await client.post(approve_url(run["id"], first), headers=idp.headers("dual"))
    ).status_code == 200
    await run_until_stop(idp, world, run_id)
    # D-16: "dual" holds HQ_CRISIS_DIRECTOR too, but already decided step 1.
    response = await client.post(approve_url(run["id"], second), headers=idp.headers("dual"))
    assert response.status_code == 403
    assert "same person" in response.json()["detail"]
    assert (
        await client.post(approve_url(run["id"], second), headers=idp.headers("hq"))
    ).status_code == 200
    assert await run_until_stop(idp, world, run_id) == "RUN_COMPLETED"


async def test_a_crash_mid_run_resumes_without_running_a_step_twice(
    client: AsyncClient, idp: Idp, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = uuid.UUID((await start(client, idp, world)).json()["id"])
    real_execute = engine._execute
    crashed = False

    async def crash_once(
        session: AsyncSession, run: PlaybookRun, playbook: Playbook, step: PlaybookStep
    ) -> tuple[str, dict[str, Any]]:
        nonlocal crashed
        if step.seq == 2 and not crashed:
            crashed = True
            await real_execute(session, run, playbook, step)  # its effects are rolled back
            raise RuntimeError("worker killed")
        return await real_execute(session, run, playbook, step)

    monkeypatch.setattr(engine, "_execute", crash_once)
    with pytest.raises(RuntimeError, match="worker killed"):
        await run_until_stop(idp, world, run_id)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        statuses = list(
            await session.scalars(
                select(PlaybookRunStep.status)
                .where(PlaybookRunStep.run_id == run_id)
                .order_by(PlaybookRunStep.started_at.nulls_last())
            )
        )
    assert sorted(statuses) == ["DONE", "PENDING", "PENDING", "PENDING"]

    # Restart: resume RUNNING runs, as the worker does at start.
    assert await engine.resumable_runs(idp.engine, idp.tenant_id) == [run_id]
    assert await run_until_stop(idp, world, run_id) == "AWAITING_APPROVAL"
    assert await counts(idp, run_id) == {
        "timeline:1": 1,
        "timeline:2": 1,
        "audit:1": 1,
        "audit:2": 1,
    }


async def test_concurrent_workers_run_each_step_once(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    run_id = uuid.UUID((await start(client, idp, world)).json()["id"])
    results = await asyncio.gather(*(run_until_stop(idp, world, run_id) for _ in range(4)))
    assert "AWAITING_APPROVAL" in results
    assert await counts(idp, run_id) == {
        "timeline:1": 1,
        "timeline:2": 1,
        "audit:1": 1,
        "audit:2": 1,
    }
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        run = await session.get_one(PlaybookRun, run_id)
    assert run.status == "AWAITING_APPROVAL"


async def test_a_run_needs_an_active_incident(client: AsyncClient, idp: Idp, world: World) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Incident).values(status="CLOSED"))
        await session.commit()
    response = await start(client, idp, world)
    assert response.status_code == 409
    assert "ACTIVE" in response.json()["detail"]


async def test_a_bad_step_config_fails_the_run_instead_of_retrying_forever(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    run_id = uuid.UUID((await start(client, idp, world, code="PB-X")).json()["id"])
    assert await run_until_stop(idp, world, run_id) == "RUN_FAILED"
    assert await engine.resumable_runs(idp.engine, idp.tenant_id) == []
    run = (await client.get(f"/api/playbook-runs/{run_id}", headers=idp.headers("viewer"))).json()
    assert run["status"] == "FAILED"
    assert "unsupported audience" in run["steps"][0]["result"]["error"]
    # The live-run slot is free again: the playbook can be started anew.
    assert (await start(client, idp, world, code="PB-X")).status_code == 201


async def test_a_failed_publish_after_commit_still_succeeds(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    class DownPublisher:
        async def publish(self, event: object) -> None:
            raise ConnectionError("redis down")

    app.dependency_overrides[get_publisher] = DownPublisher
    response = await start(client, idp, world)
    assert response.status_code == 201
    assert response.json()["status"] == "RUNNING"  # committed; the resume sweep continues it


async def test_the_audit_names_only_roles_in_scope(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        cai = await session.scalar(select(Mission.id).where(Mission.code == "CAI"))
    await idp.user("hom.both", [("HEAD_OF_MISSION", world.nbo), ("HEAD_OF_MISSION", cai)])
    run = (await start(client, idp, world)).json()
    await run_until_stop(idp, world, uuid.UUID(run["id"]))
    gate = world.step_ids["PB-T"][2]
    assert (
        await client.post(approve_url(run["id"], gate), headers=idp.headers("hom.both"))
    ).status_code == 200
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        approval = await session.scalar(
            select(AuditLog).where(AuditLog.action == "PLAYBOOK.STEP_APPROVE")
        )
    assert approval is not None
    assert approval.details["held"] == ["HEAD_OF_MISSION · NBO"]
