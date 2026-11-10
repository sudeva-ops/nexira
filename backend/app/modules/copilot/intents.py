"""What a question asks (COP-01; docs/plan-pilot-cop.md §2): deterministic keywords and
references, in a stated order, the first match winning. No fuzzy guessing (§98 Q3)."""

import re
from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    HELP = "HELP"
    REPORT = "REPORT"
    PEOPLE = "PEOPLE"
    DECISIONS = "DECISIONS"
    TRAVEL = "TRAVEL"
    READINESS = "READINESS"
    RISK = "RISK"
    INCIDENT = "INCIDENT"
    SITUATION = "SITUATION"
    UNKNOWN = "UNKNOWN"


REFERENCE = re.compile(r"\bINC-\d{4}-\d+\b", re.IGNORECASE)

# In matching order; INCIDENT is matched by a reference or a place, after these (§2).
_WORDS: list[tuple[Kind, tuple[str, ...]]] = [
    (Kind.HELP, ("help", "what can you", "what do you")),
    (Kind.REPORT, ("situation report", "sitrep", "briefing", "brief ")),
    (Kind.PEOPLE, ("check-in", "checkin", "responded", "accounted", "who has not", "safe")),
    (Kind.DECISIONS, ("decision", "approve", "waiting", "pending")),
    (Kind.TRAVEL, ("trip", "travel", "flight")),
    (Kind.READINESS, ("readiness", "exercise", "drill")),
    (Kind.RISK, ("risk", "elevated", "forecast", "this week")),
]
_SITUATION = ("situation", "summar", "what is happening", "what's happening", "overview")


@dataclass(frozen=True)
class Question:
    kind: Kind
    text: str  # lower case, single-spaced
    reference: str | None  # an incident reference, upper case


def classify(question: str) -> Question:
    text = " ".join(question.lower().split())
    found = REFERENCE.search(question)
    reference = found.group(0).upper() if found else None
    if not text:
        return Question(Kind.HELP, text, None)
    for kind, words in _WORDS:
        if any(w in f"{text} " for w in words):
            return Question(kind, text, reference)
    if reference:
        return Question(Kind.INCIDENT, text, reference)
    if any(w in text for w in _SITUATION):
        return Question(Kind.SITUATION, text, None)
    return Question(Kind.UNKNOWN, text, None)


def mentions(text: str, *names: str) -> bool:
    """A whole word or code in the question ("nbo", "nairobi"), not a fragment."""
    return any(re.search(rf"\b{re.escape(n.lower())}\b", text) for n in names if n)
