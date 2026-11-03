"""Seeding against real PostgreSQL + PostGIS as nexira_api (Prompt 4 tests).

Counts are computed with PostGIS, independently of the seeder (D-22, D-23).
"""

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import asyncpg
import pytest
from app.core.db import create_engine
from app.tests.conftest import DbUrls, set_tenant

from nexira_sim.seed import data
from nexira_sim.seed.load import seed_all

DAY = date(2026, 10, 20)
EPI = f"ST_SetSRID(ST_MakePoint({data.EPICENTRE[1]}, {data.EPICENTRE[0]}), 4326)::geography"


@dataclass
class Seeded:
    tenant_id: uuid.UUID
    issuer: str
    report: dict[str, Any]
    conn: asyncpg.Connection


async def _seed(db: DbUrls, tenant_id: uuid.UUID, issuer: str) -> dict[str, Any]:
    engine = create_engine(db.api)
    try:
        return await seed_all(
            engine, owner_dsn=db.owner, issuer=issuer, scenario_date=DAY, tenant_id=tenant_id
        )
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded(db: DbUrls) -> AsyncIterator[Seeded]:
    tenant_id = uuid.uuid4()
    issuer = f"https://kc.test/realms/seed-{tenant_id}"
    report = await _seed(db, tenant_id, issuer)
    conn = await asyncpg.connect(db.api_plain)
    await set_tenant(conn, tenant_id)
    try:
        yield Seeded(tenant_id, issuer, report, conn)
    finally:
        await conn.close()


async def test_nairobi_exposure_matches_d23(seeded: Seeded) -> None:
    rows = await seeded.conn.fetch(
        f"""
        SELECT p.person_type, count(*) AS n
          FROM person p JOIN person_location_current l ON l.person_id = p.id
         WHERE p.is_active AND ST_DWithin(l.location, {EPI}, 5000)
         GROUP BY 1
        """  # noqa: S608
    )
    by_type = {r["person_type"]: r["n"] for r in rows}
    assert by_type == {"DIPLOMAT": 12, "LOCAL_STAFF": 2, "DELEGATE": 3, "CITIZEN": 212}
    assert sum(by_type.values()) == 229  # the demo's "229 recipients"

    sites = await seeded.conn.fetch(
        f"SELECT site_type FROM site WHERE ST_DWithin(location, {EPI}, 5000) ORDER BY 1"  # noqa: S608
    )
    assert [r["site_type"] for r in sites] == ["EMBASSY", "HOTEL", "RESIDENCE"]
    property_sites = [r for r in sites if r["site_type"] != "HOTEL"]
    assert len(property_sites) == 2  # the UI "Sites" count (D-23)

    trips = await seeded.conn.fetch(
        f"""
        SELECT DISTINCT t.reference FROM trip t
          JOIN trip_traveller tt ON tt.trip_id = t.id
          JOIN person_location_current l ON l.person_id = tt.person_id
         WHERE t.starts_on <= $1 AND $1 <= t.ends_on AND ST_DWithin(l.location, {EPI}, 5000)
        """,  # noqa: S608
        DAY,
    )
    assert [r["reference"] for r in trips] == ["TRP-8812"]


async def test_nobody_else_is_near_nairobi(seeded: Seeded) -> None:
    """D-23: no other people inside the zone, even with a margin."""
    others = await seeded.conn.fetchval(
        f"""
        SELECT count(*) FROM person p JOIN person_location_current l ON l.person_id = p.id
          JOIN mission m ON m.id = p.mission_id
         WHERE m.code <> 'NBO' AND ST_DWithin(l.location, {EPI}, 50000)
        """  # noqa: S608
    )
    assert others == 0


