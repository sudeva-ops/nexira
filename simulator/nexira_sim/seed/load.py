"""Loads the seed world through the backend service layer (Prompt 4).

Everything except the tenant row runs as nexira_api in one tenant-scoped
transaction, so a failed seed leaves nothing half-loaded. Every step is
idempotent: seeding twice changes nothing and writes no new audit rows.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from app.core.db import tenant_session
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.intel.service import SourceIn, ensure_sources
from app.modules.notifications.templates import TemplateIn, ensure_templates
from app.modules.people import location
from app.modules.people.service import add_observations, ensure_mission, load_persons, load_sites
from app.modules.playbooks.service import StepIn, ensure_playbook, retire_older_versions
from app.modules.scenarios.service import ensure_scenario
from app.modules.tenancy.service import ensure_reference_counter
from app.modules.travel.service import (
    AirportIn,
    CountryRiskIn,
    SegmentSeed,
    ensure_airports,
    ensure_country_risks,
    ensure_scenario_flight,
    ensure_trip,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nexira_sim.scenarios import fra_national_protests as fra
from nexira_sim.scenarios import mnl_tropical_storm as mnl
from nexira_sim.scenarios import nbo_air_diversion as air
from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import data, world
from nexira_sim.seed.identities import bootstrap_tenant, demo_user_id, seed_identities
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

        report["country_risks"] = await ensure_country_risks(
            session,
            [
                CountryRiskIn(
                    cc,
                    *data.COUNTRY_RISK.get(cc, data.DEFAULT_COUNTRY_RISK),
                    data.COUNTRY_RISK_SOURCE,
                )
                for cc in sorted(
                    {m.country_code for m in w.missions} | {t[6] for t in data.AIR_TRIPS}
                )
            ],
        )
        missions_by_code = {m.code: m for m in w.missions}
        report["extra_trips"] = 0
        for ref, purpose, home, count, dest, cc, offset, days, status, risk in data.EXTRA_TRIPS:
            home_id = missions_by_code[home].id
            travellers = [
                p.id for p in w.persons if p.mission_id == home_id and p.person_type == "DIPLOMAT"
            ][:count]
            report["extra_trips"] += await ensure_trip(
                session,
                trip_id=seed_id(tenant_id, "trip", ref),
                reference=ref,
                purpose=purpose,
                origin=missions_by_code[home].city,
                destination=dest,
                destination_country=cc,
                starts_on=scenario_date + timedelta(days=offset),
                ends_on=scenario_date + timedelta(days=offset + days),
                traveller_ids=travellers,
                risk_level=risk,
                approval_status=status,
                mission_id=mission_ids[data.TRIP_SCOPE[ref]] if ref in data.TRIP_SCOPE else None,
                requested_by=await demo_user_id(session, data.TRIP_REQUESTER[ref])
                if ref in data.TRIP_REQUESTER
                else None,
            )

        ref, purpose, home, _count, dest, cc, _hotel, _place = data.MANILA_TRIP
        report["extra_trips"] += await ensure_trip(
            session,
            trip_id=seed_id(tenant_id, "trip", ref),
            reference=ref,
            purpose=purpose,
            origin=missions_by_code[home].city,
            destination=dest,
            destination_country=cc,
            # Active on the scenario date, like TRP-8812 (D-22, plan G-11).
            starts_on=scenario_date - timedelta(days=1),
            ends_on=scenario_date + timedelta(days=2),
            traveller_ids=w.manila_trip_ids,
            risk_level="LOW",
            approval_status="APPROVED",
        )

        report["airports"] = await ensure_airports(session, [AirportIn(*a) for a in data.AIRPORTS])
        report["air_trips"] = await _air_trips(
            session, tenant_id, w, scenario_date, missions_by_code
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

        # PB-07 v2 (Prompt 19): step 4 uses message templates (D-31). A database seeded
        # before it keeps its v1 rows for past runs; v1 is retired so only v2 is offered.
        version = data.PB07_VERSION
        report["playbook"] = await ensure_playbook(
            session,
            playbook_id=seed_id(tenant_id, "playbook", f"PB-07:v{version}"),
            code="PB-07",
            name="Civil unrest near mission",
            category="Security",
            trigger_rules=data.PB07_TRIGGER,
            steps=[
                StepIn(seq, name, kind, config, role)
                for seq, name, kind, config, role in data.PB07_STEPS_V2
            ],
            step_ids=[
                seed_id(tenant_id, "playbook_step", f"PB-07:v{version}:{seq}")
                for seq, *_ in data.PB07_STEPS_V2
            ],
            version=version,
        )
        report["playbook_retired"] = await retire_older_versions(session, "PB-07", version)
        report["playbook_pb06"] = await ensure_playbook(
            session,
            playbook_id=seed_id(tenant_id, "playbook", "PB-06:v1"),
            code="PB-06",
            name="Severe weather near mission",
            category="Natural hazard",
            trigger_rules=data.PB06_TRIGGER,
            steps=[StepIn(*step) for step in data.PB06_STEPS],
            step_ids=[
                seed_id(tenant_id, "playbook_step", f"PB-06:v1:{seq}")
                for seq, *_ in data.PB06_STEPS
            ],
            version=1,
        )

        report["templates"] = await ensure_templates(
            session,
            [
                # English is the source text, not a translation: only AR/FR/SW are reviewed.
                TemplateIn(
                    code,
                    kind,
                    mission,
                    name,
                    texts,
                    {lang: False for lang in texts if lang != "en"},
                )
                for code, kind, mission, name, texts in data.MESSAGE_TEMPLATES
            ],
        )

        report["agents"] = await ensure_agents(
            session, [AgentIn(code, name, desc, level) for code, name, desc, level in data.AGENTS]
        )
        report["policies"] = await ensure_policies(
            session,
            [PolicyIn(action, floor, roles, undo) for action, floor, roles, undo in data.POLICIES]
            + [PolicyIn(*policy) for policy in data.TRAVEL_POLICIES],
        )

        report["counters"] = [
            await ensure_reference_counter(
                session, prefix="INC", with_year=True, last_value=data.INC_START
            ),
            await ensure_reference_counter(
                session, prefix="NTF", with_year=False, last_value=data.NTF_START
            ),
            await ensure_reference_counter(
                session, prefix="TRP", with_year=False, last_value=data.TRP_START
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
        report["scenario_air"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", air.CODE),
            code=air.CODE,
            name=air.NAME,
            description=air.DESCRIPTION,
            events=air.build_events(w, tenant_id),
        )
        report["scenario_mnl"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", mnl.CODE),
            code=mnl.CODE,
            name=mnl.NAME,
            description=mnl.DESCRIPTION,
            events=mnl.build_events(w, tenant_id),
        )
        await session.commit()
    return report


GST = timezone(timedelta(hours=4))  # the home zone (plan Q2)


async def _air_trips(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    w: world.World,
    scenario_date: date,
    missions: dict[str, world.MissionIn],
) -> int:
    """Approved trips with one tracked FLIGHT segment (D-33, plan G-1, G-3, G-4)."""
    created = 0
    now = datetime.now(UTC)
    today = now.astimezone(GST).date()
    for (
        ref,
        purpose,
        home,
        skip,
        count,
        destination,
        country,
        flight_number,
        from_airport,
        to_airport,
        departs_h,
        hours,
        restricted,
        scenario,
    ) in data.AIR_TRIPS:
        home_id = missions[home].id
        travellers = [
            p.id for p in w.persons if p.mission_id == home_id and p.person_type == "DIPLOMAT"
        ][skip : skip + count]
        anchor = datetime.combine(scenario_date, time(0), tzinfo=GST) if scenario else now
        departs = anchor + timedelta(hours=departs_h)
        first = (scenario_date if scenario else today) - timedelta(days=1)
        risk = data.COUNTRY_RISK.get(country)
        trip_id = seed_id(tenant_id, "trip", ref)
        created += await ensure_trip(
            session,
            trip_id=trip_id,
            reference=ref,
            purpose=purpose,
            origin=missions[home].city,
            destination=destination,
            destination_country=country,
            starts_on=first,
            ends_on=first + timedelta(days=4),
            traveller_ids=travellers,
            risk_level=CountryRiskIn(country, *risk, "").level if risk else "LOW",
            approval_status="APPROVED",
            restricted=restricted,
            segments=[
                SegmentSeed(
                    kind="FLIGHT",
                    # A restricted trip's segment names nothing (D-33; plan G-7 masks the
                    # rest in the trip API).
                    title="Flight" if restricted else flight_number,
                    place_label=None if restricted else f"{from_airport} → {to_airport}",
                    starts_at=departs,
                    ends_at=departs + timedelta(hours=hours),
                    flight_number=flight_number,
                    from_airport=from_airport,
                    to_airport=to_airport,
                )
            ],
        )
        if scenario:
            await ensure_scenario_flight(session, trip_id)
    return created
