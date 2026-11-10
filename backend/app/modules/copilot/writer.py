"""Simulated wording (COP-05; docs/plan-pilot-cop.md §5): one stated template per question type,
filled from the facts. Every sentence cites the sources of the facts it states; only the help
text and "I can't answer that yet" have none. A writer backed by the local model can replace
this one (app/core/llm.py's Writer), given the same facts."""

from app.core.llm import Sentence, Source
from app.modules.copilot.facts import CheckinFact, Facts, IncidentFact
from app.modules.copilot.intents import Kind

LABEL = "Simulated copilot · rule-based wording · simulated data"

CAN_ANSWER = (
    "the situation now",
    "an incident, by reference or place",
    "our people and the check-in",
    "decisions waiting",
    "missions at risk",
    "travel near an incident",
    "a mission's readiness",
    "a situation report for an incident",
)
EXAMPLES = (
    "Summarise the Nairobi situation",
    "Which missions are at elevated risk this week?",
    "Who has not responded to the check-in?",
)
LABELS = {"CIVIL_UNREST": "civil unrest", "TRANSPORT_STRIKE": "transport strike"}


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def incident_phrase(i: IncidentFact) -> str:
    what = LABELS.get(i.category, i.category.replace("_", " ").lower())
    drill = " (exercise)" if i.exercise else ""
    return f"{i.reference}{drill}, {what} at {i.place or 'an unknown place'}"


def _about(i: IncidentFact) -> Sentence:
    confidence = f", confidence {i.confidence}%" if i.confidence is not None else ""
    return Sentence(
        f"{incident_phrase(i)}: {i.severity}, {i.status.lower()}{confidence}, from "
        f"{plural(i.sources_named, 'intelligence source')}.",
        (i.source,),
    )


def exposure_sentence(i: IncidentFact) -> Sentence | None:
    e = i.exposed
    if not e or not e.get("people"):
        return None
    return Sentence(
        f"{plural(e['people'], 'person', 'people')} are in the impact zone: "
        f"{e['staff']} staff, {e['delegates']} delegates and {e['citizens']} citizens; "
        f"{plural(e['sites'], 'mission site')} and {plural(e['trips'], 'trip')}.",
        (i.source,),
    )


def checkin_sentences(c: CheckinFact) -> list[Sentence]:
    p, ci = c.personnel, c.citizens
    out = [
        Sentence(
            f"Check-in {c.reference}: of {p.recipients} personnel, {p.safe} safe, "
            f"{p.need_help} need help and {p.pending} not yet answered; of {ci.recipients} "
            f"citizens, {ci.safe} safe, {ci.need_help} need help and {ci.pending} "
            "not yet answered.",
            (c.source,),
        )
    ]
    if c.need_help:
        out.append(Sentence(f"Asked for help: {names(c.need_help)}.", (c.source,)))
    if c.pending:
        out.append(Sentence(f"Not yet answered: {names(c.pending)}.", (c.source,)))
    return out


def _not_found(subject: str | None) -> Sentence:
    about = f" for {subject}" if subject else ""
    return Sentence(f"I found no incident{about}.", ())