async def test_section_7_distances(seeded: Seeded) -> None:
    async def km(where: str, *args: object) -> float:
        value = await seeded.conn.fetchval(
            f"SELECT ST_Distance(location, {EPI}) / 1000 FROM {where}",  # noqa: S608
            *args,
        )
        return round(float(value), 1)

    loc = "person_location_current l JOIN person p ON p.id = l.person_id WHERE p.full_name = $1"
    assert await km(loc, "Hana Takeda") == 2.4
    assert await km(loc, "Peter Mwangi") == 1.7
    assert await km("site WHERE site_type = 'EMBASSY' AND name = 'Embassy Nairobi'") == 2.2
    assert await km("site WHERE site_type = 'HOTEL'") == 1.5
    assert await km("site WHERE name = $1", "Ambassador's Residence Nairobi") == 3.6
    farthest_staff = await seeded.conn.fetchval(
        f"""
        SELECT max(ST_Distance(l.location, {EPI})) FROM person_location_current l
          JOIN person p ON p.id = l.person_id JOIN mission m ON m.id = p.mission_id
         WHERE m.code = 'NBO' AND p.person_type IN ('DIPLOMAT', 'LOCAL_STAFF')
           AND p.full_name NOT IN ('Hana Takeda', 'Peter Mwangi', 'Amb. Layla Haddad')
        """  # noqa: S608
    )
    assert farthest_staff < 3100  # "other 11 staff ... < 3.1 km"


async def test_location_confidence_engine_values(seeded: Seeded) -> None:
    rows = await seeded.conn.fetch(
        "SELECT p.full_name, l.confidence, l.primary_source, l.place_label "
        "FROM person_location_current l JOIN person p ON p.id = l.person_id"
    )
    got = {r["full_name"]: (r["confidence"], r["primary_source"], r["place_label"]) for r in rows}
    for name, _title, place, source, conf, _type in data.NAIROBI_PEOPLE:
        assert got[name] == (conf, source, place), name
    assert got["Hana Takeda"] == (72, "CALENDAR_HR", "Last seen · Westlands")  # PPL-03


