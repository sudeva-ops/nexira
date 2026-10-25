"""Scene 5 fixture (decisions.md §7, plan G-16): inject a START_EVACUATION proposal
for the active Nairobi incident through the proposal service, as the
RESPONSE_PLANNER agent. No Phase 1 agent proposes START_EVACUATION; this exists so
the two-person rule can be demonstrated and tested end to end.

    APP_ENV=local uv run python -m nexira_sim.fixtures.evacuation   # prints the proposal id

Refuses to run unless APP_ENV is local or demo.
"""

import asyncio
import os
import sys
import time

from app.core.db import create_engine, tenant_session
from app.modules.agents import proposals
from app.modules.intel.models import Incident
from sqlalchemy import select

from nexira_sim.seed.ids import DEMO_TENANT_ID


async def inject() -> str:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        async with tenant_session(DEMO_TENANT_ID, engine) as session:
            incident = await session.scalar(
                select(Incident)
                .where(Incident.status == "ACTIVE", Incident.category == "CIVIL_UNREST")
                .order_by(Incident.opened_at.desc())
                .limit(1)
            )
            if incident is None:
                raise SystemExit("no ACTIVE civil unrest incident; play scene 1 first")
            outcome = await proposals.create(
                session,
                proposals.ProposalIn(
                    agent_code="RESPONSE_PLANNER",
                    proposal_key=f"TEST:START_EVACUATION:{incident.id}:{time.time_ns()}",
                    action_type="START_EVACUATION",
                    title="Evacuate Embassy staff via route B",
                    proposed_action="Move personnel in the zone to the airport via route B.",
                    action_payload={"route": "B"},
                    incident_id=incident.id,
                    evidence=[
                        {"text": "Scene 5 test fixture (plan G-16)", "source": "test fixture"}
                    ],
                    risk_if_no_action="Staff remain in the impact zone.",
                    confidence=80,
                ),
                undo_window_s=300,
            )
            await session.commit()
            return str(outcome.proposal.id)
    finally:
        await engine.dispose()


def main() -> None:
    if os.environ.get("APP_ENV") not in ("local", "demo"):
        sys.exit("refused: APP_ENV must be local or demo")
    print(asyncio.run(inject()))


if __name__ == "__main__":
    main()
