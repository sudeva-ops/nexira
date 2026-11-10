"""Exercise & Training service (EXR-05..07; D-48; docs/plan-pilot-exr.md §3, §5): the rounding
the database checks, "—" without an incident, the scores agreeing with After-Action Review's
metrics on a hand-built record, the seeded history (idempotent, audited), the KPIs, and readiness
from the latest completed exercise on People & Sites, Site Twin and the Executive Overview.
Against real PostgreSQL, as nexira_api (the seeded Nairobi run is in the simulator's tests)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.modules.aar import service as aar
from app.modules.exercises import queries
from app.modules.exercises import service as exercises
from app.modules.people.models import Site
from app.modules.twin import service as twin_service
from app.tests.auth_helpers import Idp
from app.tests.test_aar_service import NOW, _world

DRILLED = datetime(2026, 10, 19, 10, tzinfo=UTC)


def test_rounding_is_half_up_as_the_database() -> None:
    assert [aar.half_up(v) for v in (89.5, 90.5, 98.8, 0.4)] == [90, 91, 99, 0]
    assert exercises.overall([None, 94, None, 85, None]) == 90  # 89.5
    assert exercises.overall([100, 94, 100, 100, 100]) == 99  # the demo record (plan §3)
    assert exercises.overall([None] * 5) is None


async def test_without_an_incident_every_score_is_a_dash(idp: Idp) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        scored = await exercises.score(session, None, NOW)
    assert [(s.dimension, s.score) for s in scored.scores] == [
        (d, None) for d in exercises.DIMENSIONS
    ]
    assert (scored.overall, scored.participants) == (None, 0)


async def test_the_scores_use_the_after_action_metrics(idp: Idp) -> None:
    incident = await _world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        found = await aar.incident(session, incident)
        assert found is not None
        metrics = {m.key: m for m in await aar.metrics(session, found, NOW)}
        made = await aar.decisions(session, found, NOW)
        scored = await exercises.score(session, incident, NOW)
    by = {s.dimension: s for s in scored.scores}
    notified = metrics["detection_to_notification"].value
    assert notified is not None
    assert by["DETECTION"].score == min(100, aar.half_up(100 * 120 / max(notified, 1.0)))
    assert by["DETECTION"].measured == {"seconds": notified, "target_s": 120.0}
    assert by["ACCOUNTABILITY"].score == metrics["personnel_accounted"].value
    within = sum(d.wait_s <= 300 for d in made)
    assert by["DECISION_SPEED"].measured["within"] == within
    assert by["DECISION_SPEED"].score == aar.half_up(100 * within / len(made))
    assert by["COMMUNICATION"].measured["simulated_delivery"] is True
    assert scored.overall == exercises.overall([s.score for s in scored.scores])


async def test_a_quiet_record_scores_what_it_has(idp: Idp) -> None:
    incident = await _world(idp, quiet=True)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        scored = await exercises.score(session, incident, NOW)
    assert len(scored.scores) == 5
    assert all(s.score is None or 0 <= s.score <= 100 for s in scored.scores)


async def _history(idp: Idp, mission: uuid.UUID, score: int = 79) -> list[exercises.HistoryIn]:
    return [
        exercises.HistoryIn(
            id=uuid.uuid5(mission, "exercise"),
            mission_id=mission,
            name="Civil unrest drill",
            kind="TABLETOP",
            started_at=DRILLED - timedelta(hours=2),
            ended_at=DRILLED,
            scores=(score + 2, score - 1, score + 1, score - 3, score + 1),
            participants=14,
        )
    ]


async def test_the_history_is_seeded_once_and_audited(idp: Idp) -> None:
    mission = await idp.mission("NBO")
    rows = await _history(idp, mission)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert await exercises.ensure_history(session, rows) == 1
        await session.commit()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert await exercises.ensure_history(session, rows) == 0
        await session.commit()
        row = (
            await session.execute(
                text(
                    "SELECT overall_score, source, (SELECT count(*) FROM exercise_score) AS n, "
                    "(SELECT count(*) FROM audit_log WHERE action = 'EXERCISE.SEED') AS audited "
                    "FROM exercise"
                )
            )
        ).one()
    assert tuple(row) == (79, "ILLUSTRATIVE", 5, 1)


async def _real(idp: Idp, mission: uuid.UUID, score: int | None, status: str = "COMPLETED") -> Any:
    """A real exercise at the mission, ended now: completed with five equal scores, or not."""
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        user = await session.scalar(
            text(
                "INSERT INTO app_user (tenant_id, external_id, email, display_name) VALUES "
                "(current_tenant_id(), gen_random_uuid()::text, gen_random_uuid()::text || '@x', "
                "'Operator') RETURNING id"
            )
        )
        scenario = await session.scalar(
            text(
                "INSERT INTO scenario (tenant_id, code, name) VALUES "
                "(current_tenant_id(), 'SC-' || gen_random_uuid(), 'S') RETURNING id"
            )
        )
        run = await session.scalar(
            text(
                "INSERT INTO scenario_run (tenant_id, scenario_id, mode) VALUES "
                "(current_tenant_id(), :s, 'EXERCISE') RETURNING id"
            ),
            {"s": scenario},
        )
        exercise = await session.scalar(
            text(
                "INSERT INTO exercise (tenant_id, mission_id, scenario_id, scenario_run_id, name, "
                "kind, started_by) VALUES (current_tenant_id(), :m, :s, :r, 'Nairobi unrest', "
                "'FUNCTIONAL', :u) RETURNING id"
            ),
            {"m": mission, "s": scenario, "r": run, "u": user},
        )
        if status == "COMPLETED":
            await session.execute(
                text(
                    "UPDATE exercise SET status = 'COMPLETED', overall_score = :o, "
                    "participants = 16, ended_by = :u WHERE id = :e"
                ),
                {"o": score, "u": user, "e": exercise},
            )
            await exercises.write_scores(
                session,
                exercise,
                [exercises.Score(d, score, {}) for d in exercises.DIMENSIONS],
            )
        else:
            await session.execute(
                text(
                    "UPDATE exercise SET status = 'ABANDONED', reason = 'Called off', "
                    "ended_by = :u WHERE id = :e"
                ),
                {"u": user, "e": exercise},
            )
        await session.commit()
    return exercise


async def _site(idp: Idp, mission: uuid.UUID, kind: str, score: int) -> uuid.UUID:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        site: uuid.UUID = await session.scalar(
            text(
                "INSERT INTO site (tenant_id, mission_id, site_type, name, location, "
                "readiness_score, last_drill_on) VALUES (current_tenant_id(), :m, :k, :n, "
                "'SRID=4326;POINT(0 0)', :s, :d) RETURNING id"
            ),
            {"m": mission, "k": kind, "n": f"{kind} NBO", "s": score, "d": DRILLED.date()},
        )
        await session.commit()
    return site


async def test_readiness_is_the_latest_completed_exercise(client: AsyncClient, idp: Idp) -> None:
    mission = await idp.mission("NBO")
    other = await idp.mission("ADD")
    await idp.user("viewer", [("VIEWER", None)])
    embassy = await _site(idp, mission, "EMBASSY", 79)
    await _site(idp, mission, "RESIDENCE", 73)
    await _site(idp, other, "EMBASSY", 88)  # no exercise: the seeded site value
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await exercises.ensure_history(session, await _history(idp, mission))
        await session.commit()

    async def figures() -> tuple[Any, Any, Any, int]:
        sites = (await client.get("/api/sites", headers=idp.headers("viewer"))).json()["items"]
        async with tenant_session(idp.tenant_id, idp.engine) as session:
            site = await session.get(Site, embassy)
            assert site is not None  # the floor plan's readiness card (no plan needed here)
            twin = await twin_service._readiness(session, site, [], names=False)
        overview = await client.get("/api/executive/overview", headers=idp.headers("viewer"))
        by = {(s["mission_code"], s["site_type"]): s for s in sites}
        return by, twin, overview.json()["readiness"], overview.status_code

    by, twin, overview, status = await figures()
    assert status == 200
    nbo = by[("NBO", "EMBASSY")]
    assert (nbo["readiness_score"], nbo["last_drill_on"], nbo["readiness_source"]) == (
        79,
        "2026-10-19",
        "ILLUSTRATIVE",
    )
    for key, seeded in ((("NBO", "RESIDENCE"), 73), (("ADD", "EMBASSY"), 88)):
        assert (by[key]["readiness_score"], by[key]["readiness_source"]) == (seeded, None)
    assert (twin.score, twin.source) == (79, "ILLUSTRATIVE")
    assert overview == {"mean": 84, "sites": 2, "from_exercises": 1, "illustrative": 2}

    await _real(idp, mission, None)  # completed with no figure: skipped
    await _real(idp, mission, 50, status="ABANDONED")  # abandoned: skipped
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert (await queries.readiness(session))[mission].score == 79

    await _real(idp, mission, 99)
    by, twin, overview, _ = await figures()
    nbo = by[("NBO", "EMBASSY")]
    assert (nbo["readiness_score"], nbo["readiness_source"]) == (99, "EXERCISE")
    assert nbo["last_drill_on"] == datetime.now(UTC).date().isoformat()
    assert (twin.score, twin.source) == (99, "EXERCISE")
    assert overview == {"mean": 94, "sites": 2, "from_exercises": 1, "illustrative": 1}


async def test_the_kpis(idp: Idp) -> None:
    mission = await idp.mission("NBO")
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await exercises.ensure_history(session, await _history(idp, mission))
        await session.execute(
            text(
                "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
                "SELECT current_tenant_id(), :m, t, 'Fictional ' || n "
                "FROM unnest(ARRAY['DIPLOMAT','LOCAL_STAFF','CITIZEN']) WITH ORDINALITY AS x(t, n)"
            ),
            {"m": mission},
        )
        await session.commit()
    await _real(idp, mission, 99)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        k = await exercises.kpis(session, datetime(2026, 12, 31, tzinfo=UTC))
    assert (k.this_year, k.average, k.average_last_year) == (2, 89, None)  # (79 + 99) / 2
    assert (k.took_part, k.personnel, k.templates) == (16, 2, 0)  # the larger of 14 and 16
