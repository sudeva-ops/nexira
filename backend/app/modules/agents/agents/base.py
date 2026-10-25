"""What every Phase 1 agent is.

An agent observes one event and returns proposal drafts. It never acts: drafts go
through proposals.create(), where the database decides the level and people decide
the rest (D-12). The runner gives observe() a session whose transaction is always
rolled back, so an agent can read but nothing it writes is kept.

Agents are deterministic (rules and templates). LLM access, if ever used, goes
through app/core/llm.py, stubbed in tests (AGT-09).
"""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.agents.proposals import ProposalIn


class PhaseOneAgent(Protocol):
    code: str  # matches agent.code in the seed
    observes: frozenset[str]  # event types

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]: ...
