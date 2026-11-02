"""VIP & Delegation Protection (VIP-01..06; D-42; docs/plan-pilot-vip.md): who sees a visit and
that nobody else learns one exists (§7); segment risk from incidents, weather, attendees and
movement, with reasons and the recommendation (§3); the detail from Fleet, Health and
Partners (§4); the checklist; start, progress and cancel (§5); two-person changes through
approvals.py (§6); permissions; audit without venues or times. Against real PostgreSQL, as
nexira_api."""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event
from app.modules.audit.models import AuditLog
from app.modules.documents.service import today_utc
from app.modules.fleet import service as fleet
from app.modules.fleet.service import AssetIn
from app.modules.vip import consumer
from app.modules.vip import service as vip
from app.tests.auth_helpers import Idp

# Addis Ababa (plan §2, G-4): the city venues, Bole airport, and the industrial park about
# 11 km east of the airport; the rally 1.2 km north of the park.
MISSION = (9.0300, 38.7600)
AIRPORT = (8.9779, 38.7993)
HOTEL = (9.0200, 38.7560)
MINISTRY = (9.0330, 38.7630)
CONFERENCE = (9.0130, 38.7660)
PARK = (8.9779, 38.9000)
RALLY = (8.98869, 38.9000)
HOSPITAL_A = (9.0310, 38.7610)
HOSPITAL_B = (9.0500, 38.7400)
CAIRO = (30.0444, 31.2357)
VENUES = ("Bole", "Hotel", "Ministry", "Conference", "Industrial")

READERS = ("security", "hq", "duty", "hom.add")
OUTSIDERS = ("viewer", "travel", "hom.cai", "consular")


def pt(lat_lon: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({lat_lon[1]} {lat_lon[0]})"


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), UTC)


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    add: uuid.UUID
    cai: uuid.UUID
    visit: uuid.UUID
    reference: str
    users: dict[str, uuid.UUID]
    day: date  # the visit's first day

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def send(self, who: str, method: str, url: str, body: Any = None) -> Response:
        return await self.client.request(method, url, json=body, headers=self.idp.headers(who))

    async def ok(self, who: str, method: str, url: str, body: Any = None) -> Any:
        response = await self.send(who, method, url, body)
        assert response.status_code == 200, response.text
        return response.json()

    async def get(self, who: str = "security") -> Any:
        return await self.ok(who, "GET", f"/api/vip/visits/{self.visit}")

    async def segment(self, seq: int, who: str = "security") -> Any:
        return next(s for s in (await self.get(who))["segments"] if s["seq"] == seq)

    async def risks(self) -> list[str]:
        return [s["risk"] for s in (await self.get())["segments"]]

    async def item(self, label: str) -> Any:
        return next(c for c in (await self.get())["checklist"] if c["label"] == label)

    async def permissions(self, who: str) -> Any:
        return await self.ok(
            who, "GET", f"/api/me/permissions?entity_type=vip_visit&entity_id={self.visit}"
        )

    async def start(self, who: str = "security") -> Any:
        return await self.ok(who, "POST", f"/api/vip/visits/{self.visit}/start")

    async def progress(self, seq: int, who: str = "security") -> Response:
        segment = await self.segment(seq)
        return await self.send(who, "POST", f"/api/vip/segments/{segment['id']}/progress")

    async def propose(self, seq: int, who: str = "security", **body: Any) -> Response:
        segment = await self.segment(seq)
        payload = {"reason": "Rally planned near the venue", **body}
        return await self.send(who, "POST", f"/api/vip/segments/{segment['id']}/changes", payload)

    async def decide(self, change_id: str, who: str, verb: str = "approve") -> Response:
        return await self.send(who, "POST", f"/api/vip/changes/{change_id}/{verb}", {})

    async def incident(
        self, reference: str, where: tuple[float, float], radius_m: int = 5000
    ) -> uuid.UUID:
        found: uuid.UUID = (
            await self.sql(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, impact_radius_m, mission_id, status) VALUES "
                "(current_tenant_id(), :r, 'Planned rally', 'CIVIL_UNREST', 'MODERATE', "
                "'MODERATE', :pt, :radius, :m, 'ACTIVE') RETURNING id",
                r=reference,
                pt=pt(where),
                radius=radius_m,
                m=self.add,
            )
        ).scalar_one()
        return found

    async def audit(self) -> list[AuditLog]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog).where(AuditLog.action.like("VIP.%")).order_by(AuditLog.id)
                )
            )


async def _mission(idp: Idp, code: str, city: str, country: str, where: Any) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :city, :cc, :pt)"
            ),
            {"id": mission_id, "code": code, "city": city, "cc": country, "pt": pt(where)},
        )
        await session.commit()
    return mission_id


