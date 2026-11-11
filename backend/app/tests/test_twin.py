"""Site Twin (TWN-01..05; D-43; docs/plan-pilot-twn.md): the plan with counts (§2); presence with
names only within the people scope, and never a location observation (§3); sensors with the
Fleet systems and SITE timeline entries (§4); shelter-in-place and the route worked out on read
(§5); readiness with the tick through approvals.py (§6); permissions; the simulated feeds; audit
without names. Against real PostgreSQL, as nexira_api."""

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text

from app.core import realtime
from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.fleet import service as fleet
from app.modules.fleet.service import AssetIn
from app.modules.twin import consumer
from app.modules.twin import service as twin
from app.modules.twin.service import OccupantIn, PlanIn, RouteIn, SensorIn, ZoneIn
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

EMBASSY = (-1.2950, 36.8080)
CAIRO = (30.0444, 31.2357)
KEY = "NBO:EMBASSY"
STAFF = ("Fictional Officer A", "Fictional Officer B", "Fictional Officer C")


def pt(lat_lon: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({lat_lon[1]} {lat_lon[0]})"


ZONES = (
    ZoneIn("ch", "Chancery offices", "OFFICE", 130, 30, 270, 220),
    ZoneIn("conf", "Conference room", "CONFERENCE", 415, 155, 160, 95),
    ZoneIn("safe", "Safe room (hardened)", "SAFE_ROOM", 590, 145, 180, 105, capacity=20),
    ZoneIn("cons", "Consular hall", "CONSULAR", 315, 265, 260, 120),
    ZoneIn("g1", "Gate 1", "GATE", 20, 320, 95, 65),
    ZoneIn("g2", "Gate 2", "GATE", 680, 340, 90, 45),
)
ROUTES = (
    RouteIn("A", "Route A → main road via Gate 1", ((130, 300), (70, 350)), "g1"),
    RouteIn("B", "Route B → vehicles via Gate 2", ((680, 200), (680, 300), (725, 340)), "g2"),
)
SENSORS = (
    SensorIn("G1-MAIN", "GATE", "Gate 1 · main", "g1", "Open · screening"),
    SensorIn("G2-READER", "BADGE_READER", "Gate 2 · badge reader", "g2", "Online"),
    SensorIn("CAM-01", "CCTV", "Camera 1", "ch", mount=(132, 32, 135, 90, 220)),
    SensorIn("CAM-02", "CCTV", "Camera 2", "cons", mount=(317, 267, 120, 90, 280)),
    SensorIn("SAFE-01", "SAFE_ROOM", "Safe room", "safe", "Ready"),
)


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    cai: uuid.UUID
    site: uuid.UUID
    staff: list[uuid.UUID]
    users: dict[str, uuid.UUID]

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def send(self, who: str, method: str, url: str, body: Any = None) -> Response:
        return await self.client.request(method, url, json=body, headers=self.idp.headers(who))

    async def twin(self, who: str = "duty") -> Any:
        response = await self.send(who, "GET", f"/api/sites/{self.site}/twin")
        assert response.status_code == 200, response.text
        return response.json()

    async def presence(self, occupant: str, zone: str | None) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            outcome = await twin.presence(session, KEY, occupant, zone)
            await session.commit()
        return outcome

    async def sensor(self, code: str, status: str, detail: str | None = None) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            outcome = await twin.sensor(session, KEY, code, status, detail)
            await session.commit()
        return outcome

    async def audit(self, action: str) -> list[AuditLog]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)
                )
            )

    async def incident(self, reference: str = "INC-2026-1042") -> uuid.UUID:
        found: uuid.UUID = (
            await self.sql(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id, status) VALUES (current_tenant_id(), "
                ":r, 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', :pt, :m, 'ACTIVE') "
                "RETURNING id",
                r=reference,
                pt=pt(EMBASSY),
                m=self.nbo,
            )
        ).scalar_one()
        return found

    async def items(self) -> dict[str, Any]:
        return {i["label"]: i for i in (await self.twin())["readiness"]["items"]}


