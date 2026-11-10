"""Facts for an answer, from the platform's read functions, as the person asking (COP-01..03;
docs/plan-pilot-cop.md §3). Each fact carries the record it came from. RLS scopes every read
to the tenant; names of people are given only to the roles that may record check-in answers,
for the incident's mission (plan G-1: A). A restricted trip is never read (D-33)."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import user_has_role
from app.core.llm import Source
from app.core.security import CurrentUser
from app.modules.agents import proposals
from app.modules.agents.models import Agent, AgentProposal
from app.modules.checkin import service as checkin
from app.modules.checkin.router import RESPOND_ROLES
from app.modules.copilot.intents import Kind, Question, mentions
from app.modules.exercises import queries as exercise_queries
from app.modules.intel import queries as intel
from app.modules.intel.normalise import severity_rank
from app.modules.intel.schemas import IncidentOut
from app.modules.people.queries import list_missions
from app.modules.people.schemas import MissionOut
from app.modules.playbooks import queries as playbooks
from app.modules.predictive import service as predictive

ELEVATED = ("MODERATE", "HIGH", "CRITICAL")


def incident_source(reference: str, incident_id: uuid.UUID) -> Source:
    return Source("INCIDENT", reference, f"/incidents?id={incident_id}")


@dataclass(frozen=True)
class IncidentFact:
    id: uuid.UUID
    reference: str
    title: str
    category: str
    severity: str
    status: str
    place: str | None
    confidence: int | None
    signals: int
    sources_named: int  # distinct intelligence sources
    exercise: bool
    mission_code: str | None
    exposed: dict[str, int]  # people, staff, delegates, citizens, sites, trips
    source: Source


@dataclass(frozen=True)
class CheckinFact:
    reference: str
    personnel: checkin.Tally
    citizens: checkin.Tally
    pending: list[str] | None  # personnel names, or None when the asker may not see names
    need_help: list[str] | None
    source: Source


@dataclass(frozen=True)
class RunFact:
    code: str
    name: str
    status: str
    done: int
    steps: int
    waiting: str | None  # the step awaiting approval
    source: Source


@dataclass(frozen=True)
class DecisionFact:
    title: str
    agent: str
    incident: str | None
    can_decide: bool
    source: Source


@dataclass(frozen=True)
class TripFact:
    reference: str
    destination: str
    travellers: int
    source: Source


@dataclass(frozen=True)
class MissionFact:
    code: str
    city: str
    risk: str
    peak: int | None  # the 14-day forecast's peak, when rising
    source: Source


@dataclass(frozen=True)
class ReadinessFact:
    code: str
    city: str
    score: int
    drilled_on: str
    illustrative: bool
    source: Source


@dataclass
class Facts:
    kind: Kind
    incidents: list[IncidentFact] = field(default_factory=list)
    checkins: list[CheckinFact] = field(default_factory=list)
    runs: list[RunFact] = field(default_factory=list)
    decisions: list[DecisionFact] = field(default_factory=list)
    trips: list[TripFact] = field(default_factory=list)
    missions: list[MissionFact] = field(default_factory=list)
    readiness: list[ReadinessFact] = field(default_factory=list)
    subject: str | None = None  # what the question named that was not found
    focused: bool = False  # one incident, found by reference or place

    def sources(self) -> list[Source]:
        out: list[Source] = []
        for group in (
            self.incidents,
            self.checkins,
            self.runs,
            self.decisions,
            self.trips,
            self.missions,
            self.readiness,
        ):
            for f in group:
                if f.source not in out:
                    out.append(f.source)
        return out


# --- finding the incident a question is about (plan §2) ---------------------------------------

_LATEST_CHECKIN = text(
    """
    SELECT incident_id FROM notification_campaign
     WHERE campaign_type = 'CHECKIN' AND incident_id IS NOT NULL
     ORDER BY created_at DESC LIMIT 1
    """
)


def _named_missions(q: Question, missions: list[MissionOut]) -> list[MissionOut]:
    return [m for m in missions if mentions(q.text, m.code, m.city)]


async def _incidents(session: AsyncSession) -> list[IncidentOut]:
    return await intel.list_incidents(session, status=None, limit=200)


async def find_incident(
    session: AsyncSession, q: Question, missions: list[MissionOut], *, fallback: bool
) -> IncidentOut | None:
    """By reference; else the incident at a named mission (the worst ACTIVE, else the latest);
    else, with fallback, the worst ACTIVE incident, then the one with the latest check-in."""
    every = await _incidents(session)
    if q.reference:
        return next((i for i in every if i.reference == q.reference), None)
    named = {m.id for m in _named_missions(q, missions)}
    if named:
        at = [i for i in every if i.mission_id in named]
        active = [i for i in at if i.status == "ACTIVE"]
        latest = sorted(at, key=lambda i: i.opened_at, reverse=True)
        return (active or latest)[0] if at else None
    if not fallback:
        return None
    active = [i for i in every if i.status == "ACTIVE"]
    if active:
        return active[0]  # list_incidents is worst first
    latest = await session.scalar(_LATEST_CHECKIN)
    return next((i for i in every if i.id == latest), None)


# --- the facts --------------------------------------------------------------------------------


async def incident_fact(session: AsyncSession, incident: IncidentOut) -> IncidentFact:
    found = await intel.get_incident(session, incident.id)
    fields = found[0] if found else {}
    summary = fields.get("exposure_summary")
    exposed = (
        {
            "people": summary.people,
            "staff": summary.staff,
            "delegates": summary.delegates,
            "citizens": summary.citizens,
            "sites": summary.mission_sites,
            "trips": summary.trips,
        }
        if summary is not None
        else {}
    )
    return IncidentFact(
        id=incident.id,
        reference=incident.reference,
        title=incident.title,
        category=incident.category,
        severity=incident.severity,
        status=incident.status,
        place=incident.place_label,
        confidence=incident.confidence,
        signals=incident.signal_count,
        sources_named=len(incident.sources),
        exercise=incident.exercise,
        mission_code=fields.get("mission_code"),
        exposed=exposed,
        source=incident_source(incident.reference, incident.id),
    )


_CAMPAIGN = text(
    """
    SELECT id, reference FROM notification_campaign
     WHERE incident_id = :incident AND campaign_type = 'CHECKIN'
     ORDER BY created_at DESC LIMIT 1
    """
)

# Mission personnel (not citizens) by their latest answer to the check-in.
_PERSONNEL = text(
    """
    SELECT DISTINCT p.full_name, coalesce(l.status, 'PENDING') AS status
      FROM notification_delivery d
      JOIN person p ON p.id = d.person_id
      LEFT JOIN v_checkin_latest l ON l.campaign_id = d.campaign_id AND l.person_id = d.person_id
     WHERE d.campaign_id = :campaign AND p.person_type <> 'CITIZEN'
     ORDER BY p.full_name
    """
)


async def may_name(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID | None) -> bool:
    """Plan G-1 (A): the roles that may record check-in answers, at the incident's mission."""
    return await user_has_role(session, user, RESPOND_ROLES, mission_id)