async def add_visit(
    idp: Idp, mission: uuid.UUID, reference: str, day: date, done_by: uuid.UUID
) -> uuid.UUID:
    """The design's visit (plan §2): six segments, the detail and four checklist items."""
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        trip = await session.scalar(
            text(
                "INSERT INTO trip (tenant_id, reference, origin, destination, starts_on, "
                "ends_on, restricted) VALUES (current_tenant_id(), :r, 'Abu Dhabi', "
                "'Addis Ababa', :d, :e, true) RETURNING id"
            ),
            {"r": f"TRP-{uuid.uuid4().int % 10_000:04d}", "d": day, "e": day + timedelta(2)},
        )
        detail = {
            "team_lead": "Close-protection lead (sample)",
            "advance_team": "3 officers",
            "team_size": 8,
            "medic": True,
            "vehicles": ["VH-11", "VH-12"],
            "safe_havens": ["Embassy", "Hotel safe floor"],
        }
        visit: uuid.UUID = await session.scalar(
            text(
                "INSERT INTO vip_visit (tenant_id, reference, title, mission_id, principal_role, "
                "starts_on, ends_on, trip_id, detail) VALUES (current_tenant_id(), :r, "
                "'Minister''s visit to Addis Ababa', :m, 'Minister of Foreign Affairs', :d, :e, "
                ":t, CAST(:detail AS jsonb)) RETURNING id"
            ),
            {
                "r": reference,
                "m": mission,
                "d": day,
                "e": day + timedelta(2),
                "t": trip,
                "detail": json.dumps(detail),
            },
        )
        day2, day3 = day + timedelta(1), day + timedelta(2)
        segments = [
            (
                "ARRIVAL",
                "Arrival · Bole Intl. Airport",
                "Bole airport",
                AIRPORT,
                at(day, 6, 30),
                None,
                None,
            ),
            (
                "MOTORCADE",
                "Motorcade · Airport → Hotel",
                "Hotel",
                HOTEL,
                at(day, 6, 50),
                at(day, 7, 4),
                None,
            ),
            ("MEETING", "Bilateral meeting", "Ministry", MINISTRY, at(day, 8), at(day, 9), None),
            (
                "EVENT",
                "Business forum",
                "Conference centre",
                CONFERENCE,
                at(day, 11),
                at(day, 13),
                600,
            ),
            (
                "SITE_VISIT",
                "Site visit · Industrial park",
                "Industrial park",
                PARK,
                at(day2, 7),
                at(day2, 9),
                None,
            ),
            ("DEPARTURE", "Departure", "Bole airport", AIRPORT, at(day3, 13), None, None),
        ]
        for seq, (kind, title, venue, where, starts, ends, attendees) in enumerate(segments, 1):
            await session.execute(
                text(
                    "INSERT INTO vip_segment (tenant_id, visit_id, seq, kind, title, venue_name, "
                    "venue_location, starts_at, ends_at, attendees) VALUES (current_tenant_id(), "
                    ":v, :seq, :kind, :title, :venue, :pt, :s, :e, :a)"
                ),
                {
                    "v": visit,
                    "seq": seq,
                    "kind": kind,
                    "title": title,
                    "venue": venue,
                    "pt": pt(where),
                    "s": starts,
                    "e": ends,
                    "a": attendees,
                },
            )
        for label, done in (
            ("Threat assessment issued", True),
            ("Host-nation security liaison confirmed", True),
            ("Hospital & evacuation plan", True),
            ("Industrial park venue survey", False),
        ):
            await session.execute(
                text(
                    "INSERT INTO vip_checklist_item (tenant_id, visit_id, label, due_on, done_by) "
                    "VALUES (current_tenant_id(), :v, :l, :d, :by)"
                ),
                {"v": visit, "l": label, "d": day - timedelta(1), "by": done_by if done else None},
            )
        await session.commit()
    return visit


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    add = await _mission(idp, "ADD", "Addis Ababa", "ET", MISSION)
    cai = await _mission(idp, "CAI", "Cairo", "EG", CAIRO)
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "security": [("SECURITY_OFFICER", None)],
        "hq": [("HQ_CRISIS_DIRECTOR", None)],
        "duty": [("DUTY_OFFICER", None)],
        "hom.add": [("HEAD_OF_MISSION", add)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "viewer": [("VIEWER", None)],
        "travel": [("TRAVEL_DESK", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "both": [("SECURITY_OFFICER", None), ("HQ_CRISIS_DIRECTOR", None)],
        "admin": [("ADMIN", None)],
    }
    users = {sub: await idp.user(sub, roles) for sub, roles in grants.items()}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for name, where in (("Sample Hospital A", HOSPITAL_A), ("Sample Hospital B", HOSPITAL_B)):
            await session.execute(
                text(
                    "INSERT INTO medical_facility (tenant_id, mission_id, name, location, "
                    "capabilities, open_24_7) VALUES (current_tenant_id(), :m, :n, :pt, "
                    "ARRAY['EMERGENCY'], true)"
                ),
                {"m": add, "n": name, "pt": pt(where)},
            )
        await session.execute(
            text(
                "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
                "VALUES (current_tenant_id(), 'KES', 'Kestrel Medical (simulated)', "
                "ARRAY['MEDICAL'], ARRAY['ET','KE'], 30)"
            )
        )
        lat, lon = MISSION
        suv = ("VEHICLE", "Armoured SUV (B6)")
        await fleet.ensure_assets(
            session,
            [
                AssetIn(add, "VH-11", *suv, lat, lon, "Embassy garage", 80, armoured=True, seats=4),
                AssetIn(
                    add,
                    "VH-12",
                    *suv,
                    lat,
                    lon,
                    "Workshop",
                    60,
                    armoured=True,
                    seats=4,
                    status="MAINTENANCE",
                    status_reason="Brakes",
                ),
            ],
            today_utc(),
        )
        await session.commit()
    day = today_utc() + timedelta(4)
    visit = await add_visit(idp, add, "VV-2026-031", day, users["security"])
    return World(idp, client, add, cai, visit, "VV-2026-031", users, day)


# --- who sees a visit (VIP-06, §7) --------------------------------------------------------------


async def test_the_protection_roles_see_the_visit(world: World) -> None:
    for who in READERS:
        assert await world.ok(who, "GET", "/api/vip/access") == {"visible": True}, who
        visits = await world.ok(who, "GET", "/api/vip/visits")
        assert [(v["reference"], v["status"], v["risk"]) for v in visits] == [
            ("VV-2026-031", "PLANNED", "MODERATE")
        ], who
        visit = await world.get(who)
        assert [s["kind"] for s in visit["segments"]] == [
            "ARRIVAL", "MOTORCADE", "MEETING", "EVENT", "SITE_VISIT", "DEPARTURE"
        ]  # fmt: skip
        assert visit["principal_role"] == "Minister of Foreign Affairs"
        assert visit["trip_reference"].startswith("TRP-")


async def test_nobody_else_learns_that_a_visit_exists(world: World) -> None:
    visit = await world.get()
    segment = visit["segments"][4]["id"]
    item = (await world.item("Industrial park venue survey"))["id"]
    change = (await world.propose(5, new_starts_at=at(world.day, 5).isoformat())).json()
    change_id = change["segments"][4]["pending_change"]["id"]
    urls = [
        ("GET", f"/api/vip/visits/{world.visit}", None),
        ("POST", f"/api/vip/visits/{world.visit}/start", None),
        ("POST", f"/api/vip/visits/{world.visit}/cancel", {"reason": "x"}),
        ("POST", f"/api/vip/segments/{segment}/progress", None),
        ("POST", f"/api/vip/segments/{segment}/changes", {"reason": "x", "make_virtual": True}),
        ("POST", f"/api/vip/changes/{change_id}/approve", {}),
        ("POST", f"/api/vip/changes/{change_id}/reject", {}),
        ("POST", f"/api/vip/checklist/{item}/done", None),
    ]
    missing = uuid.uuid4()
    for who in OUTSIDERS:
        assert await world.ok(who, "GET", "/api/vip/access") == {"visible": False}, who
        assert await world.ok(who, "GET", "/api/vip/visits") == [], who
        for method, url, body in urls:
            response = await world.send(who, method, url, body)
            # The same answer as for an id that does not exist.
            absent = await world.send(
                who, method, url.replace(url.split("/")[4], str(missing)), body
            )
            assert (response.status_code, response.json()) == (404, {"detail": "Visit not found"})
            assert (absent.status_code, absent.json()) == (404, {"detail": "Visit not found"})
        allowed = await world.permissions(who)
        assert not any(v for k, v in allowed.items() if k not in ("entity_type", "entity_id"))
    # Nothing was changed by the refused calls.
    after = await world.get()
    assert after["status"] == "PLANNED"
    assert (await world.item("Industrial park venue survey"))["done"] is False
    assert after["segments"][4]["pending_change"]["status"] == "PENDING"


async def test_a_head_of_mission_sees_only_their_missions_visits(world: World) -> None:
    other = await add_visit(world.idp, world.cai, "VV-2026-032", world.day, world.users["security"])
    assert [v["reference"] for v in await world.ok("hom.add", "GET", "/api/vip/visits")] == [
        "VV-2026-031"
    ]
    assert [v["reference"] for v in await world.ok("hom.cai", "GET", "/api/vip/visits")] == [
        "VV-2026-032"
    ]
    assert len(await world.ok("security", "GET", "/api/vip/visits")) == 2
    assert (await world.send("hom.add", "GET", f"/api/vip/visits/{other}")).status_code == 404
    assert await world.ok("hom.cai", "GET", "/api/vip/access") == {"visible": True}


async def test_the_audit_trail_is_shown_only_to_those_who_see_the_visit(world: World) -> None:
    """Review of Prompt 79, H1: GET /api/audit never tells anyone else a visit exists."""
    await world.start()
    other = await add_visit(world.idp, world.cai, "VV-2026-032", world.day, world.users["security"])
    await world.ok("security", "POST", f"/api/vip/visits/{other}/start")
    url = "/api/audit?entity_type=vip_visit&entity_id={}"
    for who in ("viewer", "travel", "consular", "admin", "hom.cai"):
        assert await world.ok(who, "GET", url.format("VV-2026-031")) == [], who
    for who in READERS:
        trail = await world.ok(who, "GET", url.format("VV-2026-031"))
        assert [e["action"] for e in trail] == ["VIP.START"], who
    assert len(await world.ok("hom.cai", "GET", url.format("VV-2026-032"))) == 1
    assert await world.ok("hom.add", "GET", url.format("VV-2026-032")) == []
    # The whole log (ADMIN only) has no VIP row for an ADMIN who is not a reader.
    everything = await world.ok("admin", "GET", "/api/audit?limit=500")
    assert everything
    assert all(e["entity_type"] != "vip_visit" for e in everything)
    assert "VV-2026" not in json.dumps(everything)


async def test_no_position_in_any_response(world: World) -> None:
    body = json.dumps([await world.get(), await world.ok("hq", "GET", "/api/vip/visits")])
    for key in ('"lat"', '"lon"', '"location"', '"venue_location"', "POINT"):
        assert key not in body


# --- segment risk (VIP-02, §3) ------------------------------------------------------------------


async def test_before_the_demo_the_motorcade_and_the_forum_are_moderate(world: World) -> None:
    visit = await world.get()
    assert [s["risk"] for s in visit["segments"]] == [
        "LOW", "MODERATE", "LOW", "MODERATE", "LOW", "LOW"
    ]  # fmt: skip
    reasons = {s["seq"]: [r["text"] for r in s["reasons"]] for s in visit["segments"]}
    assert reasons[2] == ["exposed movement"]
    assert reasons[4] == ["600 attendees"]
    assert visit["risk"] == "MODERATE"
    assert all(s["recommendation"] is None for s in visit["segments"])
    assert (visit["kpis"]["segments"], visit["kpis"]["high"]) == (6, 0)


async def test_a_rally_near_the_park_makes_the_site_visit_high(world: World) -> None:
    incident = await world.incident("INC-2026-1043", RALLY)
    visit = await world.get()
    assert [s["risk"] for s in visit["segments"]] == [
        "LOW", "MODERATE", "LOW", "MODERATE", "HIGH", "LOW"
    ]  # fmt: skip
    site = visit["segments"][4]
    assert site["reasons"] == [
        {
            "level": "HIGH",
            "text": "civil unrest 1.2 km away · INC-2026-1043",
            "incident_id": str(incident),
            "incident_reference": "INC-2026-1043",
        }
    ]
    assert site["recommendation"] == vip.RECOMMENDATION
    assert (visit["risk"], visit["kpis"]["high"]) == ("HIGH", 1)
    # Over: the risk clears by itself (worked out on read).
    await world.sql("UPDATE incident SET status = 'CLOSED' WHERE id = :i", i=incident)
    assert (await world.segment(5))["risk"] == "LOW"


async def test_a_zone_edge_within_5_km_is_moderate(world: World) -> None:
    await world.incident("INC-2026-1044", (PARK[0] + 0.02713, PARK[1]), radius_m=500)
    site = await world.segment(5)
    assert site["risk"] == "MODERATE"
    assert [r["text"] for r in site["reasons"]] == ["civil unrest 3.0 km away · INC-2026-1044"]
    assert site["recommendation"] is None


async def test_severe_weather_and_the_country_risk(world: World) -> None:
    await world.sql(
        "INSERT INTO weather_current (tenant_id, mission_id, observed_at, temperature_c, "
        "condition, wind_kph, gust_kph) VALUES (current_tenant_id(), :m, now(), 18, 'STORM', "
        "70, 95)",
        m=world.add,
    )
    visit = await world.get()
    assert [s["risk"] for s in visit["segments"]] == ["MODERATE"] * 6
    assert [r["text"] for r in visit["segments"][3]["reasons"]] == [
        "severe weather",
        "600 attendees",
    ]
    await world.sql(
        "INSERT INTO country_risk (tenant_id, country_code, level, security, unrest, health, "
        "transport, source) VALUES (current_tenant_id(), 'ET', 'HIGH', 60, 60, 40, 40, 'x')"
    )
    visit = await world.get()
    assert (visit["risk"], visit["country_risk"], visit["kpis"]["high"]) == ("HIGH", "HIGH", 0)


async def test_completed_segments_keep_their_risk_but_leave_the_visit_risk(world: World) -> None:
    await world.start()
    for seq in (1, 2, 3, 4):
        for _ in range(2):
            assert (await world.progress(seq)).status_code == 200
    visit = await world.get()
    assert visit["segments"][1]["risk"] == "MODERATE"
    assert visit["risk"] == "LOW"


# --- detail and checklist (VIP-03, §4) ----------------------------------------------------------


async def test_the_detail_comes_from_fleet_health_and_partners(world: World) -> None:
    visit = await world.get()
    detail = visit["detail"]
    assert [(v["code"], v["state"], v["available"]) for v in detail["vehicles"]] == [
        ("VH-11", "AVAILABLE", True),
        ("VH-12", "MAINTENANCE", False),
    ]
    assert detail["medical"]["facility_name"] == "Sample Hospital A"
    assert detail["medical"]["partner_name"] == "Kestrel Medical (simulated)"
    assert detail["safe_havens"] == ["Embassy", "Hotel safe floor", "Sample Hospital A"]
    assert (detail["team_lead"], detail["team_size"], detail["medic"]) == (
        "Close-protection lead (sample)",
        8,
        True,
    )
    kpis = visit["kpis"]
    assert (kpis["team_size"], kpis["vehicles"], kpis["medics"]) == (8, 2, 1)
    assert (kpis["venues_surveyed"], kpis["venues"]) == (4, 5)  # G-2: the design's 4 / 5


async def test_a_hospital_in_an_active_zone_is_not_the_nearest_safe_haven(world: World) -> None:
    await world.incident("INC-2026-1045", HOSPITAL_A, radius_m=300)
    detail = (await world.get())["detail"]
    assert detail["medical"]["facility_name"] == "Sample Hospital B"
    assert detail["safe_havens"][-1] == "Sample Hospital B"


async def test_ticking_the_checklist(world: World) -> None:
    survey = await world.item("Industrial park venue survey")
    url = f"/api/vip/checklist/{survey['id']}/done"
    assert (survey["done"], survey["overdue"]) == (False, False)
    for who in ("duty", "hq"):
        assert (await world.send(who, "POST", url)).status_code == 403, who
    visit = await world.ok("security", "POST", url)
    ticked = next(c for c in visit["checklist"] if c["id"] == survey["id"])
    assert (ticked["done"], ticked["done_by_name"]) == (True, "User security")
    assert ticked["done_at"] is not None
    assert visit["kpis"]["venues_surveyed"] == 5
    response = await world.send("hom.add", "POST", url)
    assert (response.status_code, response.json()["detail"]) == (409, "The item is already done")
    assert [(a.action, a.details) for a in await world.audit()] == [
        ("VIP.CHECKLIST_DONE", {"item": survey["id"]})
    ]


# --- during the visit (VIP-04, §5) --------------------------------------------------------------


async def test_starting_the_visit(world: World) -> None:
    url = f"/api/vip/visits/{world.visit}/start"
    for who in ("duty", "hq"):
        response = await world.send(who, "POST", url)
        assert response.status_code == 403, who
    visit = await world.start("hom.add")
    assert visit["status"] == "LIVE"
    assert visit["started_at"] is not None
    response = await world.send("security", "POST", url)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "VV-2026-031 is live, not planned",
    )
    audit = await world.audit()
    assert [(a.action, a.actor_id, a.entity_type, a.entity_id, a.details) for a in audit] == [
        (
            "VIP.START",
            str(world.users["hom.add"]),
            "vip_visit",
            "VV-2026-031",
            {"from": "PLANNED", "to": "LIVE"},
        )
    ]


async def test_the_programme_moves_one_step_at_a_time_while_live(world: World) -> None:
    response = await world.progress(1)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "VV-2026-031 is planned, not live",
    )
    await world.start()
    assert (await world.progress(1, "duty")).status_code == 403
    assert (await world.progress(1)).json()["segments"][0]["status"] == "IN_PROGRESS"
    assert (await world.progress(1, "hom.add")).json()["segments"][0]["status"] == "COMPLETED"
    response = await world.progress(1)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "Segment 1 is already completed",
    )
    assert (await world.progress(2)).json()["segments"][1]["status"] == "IN_PROGRESS"
    # In programme order (review of Prompt 79, M2): not the departure while 2..5 are open.
    response = await world.progress(6)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "Segment 2 is not completed yet",
    )
    assert (await world.progress(3)).status_code == 409
    for seq in (2, 3, 3, 4, 4, 5, 5):
        assert (await world.progress(seq)).status_code == 200, seq
    # The departure completed completes the visit (L6); nothing moves after.
    await world.progress(6)
    visit = (await world.progress(6)).json()
    assert visit["status"] == "COMPLETED"
    assert (await world.progress(2)).status_code == 409
    allowed = await world.permissions("security")
    assert not any(v for k, v in allowed.items() if k not in ("entity_type", "entity_id"))
    actions = [(a.action, a.details) for a in await world.audit()]
    assert actions[-2:] == [
        ("VIP.SEGMENT", {"seq": 6, "from": "IN_PROGRESS", "to": "COMPLETED"}),
        ("VIP.COMPLETE", {"from": "LIVE", "to": "COMPLETED", "pending_changes_closed": 0}),
    ]


