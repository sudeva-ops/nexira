"""Supply Chain & Third-Party Risk (SUP-01..06; D-44; docs/plan-pilot-sup.md): the seeded
register and routes (§2); reported and shown statuses (§3: ROUTE BLOCKED, ALTERNATE, the worst
first); disruption from incidents (§4: the zone tag, "impacted", banners, SUPPLY timeline
entries on changes only, the fuel stock from Fleet); mitigations through approvals.py, once per
supplier, stood down once, nothing sent (§5); names by scope (§6); the simulated feeds and
SUPPLY_UPDATED with ids only. Against real PostgreSQL, as nexira_api."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.core.realtime import FORWARDED
from app.core.security import CurrentUser
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.supply import consumer
from app.modules.supply import service as supply
from app.modules.supply.service import RouteIn, SupplierIn
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

EPICENTRE = (-1.2838, 36.8245)
EMBASSY = (-1.2950, 36.8080)
JKIA = (-1.3192, 36.9278)
CAIRO = (30.0444, 31.2357)
TODAY = date.today()
VETTED = TODAY + timedelta(days=200)
ROAD_CLOSED = "Road closure CBD → JKIA; reroute via Southern Bypass, +55 min"


def pt(lat_lon: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({lat_lon[1]} {lat_lon[0]})"


def _register(nbo: uuid.UUID, cai: uuid.UUID) -> tuple[list[SupplierIn], list[RouteIn]]:
    suppliers = [
        # Backups listed after what they back up: ensure_register orders them.
        SupplierIn("SUP-104", "Swiftline Couriers", "Diplomatic pouch courier", nbo, 1, VETTED,
                   backup_code="SUP-105", in_bcp=True, performance_score=92),
        SupplierIn("SUP-105", "Falcon Express Couriers", "Diplomatic pouch courier", nbo, 2,
                   VETTED),
        SupplierIn("SUP-117", "Equator Guard Services", "Guard force contractor", nbo, 1, VETTED,
                   backup_code="SUP-118", in_bcp=True),
        SupplierIn("SUP-118", "Highland Guard Services", "Guard force contractor", nbo, 2, VETTED),
        SupplierIn("SUP-121", "Rift Valley Fuels", "Generator fuel supply", nbo, 2, VETTED,
                   backup_code="SUP-122"),
        SupplierIn("SUP-122", "Mara Energy Supplies", "Generator fuel supply", nbo, 2, VETTED),
        SupplierIn("SUP-130", "Kilima Catering", "Catering services", nbo, 3,
                   TODAY - timedelta(days=1)),  # vetting lapsed
        SupplierIn("SUP-233", "Nile Secure Mobility", "Armoured vehicle leasing", cai, 1, VETTED),
        SupplierIn("SUP-305", "Northbridge Translations", "Interpretation services", None, 3,
                   VETTED),
    ]  # fmt: skip
    via_cbd = (EMBASSY, (-1.2864, 36.8172), JKIA)
    bypass = (EMBASSY, (-1.3300, 36.8000), JKIA)
    routes = [
        RouteIn("R-NBO-2", nbo, "Pouch: Embassy → JKIA via Southern Bypass", "POUCH", bypass,
                "SUP-104", "R-NBO-1"),
        RouteIn("R-NBO-1", nbo, "Pouch: Embassy → JKIA via CBD", "POUCH", via_cbd, "SUP-104"),
        RouteIn("R-NBO-3", nbo, "Fuel: depot → Embassy", "FUEL",
                ((-1.3100, 36.8500), EMBASSY), "SUP-121"),
        RouteIn("R-NBO-4", nbo, "Staff shuttle: Westlands → Embassy", "STAFF_TRANSPORT",
                ((-1.2676, 36.8108), EMBASSY), "SUP-117"),
        RouteIn("R-CAI-1", cai, "Pouch: Embassy → CAI", "POUCH",
                (CAIRO, (30.1219, 31.4056)), "SUP-233"),
    ]  # fmt: skip
    return suppliers, routes


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    cai: uuid.UUID
    incident: uuid.UUID

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def get(self, who: str, url: str) -> Any:
        response = await self.client.get(url, headers=self.idp.headers(who))
        assert response.status_code == 200, response.text
        return response.json()

    async def send(self, who: str, url: str, body: Any = None) -> Any:
        return await self.client.post(url, json=body, headers=self.idp.headers(who))

    async def suppliers(self, who: str = "duty") -> dict[str, Any]:
        return {s["code"]: s for s in await self.get(who, "/api/supply/suppliers")}

    async def supplier_id(self, code: str) -> uuid.UUID:
        found: uuid.UUID = (
            await self.sql("SELECT id FROM supplier WHERE code = :c", c=code)
        ).scalar_one()
        return found

    async def routes(self) -> dict[str, Any]:
        return {r["code"]: r for r in await self.get("duty", "/api/supply/routes")}

    async def route(self, code: str, status: str, detail: str | None = None) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            outcome = await supply.route_status(session, code, status, detail)
            await session.commit()
        return outcome

    async def notice(self, code: str, status: str, detail: str | None = None) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            outcome = await supply.supplier_status(session, code, status, detail)
            await session.commit()
        return outcome

    async def timeline(self) -> list[str]:
        rows = await self.sql(
            "SELECT summary FROM incident_event WHERE event_type = 'SUPPLY' ORDER BY id"
        )
        return [r.summary for r in rows]

    async def actions(self) -> list[str]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog.action)
                    .where(AuditLog.action.like("SUPPLY.%"))
                    .order_by(AuditLog.id)
                )
            )

    async def disrupt(self) -> None:
        """NBO-SUPPLY scenes 1 and 2 (plan §8)."""
        await self.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
        await self.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
        await self.route("R-NBO-3", "DELAYED", "Delivery postponed 24 h")
        await self.notice(
            "SUP-117", "AT_RISK", "18:00 shift change: 6 guards must cross the impact zone"
        )
        await self.route("R-NBO-4", "RESTRICTED", "Restricted: route crosses the impact zone")

    async def permissions(self, who: str, code: str) -> tuple[bool, bool]:
        p = await self.get(
            who,
            f"/api/me/permissions?entity_type=supplier&entity_id={await self.supplier_id(code)}",
        )
        return p["activate_mitigation"], p["stand_down_mitigation"]


async def _mission(idp: Idp, code: str, city: str, at: tuple[float, float]) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :city, 'XX', :pt)"
            ),
            {"id": mission_id, "code": code, "city": city, "pt": pt(at)},
        )
        await session.commit()
    return mission_id


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo = await _mission(idp, "NBO", "Nairobi", EPICENTRE)
    cai = await _mission(idp, "CAI", "Cairo", CAIRO)
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "travel": [("TRAVEL_DESK", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        incident = await session.scalar(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id, status) VALUES (current_tenant_id(), "
                "'INC-2026-1042', 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', :pt, :m, "
                "'ACTIVE') RETURNING id"
            ),
            {"m": nbo, "pt": pt(EPICENTRE)},
        )
        await session.execute(
            text(
                "INSERT INTO fleet_asset (tenant_id, mission_id, code, kind, type_label, "
                "location, location_label, fuel_pct) VALUES (current_tenant_id(), :m, 'GEN-NBO', "
                "'EQUIPMENT', 'Generator 250 kVA', :pt, 'Embassy', 72)"
            ),
            {"m": nbo, "pt": pt(EMBASSY)},
        )
        suppliers, routes = _register(nbo, cai)
        assert await supply.ensure_register(session, suppliers, routes) == (9, 5)
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, cai, incident)


# --- the register (§2) ---------------------------------------------------------------------------


async def test_the_register_is_seeded_once(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        suppliers, routes = _register(world.nbo, world.cai)
        assert await supply.ensure_register(session, suppliers, routes) == (0, 0)
        await session.commit()
    assert await world.actions() == ["SUPPLY.SEED"]
    found = await world.suppliers()
    courier = found["SUP-104"]
    assert courier["backup"]["name"] == "Falcon Express Couriers"
    assert (courier["in_bcp"], courier["vetting_current"], courier["performance_score"]) == (
        True,
        True,
        92,
    )
    assert courier["source"] == "Illustrative supplier register (simulated)"
    assert found["SUP-130"]["vetting_current"] is False
    assert found["SUP-305"]["mission_code"] is None  # Global
    assert found["SUP-121"]["fuel_stock_hours"] == 72  # GEN-NBO 72% x 100 h (G-7)
    assert found["SUP-104"]["fuel_stock_hours"] is None  # not a fuel supplier


async def test_a_circular_backup_is_refused(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        with pytest.raises(ValueError, match="circular backups"):
            await supply.ensure_register(
                session,
                [
                    SupplierIn("SUP-401", "A", "x", world.nbo, 3, VETTED, backup_code="SUP-402"),
                    SupplierIn("SUP-402", "B", "x", world.nbo, 3, VETTED, backup_code="SUP-401"),
                ],
                [],
            )


async def test_before_any_disruption_nothing_is_impacted(world: World) -> None:
    summary = await world.get("viewer", "/api/supply/summary")
    assert summary == {
        "suppliers": 9,
        "missions": 2,
        "tier1": 3,
        "impacted": 0,
        "impacted_missions": [],
        "routes": 5,
        "banners": [],
    }
    found = await world.suppliers()
    assert {c: s["shown"] for c, s in found.items()} == {c: "NORMAL" for c in found}
    routes = await world.routes()
    assert {c: r["shown"] for c, r in routes.items()} == {c: "OPEN" for c in routes}
    # Every Nairobi route starts inside the 5 km zone: tagged, but the status stays (G-4).
    assert routes["R-NBO-1"]["zone_incidents"] == ["INC-2026-1042"]
    assert routes["R-CAI-1"]["zone_incidents"] == []
    assert routes["R-NBO-2"]["alternate_of_code"] == "R-NBO-1"


# --- statuses and disruption (§3, §4) -----------------------------------------------------------


async def test_a_blocked_route_makes_its_supplier_route_blocked_and_the_bypass_alternate(
    world: World,
) -> None:
    await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    found = await world.suppliers()
    courier = found["SUP-104"]
    assert (courier["status"], courier["shown"], courier["detail"]) == (
        "NORMAL",
        "ROUTE_BLOCKED",
        ROAD_CLOSED,
    )
    assert (courier["impacted"], courier["incident_reference"]) == (True, "INC-2026-1042")
    routes = await world.routes()
    assert (routes["R-NBO-1"]["shown"], routes["R-NBO-2"]["shown"]) == ("BLOCKED", "ALTERNATE")
    assert await world.timeline() == [
        "Nairobi · Pouch: Embassy → JKIA via CBD: BLOCKED "
        "(Road closure CBD → JKIA; reroute via Southern Bypass, +55 min)."
    ]


async def test_three_impacted_with_a_banner_then_recovery(world: World) -> None:
    await world.disrupt()
    summary = await world.get("viewer", "/api/supply/summary")
    assert (summary["impacted"], summary["impacted_missions"]) == (3, ["NBO"])
    [banner] = summary["banners"]
    assert (banner["incident_reference"], banner["mission_code"]) == ("INC-2026-1042", "NBO")
    assert [(s["code"], s["shown"]) for s in banner["suppliers"]] == [
        ("SUP-104", "ROUTE_BLOCKED"),
        ("SUP-117", "AT_RISK"),
        ("SUP-121", "DELAYED"),
    ]
    routes = await world.routes()
    assert routes["R-NBO-4"]["shown"] == "RESTRICTED"
    assert len(await world.timeline()) == 5
    for code in ("R-NBO-1", "R-NBO-3", "R-NBO-4"):
        await world.route(code, "OPEN")
    for code in ("SUP-117", "SUP-121"):
        await world.notice(code, "NORMAL")
    assert (await world.get("viewer", "/api/supply/summary"))["impacted"] == 0
    timeline = await world.timeline()
    assert len(timeline) == 10  # plan §8: 1 + 4 + 5
    assert timeline[-1] == "Nairobi · Rift Valley Fuels: NORMAL."


async def test_the_worst_status_wins(world: World) -> None:
    await world.notice("SUP-104", "WATCH", "Monitoring local disruption")
    assert (await world.suppliers())["SUP-104"]["shown"] == "WATCH"
    assert (await world.suppliers())["SUP-104"]["impacted"] is False  # WATCH does not impact
    await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    assert (await world.suppliers())["SUP-104"]["shown"] == "ROUTE_BLOCKED"
    await world.notice("SUP-117", "AT_RISK", "Shift change")
    await world.route("R-NBO-4", "BLOCKED", "Closed")
    guard = (await world.suppliers())["SUP-117"]
    assert (guard["shown"], guard["detail"]) == ("ROUTE_BLOCKED", "Closed")


async def test_only_a_mission_with_an_active_incident_is_impacted(world: World) -> None:
    await world.notice("SUP-233", "DELAYED", "Lease paperwork")  # Cairo: no incident
    await world.notice("SUP-305", "AT_RISK", "Interpreter shortage")  # Global
    found = await world.suppliers()
    assert (found["SUP-233"]["impacted"], found["SUP-305"]["impacted"]) == (False, False)
    assert await world.timeline() == []  # no ACTIVE incident at either
    await world.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
    await world.sql("UPDATE incident SET status = 'MONITORING' WHERE id = :i", i=world.incident)
    summary = await world.get("viewer", "/api/supply/summary")
    assert (summary["impacted"], summary["banners"]) == (0, [])
    routes = await world.routes()
    assert routes["R-NBO-1"]["zone_incidents"] == []  # the tag clears by itself


async def test_a_report_of_the_same_status_changes_nothing(world: World) -> None:
    await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    before = (await world.actions(), await world.timeline())
    outcome = await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    assert outcome.events == []
    assert (await world.actions(), await world.timeline()) == before
    # A new detail is audited, but only a change of status writes on the timeline.
    await world.route("R-NBO-1", "BLOCKED", "Still closed")
    assert (await world.actions())[-1] == "SUPPLY.ROUTE_STATUS"
    assert await world.timeline() == before[1]
    assert await world.route("R-XXX-1", "OPEN") is None
    assert await world.notice("SUP-999", "NORMAL") is None
    assert await world.route("R-NBO-1", "ALTERNATE") is None  # shown, never reported


# --- mitigation (§5) and names (§6) ------------------------------------------------------------


async def test_a_mitigation_records_the_backup_and_the_alternate(world: World) -> None:
    await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    courier = await world.supplier_id("SUP-104")
    url = f"/api/supply/suppliers/{courier}/mitigation"
    assert await world.permissions("duty", "SUP-104") == (True, False)
    for who in ("viewer", "travel", "hom.cai"):
        assert (await world.send(who, url, {})).status_code == 403, who
        assert await world.permissions(who, "SUP-104") == (False, False)
    response = await world.send("duty", url, {"note": "  Backup courier briefed  "})
    assert response.status_code == 201, response.text
    out = response.json()
    m = out["mitigation"]
    assert (m["backup"]["code"], m["route_code"], m["note"]) == (
        "SUP-105",
        "R-NBO-2",
        "Backup courier briefed",
    )
    assert (m["incident_reference"], m["activated_by_name"], m["active"]) == (
        "INC-2026-1042",
        "User duty",
        True,
    )
    assert (await world.send("security", url, {})).status_code == 409  # one active
    assert await world.permissions("duty", "SUP-104") == (False, True)
    assert (await world.timeline())[-1] == (
        "Nairobi · Swiftline Couriers: mitigation activated · backup Falcon Express Couriers "
        "on standby · Pouch: Embassy → JKIA via Southern Bypass in use."
    )
    viewer = (await world.suppliers("viewer"))["SUP-104"]["mitigation"]
    assert (viewer["activated_by_name"], viewer["active"]) == (None, True)
    stand_down = f"/api/supply/mitigations/{m['id']}/stand-down"
    assert (await world.send("viewer", stand_down)).status_code == 403
    response = await world.send("hom.nbo", stand_down)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["mitigation"] is None
    [history] = detail["mitigations"]
    assert (history["active"], history["stood_down_by_name"]) == (False, "User hom.nbo")
    assert (await world.send("duty", stand_down)).status_code == 409  # once
    assert (await world.timeline())[-1] == "Nairobi · Swiftline Couriers: mitigation stood down."
    assert (await world.send("duty", url, {})).status_code == 201  # a new one after
    assert [a for a in await world.actions() if "MITIGATION" in a] == [
        "SUPPLY.MITIGATION_ACTIVATED",
        "SUPPLY.MITIGATION_STOOD_DOWN",
        "SUPPLY.MITIGATION_ACTIVATED",
    ]


async def test_only_an_impacted_supplier_is_mitigated(world: World) -> None:
    for code in ("SUP-104", "SUP-233", "SUP-305"):
        url = f"/api/supply/suppliers/{await world.supplier_id(code)}/mitigation"
        assert (await world.send("duty", url, {})).status_code == 409, code
    unknown = f"/api/supply/suppliers/{uuid.uuid4()}/mitigation"
    assert (await world.send("duty", unknown, {})).status_code == 404
    long = {"note": "x" * 501}
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-121')}/mitigation"
    assert (await world.send("duty", url, long)).status_code == 422


async def test_a_mitigation_without_an_alternate_or_backup(world: World) -> None:
    await world.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-121')}/mitigation"
    m = (await world.send("security", url, {})).json()["mitigation"]
    assert (m["backup"]["name"], m["route_code"], m["note"]) == ("Mara Energy Supplies", None, None)
    assert (await world.timeline())[-1] == (
        "Nairobi · Rift Valley Fuels: mitigation activated · backup Mara Energy Supplies on "
        "standby."
    )


async def test_a_stand_down_after_the_incident_closed_writes_no_entry(world: World) -> None:
    await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-104')}/mitigation"
    m = (await world.send("duty", url, {})).json()["mitigation"]
    await world.sql("UPDATE incident SET status = 'CLOSED' WHERE id = :i", i=world.incident)
    entries = len(await world.timeline())
    response = await world.send("duty", f"/api/supply/mitigations/{m['id']}/stand-down")
    assert response.status_code == 200
    assert len(await world.timeline()) == entries
    [history] = response.json()["mitigations"]
    assert history["incident_reference"] == "INC-2026-1042"  # kept after the incident closed


async def test_nothing_is_sent(world: World) -> None:
    counts = (
        "SELECT (SELECT count(*) FROM notification_campaign) AS c, "
        "(SELECT count(*) FROM notification_delivery) AS d, "
        "(SELECT count(*) FROM partner_request) AS p"
    )
    before = tuple((await world.sql(counts)).one())
    await world.disrupt()
    for code in ("SUP-104", "SUP-117", "SUP-121"):
        url = f"/api/supply/suppliers/{await world.supplier_id(code)}/mitigation"
        assert (await world.send("duty", url, {})).status_code == 201
    assert tuple((await world.sql(counts)).one()) == before


# --- realtime and the feeds ---------------------------------------------------------------------


async def test_supply_updated_carries_ids_only(world: World) -> None:
    assert "SUPPLY_UPDATED" in FORWARDED
    outcome = await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)
    [event] = outcome.events
    assert set(event.payload) == {"supplier_id", "route_id", "change", "status"}
    assert event.payload["status"] == "BLOCKED"
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-104')}/mitigation"
    await world.send("duty", url, {})
    [published] = world.publisher.events
    assert published.type == "SUPPLY_UPDATED"
    assert "duty" not in repr(published.payload)


async def test_the_consumers_take_only_the_scenario_player(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    publisher = ListPublisher()
    routes = consumer.route_handler(world.idp.engine, publisher)
    notices = consumer.supplier_handler(world.idp.engine, publisher)
    tenant = world.idp.tenant_id
    good = {"route": "R-NBO-1", "status": "BLOCKED", "detail": ROAD_CLOSED}
    with caplog.at_level(logging.WARNING):
        await routes(Event("SUPPLY_ROUTE", tenant, good, "api"))
        await routes(Event("SUPPLY_ROUTE", tenant, {"route": "x"}, "scenario:NBO-SUPPLY:1"))
        unknown = {**good, "route": "R-ZZZ-1"}
        await routes(Event("SUPPLY_ROUTE", tenant, unknown, "scenario:NBO-SUPPLY:1"))
        late = {"supplier": "SUP-121", "status": "LATE"}
        await notices(Event("SUPPLY_SUPPLIER", tenant, late, "scenario:NBO-SUPPLY:1"))
    assert publisher.events == []
    for logged in ("ignored", "refused", "unknown route"):
        assert logged in caplog.text
    await routes(Event("SUPPLY_ROUTE", tenant, good, "scenario:NBO-SUPPLY:1"))
    await notices(
        Event(
            "SUPPLY_SUPPLIER",
            tenant,
            {"supplier": "SUP-121", "status": "DELAYED", "detail": "Fuel delivery postponed 24 h"},
            "scenario:NBO-SUPPLY:2",
        )
    )
    assert [e.payload["status"] for e in publisher.events] == ["BLOCKED", "DELAYED"]
    found = await world.suppliers()
    assert (found["SUP-104"]["shown"], found["SUP-121"]["shown"]) == ("ROUTE_BLOCKED", "DELAYED")
    assert await world.actions() == [
        "SUPPLY.SEED",
        "SUPPLY.ROUTE_STATUS",
        "SUPPLY.SUPPLIER_STATUS",
    ]


async def test_the_detail_lists_the_missions_routes(world: World) -> None:
    detail = await world.get(
        "viewer", f"/api/supply/suppliers/{await world.supplier_id('SUP-121')}"
    )
    assert [r["code"] for r in detail["routes"]] == ["R-NBO-1", "R-NBO-2", "R-NBO-3", "R-NBO-4"]
    assert detail["mitigations"] == []
    response = await world.client.get(
        f"/api/supply/suppliers/{uuid.uuid4()}", headers=world.idp.headers("viewer")
    )
    assert response.status_code == 404
    cairo = await world.get("viewer", f"/api/supply/suppliers?mission_id={world.cai}")
    assert [s["code"] for s in cairo] == ["SUP-233"]


# --- review of Prompt 91 -----------------------------------------------------------------------


async def _current(world: World, sub: str) -> CurrentUser:
    row = (
        await world.sql(
            "SELECT id, email, display_name FROM app_user WHERE external_id = :s", s=sub
        )
    ).one()
    return CurrentUser(
        id=row.id,
        tenant_id=world.idp.tenant_id,
        external_id=sub,
        email=row.email,
        display_name=row.display_name,
    )


async def test_an_activation_waiting_on_a_recovery_sees_it(world: World) -> None:
    """M1: the supplier is re-read under the lock, so a status a feed changed while the
    activation waited counts: the recovered supplier is no longer impacted (409)."""
    await world.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
    supplier_id = await world.supplier_id("SUP-121")
    duty = await _current(world, "duty")
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as feed:
        await supply.supplier_status(feed, "SUP-121", "NORMAL", None)  # holds the row lock

        async def activation() -> Any:
            async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
                return await supply.activate(session, duty, TODAY, supplier_id, None)

        waiting = asyncio.create_task(activation())
        await asyncio.sleep(0.5)  # loaded DELAYED, now waits on the lock
        assert not waiting.done()
        await feed.commit()
    with pytest.raises(supply.SupplyError) as refused:
        await waiting
    assert refused.value.status_code == 409
    assert (await world.sql("SELECT count(*) FROM supply_mitigation")).scalar_one() == 0


async def test_two_activations_at_once_record_one(world: World) -> None:
    await world.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-121')}/mitigation"
    results = await asyncio.gather(world.send("duty", url, {}), world.send("security", url, {}))
    assert sorted(r.status_code for r in results) == [201, 409]
    assert (await world.sql("SELECT count(*) FROM supply_mitigation")).scalar_one() == 1


async def test_who_may_act_and_who_sees_names(world: World, idp: Idp) -> None:
    await idp.user("nobody", [])
    await world.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-121')}/mitigation"
    assert (await world.send("nobody", url, {})).status_code == 403
    response = await world.send("hom.nbo", url, {})
    assert response.status_code == 201, response.text
    stand_down = f"/api/supply/mitigations/{response.json()['mitigation']['id']}/stand-down"
    for who in ("hom.cai", "travel", "nobody", "viewer"):
        assert (await world.send(who, stand_down)).status_code == 403, who
    assert (await world.send("duty", stand_down)).status_code == 200
    for who, activated, stood_down in (
        ("hom.nbo", "User hom.nbo", "User duty"),
        ("duty", "User hom.nbo", "User duty"),
        ("hom.cai", None, None),  # a name reader, but not for Nairobi
        ("viewer", None, None),
    ):
        detail = await world.get(who, f"/api/supply/suppliers/{await world.supplier_id('SUP-121')}")
        [m] = detail["mitigations"]
        assert (m["activated_by_name"], m["stood_down_by_name"]) == (activated, stood_down), who
    # The audit and the timeline record who acted by user id, as everywhere else (D-20); never
    # a name (review L1).
    rows = await world.sql(
        "SELECT actor_id, details::text AS details FROM audit_log "
        "WHERE action LIKE 'SUPPLY.MITIGATION%' ORDER BY id"
    )
    for row in rows:
        assert "User " not in row.details
        uuid.UUID(row.actor_id)
    summaries = await world.timeline()
    assert not any("User " in summary for summary in summaries)


async def test_a_global_supplier_running_a_route_shows_it(world: World) -> None:
    """L3."""
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        await supply.ensure_register(
            session,
            [],
            [
                RouteIn(
                    "R-NBO-9",
                    world.nbo,
                    "Interpreters: hotel → Embassy",
                    "STAFF_TRANSPORT",
                    ((-1.2975, 36.8240), EMBASSY),
                    "SUP-305",
                )
            ],
        )
        await session.commit()
    await world.route("R-NBO-9", "BLOCKED", "Closed")
    global_id = await world.supplier_id("SUP-305")
    detail = await world.get("viewer", f"/api/supply/suppliers/{global_id}")
    assert (detail["shown"], detail["impacted"]) == ("ROUTE_BLOCKED", False)  # no mission
    assert [r["code"] for r in detail["routes"]] == ["R-NBO-9"]


async def test_every_supply_event_carries_ids_and_statuses_only(world: World) -> None:
    events = [
        *(await world.route("R-NBO-1", "BLOCKED", ROAD_CLOSED)).events,
        *(await world.notice("SUP-121", "DELAYED", "Fuel delivery postponed 24 h")).events,
    ]
    url = f"/api/supply/suppliers/{await world.supplier_id('SUP-104')}/mitigation"
    mitigation = (await world.send("duty", url, {})).json()["mitigation"]
    await world.send("duty", f"/api/supply/mitigations/{mitigation['id']}/stand-down")
    events += world.publisher.events
    assert [e.payload["change"] for e in events] == [
        "route",
        "supplier",
        "mitigation",
        "mitigation",
    ]
    for event in events:
        assert event.type == "SUPPLY_UPDATED"
        assert set(event.payload) == {"supplier_id", "route_id", "change", "status"}
        for key in ("supplier_id", "route_id"):
            if event.payload[key] is not None:
                uuid.UUID(event.payload[key])
        assert event.payload["status"] in (None, "BLOCKED", "DELAYED")
