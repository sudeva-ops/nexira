import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=500)


class SourceOut(BaseModel):
    kind: str
    reference: str
    href: str


class SentenceOut(BaseModel):
    text: str
    sources: list[SourceOut]  # empty only for help and "I can't answer that yet"


class AnswerOut(BaseModel):
    kind: str  # the question type (docs/plan-pilot-cop.md §2)
    sentences: list[SentenceOut]
    sources: list[SourceOut]  # every source cited, once
    incident_id: uuid.UUID | None  # the incident a REPORT is about
    label: str  # simulated, always (COP-05)


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID


class SectionOut(BaseModel):
    heading: str
    sentences: list[SentenceOut]
    note: str | None  # how it was made, when not plain fact (the rule-based recommendations)


class ReportOut(BaseModel):
    """COP-04: a draft from the record; exported for print, never sent (§98 Q6)."""

    incident_id: uuid.UUID
    reference: str
    title: str
    as_of: datetime
    sections: list[SectionOut]
    sources: list[SourceOut]
    label: str
