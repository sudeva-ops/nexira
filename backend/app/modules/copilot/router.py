"""AI Risk Copilot API (COP-01..06; D-50). Every role may ask; each answer holds only what the
person asking may see (RLS, approvals.py; names per docs/plan-pilot-cop.md G-1). Simulated
wording, labelled; no model and no external call (COP-05)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.llm import Source
from app.core.security import CurrentUser, get_db
from app.modules.copilot import service
from app.modules.copilot.intents import Kind
from app.modules.copilot.schemas import AnswerOut, AskIn, SentenceOut, SourceOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


def _source(s: Source) -> SourceOut:
    return SourceOut(kind=s.kind, reference=s.reference, href=s.href)


@router.post("/ask")
async def ask(body: AskIn, user: Reader, session: Db) -> AnswerOut:
    answer = await service.ask(session, user, body.question)
    await session.commit()
    focused = answer.facts.incidents[0].id if answer.facts.focused else None
    return AnswerOut(
        kind=answer.question.kind.value,
        sentences=[
            SentenceOut(text=s.text, sources=[_source(x) for x in s.sources])
            for s in answer.sentences
        ],
        sources=[_source(s) for s in answer.sources],
        incident_id=focused if answer.question.kind is Kind.REPORT else None,
        label=answer.label,
    )
