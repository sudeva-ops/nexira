import uuid

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