async def _mission(idp: Idp, code: str, city: str, country: str, at: Any) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :city, :cc, :pt)"
            ),
            {"id": mission_id, "code": code, "city": city, "cc": country, "pt": pt(at)},
        )
        await session.commit()
    return mission_id


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    return await make_world(client, idp)


async def make_world(client: AsyncClient, idp: Idp) -> World:
    """The embassy with a plan, staff, a guard and visitors; also the normal day's tests."""
    nbo = await _mission(idp, "NBO", "Nairobi", "KE", EMBASSY)
    cai = await _mission(idp, "CAI", "Cairo", "EG", CAIRO)
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "viewer": [("VIEWER", None)],
        "security.cai": [("SECURITY_OFFICER", cai)],
    }
    users = {sub: await idp.user(sub, roles) for sub, roles in grants.items()}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        site = await session.scalar(
            text(
                "INSERT INTO site (tenant_id, mission_id, site_type, name, location, "
                "readiness_score, last_drill_on) VALUES (current_tenant_id(), :m, 'EMBASSY', "
                "'Embassy Nairobi', :pt, 79, current_date - 21) RETURNING id"
            ),
            {"m": nbo, "pt": pt(EMBASSY)},
        )
        await session.execute(
            text(
                "INSERT INTO site (tenant_id, mission_id, site_type, name, location) VALUES "
                "(current_tenant_id(), :m, 'RESIDENCE', 'Residence', :pt)"
            ),
            {"m": nbo, "pt": pt(EMBASSY)},
        )
        staff = [
            await session.scalar(
                text(
                    "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
                    "VALUES (current_tenant_id(), :m, 'DIPLOMAT', :n) RETURNING id"
                ),
                {"m": nbo, "n": name},
            )
            for name in STAFF
        ]
        lat, lon = EMBASSY
        await fleet.ensure_assets(
            session,
            [
                AssetIn(nbo, "GEN-NBO", "EQUIPMENT", "Generator 250 kVA", lat, lon, "Embassy", 72),
                AssetIn(nbo, "SAT-NBO", "EQUIPMENT", "Satellite terminal", lat, lon, "Comms", 100),
            ],
            date.today(),
        )
        assert site is not None
        assert await twin.ensure_plan(
            session,
            PlanIn(
                site_id=site,
                zones=ZONES,
                routes=ROUTES,
                sensors=SENSORS,
                items=(
                    ("Floor wardens assigned (3)", users["security"]),
                    ("Generator load test witnessed", None),
                ),
                occupants=(
                    OccupantIn("ch", person_id=staff[0]),
                    OccupantIn("ch", person_id=staff[1]),
                    OccupantIn("conf", person_id=staff[2]),
                    OccupantIn("g1", label="Guard 1"),
                    OccupantIn("cons", label="Visitor 1"),
                    OccupantIn("cons", label="Visitor 2"),
                ),
            ),
        )
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, cai, site, staff, users)


# --- the plan and counts (TWN-01, §2) -----------------------------------------------------------


async def test_the_plan_with_counts_sensors_systems_and_readiness(world: World) -> None:
    out = await world.twin()
    assert out["site"]["name"] == "Embassy Nairobi"
    assert {z["code"]: z["count"] for z in out["zones"]} == {
        "ch": 2,
        "conf": 1,
        "safe": 0,
        "cons": 2,
        "g1": 1,
        "g2": 0,
    }
    assert out["counts"] == {
        "on_site": 6,
        "staff": 3,
        "guards": 1,
        "visitors": 2,
        "safe_room": 0,
        "safe_room_capacity": 20,
        "sensors_online": 5,
        "sensors": 5,
        "faults": 0,
    }
    assert [(s["code"], s["state"], s["fuel_pct"]) for s in out["systems"]] == [
        ("GEN-NBO", "AVAILABLE", 72),
        ("SAT-NBO", "AVAILABLE", 100),
    ]
    assert (out["readiness"]["score"], out["shelter"], out["route"]) == (79, None, None)
    items = await world.items()
    assert items["Floor wardens assigned (3)"]["done"] is True
    assert items["Generator load test witnessed"]["done"] is False
    assert items["All access points monitored"] | {"done_at": None} == {
        "id": None,
        "label": "All access points monitored",
        "done": True,
        "done_by_name": None,
        "done_at": None,
        "derived": True,
        "detail": None,
    }
    assert out["simulated"] is True