async def test_sources_playbook_agents_and_counters(seeded: Seeded) -> None:
    c = seeded.conn
    sources = {r["code"]: r for r in await c.fetch("SELECT * FROM intel_source")}
    assert len(sources) == 11  # with the seismic and air-quality networks (D-38)
    reliability = {k: float(v["reliability"]) for k, v in sources.items()}
    assert (reliability["DATAMINR"], reliability["MAX"], reliability["RISKLINE"]) == (
        0.6,
        0.55,
        0.55,
    )
    assert (reliability["SEISMIC"], reliability["AIRQ"]) == (0.7, 0.6)
    assert {
        v
        for k, v in reliability.items()
        if k not in ("DATAMINR", "MAX", "RISKLINE", "SEISMIC", "AIRQ")
    } == {0.5}
    # The measure decides a measured hazard's severity, so these have no severity map.
    assert json.loads(sources["SEISMIC"]["severity_map"]) == {}
    xweather = json.loads(sources["XWEATHER"]["category_map"])
    assert (xweather["Tropical cyclone"], xweather["Wildfire"]) == ("TROPICAL_CYCLONE", "WILDFIRE")
    assert not sources["OSINT"]["is_enabled"]
    assert not sources["OSINT"]["takes_part_in_fusion"]
    assert all(s["connector_type"] == "SIMULATED" for s in sources.values())

    def sev(code: str, provider: str) -> str:
        mapping: dict[str, str] = json.loads(sources[code]["severity_map"])
        return mapping[provider]

    assert sev("DATAMINR", "High") == "HIGH"
    assert sev("MAX", "Level 4") == "HIGH"
    assert sev("RISKLINE", "Moderate") == "MODERATE"  # D-11

    steps = await c.fetch(
        "SELECT s.seq, s.action_type, s.requires_approval_role FROM playbook_step s "
        "JOIN playbook p ON p.id = s.playbook_id WHERE p.code = 'PB-07' ORDER BY s.seq"
    )
    assert [r["seq"] for r in steps] == list(range(1, 9))
    assert [r["requires_approval_role"] for r in steps if r["requires_approval_role"]] == [
        "HEAD_OF_MISSION"
    ]
    assert steps[6]["requires_approval_role"] == "HEAD_OF_MISSION"

    agents = {r["code"]: r["autonomy_level"] for r in await c.fetch("SELECT * FROM agent")}
    assert agents == {
        "WATCH_OFFICER": 0,
        "EXPOSURE": 0,
        "RESPONSE_PLANNER": 2,
        "COMMUNICATIONS": 2,
        "TRAVEL_AIR": 2,  # D-34
        "COMPLIANCE": 2,  # D-37
        "FORECAST": 4,  # D-46: advice only (plan-pilot-prd G-1)
    }
    policies = {
        r["action_type"]: (r["min_autonomy_level"], r["approver_roles"], r["is_undoable"])
        for r in await c.fetch("SELECT * FROM action_policy")
    }
    assert policies["NOTIFY_TRAVELLERS"] == (2, ["TRAVEL_DESK|SECURITY_OFFICER"], False)
    assert policies["CANCEL_TRIP"] == (2, ["SECURITY_OFFICER"], False)
    assert "ADVISE_REBOOKING" not in policies  # advice only (D-12)
    assert policies["START_DOCUMENT_RENEWAL"] == (2, ["CONSULAR_OFFICER|DUTY_OFFICER"], False)
    assert "ADVISE_EMERGENCY_DOCUMENTS" not in policies
    assert policies["ARM_PLAYBOOK"] == (2, ["SECURITY_OFFICER|DUTY_OFFICER"], False)  # D-38
    assert policies["PREPARE_HEALTH_ADVISORY"] == (  # D-39, plan-pilot-hl §7
        2,
        ["DUTY_OFFICER|CONSULAR_OFFICER"],
        False,
    )
    deadlines = await c.fetch(
        "SELECT decision_deadline_s FROM action_policy "
        "WHERE action_type IN ('NOTIFY_TRAVELLERS', 'CANCEL_TRIP', 'START_DOCUMENT_RENEWAL')"
    )
    assert {r["decision_deadline_s"] for r in deadlines} == {3600}
    assert policies["START_EVACUATION"] == (3, ["HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"], False)
    assert policies["SEND_EXTERNAL_MESSAGE"] == (2, ["DUTY_OFFICER|CONSULAR_OFFICER"], False)
    assert policies["LOG_INFO"] == (0, [], True)

    inc = await c.fetchval("SELECT next_reference('INC', true)")
    assert re.fullmatch(r"INC-\d{4}-1042", inc)
    assert await c.fetchval("SELECT next_reference('NTF', false)") == "NTF-3101"


async def test_mission_risk_and_site_readiness(seeded: Seeded) -> None:
    rows = await seeded.conn.fetch("SELECT city, risk_level FROM mission")
    assert len(rows) == 36
    assert {r["city"] for r in rows if r["risk_level"] == "MODERATE"} == data.ELEVATED
    nbo = await seeded.conn.fetchrow(
        "SELECT readiness_score, last_drill_on FROM site WHERE name = 'Embassy Nairobi'"
    )
    assert nbo is not None
    assert nbo["readiness_score"] == 79  # demo: 70 + (12 * 37) % 29
    assert (DAY - nbo["last_drill_on"]).days == 21  # demo: "3 weeks ago"


async def _snapshot(conn: asyncpg.Connection) -> dict[str, Any]:
    tables = [
        "mission", "site", "person", "location_observation", "person_location_current", "trip",
        "trip_traveller", "intel_source", "playbook", "playbook_step", "agent", "action_policy",
        "app_user", "role", "user_role", "reference_counter", "scenario", "scenario_event",
        "message_template", "country_risk", "travel_document",
    ]  # fmt: skip
    snap: dict[str, Any] = {}
    for t in tables:
        snap[t] = await conn.fetch(f"SELECT * FROM {t} ORDER BY 1, 2")  # noqa: S608
    snap["audit_rows"] = await conn.fetchval("SELECT count(*) FROM audit_log")
    return snap


