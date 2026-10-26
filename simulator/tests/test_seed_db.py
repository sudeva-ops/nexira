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
    assert len(sources) == 9
    reliability = {k: float(v["reliability"]) for k, v in sources.items()}
    assert (reliability["DATAMINR"], reliability["MAX"], reliability["RISKLINE"]) == (
        0.6,
        0.55,
        0.55,
    )
    assert {v for k, v in reliability.items() if k not in ("DATAMINR", "MAX", "RISKLINE")} == {0.5}
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
    assert agents == {"WATCH_OFFICER": 0, "EXPOSURE": 0, "RESPONSE_PLANNER": 2, "COMMUNICATIONS": 2}
    policies = {
        r["action_type"]: (r["min_autonomy_level"], r["approver_roles"], r["is_undoable"])
        for r in await c.fetch("SELECT * FROM action_policy")
    }
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
        "message_template",
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
    assert sum(actions.values()) < 150  # not one row per person


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
    ]
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