async def checkin_fact(
    session: AsyncSession, user: CurrentUser, incident: IncidentOut
) -> CheckinFact | None:
    row = (await session.execute(_CAMPAIGN, {"incident": incident.id})).one_or_none()
    if row is None:
        return None
    tallies = await checkin.tally(session, row.id)
    named = await may_name(session, user, incident.mission_id)
    people = list(await session.execute(_PERSONNEL, {"campaign": row.id})) if named else []
    return CheckinFact(
        reference=row.reference,
        personnel=tallies["personnel"],
        citizens=tallies["citizens"],
        pending=[p.full_name for p in people if p.status == "PENDING"] if named else None,
        need_help=[p.full_name for p in people if p.status == "NEED_HELP"] if named else None,
        source=Source("CHECKIN", row.reference, f"/checkin?campaign={row.id}"),
    )


async def run_facts(session: AsyncSession, incident: IncidentOut) -> list[RunFact]:
    runs = await playbooks.list_runs(session, incident_id=incident.id, status=None, limit=5)
    return [
        RunFact(
            code=r.playbook_code,
            name=r.playbook_name,
            status=r.status,
            done=sum(s.status == "DONE" for s in r.steps),
            steps=len(r.steps),
            waiting=next((s.name for s in r.steps if s.status == "AWAITING_APPROVAL"), None),
            source=Source(
                "PLAYBOOK_RUN", r.playbook_code, f"/playbooks?code={r.playbook_code}&run={r.id}"
            ),
        )
        for r in runs
    ]


