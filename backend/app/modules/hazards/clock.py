"""The hazard clock and the demo clock (plan-pilot-hz §5, G-9).

The hazard clock is real time, plus the hours a running demo scenario has moved it on
with DEMO_CLOCK scene events ({"advance_h": 24}). It is used for two things only: the
landfall countdown and when an armed playbook run is due. Check-in escalation, flights
and audit timestamps stay on real time.

DEMO_CLOCK events are accepted only while a demo scenario is running in the tenant,
as CHECKIN_CLOCK: a stray or forged stream event must not start a real armed run early.
Each accepted event is one SCENARIO.CLOCK_ADVANCE audit row, which is also the record
the clock sums (from the running demo's start, so a reset scenario starts at zero). A
redelivered event finds its row and changes nothing.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.events import Event
from app.modules.audit.models import AuditLog
from app.modules.notifications.service import demo_running, demo_started_at
from app.modules.tenancy.service import Actor

SCENARIO_CLOCK = Actor(type="SYSTEM", id="scenario.clock")
ADVANCE = "SCENARIO.CLOCK_ADVANCE"
ADVANCE_MAX_H = 72


@dataclass(frozen=True)
class HazardTime:
    now: datetime  # real time plus the demo's advance
    demo_advance_h: int


async def demo_since(session: AsyncSession) -> datetime | None:
    """When the running demo started (None if none is running)."""
    return await demo_started_at(session)


async def hazard_now(session: AsyncSession, now: datetime | None = None) -> HazardTime:
    real = now or datetime.now(UTC)
    since = await demo_started_at(session)
    if since is None:
        return HazardTime(real, 0)
    details = await session.scalars(
        select(AuditLog.details).where(AuditLog.action == ADVANCE, AuditLog.occurred_at >= since)
    )
    hours = sum(int(d.get("advance_h", 0)) for d in details)
    return HazardTime(real + timedelta(hours=hours), hours)


async def advance(session: AsyncSession, event: Event) -> int | None:
    """Apply one DEMO_CLOCK event in the caller's transaction: the hours added, or None
    when it is refused (no demo running, bad value) or was applied already. Audited."""
    hours = event.payload.get("advance_h")
    if not await demo_running(session) or not (
        isinstance(hours, int) and not isinstance(hours, bool) and 0 < hours <= ADVANCE_MAX_H
    ):
        await audit.write(
            session,
            actor_type=SCENARIO_CLOCK.type,
            actor_id=SCENARIO_CLOCK.id,
            action="SCENARIO.CLOCK_REJECT",
            entity_type="event",
            entity_id=str(event.id),
            details={"reason": "clock event outside a running demo or invalid"},
        )
        return None
    # One clock event at a time per tenant, so two overlapping deliveries of the same
    # event cannot both pass the check below (review of Prompt 55, M2).
    await session.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtext('nexira:hazard-clock:' || current_tenant_id()))"
        )
    )
    seen = await session.scalar(
        select(AuditLog.id)
        .where(AuditLog.action == ADVANCE, AuditLog.entity_id == str(event.id))
        .limit(1)
    )
    if seen is not None:
        return None
    await audit.write(
        session,
        actor_type=SCENARIO_CLOCK.type,
        actor_id=SCENARIO_CLOCK.id,
        action=ADVANCE,
        entity_type="event",
        entity_id=str(event.id),
        details={"advance_h": hours},
    )
    return hours


def demo_clock_event(tenant_id: uuid.UUID, advance_h: int) -> Event:
    """To browsers, so countdowns refresh at once."""
    return Event(
        type="HAZARD_CLOCK_ADVANCED",
        tenant_id=tenant_id,
        payload={"advance_h": advance_h},
        source="scenario.clock",
    )