async def test_seeding_twice_gives_identical_data(seeded: Seeded, db: DbUrls) -> None:
    before = await _snapshot(seeded.conn)
    again = await _seed(db, seeded.tenant_id, seeded.issuer)
    after = await _snapshot(seeded.conn)
    assert before == after  # including the audit row count: nothing re-audited
    assert again["persons"] == 0
    assert again["observations"] == 0
    assert again["locations_changed"] == 0
    assert await seeded.conn.fetchval("SELECT audit_verify_chain()") is None


async def test_bulk_loads_are_audited_once_per_batch(seeded: Seeded) -> None:
    actions = {
        r["action"]: r["n"]
        for r in await seeded.conn.fetch(
            "SELECT action, count(*) AS n FROM audit_log GROUP BY action"
        )
    }
    assert actions["PERSON.BULK_LOAD"] == 1  # one row per load, with the count (G-20)
    assert actions["SITE.BULK_LOAD"] == 1
    assert actions["LOCATION_OBSERVATION.BULK_LOAD"] == 1
    assert actions["LOCATION.RECOMPUTE"] == 1
    assert actions["MISSION.CREATE"] == 36
    assert actions["CLIMATE_RISK.SEED"] == 1  # one row for the 36 scores (D-38)
    assert sum(actions.values()) < 175  # not one row per person


async def test_message_templates_generic_nairobi_and_paris(seeded: Seeded) -> None:
    """D-31: per code, one generic template and one per mission; nothing reviewed yet
    (D-15). Nairobi keeps PB-07 v1's exact words, so the acceptance scenario is unchanged."""
    rows = await seeded.conn.fetch(
        "SELECT t.code, m.code AS mission, t.kind, t.texts, t.reviewed FROM message_template t "
        "LEFT JOIN mission m ON m.id = t.mission_id ORDER BY t.code, m.code NULLS FIRST"
    )
    assert [(r["code"], r["mission"], r["kind"]) for r in rows] == [
        ("CIVIL_UNREST_SHELTER", None, "ADVISORY"),
        ("CIVIL_UNREST_SHELTER", "NBO", "ADVISORY"),
        ("CIVIL_UNREST_SHELTER", "PAR", "ADVISORY"),
        ("CIVIL_UNREST_STAFF_ALERT", None, "ALERT"),
        ("CIVIL_UNREST_STAFF_ALERT", "NBO", "ALERT"),
        ("CIVIL_UNREST_STAFF_ALERT", "PAR", "ALERT"),
        # PB-01 (D-38): English only, generic.
        ("EARTHQUAKE_CITIZEN_ADVISORY", None, "ADVISORY"),
        ("EARTHQUAKE_STAFF_ALERT", None, "ALERT"),
        # The evacuation movement order (D-40, plan-pilot-ev G-7): generic and Nairobi.
        ("EVACUATION_MOVE", None, "ALERT"),
        ("EVACUATION_MOVE", "NBO", "ALERT"),
        # Health (D-39, plan-pilot-hl G-1): per topic, with the generic fallback.
        ("HEALTH_CHOLERA", None, "ADVISORY"),
        ("HEALTH_CHOLERA", "NBO", "ADVISORY"),
        ("HEALTH_GENERAL", None, "ADVISORY"),
        # PB-06 (D-35): English only, generic and Manila.
        ("SEVERE_WEATHER_SHELTER", None, "ADVISORY"),
        ("SEVERE_WEATHER_SHELTER", "MNL", "ADVISORY"),
        ("SEVERE_WEATHER_STAFF_ALERT", None, "ALERT"),
        ("SEVERE_WEATHER_STAFF_ALERT", "MNL", "ALERT"),
    ]
    evacuation = [r for r in rows if r["code"] == "EVACUATION_MOVE"]
    assert "{city}" in json.loads(evacuation[0]["texts"])["en"]
    assert "Embassy courtyard" in json.loads(evacuation[1]["texts"])["en"]
    assert [json.loads(r["reviewed"]) for r in evacuation] == [
        {"ar": False, "fr": False, "sw": False}
    ] * 2
    rows = [r for r in rows if r["code"] != "EVACUATION_MOVE"]
    health = [r for r in rows if r["code"].startswith("HEALTH_")]
    rows = [r for r in rows if not r["code"].startswith("HEALTH_")]
    weather, rows = rows[6:], rows[:6]
    assert json.loads(health[1]["texts"]) == data.HEALTH_CHOLERA_NBO
    assert "{city}" in json.loads(health[0]["texts"])["en"]
    assert set(json.loads(health[2]["texts"])) == {"en", "ar", "fr", "sw"}
    assert [json.loads(r["reviewed"]) for r in health] == [
        {},
        {"ar": False, "fr": False, "sw": False},
        {"ar": False, "fr": False, "sw": False},
    ]
    assert [set(json.loads(r["texts"])) for r in weather] == [{"en"}] * 6
    assert [json.loads(r["reviewed"]) for r in weather] == [{}] * 6
    assert "{city}" in json.loads(weather[0]["texts"])["en"]
    assert "{city}" in json.loads(weather[2]["texts"])["en"]
    assert "Manila" in json.loads(weather[3]["texts"])["en"]
    texts = [json.loads(r["texts"]) for r in rows]
    assert "{city}" in texts[0]["en"]
    assert texts[1] == data.CITIZEN_ADVISORY
    assert "Paris" in texts[2]["en"]
    assert "Nairobi" not in texts[2]["en"]
    assert texts[4] == {"en": "Shelter in place. Avoid CBD and Upper Hill."}  # PB-07 v1
    assert "CBD" not in texts[5]["en"]
    reviewed = [json.loads(r["reviewed"]) for r in rows]
    assert all(set(r) == {"ar", "fr", "sw"} for r in reviewed[:3])  # not English (D-15)
    assert reviewed[3:] == [{}, {}, {}]  # English only: nothing to review
    assert not any(any(r.values()) for r in reviewed)


