"""Exercise & Training (D-48; docs/plan-pilot-exr.md §3, §5): the five scores worked out from
the run's incident with After-Action Review's metrics and targets (D-47), the KPIs, the seeded
illustrative history, and a mission's readiness from its latest completed exercise."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.aar import service as aar
from app.modules.exercises import queries
from app.modules.exercises.models import Exercise, ExerciseScore
from app.modules.tenancy.service import SYSTEM, Actor

DIMENSIONS = ("DETECTION", "ACCOUNTABILITY", "DECISION_SPEED", "COMMUNICATION", "PLAN_ADHERENCE")
TOOK_PART_DAYS = 365  # "Staff who took part": the last 12 months (§93 Q7)


@dataclass(frozen=True)
class Score:
    dimension: str
    score: int | None  # None is "—"
    measured: dict[str, Any]


@dataclass(frozen=True)
class Scored:
    scores: list[Score]
    overall: int | None
    participants: int


def overall(scores: list[int | None]) -> int | None:
    """The rounded mean of the scores that have a figure; the database checks the same rule."""
    figures = [s for s in scores if s is not None]
    return aar.half_up(sum(figures) / len(figures)) if figures else None


def _share(part: int, whole: int) -> int | None:
    return aar.half_up(100 * part / whole) if whole else None


_COMMUNICATION = text(
    """
    WITH exposed AS (
      SELECT subject_id FROM incident_exposure
       WHERE incident_id = :incident AND subject_type = 'PERSON'
    )
    SELECT (SELECT count(*) FROM exposed) AS exposed,
           (SELECT count(DISTINCT d.person_id)
              FROM notification_delivery d
              JOIN notification_campaign c ON c.id = d.campaign_id
             WHERE c.incident_id = :incident AND d.status IN ('DELIVERED','READ')
               AND d.person_id IN (SELECT subject_id FROM exposed)) AS reached
    """
)

# The incident's first playbook run (plan §3).
_PLAN = text(
    """
    SELECT r.id, count(s.*) AS steps, count(s.*) FILTER (WHERE s.status = 'DONE') AS done
      FROM playbook_run r LEFT JOIN playbook_run_step s ON s.run_id = r.id
     WHERE r.incident_id = :incident
     GROUP BY r.id, r.started_at
     ORDER BY r.started_at NULLS LAST, r.id
     LIMIT 1
    """
)

_PARTICIPANTS = text(
    """
    SELECT count(DISTINCT l.person_id)
      FROM v_checkin_latest l
      JOIN notification_campaign c ON c.id = l.campaign_id
      JOIN person p ON p.id = l.person_id
     WHERE c.incident_id = :incident AND c.campaign_type = 'CHECKIN'
       AND p.person_type <> 'CITIZEN' AND l.status IN ('SAFE','NEED_HELP')
    """
)


async def score(session: AsyncSession, incident_id: uuid.UUID | None, now: datetime) -> Scored:
    """EXR-05: the five scores from the run's incident up to now; every one "—" without one."""
    found = await aar.incident(session, incident_id) if incident_id else None
    if found is None:
        return Scored([Score(d, None, {}) for d in DIMENSIONS], None, 0)
    params = {"incident": found.id}
    metrics = {m.key: m for m in await aar.metrics(session, found, now)}

    notified = metrics["detection_to_notification"].value
    target = aar.NOTIFICATION_TARGET_S
    detection = Score(
        "DETECTION",
        None if notified is None else min(100, aar.half_up(100 * target / max(notified, 1.0))),
        {"seconds": notified, "target_s": target},
    )

    answers = await aar.checkin_answers(session, found)
    accountability = Score(
        "ACCOUNTABILITY",
        _share(answers.answered, answers.asked) if answers else None,
        {"answered": answers.answered, "asked": answers.asked, "campaign": answers.reference}
        if answers
        else {},
    )

    made = await aar.decisions(session, found, now)
    in_time = sum(1 for d in made if d.wait_s <= aar.GATE_WAIT_S)
    decision_speed = Score(
        "DECISION_SPEED",
        _share(in_time, len(made)),
        {"within": in_time, "decisions": len(made), "target_s": aar.GATE_WAIT_S},
    )

    reach = (await session.execute(_COMMUNICATION, params)).one()
    communication = Score(
        "COMMUNICATION",
        _share(reach.reached, reach.exposed),
        {"reached": reach.reached, "exposed": reach.exposed, "simulated_delivery": True},
    )

    plan = (await session.execute(_PLAN, params)).one_or_none()
    adherence = Score(
        "PLAN_ADHERENCE",
        _share(plan.done, plan.steps) if plan else None,
        {"done": plan.done, "steps": plan.steps} if plan else {},
    )

    scores = [detection, accountability, decision_speed, communication, adherence]
    participants = await session.scalar(_PARTICIPANTS, params) or 0
    return Scored(scores, overall([s.score for s in scores]), participants)