async def test_the_simulated_progress_events(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await vip.simulated_progress(session, world.reference, 1, "IN_PROGRESS") is None
    await world.start()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await vip.simulated_progress(session, world.reference, 1, "COMPLETED") is None
        assert await vip.simulated_progress(session, "VV-2026-999", 1, "IN_PROGRESS") is None
        assert await vip.simulated_progress(session, world.reference, 9, "IN_PROGRESS") is None
        assert await vip.simulated_progress(session, world.reference, 2, "IN_PROGRESS") is None
        assert await vip.simulated_progress(session, world.reference, 1, "IN_PROGRESS")
        assert await vip.simulated_progress(session, world.reference, 1, "COMPLETED")
        await session.commit()
    assert (await world.segment(1))["status"] == "COMPLETED"
    audit = [a for a in await world.audit() if a.action == "VIP.SEGMENT"]
    assert {(a.actor_type, a.actor_id) for a in audit} == {("SYSTEM", "visit progress (simulated)")}


async def test_only_the_hq_crisis_director_cancels_with_a_reason(world: World) -> None:
    url = f"/api/vip/visits/{world.visit}/cancel"
    proposed = (await world.propose(5, make_virtual=True)).json()
    change_id = proposed["segments"][4]["pending_change"]["id"]
    for who in ("security", "hom.add", "duty"):
        assert (await world.send(who, "POST", url, {"reason": "x"})).status_code == 403, who
    assert (await world.send("hq", "POST", url, {"reason": ""})).status_code == 422
    visit = await world.ok("hq", "POST", url, {"reason": "Visit postponed by HQ"})
    assert (visit["status"], visit["cancel_reason"]) == ("CANCELLED", "Visit postponed by HQ")
    assert visit["cancelled_at"] is not None
    # A pending change closes with the visit (L4) and cannot be decided.
    assert [c["status"] for c in visit["changes"]] == ["CLOSED"]
    assert visit["segments"][4]["pending_change"] is None
    response = await world.decide(change_id, "hq")
    assert response.status_code == 409
    assert (await world.send("hq", "POST", url, {"reason": "x"})).status_code == 409
    assert (
        await world.send("security", "POST", f"/api/vip/visits/{world.visit}/start")
    ).status_code == 409
    cancel = [a for a in await world.audit() if a.action == "VIP.CANCEL"]
    assert cancel[0].details == {"from": "PLANNED", "to": "CANCELLED", "pending_changes_closed": 1}


# --- programme changes with two people (VIP-05, §6) ---------------------------------------------


async def test_a_new_time_proposed_by_one_and_approved_by_another(world: World) -> None:
    await world.incident("INC-2026-1043", RALLY)
    before = await world.segment(5)
    eight = at(world.day + timedelta(1), 5)  # 08:00 in Addis Ababa
    for who in ("hq", "hom.add", "duty"):
        assert (await world.propose(5, who, new_starts_at=eight.isoformat())).status_code == 403
    visit = (await world.propose(5, new_starts_at=eight.isoformat())).json()
    change = visit["segments"][4]["pending_change"]
    # The duration is kept (L5): 2 hours.
    assert (change["new_starts_at"], change["new_ends_at"]) == (
        eight.isoformat().replace("+00:00", "Z"),
        (eight + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    )
    assert (change["status"], change["proposed_by_name"]) == ("PENDING", "User security")
    again = await world.propose(5, make_virtual=True)
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "Segment 5 already has a change waiting for a decision",
    )
    response = await world.decide(change["id"], "security")
    assert response.status_code == 403
    assert (await world.decide(change["id"], "hom.cai")).status_code == 404
    assert (await world.decide(change["id"], "duty")).status_code == 403
    visit = (await world.decide(change["id"], "hq")).json()
    site = visit["segments"][4]
    assert site["starts_at"] == change["new_starts_at"]
    assert site["ends_at"] == change["new_ends_at"]
    assert site["pending_change"] is None
    assert visit["changes"][0]["status"] == "APPROVED"
    assert visit["changes"][0]["decided_by_name"] == "User hq"
    # The rules use place, not time: still HIGH while the rally is ACTIVE (G-5).
    assert site["risk"] == "HIGH"
    assert before["starts_at"] != site["starts_at"]
    assert (await world.decide(change["id"], "hom.add")).status_code == 409


async def test_a_virtual_alternative_has_no_venue_risk(world: World) -> None:
    await world.incident("INC-2026-1043", RALLY)
    change = (await world.propose(5, make_virtual=True)).json()["segments"][4]["pending_change"]
    visit = (await world.decide(change["id"], "hom.add")).json()
    site = visit["segments"][4]
    assert (site["virtual"], site["risk"], site["reasons"], site["recommendation"]) == (
        True,
        "LOW",
        [],
        None,
    )
    assert visit["risk"] == "MODERATE"
    # A virtual segment has no venue, so the park's open survey no longer counts (G-2).
    assert (visit["kpis"]["venues_surveyed"], visit["kpis"]["venues"]) == (4, 4)
    again = await world.propose(5, make_virtual=True)
    assert (again.status_code, again.json()["detail"]) == (409, "Segment 5 is already virtual")


async def test_a_rejection_keeps_the_segment(world: World) -> None:
    before = await world.segment(5)
    proposed = await world.propose(5, new_starts_at=at(world.day, 5).isoformat())
    change = proposed.json()["segments"][4]["pending_change"]
    response = await world.send(
        "hq", "POST", f"/api/vip/changes/{change['id']}/reject", {"note": "Keep the plan"}
    )
    visit = response.json()
    site = visit["segments"][4]
    assert (site["starts_at"], site["ends_at"], site["pending_change"]) == (
        before["starts_at"],
        before["ends_at"],
        None,
    )
    assert (visit["changes"][0]["status"], visit["changes"][0]["decision_note"]) == (
        "REJECTED",
        "Keep the plan",
    )
    # Another proposal is possible after a decision.
    assert (await world.propose(5, make_virtual=True)).status_code == 200


async def test_the_proposer_never_decides_even_holding_both_roles(world: World) -> None:
    proposed = await world.propose(5, "both", make_virtual=True)
    change = proposed.json()["segments"][4]["pending_change"]
    response = await world.decide(change["id"], "both")
    assert (response.status_code, response.json()["detail"]) == (
        403,
        "The same person cannot decide two steps (D-16)",
    )
    assert (await world.permissions("both"))["decide_vip_change"] == []
    assert (await world.permissions("hq"))["decide_vip_change"] == [change["id"]]


async def test_change_refusals(world: World) -> None:
    eight = at(world.day, 5)
    for body in (
        {},
        {"make_virtual": True, "new_starts_at": eight.isoformat()},
        {"make_virtual": True, "new_ends_at": eight.isoformat()},
        {"new_starts_at": eight.isoformat(), "new_ends_at": (eight - timedelta(1)).isoformat()},
        {"new_starts_at": "2026-11-06T05:00:00"},  # no time zone
    ):
        assert (await world.propose(5, **body)).status_code == 422, body
    same = (await world.segment(5))["starts_at"]
    response = await world.propose(5, new_starts_at=same)
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "Segment 5 is already at that time",
    )
    # Under way: no proposal, and a change waiting from before can only be rejected.
    change = (await world.propose(1, make_virtual=True)).json()["segments"][0]["pending_change"]
    await world.start()
    await world.progress(1)
    response = await world.propose(1, new_starts_at=eight.isoformat())
    assert response.status_code == 409
    response = await world.decide(change["id"], "hq")
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "Segment 1 is under way; the change can only be rejected",
    )
    assert (await world.decide(change["id"], "hq", "reject")).status_code == 200