async def decision_facts(session: AsyncSession, user: CurrentUser) -> list[DecisionFact]:
    rows = list(
        await session.scalars(
            select(AgentProposal)
            .where(AgentProposal.status == "PENDING")
            .order_by(AgentProposal.deadline_at.asc().nulls_last(), AgentProposal.created_at)
            .limit(10)
        )
    )
    agents = {a.id: a.name for a in await session.scalars(select(Agent))}
    references = {i.id: i.reference for i in await _incidents(session)}
    return [
        DecisionFact(
            title=p.title,
            agent=agents.get(p.agent_id, "An agent"),
            incident=references.get(p.incident_id) if p.incident_id else None,
            can_decide=await proposals.can_decide(session, user, p),
            source=Source("PROPOSAL", p.title, f"/?proposal={p.id}"),
        )
        for p in rows
    ]


# Unrestricted trips in the incident's exposure, with their travellers (D-33).
_TRIPS = text(
    """
    SELECT t.id, t.reference, t.destination,
           (SELECT count(*) FROM trip_traveller tt WHERE tt.trip_id = t.id) AS travellers
      FROM incident_exposure e JOIN trip t ON t.id = e.subject_id
     WHERE e.incident_id = :incident AND e.subject_type = 'TRIP' AND NOT t.restricted
     ORDER BY t.reference
    """
)


async def trip_facts(session: AsyncSession, incident: IncidentOut) -> list[TripFact]:
    return [
        TripFact(
            r.reference,
            r.destination,
            r.travellers,
            Source("TRIP", r.reference, f"/journeys?trip={r.id}"),
        )
        for r in await session.execute(_TRIPS, {"incident": incident.id})
    ]


async def risk_facts(session: AsyncSession, missions: list[MissionOut]) -> list[MissionFact]:
    rising = {
        r.mission_id: r.peak for r in (await predictive.overview(session)).rising if r.crosses
    }
    picked = [m for m in missions if m.display_risk in ELEVATED or m.id in rising]
    picked.sort(key=lambda m: (-severity_rank(m.display_risk), -(rising.get(m.id) or 0), m.code))
    return [
        MissionFact(
            m.code,
            m.city,
            m.display_risk,
            rising.get(m.id),
            Source("MISSION", m.code, f"/predictive?mission={m.id}"),
        )
        for m in picked
    ]


async def readiness_facts(
    session: AsyncSession, q: Question, missions: list[MissionOut]
) -> list[ReadinessFact]:
    drills = await exercise_queries.readiness(session)
    named = _named_missions(q, missions)
    chosen = (
        named
        or sorted((m for m in missions if m.id in drills), key=lambda m: drills[m.id].score)[:3]
    )  # unnamed: the three lowest
    return [
        ReadinessFact(
            m.code,
            m.city,
            d.score,
            d.drilled_on.isoformat(),
            d.source != "EXERCISE",
            Source("EXERCISE", d.name, f"/exercises?exercise={d.exercise_id}"),
        )
        for m in chosen
        if (d := drills.get(m.id)) is not None
    ]


async def gather(session: AsyncSession, user: CurrentUser, q: Question) -> Facts:
    facts = Facts(q.kind)
    if q.kind in (Kind.HELP, Kind.UNKNOWN):
        return facts
    missions = await list_missions(session)
    if q.kind is Kind.DECISIONS:
        facts.decisions = await decision_facts(session, user)
        return facts
    if q.kind is Kind.RISK:
        facts.missions = await risk_facts(session, missions)
        return facts
    if q.kind is Kind.READINESS:
        facts.readiness = await readiness_facts(session, q, missions)
        return facts
    needs_one = q.kind in (Kind.INCIDENT, Kind.PEOPLE, Kind.TRAVEL, Kind.REPORT)
    named = bool(q.reference or _named_missions(q, missions))
    if q.kind is Kind.SITUATION and not named:
        for active in [i for i in await _incidents(session) if i.status == "ACTIVE"][:5]:
            facts.incidents.append(await incident_fact(session, active))
            if (c := await checkin_fact(session, user, active)) is not None:
                facts.checkins.append(c)
        return facts
    incident = await find_incident(session, q, missions, fallback=needs_one)
    if incident is None:
        facts.subject = q.reference or ", ".join(m.city for m in _named_missions(q, missions))
        return facts
    facts.incidents = [await incident_fact(session, incident)]
    facts.focused = True
    with_checkin = (Kind.SITUATION, Kind.INCIDENT, Kind.PEOPLE, Kind.REPORT)
    if q.kind in with_checkin and (c := await checkin_fact(session, user, incident)) is not None:
        facts.checkins = [c]
    if q.kind in (Kind.SITUATION, Kind.INCIDENT):
        facts.runs = await run_facts(session, incident)
    if q.kind is Kind.TRAVEL:
        facts.trips = await trip_facts(session, incident)
    return facts
