"""After-Action Review API (AAR-01, AAR-05..08; D-47; docs/plan-pilot-aar.md §5-§7): who may
start, decide, add, mark done and finalise, each refusal, every audited action, the metrics
frozen when final, the audited export, the Viewer reading only, and no name in any answer.
Against real PostgreSQL, as nexira_api, on the hand-built record of test_aar_service."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.core.realtime import FORWARDED
from app.tests.auth_helpers import Idp
from app.tests.test_aar_service import NAMES, PT, _world

DUE = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()


async def _setup(idp: Idp) -> dict[str, Any]:
    incident = await _world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        nbo = await s.scalar(text("SELECT mission_id FROM incident WHERE id = :i"), {"i": incident})
        other = await s.scalar(
            text(
                "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
                f"(current_tenant_id(), 'CAI', 'Cairo', 'EG', {PT}) RETURNING id"
            )
        )
        active = await s.scalar(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, mission_id, location) VALUES (current_tenant_id(), "
                f"'INC-2026-1050', 'Unrest', 'CIVIL_UNREST', 'HIGH', 'HIGH', :m, {PT}) RETURNING id"
            ),
            {"m": nbo},
        )
        await s.commit()
    for sub, role, mission in (
        ("duty", "DUTY_OFFICER", None),
        ("security", "SECURITY_OFFICER", None),
        ("hom", "HEAD_OF_MISSION", nbo),
        ("hom-cairo", "HEAD_OF_MISSION", other),
        ("viewer", "VIEWER", None),
    ):
        await idp.user(sub, [(role, mission)])
    return {"incident": incident, "active": active}


async def _audit(idp: Idp, prefix: str = "AAR.") -> list[str]:
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        return list(
            await s.scalars(
                text("SELECT action FROM audit_log WHERE action LIKE :p ORDER BY id"),
                {"p": f"{prefix}%"},
            )
        )


def _no_names(body: str) -> None:
    assert not [name for name in NAMES if name in body]


async def test_a_reviewer_starts_a_review_with_its_drafts(client: AsyncClient, idp: Idp) -> None:
    w = await _setup(idp)
    listed = (await client.get("/api/aar", headers=idp.headers("viewer"))).json()
    assert listed["reviews"] == []
    assert [(r["reference"], r["can_start"]) for r in listed["ready"]] == [("INC-2026-1042", False)]
    start = {"incident_id": str(w["incident"])}
    assert (
        await client.post("/api/aar", json=start, headers=idp.headers("viewer"))
    ).status_code == 403
    assert (
        await client.post("/api/aar", json=start, headers=idp.headers("hom-cairo"))
    ).status_code == 403  # another mission's Head of Mission (D-06)
    active = await client.post(
        "/api/aar", json={"incident_id": str(w["active"])}, headers=idp.headers("duty")
    )
    assert (active.status_code, active.json()["detail"]) == (409, "INC-2026-1050 is still ACTIVE")
    missing = await client.post(
        "/api/aar", json={"incident_id": str(uuid.uuid4())}, headers=idp.headers("duty")
    )
    assert missing.status_code == 404

    response = await client.post("/api/aar", json=start, headers=idp.headers("hom"))
    assert response.status_code == 201, response.text
    review = response.json()
    assert (review["reference"], review["status"], review["incident_reference"]) == (
        "AAR-2026-1042",
        "DRAFT",
        "INC-2026-1042",
    )
    assert [i["rule_code"] for i in review["items"]] == [
        "CHECKIN_SILENT",
        "FLEET_ZONE",
        "GATE_WAIT",
        "LOW_CONFIDENCE",
        "NOTIFY_LATE",
        "SITE_FAULT",
        "SUPPLY_IMPACT",
    ]
    assert {i["status"] for i in review["items"]} == {"DRAFT"}
    assert review["label"] == "Drafted from the platform record by rules · reviewed by people"
    assert (review["can_act"], review["can_finalise"]) == (True, False)
    assert review["timeline"]
    assert review["metrics"]
    _no_names(response.text)
    again = await client.post("/api/aar", json=start, headers=idp.headers("duty"))
    assert (again.status_code, again.json()["detail"]) == (409, "AAR-2026-1042 already exists")
    assert await _audit(idp) == ["AAR.START"]
    listed = (await client.get("/api/aar", headers=idp.headers("viewer"))).json()
    assert [(r["reference"], r["drafts"], r["items"]) for r in listed["reviews"]] == [
        ("AAR-2026-1042", 7, 7)
    ]
    assert listed["ready"] == []
    assert "AAR_UPDATED" in FORWARDED


async def _started(client: AsyncClient, idp: Idp) -> dict[str, Any]:
    w = await _setup(idp)
    review: dict[str, Any] = (
        await client.post(
            "/api/aar", json={"incident_id": str(w["incident"])}, headers=idp.headers("duty")
        )
    ).json()
    review["by_rule"] = {i["rule_code"]: i["id"] for i in review["items"]}
    return review


async def test_people_decide_each_draft(client: AsyncClient, idp: Idp) -> None:
    review = await _started(client, idp)
    silent = review["by_rule"]["CHECKIN_SILENT"]
    fleet = review["by_rule"]["FLEET_ZONE"]
    accept = {"owner_team": "HR", "due_on": DUE, "action": "Add a second contact channel."}
    refused = await client.post(
        f"/api/aar/items/{silent}/accept", json=accept, headers=idp.headers("viewer")
    )
    assert refused.status_code == 403
    past = {**accept, "due_on": "2020-01-01"}
    late = await client.post(
        f"/api/aar/items/{silent}/accept", json=past, headers=idp.headers("duty")
    )
    assert (late.status_code, late.json()["detail"]) == (422, "The due date is in the past")
    done = await client.post(
        f"/api/aar/items/{silent}/accept", json=accept, headers=idp.headers("duty")
    )
    assert done.status_code == 200, done.text
    item = next(i for i in done.json()["items"] if i["id"] == silent)
    assert (item["status"], item["owner_team"], item["due_on"], item["action"]) == (
        "ACCEPTED",
        "HR",
        DUE,
        "Add a second contact channel.",
    )
    twice = await client.post(
        f"/api/aar/items/{silent}/reject", json={"reason": "No"}, headers=idp.headers("duty")
    )
    assert (twice.status_code, twice.json()["detail"]) == (409, "Only a draft is rejected")
    rejected = await client.post(
        f"/api/aar/items/{fleet}/reject",
        json={"reason": "Handled offline"},
        headers=idp.headers("hom"),
    )
    assert next(i for i in rejected.json()["items"] if i["id"] == fleet)["reason"] == (
        "Handled offline"
    )
    added = await client.post(
        f"/api/aar/{review['id']}/items",
        json={
            "finding": "The hotline was busy before the portal opened.",
            "action": "Open the crisis portal at CRITICAL severity.",
            "owner_team": "CONSULAR",
            "priority": "MEDIUM",
            "due_on": DUE,
        },
        headers=idp.headers("duty"),
    )
    assert added.status_code == 201
    own = next(i for i in added.json()["items"] if i["rule_code"] is None)
    assert own["status"] == "ACCEPTED"
    marked = await client.post(f"/api/aar/items/{own['id']}/done", headers=idp.headers("duty"))
    assert next(i for i in marked.json()["items"] if i["id"] == own["id"])["status"] == "DONE"
    bad = await client.post(
        f"/api/aar/items/{silent}/accept",
        json={"owner_team": "PRESS", "due_on": DUE},
        headers=idp.headers("duty"),
    )
    assert bad.status_code == 422
    assert await _audit(idp) == [
        "AAR.START",
        "AAR.ITEM_ACCEPT",
        "AAR.ITEM_REJECT",
        "AAR.ITEM_ADD",
        "AAR.ITEM_DONE",
    ]


async def test_finalising_freezes_the_metrics(client: AsyncClient, idp: Idp) -> None:
    review = await _started(client, idp)
    final = f"/api/aar/{review['id']}/finalise"
    assert (await client.post(final, headers=idp.headers("duty"))).status_code == 403
    pending = await client.post(final, headers=idp.headers("security"))
    assert (pending.status_code, pending.json()["detail"]) == (409, "7 drafts still to be decided")
    first, *others = list(review["by_rule"].values())
    await client.post(
        f"/api/aar/items/{first}/accept",
        json={"owner_team": "HR", "due_on": DUE},
        headers=idp.headers("duty"),
    )
    for item in others:
        await client.post(
            f"/api/aar/items/{item}/reject",
            json={"reason": "Not needed"},
            headers=idp.headers("duty"),
        )
    before = (await client.get(f"/api/aar/{review['id']}", headers=idp.headers("security"))).json()
    assert before["can_finalise"] is True
    response = await client.post(final, headers=idp.headers("security"))
    assert response.status_code == 200, response.text
    out = response.json()
    assert (out["status"], out["can_finalise"]) == ("FINAL", False)
    assert out["finalised_at"] is not None
    frozen = [(m["key"], m["value"]) for m in out["metrics"]]
    assert frozen == [(m["key"], m["value"]) for m in before["metrics"]]
    # Later events change nothing on a final review.
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        await s.execute(
            text(
                "INSERT INTO incident_event (tenant_id, incident_id, event_type, summary, "
                "actor_type) VALUES (current_tenant_id(), :i, 'STATUS', 'Status MONITORING → "
                "CLOSED.', 'USER')"
            ),
            {"i": out["incident_id"]},
        )
        await s.commit()
    after = (await client.get(f"/api/aar/{review['id']}", headers=idp.headers("viewer"))).json()
    assert [(m["key"], m["value"]) for m in after["metrics"]] == frozen
    assert "Status MONITORING → CLOSED." not in [t["text"] for t in after["timeline"]]
    assert (await client.post(final, headers=idp.headers("security"))).status_code == 409
    add = await client.post(
        f"/api/aar/{review['id']}/items",
        json={"finding": "F", "action": "A", "owner_team": "IT", "priority": "LOW", "due_on": DUE},
        headers=idp.headers("duty"),
    )
    assert (add.status_code, add.json()["detail"]) == (409, "AAR-2026-1042 is final")
    done = await client.post(f"/api/aar/items/{first}/done", headers=idp.headers("hom"))
    assert done.status_code == 200  # marking done still works on a final review
    assert (await _audit(idp))[-2:] == ["AAR.FINALISE", "AAR.ITEM_DONE"]


async def test_the_export_is_audited_and_the_viewer_reads(client: AsyncClient, idp: Idp) -> None:
    review = await _started(client, idp)
    viewer = await client.get(f"/api/aar/{review['id']}", headers=idp.headers("viewer"))
    assert viewer.status_code == 200
    assert (viewer.json()["can_act"], viewer.json()["can_finalise"]) == (False, False)
    exported = await client.post(f"/api/aar/{review['id']}/export", headers=idp.headers("viewer"))
    assert exported.status_code == 200
    _no_names(exported.text)
    assert (await _audit(idp))[-1] == "AAR.EXPORT"
    missing = await client.get(f"/api/aar/{uuid.uuid4()}", headers=idp.headers("viewer"))
    assert missing.status_code == 404