# --- permissions and audit ----------------------------------------------------------------------


async def test_the_buttons_follow_the_roles(world: World) -> None:
    def flags(p: Any) -> dict[str, Any]:
        return {k: v for k, v in p.items() if k.endswith(("visit", "checklist", "change"))}

    segments = [s["id"] for s in (await world.get())["segments"]]
    assert flags(await world.permissions("security")) == {
        "start_visit": True,
        "progress_visit": False,
        "cancel_visit": False,
        "tick_vip_checklist": True,
        "propose_vip_change": segments,
        "decide_vip_change": [],
    }
    assert flags(await world.permissions("hq")) == {
        "start_visit": False,
        "progress_visit": False,
        "cancel_visit": True,
        "tick_vip_checklist": False,
        "propose_vip_change": [],
        "decide_vip_change": [],
    }
    assert not any(flags(await world.permissions("duty")).values())
    change = (await world.propose(5, make_virtual=True)).json()["segments"][4]["pending_change"]
    await world.start()
    hom = flags(await world.permissions("hom.add"))
    assert (hom["start_visit"], hom["progress_visit"], hom["tick_vip_checklist"]) == (
        False,
        True,
        True,
    )
    assert hom["decide_vip_change"] == [change["id"]]
    assert (await world.permissions("security"))["propose_vip_change"] == [
        s for i, s in enumerate(segments) if i != 4
    ]


