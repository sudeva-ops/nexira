"""Map annotations API (ANN-01..ANN-06; D-52; plan-pilot-map §2) on real PostgreSQL, as
nexira_api: every role reads; the annotating roles add, edit and withdraw within their mission
scope (§115 Q2, G-2); the author's role and never a name (ANN-04); each change audited, on a
linked incident's timeline (the label there, the kind only in AAR-02 and the replay: G-4) and
published as ANNOTATION_UPDATED."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.core.realtime import FORWARDED
from app.core.security import CurrentUser
from app.main import app
from app.modules.annotations import service
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

NBO = "'SRID=4326;POINT(36.8219 -1.2921)'"
CAI = "'SRID=4326;POINT(31.2357 30.0444)'"
CHECKPOINT: dict[str, Any] = {
    "kind": "MARK",
    "symbol": "CHECKPOINT",
    "shape": {"type": "Point", "coordinates": [36.817, -1.283]},
    "label": "Checkpoint · Uhuru Highway",
}
AREA: dict[str, Any] = {
    "kind": "AREA",
    "shape": {
        "type": "Polygon",
        "coordinates": [[[36.81, -1.28], [36.83, -1.28], [36.83, -1.30]]],  # closed by the API
    },
    "label": "Avoid: crowd at the CBD",
}
OCEAN: dict[str, Any] = {**CHECKPOINT, "shape": {"type": "Point", "coordinates": [-30.0, 0.0]}}
NAMES = ("User duty", "User hom", "User security", "duty@demo.invalid")


@pytest.fixture
async def publisher(client: AsyncClient) -> AsyncIterator[ListPublisher]:
    published = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: published
    yield published
    app.dependency_overrides.pop(get_publisher, None)


async def _setup(idp: Idp) -> dict[str, Any]:
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        nbo = await s.scalar(
            text(
                "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
                f"(current_tenant_id(), 'NBO', 'Nairobi', 'KE', {NBO}) RETURNING id"
            )
        )
        cai = await s.scalar(
            text(
                "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
                f"(current_tenant_id(), 'CAI', 'Cairo', 'EG', {CAI}) RETURNING id"
            )
        )
        incident = await s.scalar(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, mission_id, location) VALUES (current_tenant_id(), "
                f"'INC-2026-1042', 'Unrest', 'CIVIL_UNREST', 'HIGH', 'HIGH', :m, {NBO}) "
                "RETURNING id"
            ),
            {"m": nbo},
        )
        await s.commit()
    users = {}
    for sub, role, mission in (
        ("duty", "DUTY_OFFICER", None),
        ("security", "SECURITY_OFFICER", None),
        ("hq", "HQ_CRISIS_DIRECTOR", None),
        ("hom", "HEAD_OF_MISSION", nbo),
        ("hom-cairo", "HEAD_OF_MISSION", cai),
        ("consular", "CONSULAR_OFFICER", None),
        ("travel", "TRAVEL_DESK", None),
        ("viewer", "VIEWER", None),
    ):
        users[sub] = await idp.user(sub, [(role, mission)])
    return {"nbo": nbo, "cai": cai, "incident": incident, "users": users}


async def _add(client: AsyncClient, idp: Idp, who: str, body: dict[str, Any]) -> Any:
    return await client.post("/api/annotations", json=body, headers=idp.headers(who))


async def _rows(idp: Idp, sql: str, **params: Any) -> list[Any]:
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        return list(await s.execute(text(sql), params))


def _no_names(body: str) -> None:
    assert not [name for name in NAMES if name in body]


async def test_a_duty_officer_marks_a_checkpoint_on_the_incident(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    w = await _setup(idp)
    response = await _add(client, idp, "duty", {**CHECKPOINT, "incident_id": str(w["incident"])})
    assert response.status_code == 201, response.text
    added = response.json()
    assert (added["role"], added["mission_code"], added["incident_reference"]) == (
        "Duty Officer",
        "NBO",
        "INC-2026-1042",
    )
    assert (added["status"], added["can_edit"], added["updated_at"]) == ("ACTIVE", True, None)
    assert added["shape"] == {"type": "Point", "coordinates": [36.817, -1.283]}
    _no_names(response.text)
    assert [(e.type, e.payload) for e in publisher.events] == [
        (
            "ANNOTATION_UPDATED",
            {"annotation_id": added["id"], "incident_id": str(w["incident"])},
        )
    ]
    assert "ANNOTATION_UPDATED" in FORWARDED
    audit = await _rows(
        idp,
        "SELECT action, actor_id, entity_type, entity_id, details FROM audit_log "
        "WHERE action LIKE 'ANNOTATION.%'",
    )
    assert [(a.action, a.actor_id, a.entity_type, a.entity_id) for a in audit] == [
        ("ANNOTATION.ADD", str(w["users"]["duty"]), "map_annotation", added["id"])
    ]
    assert audit[0].details["label"] == CHECKPOINT["label"]
    events = await _rows(
        idp,
        "SELECT summary, actor_type, data FROM incident_event WHERE event_type = 'ANNOTATION'",
    )
    assert [(e.summary, e.actor_type, e.data["action"]) for e in events] == [
        ("Annotation added: Checkpoint · Checkpoint · Uhuru Highway.", "USER", "ADD")
    ]


async def test_every_role_reads_only_the_annotating_roles_add(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    w = await _setup(idp)
    assert (await _add(client, idp, "security", CHECKPOINT)).status_code == 201
    assert (await _add(client, idp, "hq", AREA)).status_code == 201
    for who in ("viewer", "consular", "travel"):
        assert (await _add(client, idp, who, CHECKPOINT)).status_code == 403, who
        listed = (await client.get("/api/annotations", headers=idp.headers(who))).json()
        assert listed["can_add"] is False
        assert [(a["role"], a["can_edit"]) for a in listed["annotations"]] == [
            ("Security Officer", False),
            ("HQ Crisis Director", False),
        ]
    assert (await client.get("/api/annotations", headers=idp.headers("duty"))).json()["can_add"]
    on_incident = await client.get(
        "/api/annotations",
        params={"incident_id": str(w["incident"])},
        headers=idp.headers("viewer"),
    )
    assert on_incident.json()["annotations"] == []


async def test_a_head_of_mission_annotates_only_their_mission(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    """Plan G-2: near Nairobi the nearest mission is NBO (within 300 km); mid-ocean there is
    none, so the annotation is tenant-wide and needs a role for every mission."""
    await _setup(idp)
    near = await _add(client, idp, "hom", AREA)
    assert near.status_code == 201, near.text
    assert (near.json()["mission_code"], near.json()["role"]) == ("NBO", "Head of Mission")
    assert near.json()["shape"]["coordinates"][0][-1] == [36.81, -1.28]  # closed
    assert (await _add(client, idp, "hom-cairo", AREA)).status_code == 403
    assert (await _add(client, idp, "hom", OCEAN)).status_code == 403
    ocean = await _add(client, idp, "duty", OCEAN)
    assert (ocean.status_code, ocean.json()["mission_code"]) == (201, None)
    annotation = near.json()["id"]
    for request in (
        client.patch(
            f"/api/annotations/{annotation}",
            json={"label": "Mine now"},
            headers=idp.headers("hom-cairo"),
        ),
        client.post(
            f"/api/annotations/{annotation}/withdraw",
            json={"reason": "Not yours"},
            headers=idp.headers("hom-cairo"),
        ),
    ):
        assert (await request).status_code == 403
    cairo = (await client.get("/api/annotations", headers=idp.headers("hom-cairo"))).json()
    assert [a["can_edit"] for a in cairo["annotations"]] == [False, False]
    assert cairo["can_add"] is True  # in Cairo


async def test_it_is_edited_then_withdrawn_once_and_kept(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    w = await _setup(idp)
    annotation = await _add(client, idp, "duty", {**AREA, "incident_id": str(w["incident"])})
    annotation_id = annotation.json()["id"]
    url = f"/api/annotations/{annotation_id}"
    later = (datetime.now(UTC) + timedelta(hours=6)).isoformat()
    edited = await client.patch(
        url,
        json={"label": "Avoid: crowd moving north", "note": "Police line", "ends_at": later},
        headers=idp.headers("hom"),  # anyone who may annotate in that mission (ANN-03)
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["label"], edited.json()["note"]) == (
        "Avoid: crowd moving north",
        "Police line",
    )
    assert edited.json()["updated_at"] is not None
    assert edited.json()["role"] == "Duty Officer"  # the author's, not the editor's
    for body, status in (
        ({"shape": CHECKPOINT["shape"]}, 422),  # an area stays an area
        ({"ends_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}, 422),
        ({"label": None}, 422),
        ({}, 422),
    ):
        assert (
            await client.patch(url, json=body, headers=idp.headers("duty"))
        ).status_code == status
    redrawn = await client.patch(
        url,
        json={
            "shape": {
                "type": "Polygon",
                "coordinates": [[[36.8, -1.2], [36.9, -1.2], [36.9, -1.3]]],
            }
        },
        headers=idp.headers("duty"),
    )
    assert redrawn.json()["shape"]["coordinates"][0][0] == [36.8, -1.2]
    assert (
        await client.post(f"{url}/withdraw", json={"reason": ""}, headers=idp.headers("duty"))
    ).status_code == 422
    withdrawn = await client.post(
        f"{url}/withdraw", json={"reason": "Crowd dispersed"}, headers=idp.headers("security")
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert (
        withdrawn.json()["status"],
        withdrawn.json()["reason"],
        withdrawn.json()["can_edit"],
    ) == (
        "WITHDRAWN",
        "Crowd dispersed",
        False,
    )
    again = await client.post(f"{url}/withdraw", json={"reason": "x"}, headers=idp.headers("duty"))
    assert (again.status_code, again.json()["detail"]) == (409, "The annotation was withdrawn")
    assert (
        await client.patch(url, json={"label": "x"}, headers=idp.headers("duty"))
    ).status_code == 409
    listed = (await client.get("/api/annotations", headers=idp.headers("duty"))).json()
    assert listed["annotations"] == []
    actions = [
        a.action
        for a in await _rows(
            idp, "SELECT action FROM audit_log WHERE action LIKE 'ANNOTATION.%' ORDER BY id"
        )
    ]
    assert actions == [
        "ANNOTATION.ADD",
        "ANNOTATION.EDIT",
        "ANNOTATION.EDIT",
        "ANNOTATION.WITHDRAW",
    ]
    summaries = [
        e.summary
        for e in await _rows(
            idp, "SELECT summary FROM incident_event WHERE event_type = 'ANNOTATION' ORDER BY id"
        )
    ]
    assert (
        summaries[-1] == "Annotation withdrawn: Area · Avoid: crowd moving north (Crowd dispersed)."
    )
    assert len(publisher.events) == 4
    missing = await client.patch(
        f"/api/annotations/{uuid.uuid4()}", json={"label": "x"}, headers=idp.headers("duty")
    )
    assert missing.status_code == 404


async def test_the_shape_is_checked_before_it_reaches_the_database(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    await _setup(idp)
    for body in (
        {**CHECKPOINT, "symbol": None},  # a mark has a symbol
        {**AREA, "symbol": "NOTE"},  # an area has none
        {**CHECKPOINT, "shape": AREA["shape"]},  # a mark is a point
        {**CHECKPOINT, "shape": {"type": "Point", "coordinates": [200, 0]}},  # on the Earth
        {
            "kind": "LINE",
            "shape": {"type": "LineString", "coordinates": [[36.8, -1.2]]},
            "label": "L",
        },
        {**AREA, "shape": {"type": "Polygon", "coordinates": [[[36.8, -1.2], [36.9, -1.2]]]}},
        {**CHECKPOINT, "label": "x" * 81},
        {**CHECKPOINT, "ends_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
    ):
        assert (await _add(client, idp, "duty", body)).status_code == 422, body
    line = {
        "kind": "LINE",
        "shape": {
            "type": "LineString",
            "coordinates": [[36.8, -1.2], [36.85, -1.25], [36.9, -1.3]],
        },
        "label": "Closed: Moi Avenue",
    }
    assert (await _add(client, idp, "duty", line)).status_code == 201
    unknown = await _add(client, idp, "duty", {**CHECKPOINT, "incident_id": str(uuid.uuid4())})
    assert unknown.status_code == 404
    assert publisher.events
    assert len(publisher.events) == 1


async def test_an_ended_annotation_leaves_the_map_but_stays_on_record(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    w = await _setup(idp)
    ends = datetime.now(UTC) + timedelta(hours=1)
    await _add(client, idp, "duty", {**CHECKPOINT, "ends_at": ends.isoformat()})
    duty = CurrentUser(
        id=w["users"]["duty"],
        tenant_id=idp.tenant_id,
        external_id="duty",
        email="duty@demo.invalid",
        display_name="User duty",
    )
    async with tenant_session(idp.tenant_id, idp.engine) as s:
        now = await service.listed(s, duty, datetime.now(UTC), None)
        after = await service.listed(s, duty, ends + timedelta(seconds=1), None)
    assert [a.label for a in now.annotations] == [CHECKPOINT["label"]]
    assert after.annotations == []
    assert len(await _rows(idp, "SELECT id FROM map_annotation")) == 1


async def test_the_replay_and_the_review_show_the_kind_never_the_label(
    client: AsyncClient, idp: Idp, publisher: ListPublisher
) -> None:
    w = await _setup(idp)
    incident = str(w["incident"])
    mark = (await _add(client, idp, "duty", {**CHECKPOINT, "incident_id": incident})).json()
    await _add(client, idp, "duty", {**AREA, "incident_id": incident})
    await client.post(
        f"/api/annotations/{mark['id']}/withdraw",
        json={"reason": "Cleared"},
        headers=idp.headers("duty"),
    )
    response = await client.get(f"/api/incidents/{incident}/replay", headers=idp.headers("viewer"))
    assert response.status_code == 200, response.text
    replay = response.json()
    assert [(a["kind"], a["symbol"], a["until"] is not None) for a in replay["annotations"]] == [
        ("MARK", "CHECKPOINT", True),
        ("AREA", None, False),
    ]
    lines = [(e["source"], e["text"]) for e in replay["timeline"] if e["source"] == "ANNOTATION"]
    assert lines == [
        ("ANNOTATION", "Map annotation added: Checkpoint."),
        ("ANNOTATION", "Map annotation added: Area."),
        ("ANNOTATION", "Map annotation withdrawn: Checkpoint."),
    ]
    for free_text in (CHECKPOINT["label"], AREA["label"], "Cleared"):
        assert free_text not in response.text
    _no_names(response.text)