async def write_scores(session: AsyncSession, exercise_id: uuid.UUID, scores: list[Score]) -> None:
    """In the transaction that completes the exercise (the database checks it at commit)."""
    session.add_all(
        ExerciseScore(
            tenant_id=session.info["tenant_id"],
            exercise_id=exercise_id,
            dimension=s.dimension,
            score=s.score,
            measured=s.measured,
        )
        for s in scores
    )
    await session.flush()


# --- readiness (EXR-07) --------------------------------------------------------------------

# --- KPIs (EXR-06) -------------------------------------------------------------------------

_YEAR = text(
    """
    SELECT count(*) AS n, round(avg(overall_score)) AS mean FROM exercise
     WHERE status = 'COMPLETED' AND ended_at >= :start AND ended_at < :end
    """
)

# Per mission, the most who took part in any one exercise in the last 12 months, summed: the
# illustrative rows count people, not names (plan G-4).
_TOOK_PART = text(
    """
    SELECT coalesce(sum(most), 0) FROM (
      SELECT max(participants) AS most FROM exercise
       WHERE status = 'COMPLETED' AND ended_at >= :since GROUP BY mission_id
    ) x
    """
)
_PERSONNEL = text("SELECT count(*) FROM person WHERE person_type <> 'CITIZEN'")


@dataclass(frozen=True)
class Kpis:
    this_year: int
    average: int | None
    average_last_year: int | None
    took_part: int
    personnel: int
    templates: int


async def kpis(session: AsyncSession, now: datetime) -> Kpis:
    year = datetime(now.year, 1, 1, tzinfo=now.tzinfo)
    last = datetime(now.year - 1, 1, 1, tzinfo=now.tzinfo)
    this = (await session.execute(_YEAR, {"start": year, "end": now})).one()
    before = (await session.execute(_YEAR, {"start": last, "end": year})).one()
    templates = len(list(await session.execute(text(queries.TEMPLATES_SQL))))
    return Kpis(
        this_year=this.n,
        average=int(this.mean) if this.mean is not None else None,
        average_last_year=int(before.mean) if before.mean is not None else None,
        took_part=await session.scalar(_TOOK_PART, {"since": now - timedelta(days=TOOK_PART_DAYS)})
        or 0,
        personnel=await session.scalar(_PERSONNEL) or 0,
        templates=templates,
    )


# --- the seeded illustrative history (EXR-06, §93 Q8) ---------------------------------------


@dataclass(frozen=True)
class HistoryIn:
    id: uuid.UUID
    mission_id: uuid.UUID
    name: str
    kind: str
    started_at: datetime
    ended_at: datetime
    scores: tuple[int, int, int, int, int]  # in DIMENSIONS order
    participants: int


async def ensure_history(
    session: AsyncSession, rows: list[HistoryIn], actor: Actor = SYSTEM
) -> int:
    """One illustrative completed exercise per mission, with its five scores, if new (by id).
    Audited once for the rows created."""
    created = 0
    tenant_id = session.info["tenant_id"]
    for h in rows:
        mean = overall(list(h.scores))
        added = await session.scalar(
            insert(Exercise)
            .values(
                id=h.id,
                tenant_id=tenant_id,
                mission_id=h.mission_id,
                name=h.name,
                kind=h.kind,
                status="COMPLETED",
                overall_score=mean,
                participants=h.participants,
                source="ILLUSTRATIVE",
                started_at=h.started_at,
                ended_at=h.ended_at,
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(Exercise.id)
        )
        if added is None:
            continue
        await write_scores(
            session,
            added,
            [
                Score(d, s, {"illustrative": True})
                for d, s in zip(DIMENSIONS, h.scores, strict=True)
            ],
        )
        created += 1
    if created:
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="EXERCISE.SEED",
            entity_type="exercise",
            details={"count": created, "source": "ILLUSTRATIVE"},
        )
    return created