async def test_audit_gives_references_never_venues_times_or_the_principal(world: World) -> None:
    await world.incident("INC-2026-1043", RALLY)
    survey = await world.item("Industrial park venue survey")
    await world.ok("security", "POST", f"/api/vip/checklist/{survey['id']}/done")
    change = (await world.propose(5, new_starts_at=at(world.day, 5).isoformat())).json()
    await world.decide(change["segments"][4]["pending_change"]["id"], "hq")
    change = (await world.propose(3, make_virtual=True)).json()
    await world.decide(change["segments"][2]["pending_change"]["id"], "hq", "reject")
    await world.start()
    await world.progress(1)
    await world.ok("hq", "POST", f"/api/vip/visits/{world.visit}/cancel", {"reason": "Venue x"})
    audit = await world.audit()
    assert [a.action for a in audit] == [
        "VIP.CHECKLIST_DONE",
        "VIP.CHANGE_PROPOSE",
        "VIP.CHANGE_APPROVE",
        "VIP.CHANGE_PROPOSE",
        "VIP.CHANGE_REJECT",
        "VIP.START",
        "VIP.SEGMENT",
        "VIP.CANCEL",
    ]
    assert {(a.entity_type, a.entity_id) for a in audit} == {("vip_visit", "VV-2026-031")}
    details = json.dumps([a.details for a in audit])
    for word in (*VENUES, "Minister", "Rally", "Venue x", "venue survey"):
        assert word not in details, word
    assert not re.search(r"\d{2}:\d{2}", details)  # no times


