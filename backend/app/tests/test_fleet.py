"""Fleet & Assets (FLT-01..07; D-41; docs/plan-pilot-flt.md): the seeded register (§2); the
derived states (§3: maintenance, blocked by the driver's SOS, in an impact zone unless at a
mission site (G-1), assigned to an ACTIVE evacuation); capacity with a partner suggestion
(§4); maintenance and status through approvals.py (§5); simulated telematics with FLEET
timeline entries on crossings and the simulated workshop (§6); driver names by scope (§7,
G-8); permissions. Against real PostgreSQL, as nexira_api."""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.fleet import consumer
from app.modules.fleet import service as fleet
from app.modules.fleet.service import AssetIn, ItemIn
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

# Nairobi as the seed (plan §2): the epicentre, the embassy and residence sites, and the
# driver's position, all inside the 5 km zone; the sites make their vehicles "at site" (G-1).
EPICENTRE = (-1.2838, 36.8245)
EMBASSY = (-1.2950, 36.8080)
RESIDENCE = (-1.2745, 36.7935)
ROAD = (-1.2985, 36.8195)  # Haile Selassie Ave
CBD = (-1.2860, 36.8200)  # Uhuru Highway, off any site
CAIRO = (30.0444, 31.2357)


def pt(lat_lon: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({lat_lon[1]} {lat_lon[0]})"


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    cai: uuid.UUID
    incident: uuid.UUID
    driver: uuid.UUID

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def get(self, who: str, url: str) -> Any:
        response = await self.client.get(url, headers=self.idp.headers(who))
        assert response.status_code == 200, response.text
        return response.json()

    async def send(self, who: str, method: str, url: str, body: Any = None) -> Any:
        return await self.client.request(method, url, json=body, headers=self.idp.headers(who))

    async def assets(self, who: str = "duty", mission: uuid.UUID | None = None) -> dict[str, Any]:
        query = f"?mission_id={mission}" if mission else ""
        return {a["code"]: a for a in await self.get(who, f"/api/fleet/assets{query}")}

    async def states(self) -> dict[str, list[str]]:
        return {c: [t["code"] for t in a["tags"]] for c, a in (await self.assets()).items()}

    async def mission(self, mission: uuid.UUID | None = None) -> Any:
        return await self.get("duty", f"/api/fleet/missions/{mission or self.nbo}")

    async def actions(self, prefix: str) -> list[str]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog.action)
                    .where(AuditLog.action.like(f"{prefix}%"))
                    .order_by(AuditLog.id)
                )
            )

    async def user_id(self, sub: str) -> uuid.UUID:
        found: uuid.UUID = (
            await self.sql("SELECT id FROM app_user WHERE external_id = :s", s=sub)
        ).scalar_one()
        return found

    async def position(self, code: str, at: tuple[float, float], label: str) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            outcome = await fleet.position(session, code, at[0], at[1], label, 60)
            await session.commit()
        return outcome

    async def timeline(self) -> list[str]:
        rows = await self.sql(
            "SELECT summary FROM incident_event WHERE event_type = 'FLEET' ORDER BY id"
        )
        return [r.summary for r in rows]


async def _mission(idp: Idp, code: str, city: str, country: str, at: tuple[float, float]) -> Any:
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


