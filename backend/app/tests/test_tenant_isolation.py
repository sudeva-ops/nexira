"""Tenant isolation for EVERY tenant table (D-01, D-02, D-03, Prompt 2 b/c).

The table list comes from the database catalogue (every public table with a
tenant_id column), not from a hand-picked list. ROWS must provide one insert
per catalogue table; test_every_tenant_table_has_a_row_factory fails if a table
is added to the schema without one.
"""

import asyncio
import uuid
from dataclasses import dataclass

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant


@dataclass(frozen=True)
class Ids:
    t: uuid.UUID
    user: uuid.UUID
    role: uuid.UUID
    mission: uuid.UUID
    person: uuid.UUID
    trip: uuid.UUID
    source: uuid.UUID
    signal: int
    incident: uuid.UUID
    playbook: uuid.UUID
    step: uuid.UUID
    run: uuid.UUID
    campaign: uuid.UUID
    agent: uuid.UUID
    proposal: uuid.UUID
    scenario: uuid.UUID
    flight_trip: uuid.UUID
    segment: uuid.UUID
    flight: uuid.UUID
    partner: uuid.UUID
    activator: uuid.UUID
    plan: uuid.UUID
    evacuation: uuid.UUID
    asset: uuid.UUID
    visit: uuid.UUID
    vip_segment: uuid.UUID
    site: uuid.UUID
    zone: uuid.UUID
    supplier: uuid.UUID
    route: uuid.UUID


PT = "'SRID=4326;POINT(36.8245 -1.2838)'"