# --- the seed and the simulated progress (Prompt 80; plan §2, §5, §9) ---------------------------


async def test_ensure_visits_seeds_once_and_audits_counts_only(world: World) -> None:
    first = world.day + timedelta(10)
    visit = vip.VisitIn(
        reference="VV-2026-040",
        title="Delegation visit",
        mission_id=world.cai,
        principal_role="Deputy Minister",
        starts_on=first,
        ends_on=first,
        trip_id=None,
        detail={"team_size": 4, "vehicles": [], "safe_havens": ["Embassy"]},
        segments=(
            vip.SegmentIn("ARRIVAL", "Arrival", "Cairo airport", *CAIRO, at(first, 6)),
            vip.SegmentIn("DEPARTURE", "Departure", "Cairo airport", *CAIRO, at(first, 18)),
        ),
        checklist=(
            vip.ItemIn("Threat assessment issued", first, world.users["security"]),
            vip.ItemIn("Cairo airport venue survey", first),
        ),
    )
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await vip.ensure_visits(session, [visit]) == 1
        assert await vip.ensure_visits(session, [visit]) == 0
        await session.commit()
    seeded = next(
        v
        for v in await world.ok("security", "GET", "/api/vip/visits")
        if v["mission_code"] == "CAI"
    )
    detail = await world.ok("hom.cai", "GET", f"/api/vip/visits/{seeded['id']}")
    assert [s["kind"] for s in detail["segments"]] == ["ARRIVAL", "DEPARTURE"]
    assert {c["label"]: c["done"] for c in detail["checklist"]} == {
        "Threat assessment issued": True,
        "Cairo airport venue survey": False,
    }
    assert (detail["kpis"]["venues_surveyed"], detail["kpis"]["venues"]) == (0, 1)
    seed = [a for a in await world.audit() if a.action == "VIP.SEED"]
    assert [(a.actor_type, a.entity_id, a.details) for a in seed] == [
        ("SYSTEM", "VV-2026-040", {"segments": 2, "checklist": 2, "done": 1})
    ]