async def test_a_camera_carries_its_mount(world: World) -> None:
    """TWN-08 (PC-53): where each camera is mounted and points; other sensors have none."""
    out = await world.twin()
    assert {s["code"]: s["mount"] for s in out["sensors"]} == {
        "G1-MAIN": None,
        "G2-READER": None,
        "CAM-01": {"x": 132, "y": 32, "heading_deg": 135, "fov_deg": 90, "range_u": 220},
        "CAM-02": {"x": 317, "y": 267, "heading_deg": 120, "fov_deg": 90, "range_u": 280},
        "SAFE-01": None,
    }


async def test_only_sites_with_a_plan_are_listed(world: World) -> None:
    response = await world.send("viewer", "GET", "/api/sites/twin")
    assert [s["name"] for s in response.json()] == ["Embassy Nairobi"]
    residence = (await world.sql("SELECT id FROM site WHERE site_type = 'RESIDENCE'")).scalar_one()
    response = await world.send("viewer", "GET", f"/api/sites/{residence}/twin")
    assert (response.status_code, response.json()["detail"]) == (404, "No floor plan yet")
    assert (await world.send("viewer", "GET", f"/api/sites/{uuid.uuid4()}/twin")).status_code == 404


async def test_the_plan_is_seeded_once(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert not await twin.ensure_plan(
            session, PlanIn(world.site, ZONES, ROUTES, SENSORS, (), ())
        )
    seed = await world.audit("SITE.SEED")
    assert [a.details for a in seed] == [
        {"zones": 6, "routes": 2, "sensors": 5, "items": 2, "occupants": 6}
    ]


# --- presence and names (TWN-02, §3, §68 Q3) ----------------------------------------------------


async def test_names_only_within_the_people_scope(world: World) -> None:
    staff = [o for o in (await world.twin("duty"))["occupants"] if o["kind"] == "STAFF"]
    assert sorted(o["name"] for o in staff) == sorted(STAFF)
    for who in ("viewer", "hom.cai"):
        out = await world.twin(who)
        assert out["counts"]["staff"] == 3, who
        assert all(o["name"] is None for o in out["occupants"]), who
        assert not any(name in json.dumps(out) for name in STAFF), who
    labels = sorted(o["label"] for o in (await world.twin("viewer"))["occupants"] if o["label"])
    assert labels == ["Guard 1", "Visitor 1", "Visitor 2"]


async def test_presence_moves_arrives_and_leaves(world: World) -> None:
    officer = str(world.staff[0])
    assert await world.presence(officer, "safe")
    assert await world.presence("Visitor 3", "conf")  # an arrival
    assert await world.presence("Visitor 1", None)  # a departure
    assert await world.presence(officer, "safe") is None  # no change
    assert await world.presence(officer, "kitchen") is None  # no such zone
    assert await world.presence("Visitor 9", None) is None  # not on site
    assert await world.presence(str(uuid.uuid4()), "ch") is None  # a staff row needs a person
    counts = (await world.twin())["counts"]
    assert (counts["on_site"], counts["safe_room"], counts["visitors"]) == (6, 1, 2)
    moves = await world.audit("SITE.PRESENCE")
    assert [(a.actor_type, a.actor_id) for a in moves] == [
        ("SYSTEM", "access control (simulated)")
    ] * 3
    assert moves[0].details == {
        "kind": "STAFF",
        "from": "ch",
        "to": "safe",
        "person_id": officer,
    }
    assert moves[2].details == {"kind": "VISITOR", "from": "cons", "to": None, "label": "Visitor 1"}
    assert not any(name in json.dumps([a.details for a in moves]) for name in STAFF)


async def test_presence_never_becomes_a_location_observation(world: World) -> None:
    """D-43: People & Sites, exposure and the check-in never change."""
    before = (
        await world.sql(
            "SELECT (SELECT count(*) FROM location_observation) AS obs, "
            "(SELECT count(*) FROM person_location_current) AS current"
        )
    ).one()
    await world.presence(str(world.staff[0]), "safe")
    await world.presence(str(world.staff[1]), None)
    after = (
        await world.sql(
            "SELECT (SELECT count(*) FROM location_observation) AS obs, "
            "(SELECT count(*) FROM person_location_current) AS current"
        )
    ).one()
    assert tuple(after) == tuple(before)


async def test_site_updated_carries_ids_and_counts_only(world: World) -> None:
    outcome = await world.presence(str(world.staff[0]), "safe")
    (event,) = outcome.events
    assert event.type == "SITE_UPDATED"
    assert event.payload == {
        "site_id": str(world.site),
        "mission_id": str(world.nbo),
        "change": "presence",
        "on_site": 6,
        "safe_room": 1,
        "sensors_online": 5,
    }
    assert "SITE_UPDATED" in realtime.FORWARDED  # G-8: counts every role may see


# --- sensors (TWN-03, §4) -----------------------------------------------------------------------


async def test_a_fault_in_an_active_zone_writes_a_timeline_entry(world: World) -> None:
    assert await world.sensor("CAM-01", "DEGRADED", "Low light") is not None  # no incident yet
    incident = await world.incident()
    outcome = await world.sensor("G2-READER", "FAULT", "Fault · manual guard")
    assert outcome.events[0].payload["incident_ids"] == [str(incident)]
    assert await world.sensor("G2-READER", "FAULT", "Fault · manual guard") is None  # no change
    await world.sensor("CAM-02", "OFFLINE")
    await world.sensor("CAM-01", "OK")  # DEGRADED → OK: online both ways, no entry
    await world.sensor("G2-READER", "OK", "Online")
    timeline = (
        await world.sql(
            "SELECT summary, actor_type FROM incident_event WHERE event_type = 'SITE' ORDER BY id"
        )
    ).all()
    assert [tuple(t) for t in timeline] == [
        ("Embassy Nairobi · Gate 2 · badge reader: FAULT (Fault · manual guard).", "SYSTEM"),
        ("Embassy Nairobi · Camera 2: OFFLINE.", "SYSTEM"),
        ("Embassy Nairobi · Gate 2 · badge reader: OK (Online).", "SYSTEM"),
    ]
    out = await world.twin()
    assert (out["counts"]["sensors_online"], out["counts"]["faults"]) == (4, 1)
    assert [a.details["to"] for a in await world.audit("SITE.SENSOR")] == [
        "DEGRADED",
        "FAULT",
        "OFFLINE",
        "OK",
        "OK",
    ]


async def test_access_points_monitored_follows_the_gates(world: World) -> None:
    await world.sensor("G2-READER", "FAULT", "Fault · manual guard")
    item = (await world.items())["All access points monitored"]
    assert (item["done"], item["detail"]) == (False, "Gate 2 · badge reader: Fault · manual guard")
    await world.sensor("CAM-01", "OFFLINE")  # a camera is not an access point
    await world.sensor("G2-READER", "OK", "Online")
    assert (await world.items())["All access points monitored"]["done"] is True


# --- overlays, worked out on read (TWN-04, §5) --------------------------------------------------


async def _shelter_run(world: World, incident: uuid.UUID, status: str) -> None:
    await world.sql(
        """
        WITH p AS (INSERT INTO playbook (tenant_id, code, name, category)
                   VALUES (current_tenant_id(), 'PB-07', 'Unrest', 'Security') RETURNING id),
             s AS (INSERT INTO playbook_step (tenant_id, playbook_id, seq, name, action_type,
                                              action_config)
                   SELECT current_tenant_id(), p.id, 4, 'Shelter', 'NOTIFY',
                          '{"campaign_type": "ALERT", "citizen_advisory_template": "SHELTER"}'
                     FROM p RETURNING id, playbook_id),
             r AS (INSERT INTO playbook_run (tenant_id, playbook_id, incident_id, status)
                   SELECT current_tenant_id(), s.playbook_id, :i, 'RUNNING' FROM s RETURNING id)
        INSERT INTO playbook_run_step (tenant_id, run_id, step_id, status)
        SELECT current_tenant_id(), r.id, s.id, :status FROM r, s
        """,
        i=incident,
        status=status,
    )


async def test_shelter_follows_the_shelter_alert_of_an_active_incident(world: World) -> None:
    incident = await world.incident()
    await _shelter_run(world, incident, "PENDING")
    assert (await world.twin())["shelter"] is None  # the alert has not gone out
    await world.sql("UPDATE playbook_run_step SET status = 'DONE'")
    assert (await world.twin())["shelter"] == {
        "incident_id": str(incident),
        "incident_reference": "INC-2026-1042",
    }
    await world.sql("UPDATE incident SET status = 'MONITORING' WHERE id = :i", i=incident)
    assert (await world.twin())["shelter"] is None  # clears by itself


async def test_the_route_shows_while_the_mission_evacuates(world: World) -> None:
    activator = world.users["hom.nbo"]
    await world.sql(
        "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
        "muster_location, route_label, destination, options) VALUES (current_tenant_id(), :m, "
        "'EVP-NBO', 'Courtyard', :pt, 'Route B', 'Dubai', "
        '\'[{"role": "PRIMARY", "kind": "CHARTER", "label": "C", "seats": 72}]\')',
        m=world.nbo,
        pt=pt(EMBASSY),
    )
    await world.sql(
        "INSERT INTO evacuation (tenant_id, reference, plan_id, mission_id, requested_by, "
        "requested_role) SELECT current_tenant_id(), 'EVN-1001', id, mission_id, :u, "
        "'HQ_CRISIS_DIRECTOR' FROM evacuation_plan",
        u=world.users["duty"],
    )
    assert (await world.twin())["route"] is None  # not yet active
    await world.sql(
        "UPDATE evacuation SET status = 'ACTIVE', activated_by = :a, step = 2", a=activator
    )
    assert (await world.twin())["route"] == {
        "code": "B",
        "label": "Route B → vehicles via Gate 2",
        "path": [[680, 200], [680, 300], [725, 340]],
        "exit_zone_code": "g2",
        "evacuation_reference": "EVN-1001",
    }


# --- readiness and permissions (TWN-05, §6; review of Prompt 84, M2) ----------------------------


async def test_a_readiness_item_is_ticked_once_by_the_caller(world: World) -> None:
    item = (await world.items())["Generator load test witnessed"]
    url = f"/api/sites/readiness/{item['id']}/done"
    for who in ("viewer", "duty", "hom.cai", "security.cai"):
        assert (await world.send(who, "POST", url)).status_code == 403, who
    response = await world.send("hom.nbo", "POST", url)
    assert response.status_code == 200, response.text
    ticked = next(i for i in response.json()["readiness"]["items"] if i["id"] == item["id"])
    assert (ticked["done"], ticked["done_by_name"]) == (True, "User hom.nbo")
    assert ticked["done_at"] is not None  # written by the database, read back (review L2)
    again = await world.send("security", "POST", url)
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "Generator load test witnessed is already done",
    )
    assert (
        await world.send("security", "POST", f"/api/sites/readiness/{uuid.uuid4()}/done")
    ).status_code == 404
    done = await world.audit("SITE.READINESS_DONE")
    assert [(a.actor_id, a.details) for a in done] == [
        (str(world.users["hom.nbo"]), {"item": item["id"]})
    ]
    assert [e.type for e in world.publisher.events] == ["SITE_UPDATED"]