# One INSERT per tenant table, in dependency order. {t} is the tenant id.
ROWS: dict[str, str] = {
    "app_user": "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
    "VALUES ('{user}', '{t}', 'sub-{user}', '{user}@x', 'U')",
    "role": "INSERT INTO role (id, tenant_id, code, name) VALUES ('{role}', '{t}', 'VIEWER', 'V')",
    "mission": "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
    "VALUES ('{mission}', '{t}', 'NBO', 'Nairobi', 'KE', " + PT + ")",
    "user_role": "INSERT INTO user_role (tenant_id, user_id, role_id, mission_id) "
    "VALUES ('{t}', '{user}', '{role}', '{mission}')",
    "site": "INSERT INTO site (id, tenant_id, mission_id, site_type, name, location) "
    "VALUES ('{site}', '{t}', '{mission}', 'EMBASSY', 'Embassy', " + PT + ")",
    "person": "INSERT INTO person (id, tenant_id, mission_id, person_type, full_name) "
    "VALUES ('{person}', '{t}', '{mission}', 'DIPLOMAT', 'Test Person')",
    "location_observation": "INSERT INTO location_observation (tenant_id, person_id, source, "
    "location, observed_at) VALUES ('{t}', '{person}', 'MANUAL', " + PT + ", now())",
    "person_location_current": "INSERT INTO person_location_current (person_id, tenant_id, "
    "location, confidence, primary_source) VALUES ('{person}', '{t}', " + PT + ", 90, 'MANUAL')",
    "trip": "INSERT INTO trip (id, tenant_id, reference, origin, destination, starts_on, ends_on) "
    "VALUES ('{trip}', '{t}', 'TRP-1', 'HQ', 'Nairobi', current_date, current_date)",
    "trip_traveller": "INSERT INTO trip_traveller (tenant_id, trip_id, person_id) "
    "VALUES ('{t}', '{trip}', '{person}')",
    "intel_source": "INSERT INTO intel_source (id, tenant_id, code, name) "
    "VALUES ('{source}', '{t}', 'SRC', 'Source')",
    "raw_signal": "INSERT INTO raw_signal (id, tenant_id, source_id, external_id, title, "
    "occurred_at) VALUES ({signal}, '{t}', '{source}', 'ext-1', 'Signal', now())",
    "incident": "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
    "signal_severity, location) VALUES ('{incident}', '{t}', 'INC-T', 'I', 'CIVIL_UNREST', "
    "'HIGH', 'HIGH', " + PT + ")",
    "incident_signal": "INSERT INTO incident_signal (tenant_id, incident_id, signal_id) "
    "VALUES ('{t}', '{incident}', {signal})",
    "incident_exposure": "INSERT INTO incident_exposure (tenant_id, incident_id, subject_type, "
    "subject_id) VALUES ('{t}', '{incident}', 'PERSON', '{person}')",
    "incident_event": "INSERT INTO incident_event (tenant_id, incident_id, event_type, summary, "
    "actor_type) VALUES ('{t}', '{incident}', 'NOTE', 'n', 'SYSTEM')",
    "playbook": "INSERT INTO playbook (id, tenant_id, code, name, category) "
    "VALUES ('{playbook}', '{t}', 'PB-T', 'P', 'Security')",
    "playbook_step": "INSERT INTO playbook_step (id, tenant_id, playbook_id, seq, name, "
    "action_type) VALUES ('{step}', '{t}', '{playbook}', 1, 'S', 'TASK')",
    "agent": "INSERT INTO agent (id, tenant_id, code, name) VALUES ('{agent}', '{t}', 'A', 'A')",
    "action_policy": "INSERT INTO action_policy (tenant_id, action_type, min_autonomy_level, "
    "approver_roles) VALUES ('{t}', 'START_PLAYBOOK', 2, '{{DUTY_OFFICER}}')",
    "agent_proposal": "INSERT INTO agent_proposal (id, tenant_id, agent_id, proposal_key, "
    "action_type, title, proposed_action) VALUES ('{proposal}', '{t}', '{agent}', 'k', "
    "'START_PLAYBOOK', 't', 'p')",
    # Step 1 is created by the trigger; this adds an undecided step 2.
    "proposal_approval": "INSERT INTO proposal_approval (tenant_id, proposal_id, step_no, "
    "required_role) VALUES ('{t}', '{proposal}', 2, 'HQ_CRISIS_DIRECTOR')",
    "playbook_run": "INSERT INTO playbook_run (id, tenant_id, playbook_id, incident_id) "
    "VALUES ('{run}', '{t}', '{playbook}', '{incident}')",
    "playbook_run_step": "INSERT INTO playbook_run_step (tenant_id, run_id, step_id) "
    "VALUES ('{t}', '{run}', '{step}')",
    "notification_campaign": "INSERT INTO notification_campaign (id, tenant_id, reference, "
    "campaign_type, message, channels, created_by_type) VALUES ('{campaign}', '{t}', 'NTF-T', "
    "'CHECKIN', 'm', '{{APP}}', 'USER')",
    "trip_segment": "INSERT INTO trip_segment (tenant_id, trip_id, seq, kind, title, starts_at, "
    "ends_at) VALUES ('{t}', '{trip}', 1, 'STAY', 'Hotel', now(), now())",
    "country_risk": "INSERT INTO country_risk (tenant_id, country_code, level, security, unrest, "
    "health, transport, source) VALUES ('{t}', 'KE', 'LOW', 1, 1, 1, 1, 'x')",
    "airport": "INSERT INTO airport (tenant_id, iata, name, city, country_code, location) "
    "VALUES ('{t}', 'AAA', 'A', 'A', 'KE', " + PT + ")",
    # A flight needs an approved (seeded) trip with a matching FLIGHT segment, loaded in
    # one transaction (migration 0004).
    "flight": "INSERT INTO trip (id, tenant_id, reference, origin, destination, starts_on, "
    "ends_on, approval_status) VALUES ('{flight_trip}', '{t}', 'TRP-F', 'A', 'B', current_date, "
    "current_date, 'APPROVED'); INSERT INTO trip_segment (id, tenant_id, trip_id, seq, kind, "
    "title, starts_at, ends_at, flight_number, from_airport, to_airport) VALUES ('{segment}', "
    "'{t}', '{flight_trip}', 1, 'FLIGHT', 'XW 1', now(), now(), 'XW 1', 'AAA', 'AAA'); "
    "INSERT INTO flight (id, tenant_id, trip_segment_id, flight_number, from_airport, to_airport, "
    "scheduled_dep, scheduled_arr, estimated_dep, estimated_arr) VALUES ('{flight}', '{t}', "
    "'{segment}', 'XW 1', 'AAA', 'AAA', now(), now(), now(), now())",
    "flight_event": "INSERT INTO flight_event (tenant_id, flight_id, event_type) "
    "VALUES ('{t}', '{flight}', 'DEPARTED')",
    "weather_current": "INSERT INTO weather_current (tenant_id, mission_id, observed_at, "
    "temperature_c, condition, wind_kph, gust_kph) VALUES ('{t}', '{mission}', now(), 24.5, "
    "'CLEAR', 10, 15)",
    "partner": "INSERT INTO partner (id, tenant_id, code, name, services, coverage, sla_minutes) "
    "VALUES ('{partner}', '{t}', 'KES', 'Kestrel', '{{MEDICAL}}', '{{KE}}', 15)",
    "travel_document": "INSERT INTO travel_document (tenant_id, person_id, doc_type, "
    "issuing_country, valid_until) VALUES ('{t}', '{person}', 'PASSPORT', 'KE', current_date)",
    "mission_climate_risk": "INSERT INTO mission_climate_risk (tenant_id, mission_id, hazards, "
    "score_today, score_2050, scenario) VALUES ('{t}', '{mission}', '{{FLOOD}}', 40, 60, 'x')",
    "health_advisory": "INSERT INTO health_advisory (tenant_id, reference, external_id, topic, "
    "topic_code, countries, region_label, level, guidance, source, published_at) VALUES ('{t}', "
    "'HA-0001', 'x', 'Cholera', 'CHOLERA', '{{KE}}', 'Kenya', 'MODERATE', 'g', 's', now())",
    "medical_facility": "INSERT INTO medical_facility (tenant_id, mission_id, name, location, "
    "capabilities, open_24_7) VALUES ('{t}', '{mission}', 'F', " + PT + ", '{{EMERGENCY}}', true)",
    "country_health_requirement": "INSERT INTO country_health_requirement (tenant_id, "
    "country_code, mandatory, recommended) VALUES ('{t}', 'KE', 'm', 'r')",
    "mission_health_readiness": "INSERT INTO mission_health_readiness (tenant_id, mission_id, "
    "staff, blood_type_on_file, insurance_active, trauma_kits, as_of) VALUES ('{t}', "
    "'{mission}', 10, 10, 10, 2, current_date)",
    "evacuation_plan": "INSERT INTO evacuation_plan (id, tenant_id, mission_id, reference, "
    "muster_name, muster_location, route_label, destination, options) VALUES ('{plan}', '{t}', "
    "'{mission}', 'EVP-NBO', 'Courtyard', " + PT + ", 'Route B', 'Dubai', "
    '\'[{{"role": "PRIMARY", "kind": "CHARTER", "label": "C", "seats": 72}}]\')',
    # The activator is a second user: the requester cannot activate (D-40).
    "evacuation": "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
    "VALUES ('{activator}', '{t}', 'sub-{activator}', '{activator}@x', 'A'); "
    "INSERT INTO evacuation (id, tenant_id, reference, plan_id, mission_id, requested_by, "
    "requested_role) VALUES ('{evacuation}', '{t}', 'EVN-0001', '{plan}', '{mission}', '{user}', "
    "'HEAD_OF_MISSION')",
    # The manifest is built in the transaction that activates the evacuation (PC-32).
    "evacuation_manifest": "UPDATE evacuation SET status = 'ACTIVE', activated_by = '{activator}', "
    "step = 2 WHERE id = '{evacuation}'; INSERT INTO evacuation_manifest (tenant_id, "
    "evacuation_id, person_id, category) VALUES ('{t}', '{evacuation}', '{person}', 'STAFF')",
    "vip_visit": "INSERT INTO vip_visit (id, tenant_id, reference, title, mission_id, "
    "principal_role, starts_on, ends_on) VALUES ('{visit}', '{t}', 'VV-2026-001', 'Visit', "
    "'{mission}', 'Minister', current_date, current_date)",
    "vip_segment": "INSERT INTO vip_segment (id, tenant_id, visit_id, seq, kind, title, "
    "venue_name, venue_location, starts_at) VALUES ('{vip_segment}', '{t}', '{visit}', 1, "
    "'ARRIVAL', 'Arrival', 'Airport', " + PT + ", now())",
    "vip_segment_change": "INSERT INTO vip_segment_change (tenant_id, segment_id, make_virtual, "
    "reason, proposed_by) VALUES ('{t}', '{vip_segment}', true, 'r', '{user}')",
    "vip_checklist_item": "INSERT INTO vip_checklist_item (tenant_id, visit_id, label, due_on) "
    "VALUES ('{t}', '{visit}', 'Survey', current_date)",
    "site_zone": "INSERT INTO site_zone (id, tenant_id, site_id, code, name, kind, x, y, w, h) "
    "VALUES ('{zone}', '{t}', '{site}', 'g2', 'Gate 2', 'GATE', 680, 340, 90, 45)",
    "site_route": "INSERT INTO site_route (tenant_id, site_id, code, label, path, exit_zone_id) "
    "VALUES ('{t}', '{site}', 'B', 'Route B', '[[680, 200], [725, 340]]', '{zone}')",
    "site_presence": "INSERT INTO site_presence (tenant_id, site_id, zone_id, kind, person_id) "
    "VALUES ('{t}', '{site}', '{zone}', 'STAFF', '{person}')",
    "site_sensor": "INSERT INTO site_sensor (tenant_id, site_id, zone_id, code, kind, label) "
    "VALUES ('{t}', '{site}', '{zone}', 'G2-READER', 'BADGE_READER', 'Gate 2 · badge reader')",
    "site_readiness_item": "INSERT INTO site_readiness_item (tenant_id, site_id, label) "
    "VALUES ('{t}', '{site}', 'Floor wardens assigned (3)')",
    "supplier": "INSERT INTO supplier (id, tenant_id, code, name, service, mission_id, tier, "
    "vetting_valid_until) VALUES ('{supplier}', '{t}', 'SUP-104', 'Courier', 'Pouch', '{mission}', "
    "1, current_date)",
    "logistics_route": "INSERT INTO logistics_route (id, tenant_id, mission_id, code, label, kind, "
    "supplier_id, path) VALUES ('{route}', '{t}', '{mission}', 'R-NBO-1', 'Pouch', 'POUCH', "
    "'{supplier}', 'SRID=4326;LINESTRING(36.808 -1.295, 36.9278 -1.3192)')",
    "supply_mitigation": "INSERT INTO supply_mitigation (tenant_id, supplier_id, activated_by) "
    "VALUES ('{t}', '{supplier}', '{user}')",
    "fleet_asset": "INSERT INTO fleet_asset (id, tenant_id, mission_id, code, kind, type_label, "
    "seats, location, location_label, fuel_pct) VALUES ('{asset}', '{t}', '{mission}', 'VH-01', "
    "'VEHICLE', 'Armoured SUV (B6)', 4, " + PT + ", 'Embassy garage', 82)",
    "fleet_maintenance": "INSERT INTO fleet_maintenance (tenant_id, asset_id, task, due_on) "
    "VALUES ('{t}', '{asset}', 'Brake service', current_date)",
    "partner_request": "INSERT INTO partner_request (tenant_id, reference, partner_id, service, "
    "mission_id, created_by_type, created_by) VALUES ('{t}', 'REQ-1', '{partner}', 'MEDICAL', "
    "'{mission}', 'USER', 'u')",
    "message_template": "INSERT INTO message_template (tenant_id, code, kind, name, texts) "
    "VALUES ('{t}', 'T', 'ADVISORY', 'T', '{{\"en\": \"m\"}}')",
    "notification_delivery": "INSERT INTO notification_delivery (tenant_id, campaign_id, "
    "person_id, channel) VALUES ('{t}', '{campaign}', '{person}', 'APP')",
    "checkin_response": "INSERT INTO checkin_response (tenant_id, campaign_id, person_id, status) "
    "VALUES ('{t}', '{campaign}', '{person}', 'SAFE')",
    "reference_counter": "INSERT INTO reference_counter (tenant_id, prefix, year, last_value) "
    "VALUES ('{t}', 'TST', 0, 1)",
    "audit_log": "INSERT INTO audit_log (tenant_id, actor_type, action, entity_type) "
    "VALUES ('{t}', 'SYSTEM', 'TEST', 'test')",
    "scenario": "INSERT INTO scenario (id, tenant_id, code, name) "
    "VALUES ('{scenario}', '{t}', 'SC', 'S')",
    "scenario_event": "INSERT INTO scenario_event (tenant_id, scenario_id, scene_no, offset_ms, "
    "event_type, payload) VALUES ('{t}', '{scenario}', 0, 0, 'RAW_SIGNAL', '{{}}')",
    "scenario_run": "INSERT INTO scenario_run (tenant_id, scenario_id) "
    "VALUES ('{t}', '{scenario}')",
}

