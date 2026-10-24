"""Signals and incidents API (Prompt 6)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident
from app.modules.intel.service import ensure_sources
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import SOURCES, ingest, intel_tenant, signal


@pytest.fixture
async def seeded(idp: Idp) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await session.commit()
    for e in (
        signal("DATAMINR", "High", place="Nairobi CBD"),
        signal(
            "FACTAL",
            "Moderate",
            at=timedelta(seconds=30),
            where=(48.86, 2.35),
            category="Strike",
            place="Paris",
        ),
        signal("MAX", "Level 4", at=timedelta(seconds=45), where=(-1.2990, 36.8150)),
        signal("RISKLINE", "Moderate", at=timedelta(seconds=100), where=(-1.2864, 36.8172)),
        signal("RISKLINE", "Extreme", at=timedelta(seconds=110)),  # unmapped: DISCARDED
    ):
        await ingest(idp.engine, idp.tenant_id, e)
    await idp.user("viewer", [("VIEWER", None)])
    await idp.user("norole")


async def test_incidents_list_and_detail(client: AsyncClient, idp: Idp, seeded: None) -> None:
    h = idp.headers("viewer")
    year = datetime.now(UTC).year
    listed = (await client.get("/api/incidents", headers=h)).json()
    assert [(i["reference"], i["severity"]) for i in listed] == [
        (f"INC-{year}-1042", "HIGH"),  # most severe first
        (f"INC-{year}-1043", "MODERATE"),
    ]
    nbo = listed[0]
    assert (nbo["confidence"], nbo["signal_count"], nbo["category"]) == (92, 3, "CIVIL_UNREST")
    # D-19: the UI labels these "<name> (simulated)".
    assert [(src["name"], src["simulated"]) for src in nbo["sources"]] == [
        ("Dataminr", True),
        ("MAX Security", True),
        ("Riskline", True),
    ]
    assert (round(nbo["lat"], 4), round(nbo["lon"], 4)) == (-1.2841, 36.8233)
    assert nbo["mission_id"] is None  # set by exposure (Prompt 7, D-06)

    detail = (await client.get(f"/api/incidents/{nbo['id']}", headers=h)).json()
    # D-11 step 4: the "Normalised (signal)" column reads HIGH, HIGH, MODERATE.
    assert [
        (s["source_name"], s["provider_severity"], s["norm_severity"]) for s in detail["signals"]
    ] == [
        ("Dataminr", "High", "HIGH"),
        ("MAX Security", "Level 4", "HIGH"),
        ("Riskline", "Moderate", "MODERATE"),
    ]
    assert [e["event_type"] for e in detail["timeline"]] == ["SIGNAL", "FUSED", "FUSED"]
    assert detail["timeline"][-1]["data"]["confidence"] == 92

    closed = (await client.get("/api/incidents?status=CLOSED", headers=h)).json()
    assert closed == []


async def test_signals_feed_and_status_filter(client: AsyncClient, idp: Idp, seeded: None) -> None:
    h = idp.headers("viewer")
    feed = (await client.get("/api/signals", headers=h)).json()
    assert len(feed) == 5
    assert feed[0]["norm_status"] == "DISCARDED"  # newest first
    fused = (await client.get("/api/signals?status=FUSED", headers=h)).json()
    assert len(fused) == 4
    assert {s["incident_reference"] for s in fused} == {
        f"INC-{datetime.now(UTC).year}-1042",
        f"INC-{datetime.now(UTC).year}-1043",
    }
    discarded = (await client.get("/api/signals?status=DISCARDED", headers=h)).json()
    assert [(s["source_code"], s["incident_id"]) for s in discarded] == [("RISKLINE", None)]
    bad = await client.get("/api/signals?status=WHATEVER", headers=h)
    assert bad.status_code == 422


async def test_reading_needs_a_role(client: AsyncClient, idp: Idp, seeded: None) -> None:
    for path in ("/api/signals", "/api/incidents", f"/api/incidents/{uuid.uuid4()}"):
        assert (await client.get(path, headers=idp.headers("norole"))).status_code == 403
        assert (await client.get(path)).status_code == 401


async def test_unknown_or_other_tenants_incident_is_404(
    client: AsyncClient, idp: Idp, db: DbUrls, seeded: None
) -> None:
    other = await intel_tenant(db, idp.engine)
    result = await ingest(idp.engine, other, signal("DATAMINR", "High"))
    assert result.fused is not None
    h = idp.headers("viewer")
    hidden = await client.get(f"/api/incidents/{result.fused.incident_id}", headers=h)
    assert hidden.status_code == 404
    assert (await client.get(f"/api/incidents/{uuid.uuid4()}", headers=h)).status_code == 404
    assert len((await client.get("/api/incidents", headers=h)).json()) == 2


# --- INC-07: status and notes ------------------------------------------------------------


@pytest.fixture
async def writable(idp: Idp, seeded: None) -> tuple[uuid.UUID, uuid.UUID, ListPublisher]:
    """The Nairobi incident, with mission NBO (as exposure would set it)."""
    nbo, cai = await idp.mission("NBO"), await idp.mission("CAI")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "admin": [("ADMIN", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        incident = await session.scalar(select(Incident).where(Incident.category == "CIVIL_UNREST"))
        assert incident is not None
        incident.mission_id = nbo
        await session.commit()
        incident_id = incident.id
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return incident_id, nbo, publisher


async def test_status_changes_are_role_and_mission_scoped(
    client: AsyncClient, idp: Idp, writable: tuple[uuid.UUID, uuid.UUID, ListPublisher]
) -> None:
    incident_id, _nbo, publisher = writable
    url = f"/api/incidents/{incident_id}/status"
    for sub in ("viewer", "admin", "consular", "hom.cai", "norole"):
        response = await client.patch(url, json={"status": "MONITORING"}, headers=idp.headers(sub))
        assert response.status_code == 403, sub

    response = await client.patch(
        url, json={"status": "MONITORING"}, headers=idp.headers("hom.nbo")
    )
    assert response.status_code == 200
    assert response.json()["event_type"] == "STATUS"
    again = await client.patch(url, json={"status": "MONITORING"}, headers=idp.headers("duty"))
    assert again.status_code == 409
    closed = await client.patch(url, json={"status": "CLOSED"}, headers=idp.headers("duty"))
    assert closed.status_code == 200
    bad = await client.patch(url, json={"status": "DONE"}, headers=idp.headers("duty"))
    assert bad.status_code == 422

    async with tenant_session(idp.tenant_id, idp.engine) as session:
        incident = await session.get_one(Incident, incident_id)
        assert (incident.status, incident.closed_at is not None) == ("CLOSED", True)
        actions = await session.scalars(
            select(AuditLog.details)
            .where(AuditLog.action == "INCIDENT.STATUS_CHANGE")
            .order_by(AuditLog.chain_seq)
        )
        assert [(d["from"], d["to"]) for d in actions] == [
            ("ACTIVE", "MONITORING"),
            ("MONITORING", "CLOSED"),
        ]
    reopened = await client.patch(url, json={"status": "ACTIVE"}, headers=idp.headers("duty"))
    assert reopened.status_code == 200
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert (await session.get_one(Incident, incident_id)).closed_at is None
    assert [(e.type, e.payload["status"]) for e in publisher.events] == [
        ("INCIDENT_UPDATED", "MONITORING"),
        ("INCIDENT_UPDATED", "CLOSED"),
        ("INCIDENT_UPDATED", "ACTIVE"),
    ]
    detail = (
        await client.get(f"/api/incidents/{incident_id}", headers=idp.headers("viewer"))
    ).json()
    assert [e["event_type"] for e in detail["timeline"]][-3:] == ["STATUS"] * 3
    assert detail["timeline"][-3]["actor_type"] == "USER"


async def test_without_a_mission_only_unscoped_roles_may_act(
    client: AsyncClient, idp: Idp, writable: tuple[uuid.UUID, uuid.UUID, ListPublisher]
) -> None:
    incident_id, _nbo, _ = writable
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Incident).values(mission_id=None))
        await session.commit()
    url = f"/api/incidents/{incident_id}/status"
    body = {"status": "MONITORING"}
    assert (await client.patch(url, json=body, headers=idp.headers("hom.nbo"))).status_code == 403
    assert (await client.patch(url, json=body, headers=idp.headers("duty"))).status_code == 200


async def test_notes(
    client: AsyncClient, idp: Idp, writable: tuple[uuid.UUID, uuid.UUID, ListPublisher]
) -> None:
    incident_id, _nbo, publisher = writable
    url = f"/api/incidents/{incident_id}/notes"
    assert (
        await client.post(url, json={"text": "x"}, headers=idp.headers("viewer"))
    ).status_code == 403
    assert (
        await client.post(url, json={"text": ""}, headers=idp.headers("duty"))
    ).status_code == 422
    response = await client.post(
        url, json={"text": "Embassy staff told to stay indoors."}, headers=idp.headers("consular")
    )
    assert response.status_code == 201
    note = response.json()
    assert (note["event_type"], note["summary"], note["actor_type"]) == (
        "NOTE",
        "Embassy staff told to stay indoors.",
        "USER",
    )
    missing = await client.post(
        f"/api/incidents/{uuid.uuid4()}/notes", json={"text": "x"}, headers=idp.headers("duty")
    )
    assert missing.status_code == 404
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        audit_row = await session.scalar(
            select(AuditLog).where(AuditLog.action == "INCIDENT.NOTE_ADD")
        )
    assert audit_row is not None
    assert audit_row.details["incident_event_id"] == note["id"]
    assert [e.type for e in publisher.events] == ["INCIDENT_NOTE_ADDED"]