async def test_the_simulated_start_is_by_the_seeded_security_officer(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await vip.simulated_start(session, "VV-2026-999") is None
        started = await vip.simulated_start(session, world.reference)
        assert started is not None
        await session.commit()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await vip.simulated_start(session, world.reference) is None  # already live
    visit = await world.get()
    assert visit["status"] == "LIVE"
    start = [a for a in await world.audit() if a.action == "VIP.START"]
    assert [(a.actor_type, a.actor_id, a.details) for a in start] == [
        (
            "SYSTEM",
            "visit progress (simulated)",
            {"from": "PLANNED", "to": "LIVE", "started_by": str(world.users["security"])},
        )
    ]


async def test_the_progress_handler(world: World) -> None:
    handle = consumer.progress_handler(world.idp.engine)

    async def send(payload: dict[str, Any]) -> None:
        await handle(Event("VIP_PROGRESS", world.idp.tenant_id, payload, "scenario"))

    for refused in (
        {"visit": world.reference, "status": "IN_PROGRESS"},  # a step needs its seq
        {"visit": world.reference, "seq": 1, "status": "LIVE"},
        {"visit": "VV-31", "status": "LIVE"},
        {"visit": world.reference, "seq": 1, "status": "DONE"},
    ):
        with pytest.raises(ValidationError):
            consumer.ProgressIn.model_validate(refused)
        await send(refused)  # logged and dropped
    await send({"visit": world.reference, "seq": 1, "status": "IN_PROGRESS"})  # not live yet
    assert (await world.segment(1))["status"] == "PLANNED"
    await send({"visit": world.reference, "status": "LIVE"})
    await send({"visit": world.reference, "seq": 1, "status": "IN_PROGRESS"})
    await send({"visit": world.reference, "seq": 1, "status": "COMPLETED"})
    await send({"visit": world.reference, "seq": 3, "status": "IN_PROGRESS"})  # out of order
    visit = await world.get()
    assert visit["status"] == "LIVE"
    assert [s["status"] for s in visit["segments"][:3]] == ["COMPLETED", "PLANNED", "PLANNED"]