# nexira_app has no UPDATE/DELETE on audit_log at all (D-20), so those fail with
# a privilege error rather than touching zero rows.
NO_UPDATE_DELETE = {  # append-only / seeded
    "audit_log",
    "checkin_response",
    "country_risk",
    "airport",
    "flight_event",
    "partner",  # seeded; no UPDATE or DELETE in the pilot (PC-21)
    "partner_request",  # UPDATE of status and ETA only, never DELETE (PC-22; review of Prompt 44)
    "travel_document",  # UPDATE of the renewal only, never DELETE (PC-23)
    "mission_climate_risk",  # seeded reference data; no UPDATE or DELETE in the pilot (PC-25)
    "health_advisory",  # UPDATE of level, guidance, status and updated_at only, no DELETE (PC-26)
    "medical_facility",  # seeded; no UPDATE or DELETE in the pilot (PC-27)
    "country_health_requirement",  # seeded; no UPDATE or DELETE in the pilot (PC-28)
    "mission_health_readiness",  # seeded counts; no UPDATE or DELETE in the pilot (PC-29)
    "evacuation_plan",  # seeded; no UPDATE or DELETE in the pilot (PC-30)
    "evacuation",  # UPDATE of status, activation, step and stand-down only, no DELETE (PC-31)
    "evacuation_manifest",  # UPDATE of the check-in only, no DELETE (PC-32)
    "fleet_asset",  # UPDATE of position, fuel and status only, no DELETE (PC-33)
    "fleet_maintenance",  # UPDATE of the done columns only, no DELETE (PC-34)
    "vip_visit",  # UPDATE of status, start and cancel only, no DELETE (PC-35)
    "vip_segment",  # UPDATE of status, times and virtual only, no DELETE (PC-36)
    "vip_segment_change",  # UPDATE of the decision only, no DELETE (PC-38)
    "vip_checklist_item",  # UPDATE of done_by only, no DELETE (PC-37)
    "site_zone",  # seeded; no UPDATE or DELETE (PC-39)
    "site_route",  # seeded; no UPDATE or DELETE (PC-40)
    "site_sensor",  # UPDATE of status and detail only, no DELETE (PC-42)
    "site_readiness_item",  # UPDATE of done_by only, no DELETE (PC-42)
    "supplier",  # UPDATE of the reported status only, no DELETE (PC-43)
    "logistics_route",  # UPDATE of the reported status only, no DELETE (PC-44)
    "supply_mitigation",  # UPDATE of the stand-down only, once; no DELETE (PC-45)
}
NO_UPDATE = {  # an UPDATE of other columns is refused; a DELETE is a departure
    "site_presence",  # UPDATE of zone_id only (PC-41)
}
NO_DELETE = {  # PC-07, PC-10, PC-11 (checkin_response: PC-12, in NO_UPDATE_DELETE)
    "message_template",
    "notification_campaign",
    "notification_delivery",
    "trip",  # cancelled, never deleted (PC-15)
    "flight",  # written only by the tracker; never deleted (PC-19)
    "weather_current",  # current values, refreshed by the feed; never deleted (PC-20)
}