class TemplateWriter:
    def write(self, facts: Facts) -> list[Sentence]:
        kind = facts.kind
        if kind is Kind.HELP:
            return [
                Sentence("I can answer about " + "; ".join(CAN_ANSWER) + ".", ()),
                Sentence("For example: " + " · ".join(EXAMPLES) + ".", ()),
            ]
        if kind is Kind.UNKNOWN:
            return [
                Sentence(
                    "I can't answer that yet. I can answer about " + "; ".join(CAN_ANSWER) + ".",
                    (),
                )
            ]
        if kind is Kind.DECISIONS:
            return self._decisions(facts)
        if kind is Kind.RISK:
            return self._risk(facts)
        if kind is Kind.READINESS:
            return self._readiness(facts)
        if not facts.incidents:
            if kind is Kind.SITUATION and facts.subject is None:
                return [Sentence("No incident is active.", ())]
            return [_not_found(facts.subject)]
        if kind is Kind.SITUATION and not facts.focused:
            return self._overview(facts)
        incident = facts.incidents[0]
        if kind is Kind.PEOPLE:
            if not facts.checkins:
                return [
                    Sentence(
                        f"No check-in has been sent for {incident.reference}.", (incident.source,)
                    )
                ]
            return checkin_sentences(facts.checkins[0])
        if kind is Kind.TRAVEL:
            return self._travel(facts, incident)
        if kind is Kind.REPORT:
            return [
                Sentence(
                    f"Here is a draft situation report for {incident_phrase(incident)}.",
                    (incident.source,),
                )
            ]
        out = [_about(incident)]
        if (e := exposure_sentence(incident)) is not None:
            out.append(e)
        for c in facts.checkins:
            out.extend(checkin_sentences(c)[:1])
        for r in facts.runs:
            waiting = f"; waiting for approval: {r.waiting}" if r.waiting else ""
            out.append(
                Sentence(
                    f"Playbook {r.code} ({r.name}): {r.done} of {r.steps} steps done, "
                    f"{r.status.lower().replace('_', ' ')}{waiting}.",
                    (r.source,),
                )
            )
        return out

    def _overview(self, facts: Facts) -> list[Sentence]:
        out = [
            Sentence(
                f"{plural(len(facts.incidents), 'incident')} active, the worst first.",
                tuple(i.source for i in facts.incidents),
            )
        ]
        checkins = {c.source.reference: c for c in facts.checkins}
        for i in facts.incidents:
            out.append(_about(i))
            if (e := exposure_sentence(i)) is not None:
                out.append(e)
        for c in checkins.values():
            out.extend(checkin_sentences(c)[:1])
        return out

    def _travel(self, facts: Facts, incident: IncidentFact) -> list[Sentence]:
        if not facts.trips:
            return [
                Sentence(f"No trip is in the zone of {incident.reference}.", (incident.source,))
            ]
        trips = ", ".join(
            f"{t.reference} to {t.destination} ({plural(t.travellers, 'traveller')})"
            for t in facts.trips
        )
        return [
            Sentence(
                f"In the zone of {incident.reference}: {trips}.",
                (incident.source, *(t.source for t in facts.trips)),
            )
        ]

    def _decisions(self, facts: Facts) -> list[Sentence]:
        if not facts.decisions:
            return [Sentence("No decision is waiting.", ())]
        mine = sum(d.can_decide for d in facts.decisions)
        out = [
            Sentence(
                f"{plural(len(facts.decisions), 'decision')} waiting, the nearest deadline first; "
                f"you can decide {mine}.",
                tuple(d.source for d in facts.decisions),
            )
        ]
        for d in facts.decisions:
            about = f" for {d.incident}" if d.incident else ""
            out.append(Sentence(f"{d.agent}{about}: {d.title}.", (d.source,)))
        return out

    def _risk(self, facts: Facts) -> list[Sentence]:
        if not facts.missions:
            return [Sentence("No mission is at elevated risk, and none is forecast to rise.", ())]
        out = []
        for m in facts.missions:
            rising = (
                f"; forecast to reach {m.peak} in the next 14 days" if m.peak is not None else ""
            )
            out.append(
                Sentence(f"{m.city} ({m.code}): {m.risk.lower()} risk{rising}.", (m.source,))
            )
        return out

    def _readiness(self, facts: Facts) -> list[Sentence]:
        if not facts.readiness:
            return [Sentence("I found no exercise for that mission.", ())]
        return [
            Sentence(
                f"{r.city} ({r.code}): readiness {r.score}/100 from its last exercise on "
                f"{r.drilled_on}{' (illustrative)' if r.illustrative else ''}.",
                (r.source,),
            )
            for r in facts.readiness
        ]


def cited(sentences: list[Sentence]) -> list[Source]:
    out: list[Source] = []
    for s in sentences:
        for src in s.sources:
            if src not in out:
                out.append(src)
    return out
