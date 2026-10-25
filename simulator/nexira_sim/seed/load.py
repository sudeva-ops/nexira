"""Loads the seed world through the backend service layer (Prompt 4).

Everything except the tenant row runs as nexira_api in one tenant-scoped
transaction, so a failed seed leaves nothing half-loaded. Every step is
idempotent: seeding twice changes nothing and writes no new audit rows.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from app.core.db import tenant_session
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.intel.service import SourceIn, ensure_sources
from app.modules.people import location
from app.modules.people.service import add_observations, ensure_mission, load_persons, load_sites
from app.modules.playbooks.service import StepIn, ensure_playbook
from app.modules.scenarios.service import ensure_scenario
from app.modules.tenancy.service import ensure_reference_counter
from app.modules.travel.service import ensure_trip
from sqlalchemy.ext.asyncio import AsyncEngine

from nexira_sim.scenarios import fra_national_protests as fra
from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import data, world
from nexira_sim.seed.identities import bootstrap_tenant, seed_identities
from nexira_sim.seed.ids import seed_id


async def seed_all(
    engine: AsyncEngine,
    *,
    owner_dsn: str,
    issuer: str,
    scenario_date: date,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    tenant_id = await bootstrap_tenant(owner_dsn, issuer, tenant_id)
    w = world.build(scenario_date, tenant_id)
    report: dict[str, Any] = {"tenant_id": str(tenant_id), "scenario_date": str(scenario_date)}

    async with tenant_session(tenant_id, engine) as session:
        mission_ids = {
            m.code: await ensure_mission(
                session,
                code=m.code,
                city=m.city,
                country_code=m.country_code,
                lat=m.lat,
                lon=m.lon,
                risk_level=m.risk_level,
                mission_id=m.id,
            )
            for m in w.missions
        }
        report["identities"] = await seed_identities(session, mission_ids)
        report["sites"] = await load_sites(session, w.sites)
        report["persons"] = await load_persons(session, w.persons)
        report["observations"] = await add_observations(session, w.observations)
        report["locations_changed"] = await location.recompute(session, w.as_of)

        report["trip"] = await ensure_trip(
            session,
            trip_id=seed_id(tenant_id, "trip", data.TRIP_REFERENCE),
            reference=data.TRIP_REFERENCE,
            purpose=data.TRIP_PURPOSE,
            origin="HQ",
            destination="Nairobi",
            destination_country="KE",
            # Active on the scenario date (D-22, plan G-11).
            starts_on=scenario_date - timedelta(days=1),
            ends_on=scenario_date + timedelta(days=3),
            traveller_ids=w.delegate_ids,
            risk_level="MODERATE",
            approval_status="APPROVED",
        )

        report["sources"] = await ensure_sources(
            session,
            [
                SourceIn(
                    code=code,
                    name=name,
                    reliability=reliability,
                    severity_map=severity,
                    category_map=category,
                    is_enabled=enabled,
                    takes_part_in_fusion=fusion,
                )
                for code, name, reliability, severity, category, enabled, fusion in data.SOURCES
            ],
        )

        report["playbook"] = await ensure_playbook(
            session,
            playbook_id=seed_id(tenant_id, "playbook", "PB-07"),
            code="PB-07",
            name="Civil unrest near mission",
            category="Security",
            trigger_rules=data.PB07_TRIGGER,
            steps=[
                StepIn(seq, name, kind, config, role)
                for seq, name, kind, config, role in data.PB07_STEPS
            ],
            step_ids=[
                seed_id(tenant_id, "playbook_step", f"PB-07:{seq}") for seq, *_ in data.PB07_STEPS
            ],
        )

        report["agents"] = await ensure_agents(
            session, [AgentIn(code, name, desc, level) for code, name, desc, level in data.AGENTS]
        )
        report["policies"] = await ensure_policies(
            session,
            [PolicyIn(action, floor, roles, undo) for action, floor, roles, undo in data.POLICIES],
        )

        report["counters"] = [
            await ensure_reference_counter(
                session, prefix="INC", with_year=True, last_value=data.INC_START
            ),
            await ensure_reference_counter(
                session, prefix="NTF", with_year=False, last_value=data.NTF_START
            ),
        ]
        report["scenario"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", nbo.CODE),
            code=nbo.CODE,
            name=nbo.NAME,
            description=nbo.DESCRIPTION,
            events=nbo.build_events(w, tenant_id),
        )
        report["scenario_fra"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", fra.CODE),
            code=fra.CODE,
            name=fra.NAME,
            description=fra.DESCRIPTION,
            events=fra.build_events(w, tenant_id),
        )
        await session.commit()
    return report
