"""Shared setup for scenario tests: a fully seeded tenant with the Nairobi incident
(scenes 1-2 through the worker handlers), and the seeded demo users."""

import uuid
from datetime import date

from app.core.db import tenant_session
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.intel.models import Incident
from app.modules.tenancy.models import AppUser
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import world
from nexira_sim.seed.load import seed_all

DAY = date(2026, 10, 20)


async def seeded_incident(db: DbUrls, engine: AsyncEngine, tenant_id: uuid.UUID) -> uuid.UUID:
    await seed_all(
        engine,
        owner_dsn=db.owner,
        issuer=f"https://kc.test/realms/pb07-{tenant_id}",
        scenario_date=DAY,
        tenant_id=tenant_id,
    )
    incidents, out = ListPublisher(), ListPublisher()
    on_signal = raw_signal_handler(engine, incidents)
    on_incident = exposure_handler(engine, out)
    for e in nbo.build_events(world.build(DAY, tenant_id), tenant_id):
        if e.event_type == "RAW_SIGNAL" and e.payload["place_label"] != "Paris":
            await on_signal(Event("RAW_SIGNAL", tenant_id, dict(e.payload), "test"))
    for published in incidents.events:
        if published.type.startswith("INCIDENT_"):
            await on_incident(published)
    async with tenant_session(tenant_id, engine) as session:
        incident = await session.scalar(select(Incident))
        assert incident is not None
        assert incident.severity == "CRITICAL"
        incident_id: uuid.UUID = incident.id
        return incident_id


async def user(session: AsyncSession, username: str) -> CurrentUser:
    row = await session.scalar(
        select(AppUser).where(AppUser.email == f"{username}@demo.nexira.invalid")
    )
    assert row is not None, username
    return CurrentUser(row.id, row.tenant_id, row.external_id, row.email, row.display_name)