def sql_for(table: str, ids: Ids) -> str:
    return ROWS[table].format(**ids.__dict__)


@dataclass(frozen=True)
class World:
    a: Ids
    b: uuid.UUID


async def _build_world(db: DbUrls) -> World:
    a = await create_tenant(db, "Isolation A")
    b = await create_tenant(db, "Isolation B")
    ids = Ids(
        t=a,
        signal=int(uuid.uuid4().int % 2**62),
        **{name: uuid.uuid4() for name in Ids.__dataclass_fields__ if name not in ("t", "signal")},
    )
    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, a)
        for table in ROWS:
            await conn.execute(sql_for(table, ids))
    finally:
        await conn.close()
    return World(a=ids, b=b)


@pytest.fixture(scope="module")
def world(db: DbUrls) -> World:
    """Tenant A with one row in every tenant table (inserted as nexira_api), and an
    empty tenant B."""
    return asyncio.run(_build_world(db))


async def _catalogue_tenant_tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT c.table_name FROM information_schema.columns c
          JOIN information_schema.tables t USING (table_schema, table_name)
         WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id'
           AND t.table_type = 'BASE TABLE'
        """
    )
    return {r["table_name"] for r in rows}


async def test_every_tenant_table_has_a_row_factory(api: asyncpg.Connection) -> None:
    assert await _catalogue_tenant_tables(api) == set(ROWS)


async def test_every_tenant_table_forces_rls_with_tenant_policy(db: DbUrls) -> None:
    """Catalogue check (plan G-02): RLS enabled AND forced, with the tenant_isolation
    policy on both USING and WITH CHECK."""
    conn = await asyncpg.connect(db.owner_plain)
    try:
        tables = await _catalogue_tenant_tables(conn)
        rows = await conn.fetch(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, p.qual, p.with_check
              FROM pg_class c
              LEFT JOIN pg_policies p
                ON p.schemaname = 'public' AND p.tablename = c.relname
               AND p.policyname = 'tenant_isolation'
             WHERE c.relnamespace = 'public'::regnamespace AND c.relname = ANY($1::text[])
            """,
            list(tables),
        )
    finally:
        await conn.close()
    assert {r["relname"] for r in rows} == tables
    expected = "(tenant_id = current_tenant_id())"
    bad = [
        r["relname"]
        for r in rows
        if not (
            r["relrowsecurity"]
            and r["relforcerowsecurity"]
            and r["qual"] == expected
            and r["with_check"] == expected
        )
    ]
    assert bad == []