async def test_journey_seed_country_risk_trips_and_counter(seeded: Seeded) -> None:
    """D-32, PC-16: simulated country risk, a few future trips, and TRP-8835 next (after the
    VIP visit's TRP-8834, D-42)."""
    levels = {
        r["country_code"]: r["level"]
        for r in await seeded.conn.fetch("SELECT country_code, level FROM country_risk")
    }
    assert (levels["KE"], levels["IQ"], levels["FR"]) == ("MODERATE", "HIGH", "LOW")
    trips = {
        r["reference"]: (r["approval_status"], r["risk_level"], r["approved_at"] is not None)
        for r in await seeded.conn.fetch(
            "SELECT reference, approval_status, risk_level, approved_at FROM trip"
        )
    }
    assert trips == {
        "TRP-8810": ("APPROVED", "LOW", True),  # Kuala Lumpur staff in Manila (WX-06)
        "TRP-8811": ("APPROVED", "LOW", True),  # the France scenario's CANCEL_TRIP (D-34)
        "TRP-8812": ("APPROVED", "MODERATE", True),
        "TRP-8814": ("PENDING", "HIGH", False),
        "TRP-8815": ("APPROVED", "LOW", True),
        "TRP-8816": ("DRAFT", "LOW", False),
        "TRP-8817": ("APPROVED", "LOW", True),
        # Air Travel Tracking (D-33): one FLIGHT segment each.
        "TRP-8813": ("APPROVED", "LOW", True),  # restricted
        "TRP-8818": ("APPROVED", "MODERATE", True),  # XW 451, the scenario flight
        "TRP-8819": ("APPROVED", "LOW", True),
        "TRP-8820": ("APPROVED", "LOW", True),
        # VIP & Delegation Protection (D-42): the visit's trip, restricted, no segments.
        "TRP-8834": ("APPROVED", "MODERATE", True),
    }
    scoped = await seeded.conn.fetchrow(
        "SELECT m.code, (SELECT count(*) FROM trip WHERE requested_by IS NOT NULL) AS requested "
        "FROM trip t JOIN mission m ON m.id = t.mission_id WHERE t.reference = 'TRP-8814'"
    )
    assert scoped is not None
    assert (scoped["code"], scoped["requested"]) == ("BGW", 1)  # plan G-2; the draft
    assert await seeded.conn.fetchval("SELECT next_reference('TRP', false)") == "TRP-8835"