async def test_the_tick_button_follows_the_roles(world: World) -> None:
    async def allowed(who: str) -> bool:
        response = await world.send(
            who, "GET", f"/api/me/permissions?entity_type=site&entity_id={world.site}"
        )
        flag: bool = response.json()["tick_readiness"]
        return flag

    assert [await allowed(w) for w in ("security", "hom.nbo", "duty", "viewer", "hom.cai")] == [
        True,
        True,
        False,
        False,
        False,
    ]


# --- the simulated feeds (review of Prompt 84, L5) ----------------------------------------------


async def test_the_feeds_take_only_the_scenario_players_events(world: World) -> None:
    on_presence = consumer.presence_handler(world.idp.engine, world.publisher)
    on_sensor = consumer.sensor_handler(world.idp.engine, world.publisher)
    move = {"site": KEY, "occupant": str(world.staff[0]), "zone": "safe"}
    fault = {"site": KEY, "code": "G2-READER", "status": "FAULT", "detail": "Fault"}
    for source in ("api", "scenario", "intel"):
        await on_presence(Event("SITE_PRESENCE", world.idp.tenant_id, move, source))
        await on_sensor(Event("SITE_SENSOR", world.idp.tenant_id, fault, source))
    for bad in (
        {**move, "site": "NBO:HOTEL"},
        {**move, "occupant": "Mr Smith"},
        {**move, "zone": "Safe Room"},
    ):
        await on_presence(Event("SITE_PRESENCE", world.idp.tenant_id, bad, "scenario:NBO-SITE:1"))
    await on_sensor(
        Event("SITE_SENSOR", world.idp.tenant_id, {**fault, "status": "BROKEN"}, "scenario:x:1")
    )
    out = await world.twin()
    assert (out["counts"]["safe_room"], out["counts"]["faults"]) == (0, 0)
    await on_presence(Event("SITE_PRESENCE", world.idp.tenant_id, move, "scenario:NBO-SITE:1"))
    await on_sensor(Event("SITE_SENSOR", world.idp.tenant_id, fault, "scenario:NBO-SITE:1"))
    out = await world.twin()
    assert (out["counts"]["safe_room"], out["counts"]["faults"]) == (1, 1)
    assert [e.type for e in world.publisher.events] == ["SITE_UPDATED", "SITE_UPDATED"]


