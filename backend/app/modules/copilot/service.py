"""The AI Risk Copilot, simulated (COP-01..06, D-50; docs/plan-pilot-cop.md): a question is
classified, its facts gathered as the person asking, and worded by the TemplateWriter. Each
question is audited with its type and the references cited, never its text (§98 Q4)."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.llm import Sentence, Source, Writer
from app.core.security import CurrentUser
from app.modules.copilot import facts as copilot_facts
from app.modules.copilot.intents import Question, classify
from app.modules.copilot.writer import LABEL, TemplateWriter, cited


@dataclass(frozen=True)
class Answer:
    question: Question
    facts: copilot_facts.Facts
    sentences: list[Sentence]
    sources: list[Source]
    label: str = LABEL


async def ask(
    session: AsyncSession,
    user: CurrentUser,
    question: str,
    writer: Writer[copilot_facts.Facts] | None = None,
) -> Answer:
    q = classify(question)
    found = await copilot_facts.gather(session, user, q)
    sentences = (writer or TemplateWriter()).write(found)
    sources = cited(sentences)
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action="COPILOT.ASK",
        entity_type="copilot",
        details={"kind": q.kind.value, "references": [s.reference for s in sources]},
    )
    return Answer(q, found, sentences, sources)