async def test_air_seed_airports_and_the_scenario_flight_only(seeded: Seeded) -> None:
    """D-33, plan G-1, G-3: XW 451 is seeded as a SCENARIO flight; the tracker (not the
    seed) creates the others; the restricted trip has none and never can."""
    assert await seeded.conn.fetchval("SELECT count(*) FROM airport") == 14
    flights = await seeded.conn.fetch(
        "SELECT f.flight_number, f.status, f.source, t.reference FROM flight f "
        "JOIN trip_segment s ON s.id = f.trip_segment_id JOIN trip t ON t.id = s.trip_id"
    )
    assert [tuple(f) for f in flights] == [("XW 451", "SCHEDULED", "SCENARIO", "TRP-8818")]
    restricted = await seeded.conn.fetch("SELECT reference FROM trip WHERE restricted")
    # TRP-8834 (the VIP visit, D-42) has no FLIGHT segment, so nothing to track either.
    assert sorted(r["reference"] for r in restricted) == ["TRP-8813", "TRP-8834"]
    # A real AT-05 fixture: a trackable FLIGHT segment that names nothing on screen.
    segment = await seeded.conn.fetchrow(
        "SELECT s.title, s.place_label, s.flight_number, s.from_airport, s.to_airport "
        "FROM trip_segment s JOIN trip t ON t.id = s.trip_id WHERE t.reference = 'TRP-8813'"
    )
    assert segment is not None
    assert tuple(segment) == ("Flight", None, "XW 777", "AMM", "AUH")
    tracked = await seeded.conn.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'FLIGHT.TRACK'"
    )
    assert tracked == 1  # once, however often the seed runs
    travellers = await seeded.conn.fetchval(
        "SELECT count(*) FROM trip_traveller tt JOIN trip t ON t.id = tt.trip_id "
        "WHERE t.reference = 'TRP-8818'"
    )
    assert travellers == 3


async def test_documents_seed_the_design_kpis(seeded: Seeded) -> None:
    """Plan-pilot-dx §8: one passport-type document each, 6 within 30 days and 31 within 90
    of the seed date, Nairobi's two, and nobody else in Nairobi under 180 days."""
    c = seeded.conn
    holders = await c.fetch(
        "SELECT p.person_type, count(d.id) FILTER (WHERE d.doc_type IN "
        "('PASSPORT', 'DIPLOMATIC_PASSPORT')) AS passports, count(d.id) AS docs "
        "FROM person p LEFT JOIN travel_document d ON d.person_id = p.id "
        "WHERE p.is_active GROUP BY p.id, p.person_type"
    )
    for r in holders:
        expected = 0 if r["person_type"] in ("CITIZEN", "DELEGATE") else 1
        assert r["passports"] == expected, r
        assert r["docs"] == len(data.DOCUMENTS_BY_TYPE.get(r["person_type"], ())), r
    within = "SELECT count(*) FROM travel_document WHERE valid_until - $1::date < $2"
    assert await c.fetchval(within, DAY, 30) == 6
    assert await c.fetchval(within, DAY, 90) == 31
    nairobi = await c.fetch(
        "SELECT p.full_name, d.doc_type, d.valid_until - $1::date AS days, d.renewal_status "
        "FROM travel_document d JOIN person p ON p.id = d.person_id "
        "JOIN mission m ON m.id = p.mission_id "
        "WHERE m.code = 'NBO' AND d.valid_until - $1::date < 180 ORDER BY days",
        DAY,
    )
    assert [tuple(r) for r in nairobi] == [
        ("Aiko Takeda", "PASSPORT", 12, "NONE"),
        ("Hana Takeda", "DIPLOMATIC_PASSPORT", 21, "NONE"),
    ]
    in_progress = await c.fetchval(
        "SELECT count(*) FROM travel_document "
        "WHERE renewal_status = 'IN_PROGRESS' AND valid_until - $1::date < 90",
        DAY,
    )
    assert in_progress == data.DOCUMENT_IN_PROGRESS
    started_by = await c.fetch(
        "SELECT DISTINCT renewal_started_by FROM travel_document "
        "WHERE renewal_started_by IS NOT NULL"
    )
    assert [r["renewal_started_by"] for r in started_by] == ["system:seed"]
    # The scenarios' other missions have none under 180 days: the agent finds only Nairobi's.
    quiet = await c.fetchval(
        "SELECT count(*) FROM travel_document d JOIN person p ON p.id = d.person_id "
        "JOIN mission m ON m.id = p.mission_id "
        "WHERE m.code IN ('PAR', 'MNL') AND d.valid_until - $1::date < 180",
        DAY,
    )
    assert quiet == 0
    actions = {
        r["action"]: r["n"]
        for r in await c.fetch(
            "SELECT action, count(*) AS n FROM audit_log "
            "WHERE action LIKE 'TRAVEL_DOCUMENT.%' OR action LIKE 'DOCUMENT.%' GROUP BY action"
        )
    }
    assert actions == {"TRAVEL_DOCUMENT.BULK_LOAD": 1, "DOCUMENT.RENEWAL_STARTED": 19}