# --- review of Prompt 85 ------------------------------------------------------------------------


async def test_who_ticked_is_shown_only_within_the_people_scope(world: World) -> None:
    """M1."""
    wardens = "Floor wardens assigned (3)"
    duty = {i["label"]: i for i in (await world.twin("duty"))["readiness"]["items"]}
    assert duty[wardens]["done_by_name"] == "User security"
    for who in ("viewer", "hom.cai"):
        items = {i["label"]: i for i in (await world.twin(who))["readiness"]["items"]}
        assert (items[wardens]["done"], items[wardens]["done_by_name"]) == (True, None), who


async def _person(world: World, mission: uuid.UUID, person_type: str = "DIPLOMAT") -> str:
    found = (
        await world.sql(
            "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
            "VALUES (current_tenant_id(), :m, :t, 'Fictional Other') RETURNING id",
            m=mission,
            t=person_type,
        )
    ).scalar_one()
    return str(found)


async def test_an_arrival_is_active_personnel_of_the_mission_only(world: World) -> None:
    """L9: none of these is applied, and nothing escapes as an error."""
    cairo = await _person(world, world.cai)
    citizen = await _person(world, world.nbo, "CITIZEN")
    dependant = await _person(world, world.nbo, "DEPENDANT")
    inactive = await _person(world, world.nbo)
    await world.sql("UPDATE person SET is_active = false WHERE id = :p", p=inactive)
    for occupant in (cairo, citizen, dependant, inactive):
        assert await world.presence(occupant, "ch") is None, occupant
    assert (await world.twin())["counts"]["staff"] == 3