def _register(nbo: uuid.UUID, cai: uuid.UUID, driver: uuid.UUID) -> list[AssetIn]:
    lat, lon = EMBASSY
    suv = ("VEHICLE", "Armoured SUV (B6)")
    return [
        AssetIn(nbo, "VH-01", *suv, lat, lon, "Embassy garage", 82, armoured=True, seats=4),
        AssetIn(
            nbo,
            "VH-02",
            *suv,
            ROAD[0],
            ROAD[1],
            "Haile Selassie Ave",
            46,
            armoured=True,
            seats=4,
            driver_id=driver,
            status="IN_USE",
        ),
        AssetIn(
            nbo,
            "VH-03",
            "VEHICLE",
            "Minibus 14-seat",
            lat,
            lon,
            "Embassy garage",
            90,
            seats=13,
            items=(ItemIn("Oil change", 30),),
        ),
        AssetIn(
            nbo,
            "VH-04",
            "VEHICLE",
            "Pickup 4x4",
            RESIDENCE[0],
            RESIDENCE[1],
            "Residence",
            64,
            seats=3,
        ),
        AssetIn(
            nbo,
            "VH-05",
            "VEHICLE",
            "Sedan (official)",
            lat,
            lon,
            "Workshop",
            30,
            seats=3,
            status="MAINTENANCE",
            status_reason="Brake service overdue",
            items=(ItemIn("Brake service", -3),),
        ),
        AssetIn(
            nbo,
            "GEN-NBO",
            "EQUIPMENT",
            "Generator 250 kVA",
            lat,
            lon,
            "Embassy",
            72,
            items=(ItemIn("Load test", 10),),
        ),
        AssetIn(
            cai, "VH-31", "VEHICLE", "Sedan (official)", CAIRO[0], CAIRO[1], "Garage", 70, seats=3
        ),
    ]


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo = await _mission(idp, "NBO", "Nairobi", "KE", EPICENTRE)
    cai = await _mission(idp, "CAI", "Cairo", "EG", CAIRO)
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "travel": [("TRAVEL_DESK", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "hq": [("HQ_CRISIS_DIRECTOR", None)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for site_type, at in (("EMBASSY", EMBASSY), ("RESIDENCE", RESIDENCE)):
            await session.execute(
                text(
                    "INSERT INTO site (tenant_id, mission_id, site_type, name, location) "
                    "VALUES (current_tenant_id(), :m, :t, :t, :pt)"
                ),
                {"m": nbo, "t": site_type, "pt": pt(at)},
            )
        people = {}
        for ptype, name in (
            ("LOCAL_STAFF", "Fictional Driver"),
            ("DIPLOMAT", "Fictional Diplomat A"),
            ("DIPLOMAT", "Fictional Diplomat B"),
            ("DELEGATE", "Fictional Delegate"),
            ("DEPENDANT", "Fictional Child"),
            ("CITIZEN", "Fictional Citizen"),  # not part of road capacity (§4)
        ):
            people[name] = await session.scalar(
                text(
                    "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
                    "VALUES (current_tenant_id(), :m, :t, :n) RETURNING id"
                ),
                {"m": nbo, "t": ptype, "n": name},
            )
        incident = await session.scalar(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id, status) VALUES (current_tenant_id(), "
                "'INC-2026-1042', 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', :pt, :m, "
                "'ACTIVE') RETURNING id"
            ),
            {"m": nbo, "pt": pt(EPICENTRE)},
        )
        for code, name, services, coverage in (
            ("SEN", "Sentinel Secure Transport (simulated)", ["SECURE_TRANSPORT"], ["KE", "EG"]),
            ("KES", "Kestrel Medical (simulated)", ["MEDICAL"], ["KE", "EG", "PK"]),
        ):
            await session.execute(
                text(
                    "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
                    "VALUES (current_tenant_id(), :c, :n, :s, :cov, 30)"
                ),
                {"c": code, "n": name, "s": services, "cov": coverage},
            )
        driver = people["Fictional Driver"]
        assert await fleet.ensure_assets(session, _register(nbo, cai, driver), date.today()) == 7
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, cai, incident, driver)


async def _checkin(world: World, answer: str) -> None:
    """The driver's answer in the incident's check-in (G-2)."""
    campaign = await world.sql("SELECT id FROM notification_campaign WHERE reference = 'NTF-3001'")
    campaign_id = campaign.scalar()
    if campaign_id is None:
        campaign_id = (
            await world.sql(
                "INSERT INTO notification_campaign (tenant_id, reference, incident_id, "
                "campaign_type, message, channels, created_by_type, status) VALUES "
                "(current_tenant_id(), 'NTF-3001', :i, 'CHECKIN', 'Are you safe?', '{APP}', "
                "'PLAYBOOK', 'SENDING') RETURNING id",
                i=world.incident,
            )
        ).scalar_one()
    await world.sql(
        "INSERT INTO checkin_response (tenant_id, campaign_id, person_id, status) "
        "VALUES (current_tenant_id(), :c, :p, :s)",
        c=campaign_id,
        p=world.driver,
        s=answer,
    )


async def _activate_evacuation(world: World) -> str:
    """An ACTIVE evacuation at Nairobi, as two people activate it (D-40), with its manifest."""
    hom, hq = await world.user_id("hom.nbo"), await world.user_id("hq")
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        plan = await session.scalar(
            text(
                "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
                "muster_location, route_label, destination, options) VALUES (current_tenant_id(), "
                ":m, 'EVP-NBO', 'Embassy courtyard', :pt, 'Route B', 'Dubai', "
                '\'[{"role": "PRIMARY", "kind": "CHARTER", "label": "C", "seats": 72}]\')'
                " RETURNING id"
            ),
            {"m": world.nbo, "pt": pt(EMBASSY)},
        )
        evacuation = await session.scalar(
            text(
                "INSERT INTO evacuation (tenant_id, reference, plan_id, mission_id, incident_id, "
                "requested_by, requested_role) VALUES (current_tenant_id(), 'EVN-1001', :p, :m, "
                ":i, :u, 'HEAD_OF_MISSION') RETURNING id"
            ),
            {"p": plan, "m": world.nbo, "i": world.incident, "u": hom},
        )
        await session.execute(
            text("UPDATE evacuation SET status = 'ACTIVE', activated_by = :u, step = 2"),
            {"u": hq},
        )
        await session.execute(
            text(
                "INSERT INTO evacuation_manifest (tenant_id, evacuation_id, person_id, category) "
                "SELECT current_tenant_id(), :e, id, CASE person_type WHEN 'DIPLOMAT' THEN 'STAFF' "
                "ELSE person_type END FROM person WHERE mission_id = :m "
                "AND person_type IN ('DIPLOMAT', 'DELEGATE', 'DEPENDANT', 'CITIZEN')"
            ),
            {"e": evacuation, "m": world.nbo},
        )
        await session.commit()
    return "EVN-1001"


# --- the register and the seed (FLT-01, §2) ----------------------------------------------------


async def test_the_register_is_seeded_once_and_labelled_simulated(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert (
            await fleet.ensure_assets(
                session, _register(world.nbo, world.cai, world.driver), date.today()
            )
            == 0
        )
        await session.commit()
    assert await world.actions("FLEET.SEED") == ["FLEET.SEED"]
    assets = await world.assets()
    assert list(assets) == ["VH-01", "VH-02", "VH-03", "VH-04", "VH-05", "GEN-NBO", "VH-31"]
    vh02 = assets["VH-02"]
    assert (vh02["type_label"], vh02["seats"], vh02["armoured"], vh02["fuel_pct"]) == (
        "Armoured SUV (B6)",
        4,
        True,
        46,
    )
    assert (vh02["location_label"], round(vh02["lat"], 4), round(vh02["lon"], 4)) == (
        "Haile Selassie Ave",
        ROAD[0],
        ROAD[1],
    )
    assert all(a["simulated"] and a["source"].endswith("(simulated)") for a in assets.values())
    assert list(await world.assets(mission=world.cai)) == ["VH-31"]


# --- the derived states (FLT-02, §3, G-1, G-2) --------------------------------------------------


async def test_vehicles_at_a_mission_site_are_not_in_the_zone_and_on_the_road_they_are(
    world: World,
) -> None:
    assets = await world.assets()
    assert (await world.states()) == {
        "VH-01": [],
        "VH-02": ["IN_ZONE"],  # on the road inside INC-1042's zone
        "VH-03": [],  # in the embassy garage: at site (G-1)
        "VH-04": [],  # at the residence: at site
        "VH-05": ["MAINTENANCE"],
        "GEN-NBO": [],
        "VH-31": [],
    }
    assert assets["VH-02"]["state"] == {"code": "IN_ZONE", "reference": "INC-2026-1042"}
    assert [assets[c]["at_site"] for c in ("VH-01", "VH-02", "VH-04")] == [True, False, True]
    assert assets["VH-01"]["state"] == {"code": "AVAILABLE", "reference": None}
    assert (await world.mission())["available"] == 3
    # The incident no longer ACTIVE: VH-02 is IN USE and available again, by itself (§58 Q3).
    await world.sql("UPDATE incident SET status = 'MONITORING'")
    after = await world.assets()
    assert (after["VH-02"]["state"]["code"], after["VH-02"]["available"]) == ("IN_USE", True)
    assert ((await world.mission())["available"], (await world.mission())["vehicles"]) == (4, 5)


async def test_the_drivers_sos_blocks_the_vehicle_until_they_answer_safe(world: World) -> None:
    await _checkin(world, "NEED_HELP")
    vh02 = (await world.assets())["VH-02"]
    assert [t["code"] for t in vh02["tags"]] == ["BLOCKED", "IN_ZONE"]
    assert vh02["state"] == {"code": "BLOCKED", "reference": "INC-2026-1042"}
    assert vh02["available"] is False
    await _checkin(world, "SAFE")  # the latest answer counts
    assert (await world.states())["VH-02"] == ["IN_ZONE"]


async def test_vehicles_are_assigned_to_an_active_evacuation(world: World) -> None:
    await _checkin(world, "NEED_HELP")
    reference = await _activate_evacuation(world)
    assets = await world.assets()
    assigned = [c for c, a in assets.items() if a["state"]["code"] == "ASSIGNED"]
    assert assigned == ["VH-01", "VH-03", "VH-04"]  # not blocked, in maintenance or equipment
    assert assets["VH-01"]["state"]["reference"] == reference
    assert assets["VH-01"]["available"] is True
    assert assets["VH-31"]["state"]["code"] == "AVAILABLE"  # another mission's
    for _ in range(3):  # steps 3 to 5; arrival completes it
        await world.sql("UPDATE evacuation SET step = step + 1")
    await world.sql("UPDATE evacuation SET status = 'COMPLETED', step = 6")
    assert (await world.assets())["VH-01"]["state"]["code"] == "AVAILABLE"  # clears by itself


# --- capacity (FLT-03, §4) ------------------------------------------------------------------------


async def test_capacity_counts_available_seats_against_the_mission_people(world: World) -> None:
    capacity = (await world.mission())["capacity"]
    # VH-01 4 + VH-03 13 + VH-04 3 (VH-02 in the zone, VH-05 in maintenance) against
    # 2 diplomats, a delegate and a dependant; citizens are not driven (§4).
    assert capacity == {
        "seats_available": 20,
        "seats_needed": 4,
        "needed_from": "PEOPLE",
        "evacuation_reference": None,
        "shortfall": 0,
        "suggestion": None,
    }
    await _activate_evacuation(world)
    capacity = (await world.mission())["capacity"]
    assert (
        capacity["seats_needed"],
        capacity["needed_from"],
        capacity["evacuation_reference"],
    ) == (
        4,
        "EVACUATION",
        "EVN-1001",
    )
    generator = (await world.mission())["generator_fuel_pct"]
    assert generator == 72


async def test_a_shortfall_suggests_a_secure_transport_partner_and_requests_nothing(
    world: World,
) -> None:
    for n in range(5):
        await world.sql(
            "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
            "VALUES (current_tenant_id(), :m, 'DIPLOMAT', :n)",
            m=world.cai,
            n=f"Fictional Cairo Diplomat {n}",
        )
    capacity = (await world.mission(world.cai))["capacity"]
    assert (capacity["seats_available"], capacity["seats_needed"], capacity["shortfall"]) == (
        3,
        5,
        2,
    )
    assert capacity["suggestion"]["partner_name"] == "Sentinel Secure Transport (simulated)"
    assert (await world.sql("SELECT count(*) FROM partner_request")).scalar() == 0
    # No secure-transport partner covers Pakistan: no suggestion.
    await world.sql("UPDATE mission SET country_code = 'PK' WHERE code = 'CAI'")
    assert (await world.mission(world.cai))["capacity"]["suggestion"] is None


# --- who sees what (FLT-07, G-8) ----------------------------------------------------------------


async def test_driver_names_only_within_the_people_scope(world: World) -> None:
    for who, sees in (
        ("duty", True),
        ("security", True),
        ("consular", True),
        ("hq", True),
        ("hom.nbo", True),
        ("hom.cai", False),  # another mission's Head of Mission
        ("viewer", False),
        ("travel", False),
    ):
        vh02 = (await world.assets(who))["VH-02"]
        assert vh02["driver_assigned"] is True, who
        assert vh02["driver_name"] == ("Fictional Driver" if sees else None), who
        assert vh02["state"]["code"] == "IN_ZONE", who  # everyone sees the state


# --- status and maintenance (FLT-04, §5) ---------------------------------------------------------


async def test_responders_set_a_vehicles_status_with_a_reason_for_maintenance(
    world: World,
) -> None:
    vh03 = (await world.assets())["VH-03"]["id"]
    url = f"/api/fleet/assets/{vh03}/status"
    body = {"status": "MAINTENANCE", "reason": "Tyre puncture"}
    for who in ("viewer", "travel", "consular", "hq", "hom.cai"):
        refused = await world.send(who, "PATCH", url, body)
        assert refused.status_code == 403, who
    assert "SECURITY_OFFICER, DUTY_OFFICER or HEAD_OF_MISSION" in refused.json()["detail"]
    done = await world.send("security", "PATCH", url, body)
    assert done.status_code == 200, done.text
    assert (done.json()["state"]["code"], done.json()["status_reason"]) == (
        "MAINTENANCE",
        "Tyre puncture",
    )
    assert (await world.send("security", "PATCH", url, body)).status_code == 409
    back = await world.send("hom.nbo", "PATCH", url, {"status": "AVAILABLE"})
    assert (back.status_code, back.json()["status_reason"]) == (200, None)
    assert await world.actions("FLEET.STATUS") == ["FLEET.STATUS", "FLEET.STATUS"]
    assert [e.type for e in world.publisher.events] == ["FLEET_UPDATED", "FLEET_UPDATED"]
    assert "name" not in str(world.publisher.events[0].payload)


@pytest.mark.parametrize(
    ("code", "body", "status"),
    [
        ("VH-03", {"status": "MAINTENANCE"}, 422),  # needs a reason
        ("VH-03", {"status": "AVAILABLE", "reason": "x"}, 422),  # a reason only for maintenance
        ("GEN-NBO", {"status": "IN_USE"}, 422),  # only a vehicle is in use
        ("VH-03", {"status": "BLOCKED"}, 422),  # derived, never set (§58 Q3)
        ("VH-03", {"status": "AVAILABLE", "driver": "x"}, 422),
    ],
)
async def test_a_status_change_is_checked(
    world: World, code: str, body: dict[str, Any], status: int
) -> None:
    asset = (await world.assets())[code]["id"]
    response = await world.send("duty", "PATCH", f"/api/fleet/assets/{asset}/status", body)
    assert response.status_code == status, response.text


async def test_maintenance_alerts_and_marking_an_item_done(world: World) -> None:
    items = {m["task"]: m for m in await world.get("viewer", "/api/fleet/maintenance")}
    assert [(t, m["alert"], m["overdue"]) for t, m in items.items()] == [
        ("Brake service", True, True),
        ("Load test", True, False),
        ("Oil change", False, False),  # in 30 days: not yet an alert (§58 Q6)
    ]
    summary = await world.get("viewer", "/api/fleet/summary")
    assert summary == {"vehicles": 6, "armoured": 2, "average_fuel_pct": 65, "maintenance_due": 2}
    url = f"/api/fleet/maintenance/{items['Brake service']['id']}/done"
    for who in ("viewer", "hom.cai", "consular"):
        assert (await world.send(who, "POST", url)).status_code == 403, who
    done = await world.send("duty", "POST", url)
    assert done.status_code == 200, done.text
    assert (done.json()[0]["alert"], done.json()[0]["done_by_type"]) == (False, "USER")
    assert (await world.send("duty", "POST", url)).status_code == 409
    done_by = (
        await world.sql("SELECT done_by FROM fleet_maintenance WHERE done_at IS NOT NULL")
    ).scalar()
    assert done_by == str(await world.user_id("duty"))  # the caller, never on behalf (L4)
    # The vehicle's status stays: a person sets it separately (G-7).
    assert (await world.assets())["VH-05"]["state"]["code"] == "MAINTENANCE"
    assert (await world.get("viewer", "/api/fleet/summary"))["maintenance_due"] == 1
    assert await world.actions("FLEET.MAINTENANCE") == ["FLEET.MAINTENANCE_DONE"]
    missing = await world.send("duty", "POST", f"/api/fleet/maintenance/{uuid.uuid4()}/done")
    assert missing.status_code == 404


async def test_permissions_follow_the_endpoints_check(world: World) -> None:
    for who, allowed in (
        ("duty", True),
        ("security", True),
        ("hom.nbo", True),
        ("hom.cai", False),
        ("consular", False),
        ("viewer", False),
    ):
        got = await world.get(who, f"/api/me/permissions?entity_type=fleet&entity_id={world.nbo}")
        assert (got["set_asset_status"], got["complete_maintenance"]) == (allowed, allowed), who
    assert (
        await world.get("hom.cai", f"/api/me/permissions?entity_type=fleet&entity_id={world.cai}")
    )["set_asset_status"]


# --- telematics and the workshop (FLT-05, §6) ----------------------------------------------------


async def test_a_vehicle_crossing_the_zone_writes_timeline_entries(world: World) -> None:
    outcome = await world.position("VH-04", CBD, "Uhuru Highway")
    assert outcome is not None
    assert outcome.events[0].payload["incident_ids"] == [str(world.incident)]
    assert (await world.states())["VH-04"] == ["IN_ZONE"]
    await world.position("VH-04", CBD, "Uhuru Highway")  # still inside: no new entry (G-4)
    await world.position("VH-04", RESIDENCE, "Ambassador's Residence")
    assert await world.timeline() == [
        "VH-04 entered the impact zone of INC-2026-1042 · Uhuru Highway.",
        "VH-04 left the impact zone of INC-2026-1042 · Ambassador's Residence.",
    ]
    assert (await world.states())["VH-04"] == []
    assert await world.actions("FLEET.POSITION") == ["FLEET.POSITION"] * 3  # G-5
    actors = await world.sql(
        "SELECT DISTINCT actor_type, actor_id FROM incident_event WHERE event_type = 'FLEET'"
    )
    assert [tuple(r) for r in actors] == [("SYSTEM", "telematics (simulated)")]


async def test_positions_without_an_active_incident_make_no_entries(world: World) -> None:
    await world.sql("UPDATE incident SET status = 'MONITORING'")
    await world.position("VH-04", CBD, "Uhuru Highway")
    assert await world.timeline() == []
    assert await world.position("VH-99", CBD, "Nowhere") is None


async def test_the_simulated_workshop_returns_a_vehicle(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await fleet.workshop_done(session, "VH-05", "Brake service") is not None
        assert await fleet.workshop_done(session, "VH-05", "Brake service") is None  # done
        assert await fleet.workshop_done(session, "VH-05", "Respray") is None  # no such item
        await session.commit()
    vh05 = (await world.assets())["VH-05"]
    assert (vh05["state"]["code"], vh05["status_reason"], vh05["available"]) == (
        "AVAILABLE",
        None,
        True,
    )
    row = (
        await world.sql(
            "SELECT done_by_type, done_by FROM fleet_maintenance WHERE done_at IS NOT NULL"
        )
    ).one()
    assert tuple(row) == ("WORKSHOP", "workshop (simulated)")
    assert await world.actions("FLEET.") == ["FLEET.SEED", "FLEET.MAINTENANCE_DONE", "FLEET.STATUS"]
    assert (await world.mission())["capacity"]["seats_available"] == 23


async def test_the_worker_handlers_validate_and_publish(world: World) -> None:
    publisher = ListPublisher()
    on_position = consumer.position_handler(world.idp.engine, publisher)
    on_workshop = consumer.workshop_handler(world.idp.engine, publisher)

    def event(event_type: str, payload: dict[str, Any]) -> Event:
        return Event(type=event_type, tenant_id=world.idp.tenant_id, payload=payload, source="test")

    await on_position(event("VEHICLE_POSITION", {"asset_code": "VH-04", "lat": 99, "lon": 0}))
    await on_position(
        event(
            "VEHICLE_POSITION",
            {
                "asset_code": "VH-04",
                "lat": CBD[0],
                "lon": CBD[1],
                "label": "Uhuru Highway",
                "fuel_pct": 62,
            },
        )
    )
    await on_workshop(event("WORKSHOP_DONE", {"asset_code": "VH-05", "task": "Brake service"}))
    await on_workshop(event("WORKSHOP_DONE", {"asset_code": "nope"}))
    assert [(e.type, e.payload["change"]) for e in publisher.events] == [
        ("FLEET_UPDATED", "position"),
        ("FLEET_UPDATED", "maintenance"),
    ]
    assert (await world.assets())["VH-04"]["fuel_pct"] == 62