async def test_the_paris_trip_has_a_document_warning(seeded: Seeded) -> None:
    """DX-06: TRP-8811's first traveller's passport ends under 180 days after the trip."""
    rows = await seeded.conn.fetch(
        "SELECT p.full_name, max(d.valid_until) AS valid_until, t.ends_on FROM trip t "
        "JOIN trip_traveller tt ON tt.trip_id = t.id JOIN person p ON p.id = tt.person_id "
        "JOIN travel_document d ON d.person_id = p.id "
        "AND d.doc_type IN ('PASSPORT', 'DIPLOMATIC_PASSPORT') "
        "WHERE t.reference = 'TRP-8811' GROUP BY p.full_name, t.ends_on"
    )
    short = [r for r in rows if (r["valid_until"] - r["ends_on"]).days < 180]
    assert len(rows) == 2
    assert len(short) == 1
    assert (short[0]["valid_until"] - DAY).days == 150


async def test_aiko_takeda_is_in_nairobi_outside_the_zone(seeded: Seeded) -> None:
    """Plan-pilot-dx G-2."""
    row = await seeded.conn.fetchrow(
        "SELECT p.person_type, m.code, ST_Distance(l.location, "
        "ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) / 1000 AS km "
        "FROM person p JOIN mission m ON m.id = p.mission_id "
        "JOIN person_location_current l ON l.person_id = p.id WHERE p.full_name = 'Aiko Takeda'",
        data.EPICENTRE[1],
        data.EPICENTRE[0],
    )
    assert row is not None
    assert (row["person_type"], row["code"]) == ("DEPENDANT", "NBO")
    assert 9 < float(row["km"]) < 10


async def test_climate_scores_for_every_mission_jakarta_highest(seeded: Seeded) -> None:
    """HZ-08, §43 Q7: illustrative, all 36 missions, Jakarta highest in 2050."""
    rows = await seeded.conn.fetch(
        "SELECT m.code, c.score_today, c.score_2050, c.hazards, c.source "
        "FROM mission_climate_risk c JOIN mission m ON m.id = c.mission_id "
        "ORDER BY c.score_2050 DESC, m.code"
    )
    assert len(rows) == 36
    assert (rows[0]["code"], rows[0]["score_2050"]) == ("JKT", 88)
    assert {r["source"] for r in rows} == {"Illustrative climate model (simulated)"}
    by_code = {r["code"]: (r["score_today"], r["score_2050"]) for r in rows}
    assert by_code["DAC"] == (79, 86)  # the design's figures
    assert by_code["LON"] == (22, 27)