async def test_a_person_deactivated_on_site_can_still_leave(world: World) -> None:
    """L3."""
    officer = world.staff[0]
    await world.sql("UPDATE person SET is_active = false WHERE id = :p", p=officer)
    assert await world.presence(str(officer), "safe") is not None  # a move
    assert await world.presence(str(officer), None) is not None  # a departure
    assert (await world.twin())["counts"]["staff"] == 2


async def test_two_arrivals_of_the_same_person_at_once(world: World) -> None:
    """L4: one applies, the other is not applied; no error."""
    newcomer = await _person(world, world.nbo)

    async def arrive() -> Any:
        async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
            outcome = await twin.presence(session, KEY, newcomer, "ch")
            await session.commit()
        return outcome

    results = await asyncio.gather(arrive(), arrive())
    assert sorted(r is None for r in results) == [False, True]
    assert (await world.twin())["counts"]["staff"] == 4


async def test_a_shelter_alert_elsewhere_does_not_shelter_this_site(world: World) -> None:
    cairo = (
        await world.sql(
            "INSERT INTO incident (tenant_id, reference, title, category, severity, "
            "signal_severity, location, mission_id, status) VALUES (current_tenant_id(), "
            "'INC-2026-1050', 'Unrest', 'CIVIL_UNREST', 'HIGH', 'HIGH', :pt, :m, 'ACTIVE') "
            "RETURNING id",
            pt=pt(CAIRO),
            m=world.cai,
        )
    ).scalar_one()
    await _shelter_run(world, cairo, "DONE")
    assert (await world.twin())["shelter"] is None


