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
from app.modules.documents.service import ensure_documents, start_renewals
from app.modules.evacuations import service as evacuations
from app.modules.fleet import service as fleet
from app.modules.hazards.service import ensure_climate
from app.modules.health_intel import service as health
from app.modules.intel.service import SourceIn, ensure_sources
from app.modules.notifications.templates import TemplateIn, ensure_templates
from app.modules.partners.models import Partner
from app.modules.partners.service import PartnerIn, ensure_partners
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
from app.modules.twin import service as twin
from app.modules.vip import service as vip
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nexira_sim.scenarios import add_visit, nbo_fleet, nbo_site
from nexira_sim.scenarios import dac_cyclone as dac
from nexira_sim.scenarios import fra_national_protests as fra
from nexira_sim.scenarios import mnl_tropical_storm as mnl
from nexira_sim.scenarios import nbo_air_diversion as air
from nexira_sim.scenarios import nbo_cholera as cholera
from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.scenarios import nbo_evacuation as evacuation
from nexira_sim.seed import data, world
from nexira_sim.seed import documents as seed_documents
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
            travellers = world.trip_travellers(w, missions_by_code[home].id, count)
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

        report["playbook_pb01"] = await ensure_playbook(
            session,
            playbook_id=seed_id(tenant_id, "playbook", "PB-01:v1"),
            code="PB-01",
            name="Earthquake near mission",
            category="Natural hazard",
            trigger_rules=data.PB01_TRIGGER,
            steps=[StepIn(*step) for step in data.PB01_STEPS],
            step_ids=[
                seed_id(tenant_id, "playbook_step", f"PB-01:v1:{seq}")
                for seq, *_ in data.PB01_STEPS
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
                for code, kind, mission, name, texts in [
                    *data.MESSAGE_TEMPLATES,
                    *data.HEALTH_TEMPLATES,
                    *data.EVACUATION_TEMPLATES,
                ]
            ],
        )

        report["partners"] = await ensure_partners(session, [PartnerIn(*p) for p in data.PARTNERS])

        report["agents"] = await ensure_agents(
            session, [AgentIn(code, name, desc, level) for code, name, desc, level in data.AGENTS]
        )
        report["policies"] = await ensure_policies(
            session,
            [PolicyIn(action, floor, roles, undo) for action, floor, roles, undo in data.POLICIES]
            + [PolicyIn(*policy) for policy in data.TRAVEL_POLICIES]
            + [PolicyIn(*policy) for policy in data.DOCUMENT_POLICIES]
            + [PolicyIn(*policy) for policy in data.HAZARD_POLICIES]
            + [PolicyIn(*policy) for policy in data.HEALTH_POLICIES],
        )

        # Document Expiry (D-37, plan §8): new documents only (G-8); the renewals already
        # under way are moved through the service, for new documents only.
        docs, in_progress = seed_documents.build(w, tenant_id)
        created = set(await ensure_documents(session, docs))
        report["documents"] = len(created)
        report["renewals_started"] = await start_renewals(
            session, [d for d in in_progress if d in created]
        )

        # HZ-08 (D-38): the illustrative climate scores, through the service (PC-25).
        report["climate"] = await ensure_climate(
            session,
            [
                {
                    "mission_id": mission_ids[code],
                    "hazards": hazards,
                    "score_today": today,
                    "score_2050": in_2050,
                    "scenario": data.CLIMATE_SCENARIO,
                }
                for code, (hazards, today, in_2050) in data.CLIMATE.items()
            ],
        )

        # Health Intelligence (D-39, plan-pilot-hl §2-5): the six advisories (no events, so
        # no agent reacts), entry requirements, sample facilities and readiness counts.
        report["health_advisories"] = await health.ensure_advisories(
            session, _advisories(scenario_date)
        )
        kestrel = await session.scalar(select(Partner.id).where(Partner.code == "KES"))
        report["health"] = await health.ensure_reference_data(
            session,
            facilities=_facilities(w, mission_ids, kestrel),
            requirements=[(cc, m, r) for cc, (m, r) in data.HEALTH_REQUIREMENTS.items()],
            readiness=[
                health.ReadinessIn(
                    mission_id=mission_ids[m.code],
                    staff=m.staff,
                    blood_type_on_file=m.staff,
                    insurance_active=m.staff,
                    trauma_kits=6 if m.code == "NBO" else max(2, m.staff // 4),
                    vaccines_offered=data.VACCINES_OFFERED.get(m.code, {}),
                    as_of=scenario_date - timedelta(days=data.READINESS_AS_OF_DAYS),
                )
                for m in w.missions
            ],
        )

        # Evacuation Management (D-40, plan-pilot-ev §2): a plan for every mission.
        partner_ids = dict((await session.execute(select(Partner.code, Partner.id))).all())
        report["evacuation_plans"] = await evacuations.ensure_plans(
            session, _plans(w, mission_ids, partner_ids)
        )

        # Fleet & Assets (D-41, plan-pilot-flt §2): every mission's vehicles and equipment.
        report["fleet_assets"] = await fleet.ensure_assets(
            session, _fleet(w, mission_ids), scenario_date
        )

        # VIP & Delegation Protection (D-42, plan-pilot-vip §2): the restricted TRP-8834 and
        # VV-<year>-031, after the identities (G-7).
        ref, purpose, home, skip, count, origin, cc = data.VIP_TRIP
        first = scenario_date + timedelta(days=data.VIP_FIRST_DAY)
        trip_id = seed_id(tenant_id, "trip", ref)
        report["vip_trip"] = await ensure_trip(
            session,
            trip_id=trip_id,
            reference=ref,
            purpose=purpose,
            origin=origin,
            destination=missions_by_code[data.VIP_MISSION].city,
            destination_country=cc,
            starts_on=first,
            ends_on=first + timedelta(days=data.VIP_DAYS - 1),
            traveller_ids=[
                p.id
                for p in w.persons
                if p.mission_id == missions_by_code[home].id and p.person_type == "DIPLOMAT"
            ][skip : skip + count],
            risk_level="MODERATE",
            approval_status="APPROVED",
            restricted=True,
        )
        # Site Twin (D-43, plan-pilot-twn §2-§6): the Nairobi embassy's plan, after the identities
        # (G-7) and Fleet (the generator and satellite terminal are read from there).
        report["twin_plan"] = await twin.ensure_plan(
            session,
            _twin(w, tenant_id, await demo_user_id(session, "security.officer")),
        )
        report["vip_visits"] = await vip.ensure_visits(
            session,
            [
                _visit(
                    w,
                    mission_ids[data.VIP_MISSION],
                    trip_id,
                    await demo_user_id(session, "security.officer"),
                )
            ],
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
            await ensure_reference_counter(
                session, prefix="REQ", with_year=False, last_value=data.REQ_START
            ),
            await ensure_reference_counter(
                session, prefix="EVN", with_year=False, last_value=data.EVN_START
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
        report["scenario_cholera"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", cholera.CODE),
            code=cholera.CODE,
            name=cholera.NAME,
            description=cholera.DESCRIPTION,
            events=cholera.build_events(w, tenant_id),
        )
        report["scenario_evacuation"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", evacuation.CODE),
            code=evacuation.CODE,
            name=evacuation.NAME,
            description=evacuation.DESCRIPTION,
            events=evacuation.build_events(w, tenant_id),
        )
        report["scenario_dac"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", dac.CODE),
            code=dac.CODE,
            name=dac.NAME,
            description=dac.DESCRIPTION,
            events=dac.build_events(w, tenant_id),
        )
        report["scenario_visit"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", add_visit.CODE),
            code=add_visit.CODE,
            name=add_visit.NAME,
            description=add_visit.DESCRIPTION,
            events=add_visit.build_events(w, tenant_id),
        )
        report["scenario_site"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", nbo_site.CODE),
            code=nbo_site.CODE,
            name=nbo_site.NAME,
            description=nbo_site.DESCRIPTION,
            events=nbo_site.build_events(w, tenant_id),
        )
        report["scenario_fleet"] = await ensure_scenario(
            session,
            scenario_id=seed_id(tenant_id, "scenario", nbo_fleet.CODE),
            code=nbo_fleet.CODE,
            name=nbo_fleet.NAME,
            description=nbo_fleet.DESCRIPTION,
            events=nbo_fleet.build_events(w, tenant_id),
        )
        await session.commit()
    return report


GST = timezone(timedelta(hours=4))  # the home zone (plan Q2)
EAT = timezone(timedelta(hours=3))  # Addis Ababa (plan-pilot-vip §2)


def _twin(w: world.World, tenant_id: uuid.UUID, officer: uuid.UUID) -> twin.PlanIn:
    """The Nairobi embassy as the design (plan-pilot-twn §2-§6): 25 on site, 43 sensors."""
    staff = {str(p.id) for p in w.persons}
    return twin.PlanIn(
        site_id=seed_id(tenant_id, "site", data.TWIN_SITE),
        zones=tuple(twin.ZoneIn(*z) for z in data.TWIN_ZONES),
        routes=tuple(twin.RouteIn(*r) for r in data.TWIN_ROUTES),
        sensors=tuple(twin.SensorIn(*s) for s in data.TWIN_SENSORS),
        items=tuple((label, officer if done else None) for label, done in data.TWIN_READINESS),
        occupants=tuple(
            twin.OccupantIn(zone, person_id=uuid.UUID(o))
            if o in staff
            else twin.OccupantIn(zone, label=o)
            for o, zone, _ in nbo_site.occupants(w)
        ),
    )


def _visit(
    w: world.World, mission_id: uuid.UUID, trip_id: uuid.UUID, officer: uuid.UUID
) -> vip.VisitIn:
    """VV-<year>-031 as the design (plan-pilot-vip §2): six segments, the detail by labels and
    counts, and the checklist with three items done by the seeded Security Officer (G-7)."""
    first = w.scenario_date + timedelta(days=data.VIP_FIRST_DAY)
    segments = []
    for kind, title, venue, (lat, lon), day, hhmm, minutes, attendees in data.VIP_SEGMENTS:
        hour, minute = (int(x) for x in hhmm.split(":"))
        starts = datetime.combine(first + timedelta(days=day), time(hour, minute), EAT)
        segments.append(
            vip.SegmentIn(
                kind=kind,
                title=title,
                venue_name=venue,
                lat=lat,
                lon=lon,
                starts_at=starts,
                ends_at=starts + timedelta(minutes=minutes) if minutes else None,
                attendees=attendees,
            )
        )
    return vip.VisitIn(
        reference=add_visit.reference(w),
        title=data.VIP_TITLE,
        mission_id=mission_id,
        principal_role=data.VIP_PRINCIPAL,
        starts_on=first,
        ends_on=first + timedelta(days=data.VIP_DAYS - 1),
        trip_id=trip_id,
        detail=data.VIP_DETAIL,
        segments=tuple(segments),
        checklist=tuple(
            vip.ItemIn(label, first - timedelta(days=before), officer if done else None)
            for label, before, done in data.VIP_CHECKLIST
        ),
    )


def _advisories(scenario_date: date) -> list[health.AdvisoryIn]:
    """Published some days before 06:00 UTC on the scenario date, never in the future."""
    base = min(datetime.combine(scenario_date, time(6), UTC), datetime.now(UTC))
    return [
        health.AdvisoryIn.model_validate(
            {
                "external_id": feed_id,
                "topic": topic,
                "topic_code": code,
                "countries": countries,
                "region_label": region,
                "level": level,  # validated: LOW, MODERATE, HIGH or CRITICAL
                "guidance": guidance,
                "source": source,
                "published_at": base - timedelta(days=days),
            }
        )
        for feed_id, topic, code, countries, region, level, guidance, source, days in (
            data.HEALTH_ADVISORIES
        )
    ]


def _plans(
    w: world.World, mission_ids: dict[str, uuid.UUID], partners: dict[str, uuid.UUID]
) -> list[evacuations.PlanIn]:
    """EVP-NBO as the design; one by pattern for every other mission (plan §2)."""
    covers = {code: set(cov) for code, _n, _s, cov, *_ in data.PARTNERS}

    def partner(code: str | None, country: str) -> str | None:
        if code is None or code not in partners or country not in covers[code]:
            return None
        return str(partners[code])

    out: list[evacuations.PlanIn] = []
    for m in w.missions:
        options: list[data.EvacuationOption]
        if m.code == "NBO":
            muster, route, destination = (
                data.NAIROBI_MUSTER,
                data.NAIROBI_ROUTE,
                data.NAIROBI_DESTINATION,
            )
            lat, lon = data.EMBASSY
            options = data.NAIROBI_OPTIONS
        else:
            destination = data.SAFE_HAVEN[m.country_code]
            muster, route, lat, lon = f"{m.city} chancery courtyard", "Primary route", m.lat, m.lon
            road = "SEN" if m.country_code in data.EMEA else "MER"
            seats = max(40, 4 * m.staff)
            options = [
                ("PRIMARY", "CHARTER", f"Charter · {m.city} → {destination}", seats, "ATL"),
                ("BACKUP", "COMMERCIAL", f"Commercial · {m.city} (seats held: 20)", 20, None),
                ("CONTINGENCY", "ROAD", f"Road · overland from {m.city}", None, road),
            ]
        out.append(
            evacuations.PlanIn(
                mission_id=mission_ids[m.code],
                mission_code=m.code,
                muster_name=muster,
                lat=lat,
                lon=lon,
                route_label=route,
                destination=destination,
                options=[
                    {
                        "role": role,
                        "kind": kind,
                        "label": label,
                        "seats": seats,
                        "partner_id": partner(code, m.country_code),
                    }
                    for role, kind, label, seats, code in options
                ],
            )
        )
    return out


def _facilities(
    w: world.World, mission_ids: dict[str, uuid.UUID], kestrel: uuid.UUID | None
) -> list[health.FacilityIn]:
    """Nairobi's four as the design; three by pattern for every other mission (§48 Q5)."""
    out: list[health.FacilityIn] = []
    for m in w.missions:
        rows = (
            data.NAIROBI_FACILITIES
            if m.code == "NBO"
            else [
                (name.format(city=m.city), m.lat + dlat, m.lon + dlon, caps, trauma, open_, vet)
                for name, dlat, dlon, caps, trauma, open_, vet in data.FACILITY_PATTERN
            ]
        )
        out.extend(
            health.FacilityIn(
                mission_id=mission_ids[m.code],
                name=name,
                lat=lat,
                lon=lon,
                capabilities=caps,
                open_24_7=open_,
                trauma_level=trauma,
                vetted_by=kestrel if vet else None,
            )
            for name, lat, lon, caps, trauma, open_, vet in rows
        )
    return out


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


def _fleet(w: world.World, mission_ids: dict[str, uuid.UUID]) -> list[fleet.AssetIn]:
    """Nairobi as the design; one vehicle at every other mission and a second at the higher-
    risk ones; a generator and a satellite terminal everywhere (plan §2, G-6)."""
    driver = next(p.id for p in w.persons if p.full_name == data.NAIROBI_DRIVER)
    places = {"EMBASSY": data.EMBASSY, "RESIDENCE": data.RESIDENCE, "PETER": data.PETER}

    def items(code: str, default: list[tuple[str, int]]) -> tuple[fleet.ItemIn, ...]:
        return tuple(fleet.ItemIn(t, d) for t, d in data.FLEET_ITEMS.get(code, default))

    out: list[fleet.AssetIn] = []
    following = data.FLEET_NEXT_CODE
    for i, m in enumerate(w.missions):
        mission_id = mission_ids[m.code]
        garage = data.EMBASSY if m.code == "NBO" else (m.lat, m.lon)
        if m.code == "NBO":
            for code, (
                label,
                seats,
            ), armoured, place, where, fuel, status, reason, todo in data.NAIROBI_FLEET:
                lat, lon = places[place]
                out.append(
                    fleet.AssetIn(
                        mission_id,
                        code,
                        "VEHICLE",
                        label,
                        lat,
                        lon,
                        where,
                        fuel,
                        armoured=armoured,
                        seats=seats,
                        driver_id=driver if place == "PETER" else None,
                        status=status,
                        status_reason=reason,
                        items=items(code, todo),
                    )
                )
        else:
            count = 2 if m.code in data.FLEET_HIGH_RISK else 1
            if m.code in data.FLEET_CODES:
                numbers = [data.FLEET_CODES[m.code] + k for k in range(count)]
            else:
                numbers = list(range(following, following + count))
                following += count
            for k, n in enumerate(numbers):
                armoured = m.code in data.FLEET_HIGH_RISK or (
                    k == 0 and m.code in data.FLEET_ARMOURED_FIRST
                )
                label, seats = data.SUV if armoured else data.SEDAN
                code = f"VH-{n:02d}"
                out.append(
                    fleet.AssetIn(
                        mission_id,
                        code,
                        "VEHICLE",
                        label,
                        *garage,
                        "Embassy garage",
                        55 + (i * 7 + k * 13) % 41,
                        armoured=armoured,
                        seats=seats,
                        items=items(code, [("Routine service", 30 + (i * 11 + k * 17) % 61)]),
                    )
                )
        for prefix, label in (("GEN", data.GENERATOR), ("SAT", data.SATELLITE)):
            code = f"{prefix}-{m.code}"
            fuel = 100 if prefix == "SAT" else data.GENERATOR_FUEL.get(m.code, 60 + (i * 9) % 36)
            out.append(
                fleet.AssetIn(
                    mission_id,
                    code,
                    "EQUIPMENT",
                    label,
                    *garage,
                    "Embassy",
                    fuel,
                    items=items(code, []),
                )
            )
    return out
