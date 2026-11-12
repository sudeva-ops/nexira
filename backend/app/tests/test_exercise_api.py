"""Exercise & Training API (EXR-01..04; D-48; docs/plan-pilot-exr.md §2, §4, §6, §7): templates;
launch, Next inject, end and abandon with each role and refusal; every audited action; frozen
scores; the run marker and fusion kept apart (G-2); the EXERCISE label; exercise incidents left
out of Executive and Predictive; and the check-in timing and answers of an exercise (G-3: A).
Against real PostgreSQL, as nexira_api. The player publishes to a list; the tests ingest it."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.exercises import service as exercises
from app.modules.intel import exposure
from app.modules.intel import queries as intel_queries
from app.modules.intel.models import Incident
from app.modules.intel.service import ensure_sources
from app.modules.notifications.service import CampaignIn, create_campaign, dispatch
from app.modules.people import location
from app.modules.people.service import ObservationIn, PersonIn, add_observations, load_persons
from app.modules.predictive import service as predictive
from app.modules.scenarios import service as scenarios
from app.modules.scenarios.service import EventIn, PlayerRegistry, ensure_scenario
from app.modules.tenancy.service import SYSTEM, ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import EPICENTRE, SOURCES, ingest, signal

CODE = "EXR-TEST"
TEMPLATE = {"mission": "NBO", "theme": "Civil unrest"}


def _signal(key: str) -> dict[str, Any]:
    payload = dict(signal("DATAMINR", "High", external_id=key).payload)
    payload.pop("occurred_at")  # the player stamps it now
    return payload


@dataclass
class Setup:
    nbo: uuid.UUID
    par: uuid.UUID
    people: dict[str, uuid.UUID]
    publisher: ListPublisher
    players: PlayerRegistry


@pytest.fixture
async def setup(client: AsyncClient, idp: Idp) -> AsyncIterator[Setup]:
    nbo, par = await idp.mission("NBO"), await idp.mission("PAR")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "admin": [("ADMIN", None)],
        "viewer": [("VIEWER", None)],
        "hom": [("HEAD_OF_MISSION", nbo)],
        "duty.par": [("DUTY_OFFICER", par)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    people = {"Hana": uuid.uuid4(), "Peter": uuid.uuid4()}
    now = datetime.now(UTC)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await ensure_reference_counter(session, prefix="NTF", with_year=False, last_value=3100)
        await load_persons(
            session,
            [
                PersonIn(people["Hana"], nbo, "DIPLOMAT", "Hana"),
                PersonIn(people["Peter"], nbo, "LOCAL_STAFF", "Peter"),
            ],
        )
        await add_observations(
            session, [ObservationIn(p, "MANUAL", *EPICENTRE, now) for p in people.values()]
        )
        await location.recompute(session, now)
        await ensure_scenario(
            session,
            code=CODE,
            name="Nairobi unrest",
            description="",
            events=[
                EventIn(0, 0, "SCENE_START", {"name": "Calm", "expect": "x", "template": TEMPLATE}),
                EventIn(
                    0,
                    0,
                    "SCENARIO_SETTINGS",
                    {"checkin_escalate_after_s": 20, "checkin_clock_scene": 1},
                ),
                EventIn(1, 0, "SCENE_START", {"name": "Signals", "expect": "One incident"}),
                EventIn(1, 10, "RAW_SIGNAL", _signal("exr-a")),
                EventIn(2, 0, "SCENE_START", {"name": "Hold"}),
                EventIn(2, 600_000, "TEST_WAIT", {}),  # keeps scene 2 PLAYING
            ],
        )
        await ensure_scenario(  # an add-on scenario: not a template
            session,
            code="ADD-ON",
            name="Add-on",
            description="",
            events=[EventIn(0, 0, "SCENE_START", {"name": "Calm"})],
        )
        await session.commit()
    publisher, players = ListPublisher(), PlayerRegistry()
    app.dependency_overrides[get_publisher] = lambda: publisher
    app.dependency_overrides[scenarios.get_registry] = lambda: players
    yield Setup(nbo, par, people, publisher, players)
    await players.close()


async def _launch(client: AsyncClient, idp: Idp, sub: str = "duty") -> Any:
    return await client.post(
        "/api/exercises", json={"template": CODE, "kind": "FUNCTIONAL"}, headers=idp.headers(sub)
    )


async def _audit(idp: Idp, prefix: str = "EXERCISE.") -> list[tuple[str, dict[str, Any]]]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        rows = await session.execute(
            select(AuditLog.action, AuditLog.details)
            .where(AuditLog.action.like(f"{prefix}%"))
            .order_by(AuditLog.chain_seq)
        )
        return [(a, d) for a, d in rows]


async def _run_id(idp: Idp, exercise_id: str) -> uuid.UUID:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        run: uuid.UUID = await session.scalar(
            text("SELECT scenario_run_id FROM exercise WHERE id = :e"), {"e": exercise_id}
        )
    return run


async def _signals(client: AsyncClient, idp: Idp, s: Setup, exercise_id: str) -> uuid.UUID:
    """Next inject plays scene 1; its signal is ingested and opens the exercise's incident,
    placed at Nairobi with its exposure (the consumers' work in the real stack)."""
    response = await client.post(f"/api/exercises/{exercise_id}/next", headers=idp.headers("duty"))
    assert response.status_code == 200, response.text
    player = s.players.get(idp.tenant_id, CODE)
    assert player is not None
    await player.wait()
    await asyncio.sleep(0.05)  # the scene-done callback
    fused = None
    for event in [e for e in s.publisher.events if e.type == "RAW_SIGNAL"]:
        fused = (await ingest(idp.engine, idp.tenant_id, event)).fused
    assert fused is not None
    return await _placed(idp, s, fused.incident_id)


async def _placed(idp: Idp, s: Setup, incident: uuid.UUID) -> uuid.UUID:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await exposure.compute(session, incident)
        await session.execute(
            update(Incident).where(Incident.id == incident).values(mission_id=s.nbo)
        )
        await session.commit()
    return incident


async def _checkin(idp: Idp, s: Setup, incident: uuid.UUID | None) -> Any:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        row, _ = await create_campaign(
            session,
            incident_id=incident,
            campaign=CampaignIn(
                campaign_type="CHECKIN",
                message="Are you safe?",
                channels=["APP"],
                audience={"exposed": True} if incident else {"missions": [str(s.nbo)]},
            ),
            created_by_type="PLAYBOOK",
            created_by="test",
            actor=SYSTEM,
        )
        await dispatch(session, datetime.now(UTC))
        await session.commit()
    return row


# --- templates and roles -----------------------------------------------------------------------


async def test_templates_name_their_mission(client: AsyncClient, idp: Idp, setup: Setup) -> None:
    viewer = (await client.get("/api/exercises/templates", headers=idp.headers("viewer"))).json()
    assert [(t["code"], t["mission_code"], t["theme"], t["scenes"]) for t in viewer] == [
        (CODE, "NBO", "Civil unrest", 2)
    ]
    assert (viewer[0]["can_launch"], viewer[0]["running"]) == (False, False)
    for sub, may in (("duty", True), ("hom", False), ("duty.par", False)):
        found = (await client.get("/api/exercises/templates", headers=idp.headers(sub))).json()
        assert found[0]["can_launch"] is may, sub


async def test_only_an_operator_at_the_mission_launches(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    for sub in ("viewer", "hom", "duty.par"):  # the Paris Duty Officer is not at Nairobi
        assert (await _launch(client, idp, sub)).status_code == 403, sub
    bad = await client.post(
        "/api/exercises",
        json={"template": CODE, "kind": "FUNCTIONAL", "source": "ILLUSTRATIVE"},
        headers=idp.headers("duty"),
    )
    assert bad.status_code == 422  # the source is never accepted (review of Prompt 113, L1)
    for template, kind in (("ADD-ON", "FUNCTIONAL"), ("NOPE", "FUNCTIONAL"), (CODE, "DRILL")):
        response = await client.post(
            "/api/exercises", json={"template": template, "kind": kind}, headers=idp.headers("duty")
        )
        assert response.status_code in (404, 422), (template, kind)
    assert await _audit(idp) == []


# --- launch, next inject, end ------------------------------------------------------------------


async def test_launch_play_and_end_scores_and_freezes(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    h = idp.headers("duty")
    demo = (await client.get(f"/api/scenarios/{CODE}", headers=h)).json()  # an IDLE demo run
    launched = await _launch(client, idp, "admin")
    assert launched.status_code == 201, launched.text
    body = launched.json()
    exercise_id, run = body["id"], await _run_id(idp, body["id"])
    assert (body["status"], body["source"], body["mission_code"], body["kind"]) == (
        "RUNNING",
        "EXERCISE",
        "NBO",
        "FUNCTIONAL",
    )
    assert body["run"]["scenes"] == [
        {"scene_no": 0, "name": "Calm"},
        {"scene_no": 1, "name": "Signals"},
        {"scene_no": 2, "name": "Hold"},
    ]  # never the expected result
    assert body["can_act"] is True
    assert (await _launch(client, idp)).status_code == 409  # one running per mission
    reset = await client.post(f"/api/scenarios/{CODE}/reset", headers=h)
    assert reset.status_code == 409  # end or abandon the exercise first
    running = (await client.get("/api/exercises/running", headers=idp.headers("viewer"))).json()
    assert [r["id"] for r in running] == [exercise_id]
    # The scenario API sees the exercise's run as the active one.
    assert (await client.get(f"/api/scenarios/{CODE}", headers=h)).json()["run_id"] == str(run)

    incident = await _signals(client, idp, setup, exercise_id)
    raw = [e for e in setup.publisher.events if e.type == "RAW_SIGNAL"]
    assert [e.payload[intel_queries.EXERCISE_MARKER] for e in raw] == [str(run)]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert await intel_queries.exercise_runs(session) == {incident: run}
    checkin = await _checkin(idp, setup, incident)
    assert checkin.escalate_after_s == 20  # the exercise's own setting (G-3: A)
    assert (await _checkin(idp, setup, None)).escalate_after_s == 600  # a live one keeps its value
    answer = Event(
        type="CHECKIN_RESPONSE",
        tenant_id=idp.tenant_id,
        payload={
            "person_id": str(setup.people["Hana"]),
            "status": "SAFE",
            "campaign": str(checkin.id),
        },
        source=f"scenario:{CODE}:{run}",
    )
    await response_handler(idp.engine, setup.publisher)(answer)

    ended = await client.post(f"/api/exercises/{exercise_id}/end", headers=h)
    assert ended.status_code == 200, ended.text
    out = ended.json()
    by = {s["dimension"]: s for s in out["scores"]}
    assert list(by) == list(exercises.DIMENSIONS)
    assert by["DETECTION"]["score"] == 100
    assert by["ACCOUNTABILITY"]["score"] == 50  # Hana of Hana and Peter
    assert (
        by["ACCOUNTABILITY"]["measured"]["answered"],
        by["ACCOUNTABILITY"]["measured"]["asked"],
    ) == (1, 2)
    assert (out["status"], out["incident_id"], out["participants"]) == (
        "COMPLETED",
        str(incident),
        1,
    )
    assert out["overall_score"] == exercises.overall([s["score"] for s in out["scores"]])
    assert (out["run"], out["can_act"], out["incident_reference"]) == (None, False, "INC-2026-1042")

    # Frozen: Peter answers afterwards; the record moves on, the exercise's scores do not.
    late = await client.post(
        f"/api/checkin/{checkin.id}/respond",
        json={"person_id": str(setup.people["Peter"]), "status": "SAFE"},
        headers=h,
    )
    assert late.status_code == 201
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        live = await exercises.score(session, incident, datetime.now(UTC))
    assert {s.dimension: s.score for s in live.scores}["ACCOUNTABILITY"] == 100
    again = (
        await client.get(f"/api/exercises/{exercise_id}", headers=idp.headers("viewer"))
    ).json()
    assert again["scores"] == out["scores"]
    assert again["overall_score"] == out["overall_score"]
    assert (await client.post(f"/api/exercises/{exercise_id}/end", headers=h)).status_code == 409
    assert (await client.post(f"/api/exercises/{exercise_id}/next", headers=h)).status_code == 409

    async with tenant_session(idp.tenant_id, idp.engine) as session:
        runs = dict(
            (r.id, (r.mode, r.status))
            for r in await session.execute(text("SELECT id, mode, status FROM scenario_run"))
        )
    assert runs[uuid.UUID(demo["run_id"])] == ("DEMO", "FINISHED")  # launch finished it
    assert runs[run] == ("EXERCISE", "FINISHED")  # end finished it
    # The scenario API starts a new demo run once the exercise is over.
    after = (await client.get(f"/api/scenarios/{CODE}", headers=h)).json()
    assert after["run_id"] not in (demo["run_id"], str(run))

    audited = await _audit(idp)
    assert [a for a, _ in audited] == ["EXERCISE.START", "EXERCISE.END"]
    start, end = audited[0][1], audited[1][1]
    assert (start["template"], start["kind"], start["run"], start["finished_run"]) == (
        CODE,
        "FUNCTIONAL",
        str(run),
        demo["run_id"],
    )
    assert (end["overall"], end["incident"], end["participants"]) == (
        out["overall_score"],
        "INC-2026-1042",
        1,
    )
    nexts = [d for a, d in await _audit(idp, "SCENARIO.NEXT")]
    assert [d["exercise_id"] for d in nexts] == [exercise_id]
    updates = [e for e in setup.publisher.events if e.type == "EXERCISE_UPDATED"]
    assert [e.payload for e in updates] == [{"exercise_id": exercise_id}] * 3  # start, next, end


async def test_launch_is_refused_while_the_template_plays(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    h = idp.headers("duty")
    await client.post(f"/api/scenarios/{CODE}/next", headers=h)
    await client.post(f"/api/scenarios/{CODE}/next", headers=h)  # scene 2 waits ten minutes
    state = (await client.get(f"/api/scenarios/{CODE}", headers=h)).json()
    assert state["status"] == "PLAYING"
    refused = await _launch(client, idp)
    assert refused.status_code == 409
    assert "pause" in refused.json()["detail"]
    await client.post(f"/api/scenarios/{CODE}/pause", headers=h)
    assert (await _launch(client, idp)).status_code == 201


async def test_ending_without_an_incident_scores_nothing(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    exercise_id = (await _launch(client, idp)).json()["id"]
    out = (
        await client.post(f"/api/exercises/{exercise_id}/end", headers=idp.headers("duty"))
    ).json()
    assert (out["status"], out["incident_id"], out["overall_score"], out["participants"]) == (
        "COMPLETED",
        None,
        None,
        0,
    )
    assert [s["score"] for s in out["scores"]] == [None] * 5


async def test_abandon_needs_a_reason_and_keeps_no_score(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    h = idp.headers("duty")
    exercise_id = (await _launch(client, idp)).json()["id"]
    url = f"/api/exercises/{exercise_id}/abandon"
    assert (await client.post(url, json={}, headers=h)).status_code == 422
    assert (
        await client.post(url, json={"reason": "x"}, headers=idp.headers("viewer"))
    ).status_code == 403
    assert (
        await client.post(url, json={"reason": "x"}, headers=idp.headers("duty.par"))
    ).status_code == 403
    out = (await client.post(url, json={"reason": "Called off"}, headers=h)).json()
    assert (out["status"], out["reason"], out["scores"], out["overall_score"]) == (
        "ABANDONED",
        "Called off",
        [],
        None,
    )
    assert (await client.post(url, json={"reason": "again"}, headers=h)).status_code == 409
    assert (await client.post(f"/api/exercises/{exercise_id}/end", headers=h)).status_code == 409
    assert [(a, d.get("reason")) for a, d in await _audit(idp)] == [
        ("EXERCISE.START", None),
        ("EXERCISE.ABANDON", "Called off"),
    ]
    listed = (await client.get("/api/exercises", headers=idp.headers("viewer"))).json()
    assert [(e["id"], e["status"]) for e in listed["exercises"]] == [(exercise_id, "ABANDONED")]
    assert listed["kpis"]["templates"] == 1
    assert (await client.get("/api/exercises/running", headers=h)).json() == []
    assert (await client.get(f"/api/exercises/{uuid.uuid4()}", headers=h)).status_code == 404


# --- the run marker, fusion and the label (plan §4) --------------------------------------------


async def test_the_marker_counts_only_from_its_own_exercise_run(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    exercise_id = (await _launch(client, idp)).json()["id"]
    run = await _run_id(idp, exercise_id)

    def marked(key: str, source: str, marker: uuid.UUID = run) -> Event:
        event = signal("DATAMINR", "High", external_id=key)
        event.payload["occurred_at"] = datetime.now(UTC).isoformat()
        event.payload[intel_queries.EXERCISE_MARKER] = str(marker)
        return Event(type=event.type, tenant_id=idp.tenant_id, payload=event.payload, source=source)

    other = uuid.uuid4()
    for event in (
        marked("live", "connector:dataminr"),  # a live signal carrying a marker
        marked("other", f"scenario:{CODE}:{other}", other),  # no such exercise run
        marked("mismatch", f"scenario:{CODE}:{other}"),  # not the run that sent it
    ):
        assert (await ingest(idp.engine, idp.tenant_id, event)).outcome == "REJECTED"
    assert (await ingest(idp.engine, idp.tenant_id, marked("ok", f"scenario:{CODE}:{run}"))).fused
    reasons = {d["reason"] for a, d in await _audit(idp, "RAW_SIGNAL.REJECT")}
    assert reasons == {"exercise marker outside its exercise run"}


async def test_fusion_keeps_exercise_and_live_apart(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    exercise_id = (await _launch(client, idp)).json()["id"]
    run = await _run_id(idp, exercise_id)
    now = datetime.now(UTC).isoformat()

    def at_epicentre(key: str, source: str, marker: uuid.UUID | None) -> Event:
        event = signal("DATAMINR", "High", external_id=key)
        event.payload["occurred_at"] = now
        if marker:
            event.payload[intel_queries.EXERCISE_MARKER] = str(marker)
        return Event(type=event.type, tenant_id=idp.tenant_id, payload=event.payload, source=source)

    live = (await ingest(idp.engine, idp.tenant_id, at_epicentre("l1", "test", None))).fused
    drill = (
        await ingest(idp.engine, idp.tenant_id, at_epicentre("e1", f"scenario:{CODE}:{run}", run))
    ).fused
    live2 = (await ingest(idp.engine, idp.tenant_id, at_epicentre("l2", "test", None))).fused
    drill2 = (
        await ingest(idp.engine, idp.tenant_id, at_epicentre("e2", f"scenario:{CODE}:{run}", run))
    ).fused
    assert live
    assert drill
    assert live2
    assert drill2
    assert live.created
    assert drill.created
    assert (live2.incident_id, live2.created) == (live.incident_id, False)
    assert (drill2.incident_id, drill2.created) == (drill.incident_id, False)

    incidents = (await client.get("/api/incidents", headers=idp.headers("viewer"))).json()
    assert {i["id"]: i["exercise"] for i in incidents} == {
        str(live.incident_id): False,
        str(drill.incident_id): True,
    }
    one = await client.get(f"/api/incidents/{drill.incident_id}", headers=idp.headers("viewer"))
    assert one.json()["exercise"] is True


async def test_the_label_reaches_campaigns_checkins_and_reviews(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    exercise_id = (await _launch(client, idp)).json()["id"]
    incident = await _signals(client, idp, setup, exercise_id)
    drill, live = await _checkin(idp, setup, incident), await _checkin(idp, setup, None)
    v = idp.headers("viewer")
    campaigns = (await client.get("/api/campaigns", headers=v)).json()
    assert {c["id"]: c["exercise"] for c in campaigns} == {str(drill.id): True, str(live.id): False}
    for row, expected in ((drill, True), (live, False)):
        summary = (await client.get(f"/api/checkin/{row.id}/summary", headers=v)).json()
        assert summary["exercise"] is expected
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            update(Incident).where(Incident.id == incident).values(status="MONITORING")
        )
        await session.commit()
    ready = (await client.get("/api/aar", headers=v)).json()["ready"]
    assert [(r["incident_id"], r["exercise"]) for r in ready] == [(str(incident), True)]


# --- left out of leadership figures (plan §4) ---------------------------------------------------


async def test_executive_and_predictive_leave_the_exercise_out(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    exercise_id = (await _launch(client, idp)).json()["id"]
    incident = await _signals(client, idp, setup, exercise_id)
    await _checkin(idp, setup, incident)
    v = idp.headers("viewer")
    overview = (await client.get("/api/executive/overview", headers=v)).json()
    assert overview["active_incidents"] == 0
    assert overview["posture"]["level"] == "GUARDED"
    assert overview["detection"]["incidents"] == 0
    assert overview["accounted"]["asked"] == 0
    live = [d for d in overview["trend"] if d["source"] == "LIVE"]  # GFX-05: illustrative aside
    assert live[-1]["day"] == overview["trend"][-1]["day"]  # today, where the exercise ran
    assert sum(d["incidents"] for d in live) == 0
    assert sum(d["signals"] for d in live) == 0
    assert overview["timeline"]["incident"] is None
    assert overview["timeline"]["recent"] == []
    assert all(m["mission_code"] != "NBO" for m in overview["attention"])
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        nbo = (await predictive.components(session, datetime.now(UTC).date()))[setup.nbo]
    assert nbo.incident is None
    # Operations still see it, labelled.
    missions = (await client.get("/api/missions", headers=v)).json()
    assert {m["code"]: m["display_risk"] for m in missions}["NBO"] == "HIGH"

    live = signal("DATAMINR", "High", external_id="live", where=(EPICENTRE[0] + 0.2, EPICENTRE[1]))
    live.payload["occurred_at"] = datetime.now(UTC).isoformat()
    fused = (await ingest(idp.engine, idp.tenant_id, live)).fused
    assert fused is not None
    assert fused.created
    await _placed(idp, setup, fused.incident_id)
    overview = (await client.get("/api/executive/overview", headers=v)).json()
    assert overview["active_incidents"] == 1
    assert overview["latest_incident"]["id"] == str(fused.incident_id)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        nbo = (await predictive.components(session, datetime.now(UTC).date()))[setup.nbo]
    assert nbo.incident is not None
    assert nbo.incident[0] == fused.reference


# --- check-in answers and clock in an exercise (plan §7) ----------------------------------------


async def test_an_exercise_answers_and_times_its_own_checkins_only(
    client: AsyncClient, idp: Idp, setup: Setup
) -> None:
    exercise_id = (await _launch(client, idp)).json()["id"]
    run = await _run_id(idp, exercise_id)
    incident = await _signals(client, idp, setup, exercise_id)
    drill = await _checkin(idp, setup, incident)
    live = await _checkin(idp, setup, None)  # newer: the simulator's "latest open check-in"
    source = f"scenario:{CODE}:{run}"

    def answer(person: str, campaign: str = "latest_open_checkin", src: str = source) -> Event:
        return Event(
            type="CHECKIN_RESPONSE",
            tenant_id=idp.tenant_id,
            payload={
                "person_id": str(setup.people[person]),
                "status": "SAFE",
                "campaign": campaign,
            },
            source=src,
        )

    handle = response_handler(idp.engine, setup.publisher)
    await handle(answer("Hana"))  # resolves to the live check-in: refused
    await handle(answer("Hana", str(live.id)))  # the live check-in by id: refused
    await handle(answer("Hana", str(drill.id), f"scenario:{CODE}:{uuid.uuid4()}"))  # no such run
    await handle(answer("Hana", str(drill.id), "simulator"))  # not a scenario's event
    await handle(answer("Hana", str(drill.id)))  # the exercise's own: recorded
    v = idp.headers("viewer")
    tallies = {
        row.id: (await client.get(f"/api/checkin/{row.id}/summary", headers=v)).json()["personnel"]
        for row in (drill, live)
    }
    assert (tallies[drill.id]["safe"], tallies[live.id]["safe"]) == (1, 0)
    reasons = [d["reason"] for a, d in await _audit(idp, "CHECKIN.REJECT")]
    assert reasons == [
        "an exercise answers its own check-ins only",
        "an exercise answers its own check-ins only",
        "simulated answers need a running demo scenario",
        "simulated answers need a running demo scenario",
    ]

    clock = Event(
        type="CHECKIN_CLOCK", tenant_id=idp.tenant_id, payload={"escalate_in_s": 20}, source=source
    )
    await clock_handler(idp.engine, setup.publisher)(clock)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        started = list(
            await session.scalars(
                select(AuditLog.entity_id).where(AuditLog.action == "CHECKIN.CLOCK_START")
            )
        )
    assert started == [drill.reference]

    # Once the exercise is over, its run sends nothing that counts.
    await client.post(
        f"/api/exercises/{exercise_id}/abandon", json={"reason": "x"}, headers=idp.headers("duty")
    )
    await handle(answer("Peter", str(drill.id)))
    peter = (await client.get(f"/api/checkin/{drill.id}/summary", headers=v)).json()["personnel"]
    assert peter["safe"] == 1
