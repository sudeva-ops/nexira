"""AI Risk Copilot API (COP-01..06; D-50). Every role may ask; each answer holds only what the
person asking may see (RLS, approvals.py; names per docs/plan-pilot-cop.md G-1). Simulated
wording, labelled; no model and no external call (COP-05)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.llm import Source
from app.core.security import CurrentUser, get_db
from app.modules.copilot import report, service
from app.modules.copilot.intents import Kind
from app.modules.copilot.schemas import (
    AnswerOut,
    AskIn,
    ReportIn,
    ReportOut,
    SectionOut,
    SentenceOut,
    SourceOut,
)
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]


def _source(s: Source) -> SourceOut:
    return SourceOut(kind=s.kind, reference=s.reference, href=s.href)


def _report_out(r: report.Report) -> ReportOut:
    return ReportOut(
        incident_id=r.incident_id,
        reference=r.reference,
        title=r.title,
        as_of=r.as_of,
        sections=[
            SectionOut(
                heading=s.heading,
                sentences=[
                    SentenceOut(text=x.text, sources=[_source(y) for y in x.sources])
                    for x in s.sentences
                ],
                note=s.note,
            )
            for s in r.sections
        ],
        sources=[_source(s) for s in r.sources],
        label=r.label,
    )


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


@router.post("/report")
async def draft_report(body: ReportIn, user: Reader, session: Db) -> ReportOut:
    """COP-04: the draft, as the person asking may see it. Reading it is not audited; asking
    for it is (COPILOT.ASK), and so is the export."""
    try:
        return _report_out(await report.build(session, user, body.incident_id))
    except report.ReportError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/report/export")
async def export_report(body: ReportIn, user: Reader, session: Db) -> ReportOut:
    """The print-ready report (a PDF from the browser), audited (COPILOT.REPORT_EXPORT)."""
    try:
        out = _report_out(await report.export(session, user, body.incident_id))
    except report.ReportError as e:
        raise HTTPException(404, str(e)) from e
    await session.commit()
    return out
