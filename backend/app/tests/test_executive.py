"""Executive Overview (EXE-01..04; D-45; docs/plan-pilot-exe.md): the posture and region rules
(§2, §3), the check-in text without a name (G-11), and the API: every role reads it, the export
is audited and the chain verifies. The seeded world's figures are in the simulator's
test_executive_nbo.py. Against real PostgreSQL, as nexira_api."""

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.modules.executive import service as executive
from app.modules.people.schemas import MissionOut
from app.tests.auth_helpers import Idp


def _mission(code: str, country: str, risk: str) -> MissionOut:
    return MissionOut(
        id=uuid.uuid4(),
        code=code,
        city=code,
        country_code=country,
        lat=0,
        lon=0,
        risk_level=risk,
        display_risk=risk,
        incident_id=None,
        incident_reference=None,
        personnel=1,
        citizens=0,
    )


def test_posture_is_severe_then_elevated_then_guarded() -> None:
    calm = [_mission("NBO", "KE", "LOW"), _mission("ISB", "PK", "MODERATE")]
    assert executive.posture(calm, 0).model_dump() == {
        "level": "GUARDED",
        "critical_missions": 0,
        "elevated_missions": 1,
    }
    assert executive.posture(calm, 1).level == "ELEVATED"  # an ACTIVE incident anywhere
    assert executive.posture([*calm, _mission("BGW", "IQ", "HIGH")], 0).level == "ELEVATED"
    assert executive.posture([*calm, _mission("CAI", "EG", "CRITICAL")], 0).level == "SEVERE"


def test_regions_are_the_mean_of_risk_points() -> None:
    missions = [
        _mission("NBO", "KE", "CRITICAL"),
        _mission("CAI", "EG", "LOW"),
        _mission("ANK", "TR", "LOW"),  # Europe (G-2)
        _mission("XYZ", "ZZ", "HIGH"),  # not in the map
    ]
    assert [(r.region, r.exposure, r.missions) for r in executive.regions(missions)] == [
        ("Africa", round((95 + 20) / 2), 2),
        ("Europe", 20, 1),
        ("Other", 75, 1),
    ]


def test_a_check_in_entry_is_shown_without_the_name() -> None:
    """G-11."""
    assert (
        executive.timeline_summary("CHECKIN", "Fictional Person needs help (NTF-1, SMS).")
        == "Check-in: a person needs help."
    )
    assert executive.timeline_summary("STATUS", "Status ACTIVE → MONITORING.") == (
        "Status ACTIVE → MONITORING."
    )


async def test_every_role_reads_it_and_the_export_is_audited(client: AsyncClient, idp: Idp) -> None:
    mission = await idp.mission("NBO")
    for sub, role in (("viewer", "VIEWER"), ("duty", "DUTY_OFFICER"), ("hom", "HEAD_OF_MISSION")):
        await idp.user(sub, [(role, mission if role == "HEAD_OF_MISSION" else None)])
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id) VALUES (current_tenant_id(), "
                "'INC-2026-1042', 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
                "'SRID=4326;POINT(36.82 -1.28)', :m)"
            ),
            {"m": mission},
        )
        await session.commit()
    for who in ("viewer", "duty", "hom"):
        response = await client.get("/api/executive/overview", headers=idp.headers(who))
        assert response.status_code == 200, who
    out = response.json()
    assert (out["posture"]["level"], out["active_incidents"]) == ("SEVERE", 1)
    [first] = out["attention"]
    assert first["drivers"][0] == {
        "kind": "INCIDENT",
        "label": "Civil unrest (critical)",
        "reference": "INC-2026-1042",
    }
    assert out["simulated"] is True
    assert (await client.get("/api/executive/overview")).status_code == 401
    exported = await client.post("/api/executive/export", headers=idp.headers("viewer"))
    assert exported.status_code == 200
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        row = (
            await session.execute(
                text(
                    "SELECT actor_type, entity_type, details FROM audit_log "
                    "WHERE action = 'EXECUTIVE.EXPORT'"
                )
            )
        ).one()
        intact = await session.scalar(text("SELECT audit_verify_chain() IS NULL"))
    assert (row.actor_type, row.entity_type) == ("USER", "executive_overview")
    assert row.details["posture"] == "SEVERE"
    assert intact is True
