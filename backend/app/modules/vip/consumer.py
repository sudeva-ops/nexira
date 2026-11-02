"""The simulated programme progress for the worker (plan-pilot-vip §5, §9). A VIP_PROGRESS
event starts a visit (status LIVE) or moves one segment one step, as the SYSTEM actor
"visit progress (simulated)", through the same checks as a person's step. Nothing is
published (G-3): the screen polls. Programme status only, never a position (VIP-04)."""

import logging

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.core.events import Event, Handler
from app.modules.vip import service

log = logging.getLogger(__name__)


class ProgressIn(BaseModel):
    visit: str = Field(pattern=r"^VV-[0-9]{4}-[0-9]{3,}$")
    seq: int | None = Field(default=None, ge=1, le=50)
    status: str = Field(pattern=r"^(LIVE|IN_PROGRESS|COMPLETED)$")

    @model_validator(mode="after")
    def _segment_or_visit(self) -> "ProgressIn":
        if (self.status == "LIVE") != (self.seq is None):
            raise ValueError("LIVE is for the visit; a segment step needs its seq")
        return self


def progress_handler(engine: AsyncEngine) -> Handler:
    async def handle(event: Event) -> None:
        try:
            p = ProgressIn.model_validate(event.payload)
        except ValidationError as e:
            log.warning("visit progress refused: %s errors", e.error_count())
            return
        async with tenant_session(event.tenant_id, engine) as session:
            if p.seq is None:
                visit = await service.simulated_start(session, p.visit)
            else:
                visit = await service.simulated_progress(session, p.visit, p.seq, p.status)
            await session.commit()
        if visit is None:  # a miscoded scenario or a replay shows in the log
            log.warning("visit progress %s %s %s did not apply", p.visit, p.seq, p.status)

    return handle
