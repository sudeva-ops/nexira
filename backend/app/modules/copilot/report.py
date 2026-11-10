"""The situation report (COP-04; docs/plan-pilot-cop.md §4): the design's sections, built from
an incident's record as the person asking, every sentence cited. Related risks are the
mission's drivers from the modules' own read functions, as the Executive Overview reads them;
the recommendations are stated rules, labelled. A draft: it is shown and exported, never sent
(§98 Q6). The export is audited (COPILOT.REPORT_EXPORT)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.llm import Sentence, Source
from app.core.security import CurrentUser
from app.modules.agents.models import AgentProposal
from app.modules.copilot import facts as f
from app.modules.copilot.writer import (
    LABEL,
    checkin_sentences,
    cited,
    exposure_sentence,
    incident_phrase,
    plural,
)
from app.modules.fleet import service as fleet
from app.modules.health_intel import service as health
from app.modules.intel import queries as intel
from app.modules.intel.schemas import IncidentOut
from app.modules.supply import service as supply
from app.modules.twin import service as twin

RULES_LABEL = "Rule-based recommendations from the record"
APPROVED = ("APPROVED", "EDITED_APPROVED", "AUTO_EXECUTED")


class ReportError(Exception):
    pass


@dataclass(frozen=True)
class Section:
    heading: str
    sentences: list[Sentence]
    note: str | None = None  # how the section was made, when it is not plain fact


@dataclass(frozen=True)
class Report:
    incident_id: uuid.UUID
    reference: str
    title: str
    as_of: datetime
    sections: list[Section]
    sources: list[Source]
    label: str = LABEL


_CAMPAIGNS = text(
    """
    SELECT id, reference, campaign_type FROM notification_campaign
     WHERE incident_id = :incident AND status IN ('SENDING', 'SENT')
     ORDER BY created_at
    """
)

_PROTECTED_SITE = text(
    """
    SELECT 1 FROM incident_exposure e JOIN site s ON s.id = e.subject_id
     WHERE e.incident_id = :incident AND e.subject_type = 'SITE' AND s.site_type <> 'HOTEL'
     LIMIT 1
    """
)


def _summary(i: f.IncidentFact) -> list[Sentence]:
    out = [
        Sentence(
            f"{incident_phrase(i)}, severity {i.severity}, status {i.status.lower()}"
            f"{f', confidence {i.confidence}%' if i.confidence is not None else ''}.",
            (i.source,),
        ),
        Sentence(
            f"Fused from {plural(i.signals, 'signal')} by "
            f"{plural(i.sources_named, 'intelligence source')}.",
            (i.source,),
        ),
    ]
    if i.exercise:
        out.append(Sentence("This incident belongs to an exercise; it is not real.", (i.source,)))
    return out


async def _actions(
    session: AsyncSession, i: f.IncidentFact, runs: list[f.RunFact]
) -> list[Sentence]:
    out = [
        Sentence(
            f"Playbook {r.code} ({r.name}): {r.done} of {r.steps} steps done, "
            f"{r.status.lower().replace('_', ' ')}"
            f"{f'; waiting for approval: {r.waiting}' if r.waiting else ''}.",
            (r.source,),
        )
        for r in runs
    ]
    sent = list(await session.execute(_CAMPAIGNS, {"incident": i.id}))
    if sent:
        kinds = ", ".join(f"{c.reference} ({c.campaign_type.lower()})" for c in sent)
        out.append(
            Sentence(
                f"Messages sent: {kinds}.",
                tuple(
                    Source("CAMPAIGN", c.reference, f"/notifications?campaign={c.id}") for c in sent
                ),
            )
        )
    approved = list(
        await session.scalars(
            select(AgentProposal)
            .where(AgentProposal.incident_id == i.id, AgentProposal.status.in_(APPROVED))
            .order_by(AgentProposal.decided_at.nulls_last(), AgentProposal.created_at)
        )
    )
    for p in approved:
        how = "approved automatically" if p.status == "AUTO_EXECUTED" else "approved by a person"
        out.append(
            Sentence(f"{p.title}: {how}.", (Source("PROPOSAL", p.title, f"/?proposal={p.id}"),))
        )
    return out or [Sentence("No action has been recorded yet.", (i.source,))]


async def _risks(
    session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID | None, today: datetime
) -> list[Sentence]:
    if mission_id is None:
        return []
    out: list[Sentence] = []
    for a in await health.list_advisories(session):
        if a.status == "OPEN" and any(m.mission_id == mission_id for m in a.missions):
            out.append(
                Sentence(
                    f"Health advisory {a.reference}: {a.topic}, level {a.level}.",
                    (Source("ADVISORY", a.reference, "/health"),),
                )
            )
    impacted = [
        s
        for s in await supply.list_suppliers(session, user, today.date(), mission_id)
        if s.impacted
    ]
    if impacted:
        out.append(
            Sentence(
                f"Supply: {plural(len(impacted), 'supplier')} impacted "
                f"({', '.join(s.name for s in impacted)}).",
                tuple(Source("SUPPLIER", s.code, "/supply") for s in impacted),
            )
        )
    blocked = [
        a
        for a in await fleet.list_assets(session, user, mission_id)
        if a.kind == "VEHICLE" and any(t.code in ("BLOCKED", "IN_ZONE") for t in a.tags)
    ]
    if blocked:
        out.append(
            Sentence(
                f"Fleet: {plural(len(blocked), 'vehicle')} unavailable "
                f"({', '.join(a.code for a in blocked)}).",
                tuple(Source("ASSET", a.code, "/fleet") for a in blocked),
            )
        )
    shelter = await twin.sheltering(session, mission_id)
    if shelter is not None:
        out.append(
            Sentence(
                "Shelter-in-place is in force at the mission's sites.",
                (Source("INCIDENT", shelter, "/twin"),),
            )
        )
    return out


async def _recommendations(
    session: AsyncSession, i: f.IncidentFact, c: f.CheckinFact | None
) -> list[Sentence]:
    """The rules of plan §4, in order; the last always applies."""
    out: list[Sentence] = []
    if c is not None:
        unaccounted = c.personnel.pending + c.citizens.pending
        if unaccounted:
            out.append(
                Sentence(
                    f"Follow up the {plural(unaccounted, 'person', 'people')} not yet "
                    "accounted for.",
                    (c.source,),
                )
            )
        if c.personnel.need_help + c.citizens.need_help:
            out.append(Sentence("Confirm assistance for everyone who asked for help.", (c.source,)))
    if await session.scalar(_PROTECTED_SITE, {"incident": i.id}):
        out.append(Sentence("Keep the mission closed to the public.", (i.source,)))
    out.append(Sentence("Reassess at the next check-in or on escalation.", (i.source,)))
    return out


async def build(session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID) -> Report:
    found = await intel.get_incident(session, incident_id)
    if found is None:
        raise ReportError("Incident not found")
    incident = IncidentOut(**{k: v for k, v in found[0].items() if k in IncidentOut.model_fields})
    now: datetime = await session.scalar(text("SELECT now()"))
    fact = await f.incident_fact(session, incident)
    checkin = await f.checkin_fact(session, user, incident)
    runs = await f.run_facts(session, incident)
    people = [s for s in [exposure_sentence(fact)] if s is not None]
    if checkin is not None:
        people.extend(checkin_sentences(checkin))
    sections = [
        Section("Summary", _summary(fact)),
        Section(
            "Our people",
            people or [Sentence("Nobody is recorded in the impact zone.", (fact.source,))],
        ),
        Section("Actions taken", await _actions(session, fact, runs)),
        Section(
            "Related risks",
            await _risks(session, user, incident.mission_id, now)
            or [Sentence("No related risk is recorded at the mission.", (fact.source,))],
        ),
        Section(
            "Recommendations", await _recommendations(session, fact, checkin), note=RULES_LABEL
        ),
    ]
    sentences = [s for section in sections for s in section.sentences]
    return Report(
        incident_id=incident.id,
        reference=incident.reference,
        title=f"Situation report · {incident.reference} · {incident.title}",
        as_of=now,
        sections=sections,
        sources=cited(sentences),
    )


async def export(session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID) -> Report:
    """COP-04: the same report for the print page, audited with its incident and sources."""
    report = await build(session, user, incident_id)
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="COPILOT.REPORT_EXPORT",
        entity_type="incident",
        entity_id=report.reference,
        details={"references": [s.reference for s in report.sources]},
    )
    return report