async def test_pb01_and_the_hazard_homes(seeded: Seeded) -> None:
    """HZ-07, HZ-11: PB-01 seeded; three Dhaka and two Jakarta staff at home in flood-prone
    wards; the seeded totals do not move."""
    c = seeded.conn
    steps = await c.fetch(
        "SELECT s.seq, s.action_type FROM playbook_step s JOIN playbook p ON p.id = s.playbook_id "
        "WHERE p.code = 'PB-01' ORDER BY s.seq"
    )
    assert [(r["seq"], r["action_type"]) for r in steps] == [
        (1, "CHECKIN"),
        (2, "NOTIFY"),
        (3, "NOTIFY"),
    ]
    homes = await c.fetch(
        "SELECT m.code, count(*) AS n FROM person_location_current l "
        "JOIN person p ON p.id = l.person_id JOIN mission m ON m.id = p.mission_id "
        "WHERE l.place_label LIKE 'Home · %flood-prone%' GROUP BY m.code ORDER BY m.code"
    )
    assert [(r["code"], r["n"]) for r in homes] == [("DAC", 3), ("JKT", 2)]
    dhaka = await c.fetchval(
        "SELECT count(*) FROM person p JOIN mission m ON m.id = p.mission_id "
        "WHERE m.code = 'DAC' AND p.person_type IN ('DIPLOMAT', 'LOCAL_STAFF')"
    )
    assert dhaka == 15  # §43 Q8: no new people


async def test_health_reference_data_is_seeded_counts_only(seeded: Seeded) -> None:
    """D-39, §48 Q2-Q5: six advisories, none HIGH (so no proposal at reset-demo), entry
    requirements for every mission country, about three facilities per mission (Nairobi's
    four), and readiness counts equal to each mission's seeded staff."""
    conn = seeded.conn
    advisories = await conn.fetch(
        "SELECT topic_code, level, status, published_at <= now() AS past FROM health_advisory "
        "ORDER BY reference"
    )
    assert [a["topic_code"] for a in advisories] == [
        "CHOLERA", "DENGUE", "MPOX", "AVIAN_INFLUENZA", "MEASLES", "HEAT_HEALTH",
    ]  # fmt: skip
    assert {a["level"] for a in advisories} <= {"LOW", "MODERATE"}
    assert all(a["status"] == "OPEN" and a["past"] for a in advisories)
    assert (
        await conn.fetchval(
            "SELECT count(*) FROM agent_proposal WHERE action_type = 'PREPARE_HEALTH_ADVISORY'"
        )
        == 0
    )
    countries = await conn.fetchval("SELECT count(DISTINCT country_code) FROM mission")
    assert await conn.fetchval("SELECT count(*) FROM country_health_requirement") == countries
    per_mission = await conn.fetch(
        "SELECT m.code, count(f.id) AS n FROM mission m LEFT JOIN medical_facility f "
        "ON f.mission_id = m.id GROUP BY m.code"
    )
    assert {r["code"]: r["n"] for r in per_mission} == {
        m[0]: 4 if m[0] == "NBO" else 3 for m in data.MISSIONS
    }
    staff = await conn.fetch(
        "SELECT m.code, r.staff, r.vaccines_offered, "
        "(SELECT count(*) FROM person p WHERE p.mission_id = m.id AND p.is_active "
        "  AND p.person_type IN ('DIPLOMAT', 'LOCAL_STAFF')) AS seeded "
        "FROM mission m JOIN mission_health_readiness r ON r.mission_id = m.id"
    )
    assert len(staff) == len(data.MISSIONS)
    assert all(r["staff"] == r["seeded"] for r in staff)
    nairobi = next(r for r in staff if r["code"] == "NBO")
    assert (nairobi["staff"], json.loads(nairobi["vaccines_offered"])) == (14, {"CHOLERA": 9})
    vetted = await conn.fetchval(
        "SELECT count(*) FROM medical_facility f JOIN partner p ON p.id = f.vetted_by "
        "WHERE p.code = 'KES'"
    )
    assert vetted == 3 + 2 * (len(data.MISSIONS) - 1)
