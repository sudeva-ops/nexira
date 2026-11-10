"""Incident Replay (RPL-01, RPL-04, RPL-05; D-51; docs/plan-pilot-rpl.md §2): the payload for one
incident, its window (G-1, G-2: A), the check-in as the Safety Check-in counts it (G-3), trips
counted without restricted ones (G-4), the SITE entries' sensor (G-8), the exercise label, and
no person's name or id anywhere. Against real PostgreSQL, as nexira_api, on the check-in
tests' Nairobi world."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.db import tenant_session
from app.modules.travel.service import ensure_trip
from app.tests.auth_helpers import Idp
from app.tests.test_checkin import PEOPLE, World, answer, make_world


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    w = await make_world(idp)
    assert await answer(client, idp, w, "Peter", "SAFE") == 201
    assert await answer(client, idp, w, "Grace", "NEED_HELP") == 201
    return w


async def replay(client: AsyncClient, idp: Idp, w: World, sub: str = "duty") -> dict[str, Any]:
    response = await client.get(f"/api/incidents/{w.incident_id}/replay", headers=idp.headers(sub))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def test_the_payload_holds_the_record(client: AsyncClient, idp: Idp, world: World) -> None:
    body = await replay(client, idp, world)
    assert body["incident"]["status"] == "ACTIVE"
    assert body["incident"]["exercise"] is False
    assert len(body["signals"]) == 1
    assert body["window"]["start"] == body["signals"][0]["received_at"]  # G-1
    assert at(body["window"]["end"]) > datetime.now(UTC) - timedelta(seconds=30)  # ACTIVE: now
    assert len(body["people"]) == len(PEOPLE)
    assert [p["index"] for p in body["people"]] == list(range(len(PEOPLE)))
    assert all(p["asked"] for p in body["people"])
    assert sum(p["personnel"] for p in body["people"]) == 3
    statuses = sorted(a["status"] for p in body["people"] for a in p["answers"])
    assert statuses == ["NEED_HELP", "SAFE"]
    first_exposure = min(at(p["exposed_at"]) for p in body["people"])
    assert at(body["incident"]["opened_at"]) <= first_exposure
    checkin = body["checkin"]
    assert checkin["reference"] == world.reference
    assert len(checkin["personnel"]) == 3
    tally = checkin["tally_end"]
    counts = (tally["recipients"], tally["safe"], tally["need_help"], tally["pending"])
    assert counts == (3, 1, 1, 1)
    summary = (
        await client.get(f"/api/checkin/{world.campaign_id}/summary", headers=idp.headers("duty"))
    ).json()["personnel"]
    assert tally == summary  # RPL-04: the end agrees with the Safety Check-in screen
    sources = {e["source"] for e in body["timeline"]}
    assert {"INCIDENT", "NOTIFICATION"} <= sources


async def test_no_name_or_id_of_a_person(client: AsyncClient, idp: Idp, world: World) -> None:
    for sub in ("duty", "viewer"):
        payload = json.dumps(await replay(client, idp, world, sub))
        for name, _ in PEOPLE:
            assert name not in payload
        for person in world.ids.values():
            assert str(person) not in payload


async def test_every_reader_and_nobody_else(client: AsyncClient, idp: Idp, world: World) -> None:
    url = f"/api/incidents/{world.incident_id}/replay"
    assert (await client.get(url, headers=idp.headers("viewer"))).status_code == 200
    assert (await client.get(url)).status_code == 401
    missing = await client.get(f"/api/incidents/{uuid.uuid4()}/replay", headers=idp.headers("duty"))
    assert missing.status_code == 404


async def test_a_monitoring_incident_ends_at_its_last_record(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    """G-2 (A): not now, but the last thing the record holds."""
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        last = await session.scalar(
            text("SELECT max(responded_at) FROM checkin_response WHERE campaign_id = :c"),
            {"c": world.campaign_id},
        )
        await session.execute(
            text("UPDATE incident SET status = 'MONITORING' WHERE id = :i"),
            {"i": world.incident_id},
        )
        await session.commit()
    body = await replay(client, idp, world)
    timeline_end = max(at(e["at"]) for e in body["timeline"])
    assert last is not None
    assert at(body["window"]["end"]) == max(last, timeline_end)


async def test_trips_are_counted_without_restricted_ones(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    """G-4, D-33."""
    today = datetime.now(UTC).date()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for restricted in (False, True):
            trip = uuid.uuid4()
            await ensure_trip(
                session,
                trip_id=trip,
                reference=f"TRP-{trip.hex[:6]}",
                purpose="Consultations",
                origin="Abu Dhabi",
                destination="Nairobi",
                destination_country="KE",
                starts_on=today,
                ends_on=today + timedelta(days=3),
                traveller_ids=[world.ids["Hana"]],
                risk_level="LOW",
                approval_status="APPROVED",
                restricted=restricted,
            )
            await session.execute(
                text(
                    "INSERT INTO incident_exposure (tenant_id, incident_id, subject_type, "
                    "subject_id, distance_m, confidence) VALUES (:t, :i, 'TRIP', :s, 100, 90)"
                ),
                {"t": idp.tenant_id, "i": world.incident_id, "s": trip},
            )
        await session.commit()
    assert (await replay(client, idp, world))["trips"] == 1


async def test_a_site_entry_carries_its_sensor(client: AsyncClient, idp: Idp, world: World) -> None:
    """G-8: the screen opens that camera (TWN-10)."""
    site = str(uuid.uuid4())
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO incident_event (tenant_id, incident_id, event_type, summary, "
                "actor_type, data) VALUES (:t, :i, 'SITE', 'Embassy · Camera 7: OFFLINE.', "
                "'SYSTEM', CAST(:d AS jsonb))"
            ),
            {
                "t": idp.tenant_id,
                "i": world.incident_id,
                "d": json.dumps({"site_id": site, "sensor": "CAM-07", "status": "OFFLINE"}),
            },
        )
        await session.commit()
    entries = [e for e in (await replay(client, idp, world))["timeline"] if e["source"] == "SITE"]
    assert [(e["site_id"], e["sensor"]) for e in entries] == [(site, "CAM-07")]


async def test_an_exercise_incident_is_labelled(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    """The marker the player adds to an exercise run's signals (EXR, plan-pilot-exr §4)."""
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "UPDATE raw_signal SET payload = payload || CAST(:m AS jsonb) WHERE id IN "
                "(SELECT signal_id FROM incident_signal WHERE incident_id = :i)"
            ),
            {"m": json.dumps({"exercise_run_id": str(uuid.uuid4())}), "i": world.incident_id},
        )
        await session.commit()
    assert (await replay(client, idp, world))["incident"]["exercise"] is True
