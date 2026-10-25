"""Runs the Phase 1 agents on stream events (worker consumer group "agents").

For each event, every agent that observes its type:
1. observe() runs in a session whose transaction is always rolled back, so an
   agent can only read;
2. each draft goes to proposals.create() in its own transaction. The stable
   proposal_key makes a redelivered or re-observed event harmless. While agents
   are paused (D-17) or an agent is disabled, creation is refused and skipped.
Events from the proposals (PROPOSAL_CREATED, executed actions) are published
after each commit.
"""

import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler, Publisher
from app.modules.agents import proposals
from app.modules.agents.actions import ActionError
from app.modules.agents.agents import AGENTS, PhaseOneAgent

log = logging.getLogger(__name__)


def observed_types(agents: Iterable[PhaseOneAgent] = AGENTS) -> set[str]:
    return {t for agent in agents for t in agent.observes}


async def run_agents(
    engine: AsyncEngine,
    publisher: Publisher,
    event: Event,
    *,
    undo_window_s: int,
    agents: Iterable[PhaseOneAgent] = AGENTS,
) -> list[proposals.Outcome]:
    outcomes = []
    for agent in agents:
        if event.type not in agent.observes:
            continue
        async with tenant_session(event.tenant_id, engine) as session:
            drafts = await agent.observe(session, event)
            await session.rollback()  # agents only read
        for draft in drafts:
            async with tenant_session(event.tenant_id, engine) as session:
                try:
                    outcome = await proposals.create(session, draft, undo_window_s=undo_window_s)
                except proposals.AgentsPausedError as e:
                    log.info("%s: %s; %s not proposed", agent.code, e, draft.proposal_key)
                    continue
                except (proposals.ProposalError, ActionError) as e:
                    log.warning("%s: draft %s refused: %s", agent.code, draft.proposal_key, e)
                    continue
                await session.commit()
            if outcome.created:
                outcomes.append(outcome)
                for published in outcome.events:
                    await publisher.publish(published)
    return outcomes


def agents_handler(engine: AsyncEngine, publisher: Publisher, undo_window_s: int) -> Handler:
    async def handle(event: Event) -> None:
        await run_agents(engine, publisher, event, undo_window_s=undo_window_s)

    return handle