@pytest.mark.parametrize("table", list(ROWS))
async def test_tenant_a_sees_its_row(api: asyncpg.Connection, world: World, table: str) -> None:
    await set_tenant(api, world.a.t)
    assert await api.fetchval(f"SELECT count(*) FROM {table}") >= 1


@pytest.mark.parametrize("table", list(ROWS))
async def test_tenant_b_cannot_read_tenant_a_rows(
    api: asyncpg.Connection, world: World, table: str
) -> None:
    await set_tenant(api, world.b)
    assert await api.fetchval(f"SELECT count(*) FROM {table}") == 0


@pytest.mark.parametrize("table", list(ROWS))
async def test_tenant_b_cannot_update_or_delete_tenant_a_rows(
    api: asyncpg.Connection, world: World, table: str
) -> None:
    await set_tenant(api, world.b)
    if table in NO_UPDATE_DELETE:
        for stmt in (f"UPDATE {table} SET tenant_id = tenant_id", f"DELETE FROM {table}"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await api.execute(stmt)
    elif table in NO_UPDATE:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await api.execute(f"UPDATE {table} SET tenant_id = tenant_id")
        assert await api.execute(f"DELETE FROM {table}") == "DELETE 0"
    else:
        assert await api.execute(f"UPDATE {table} SET tenant_id = tenant_id") == "UPDATE 0"
        if table in NO_DELETE:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await api.execute(f"DELETE FROM {table}")
        else:
            assert await api.execute(f"DELETE FROM {table}") == "DELETE 0"
    await set_tenant(api, world.a.t)
    assert await api.fetchval(f"SELECT count(*) FROM {table}") >= 1


@pytest.mark.parametrize("table", list(ROWS))
async def test_tenant_b_cannot_insert_rows_for_tenant_a(
    api: asyncpg.Connection, world: World, table: str
) -> None:
    await set_tenant(api, world.b)
    # A trip's travellers and segments are refused one step earlier, by trip_child_guard:
    # tenant B cannot see tenant A's trip (migration 0003).
    with pytest.raises(
        (asyncpg.InsufficientPrivilegeError, asyncpg.RaiseError),
        match=(
            r"row-level security|trip: no such trip|flight: no such flight"
            r"|weather: no such mission|partner request: no such partner"
            r"|travel document: no such person|climate risk: no such mission"
            r"|medical facility: no such mission|health readiness: no such mission"
            r"|evacuation plan: no such mission|evacuation manifest: no such evacuation"
            r"|fleet asset: no such mission|fleet maintenance: no such asset"
            r"|vip visit: no such mission|vip segment: no such visit|vip change: no such segment"
            r"|vip checklist: no such visit|site zone: no such site|site route: no such site"
            r"|site presence: no such site|site sensor: no such site|site readiness: no such site"
            r"|supplier: no such mission|logistics route: no such mission"
            r"|supply mitigation: no such supplier"
        ),
    ):
        await api.execute(sql_for(table, world.a))


@pytest.mark.parametrize("table", [*ROWS, "tenant"])
async def test_no_tenant_set_returns_zero_rows_without_error(
    api: asyncpg.Connection, world: World, table: str
) -> None:
    await set_tenant(api, None)
    assert await api.fetchval(f"SELECT count(*) FROM {table}") == 0


async def test_no_tenant_set_cannot_insert(api: asyncpg.Connection, world: World) -> None:
    await set_tenant(api, None)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        await api.execute(sql_for("mission", world.a))
