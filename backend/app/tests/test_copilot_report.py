"""The Copilot's situation report (COP-04; D-50; docs/plan-pilot-cop.md §4): every heading,
every sentence cited, the rule-based recommendations labelled and following the record, names
by role (G-1: A), the export audited, an unknown incident refused. Against real PostgreSQL, as
nexira_api, on the check-in tests' Nairobi world."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import tenant_session
from app.modules.audit.models import AuditLog
from app.tests.auth_helpers import Idp
from app.tests.test_checkin import World
from app.tests.test_copilot import copilot_world


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    return await copilot_world(client, idp)


HEADINGS = ["Summary", "Our people", "Actions taken", "Related risks", "Recommendations"]


async def report(
    client: AsyncClient, idp: Idp, incident: uuid.UUID, sub: str = "duty", path: str = "report"
) -> dict[str, Any]:
    response = await client.post(
        f"/api/copilot/{path}", json={"incident_id": str(incident)}, headers=idp.headers(sub)
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def section(body: dict[str, Any], heading: str) -> str:
    found = next(s for s in body["sections"] if s["heading"] == heading)
    return " ".join(x["text"] for x in found["sentences"])


async def test_the_report_has_every_heading_and_cites_every_sentence(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    body = await report(client, idp, world.incident_id)
    assert [s["heading"] for s in body["sections"]] == HEADINGS
    assert body["title"].startswith(f"Situation report · {body['reference']} · ")
    assert body["label"] == "Simulated copilot · rule-based wording · simulated data"
    for s in body["sections"]:
        for sentence in s["sentences"]:
            assert sentence["sources"], (s["heading"], sentence["text"])
    assert "civil unrest" in section(body, "Summary")
    people = section(body, "Our people")
    assert f"Check-in {world.reference}: of 3 personnel, 1 safe, 1 need help" in people
    assert "Asked for help: Grace." in people
    assert f"Messages sent: {world.reference} (checkin)." in section(body, "Actions taken")
    assert section(body, "Related risks") == "No related risk is recorded at the mission."
    refs = {s["reference"] for s in body["sources"]}
    assert {body["reference"], world.reference} <= refs


async def test_the_recommendations_are_stated_rules_from_the_record(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    body = await report(client, idp, world.incident_id)
    rules = next(s for s in body["sections"] if s["heading"] == "Recommendations")
    assert rules["note"] == "Rule-based recommendations from the record"
    # 1 staff and 3 citizens have not answered; one person needs help; no site in the zone.
    assert [x["text"] for x in rules["sentences"]] == [
        "Follow up the 4 people not yet accounted for.",
        "Confirm assistance for everyone who asked for help.",
        "Reassess at the next check-in or on escalation.",
    ]


async def test_names_follow_the_role_and_the_export_is_audited(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    viewed = await report(client, idp, world.incident_id, sub="viewer")
    assert "Grace" not in section(viewed, "Our people")
    assert "of 3 personnel, 1 safe, 1 need help" in section(viewed, "Our people")
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        before = await session.scalar(
            select(AuditLog.id).where(AuditLog.action == "COPILOT.REPORT_EXPORT")
        )
    assert before is None  # drafting is not an export
    exported = await report(client, idp, world.incident_id, sub="viewer", path="report/export")
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        row = (
            await session.execute(
                select(AuditLog.entity_id, AuditLog.details).where(
                    AuditLog.action == "COPILOT.REPORT_EXPORT"
                )
            )
        ).one()
    assert row.entity_id == exported["reference"]
    assert world.reference in row.details["references"]
    assert "Grace" not in str(row.details)


async def test_an_unknown_incident_is_refused(client: AsyncClient, idp: Idp, world: World) -> None:
    for path in ("report", "report/export"):
        response = await client.post(
            f"/api/copilot/{path}",
            json={"incident_id": str(uuid.uuid4())},
            headers=idp.headers("duty"),
        )
        assert response.status_code == 404
