"""Playbook handlers for the stream consumer (app/workers).

PLAYBOOK_RUN_STARTED and PLAYBOOK_STEP_APPROVED advance the run in engine.advance(),
which is safe to repeat: a redelivered event finds the steps already DONE.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.events import Event, Handler, Publisher
from app.modules.playbooks import engine as playbook_engine


def run_handler(engine: AsyncEngine, publisher: Publisher, step_delay_s: float) -> Handler:
    async def handle(event: Event) -> None:
        await playbook_engine.advance(
            engine,
            event.tenant_id,
            uuid.UUID(event.payload["run_id"]),
            publisher,
            step_delay_s=step_delay_s,
        )

    return handle


async def resume_runs(
    engine: AsyncEngine, publisher: Publisher, tenant_ids: list[uuid.UUID], step_delay_s: float
) -> int:
    """Continue every RUNNING run, e.g. after a worker restart. Returns how many."""
    resumed = 0
    for tenant_id in tenant_ids:
        for run_id in await playbook_engine.resumable_runs(engine, tenant_id):
            await playbook_engine.advance(
                engine, tenant_id, run_id, publisher, step_delay_s=step_delay_s
            )
            resumed += 1
    return resumed