async def test_no_timeline_entry_far_away_or_for_an_inactive_incident(world: World) -> None:
    await world.sql(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        "location, mission_id, status) VALUES (current_tenant_id(), 'INC-2026-1051', 'Far', "
        "'CIVIL_UNREST', 'HIGH', 'HIGH', :pt, :m, 'ACTIVE')",
        pt=pt(CAIRO),
        m=world.cai,
    )
    incident = await world.incident()
    await world.sql("UPDATE incident SET status = 'MONITORING' WHERE id = :i", i=incident)
    outcome = await world.sensor("G2-READER", "FAULT", "Fault")
    assert outcome.events[0].payload["incident_ids"] == []
    assert (
        await world.sql("SELECT count(*) FROM incident_event WHERE event_type = 'SITE'")
    ).scalar_one() == 0


async def test_the_route_matches_a_longer_plan_label(world: World) -> None:
    """L5: the plan may name the route at length."""
    await world.sql(
        "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
        "muster_location, route_label, destination, options) VALUES (current_tenant_id(), :m, "
        "'EVP-NBO', 'Courtyard', :pt, 'Route A via the main road', 'Dubai', "
        '\'[{"role": "PRIMARY", "kind": "CHARTER", "label": "C", "seats": 72}]\')',
        m=world.nbo,
        pt=pt(EMBASSY),
    )
    await world.sql(
        "INSERT INTO evacuation (tenant_id, reference, plan_id, mission_id, requested_by, "
        "requested_role) SELECT current_tenant_id(), 'EVN-1001', id, mission_id, :u, "
        "'HQ_CRISIS_DIRECTOR' FROM evacuation_plan",
        u=world.users["duty"],
    )
    await world.sql(
        "UPDATE evacuation SET status = 'ACTIVE', activated_by = :a, step = 2",
        a=world.users["hom.nbo"],
    )
    assert (await world.twin())["route"]["code"] == "A"
