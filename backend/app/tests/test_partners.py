"""Assistance partners: the simulated adapter, requests and their roles, the worker's tick,
the SOS suggestion, coverage and PB-07's standby step (Prompt 45; AS-01..08, D-36,
docs/plan-pilot-ast.md). Time is passed in, so every move is exact."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident
from app.modules.partners import service
from app.modules.partners.adapter import (
    Pending,
    SimulatedPartnerAdapter,
    UnsupportedPartnerAdapterError,
    adapter_for,
)
from app.modules.partners.models import PartnerRequest
from app.modules.partners.service import PartnerIn
from app.modules.tenancy.service import Actor
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

T0 = datetime(2026, 10, 30, 6, 0, tzinfo=UTC)
ADAPTER = SimulatedPartnerAdapter()

# --- the simulated partner (AS-04, plan §3) ---------------------------------------------------


def pending(status: str = "REQUESTED", incident: bool = True, **change: Any) -> Pending:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "status": status,
        "sla_minutes": 30,
        "has_incident": incident,
        "requested_at": T0,
        "accepted_at": T0 + timedelta(seconds=20) if status == "ACCEPTED" else None,
        **change,
    }
    return Pending(**values)


def test_accepts_within_5_to_15_seconds_with_an_eta_from_the_sla() -> None:
    for _ in range(200):
        request = pending()
        delay = ADAPTER.accept_after(request.id)
        assert timedelta(seconds=5) <= delay < timedelta(seconds=15)
        assert ADAPTER.respond(request, T0 + delay - timedelta(milliseconds=1)) is None
        moment = T0 + delay
        response = ADAPTER.respond(request, moment)
        assert response is not None
        assert (response.status, response.eta) == ("ACCEPTED", moment + timedelta(minutes=30))
        assert ADAPTER.respond(request, moment) == response  # the same answer again


def test_goes_en_route_10_seconds_after_accepting_and_never_completes() -> None:
    accepted = pending("ACCEPTED")
    assert accepted.accepted_at is not None
    assert ADAPTER.respond(accepted, accepted.accepted_at + timedelta(seconds=9)) is None
    response = ADAPTER.respond(accepted, accepted.accepted_at + timedelta(seconds=10))
    assert response is not None
    assert response.status == "EN_ROUTE"
    for status in ("EN_ROUTE", "COMPLETED", "DECLINED", "CANCELLED"):
        assert ADAPTER.respond(pending(status), T0 + timedelta(days=1)) is None


def test_declines_about_1_in_10_ad_hoc_requests_and_never_one_about_an_incident() -> None:
    """§33 Q4, plan G-2: the demo's requests name their incident, so none is declined."""
    later = T0 + timedelta(minutes=1)
    ad_hoc = [ADAPTER.respond(pending(incident=False), later) for _ in range(2000)]
    declined = sum(1 for r in ad_hoc if r is not None and r.status == "DECLINED")
    assert 120 <= declined <= 280
    about_incidents = [ADAPTER.respond(pending(incident=True), later) for _ in range(2000)]
    assert {r.status for r in about_incidents if r is not None} == {"ACCEPTED"}


def test_only_the_simulated_adapter_is_available() -> None:
    assert adapter_for().name == "simulated"
    with pytest.raises(UnsupportedPartnerAdapterError):
        adapter_for("kestrel-api")


# --- requests through the API -----------------------------------------------------------------

PARTNERS = [
    PartnerIn("KES", "Kestrel Medical Assistance", ["MEDICAL"], ["KE", "FR"], 15),
    PartnerIn("SEN", "Sentinel Secure Transport", ["SECURE_TRANSPORT"], ["KE"], 30),
    PartnerIn("MER", "Meridian Relocation", ["RELOCATION", "SECURE_TRANSPORT"], ["KE", "FR"], 60),
]


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    par: uuid.UUID
    peter: uuid.UUID
    incident: uuid.UUID
    partners: dict[str, uuid.UUID]

    async def sql(self, query: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(query), params)
            rows = result.all() if query.lstrip().upper().startswith("SELECT") else []
            await session.commit()
            return rows

    async def post(self, who: str, path: str, **body: Any) -> Any:
        return await self.client.post(path, json=body, headers=self.idp.headers(who))

    async def ask(self, who: str = "duty", **body: Any) -> Any:
        values = {
            "partner_id": str(self.partners["SEN"]),
            "service": "SECURE_TRANSPORT",
            "person_id": str(self.peter),
            "incident_id": str(self.incident),
            "note": "Vehicle blocked",
            **body,
        }
        return await self.post(who, "/api/partner-requests", **values)

    async def tick(self, at: datetime) -> list[PartnerRequest]:
        return await service.tick(
            self.idp.engine, self.idp.tenant_id, self.publisher, ADAPTER, now=lambda: at
        )

    async def audited(self, prefix: str) -> list[str]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            rows = await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.action.like(f"{prefix}%"))
                .order_by(AuditLog.id)
            )
            return list(rows)


async def _mission(idp: Idp, code: str, country: str, lon: float, lat: float) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :code, :cc, "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
            ),
            {"id": mission_id, "code": code, "cc": country, "lon": lon, "lat": lat},
        )
        await session.commit()
    return mission_id


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo = await _mission(idp, "NBO", "KE", 36.82, -1.29)
    par = await _mission(idp, "PAR", "FR", 2.35, 48.86)
    peter, incident = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        partners = {p.code: p for p in PARTNERS}
        await service.ensure_partners(session, list(partners.values()))
        ids = {
            code: pid for code, pid in await session.execute(text("SELECT code, id FROM partner"))
        }
        await session.execute(
            text(
                "INSERT INTO person (id, tenant_id, mission_id, person_type, full_name, "
                "role_title) VALUES (:id, current_tenant_id(), :m, 'LOCAL_STAFF', "
                "'Fictional Driver', 'Driver')"
            ),
            {"id": peter, "m": nbo},
        )
        await session.execute(
            text(
                "INSERT INTO person_location_current (person_id, tenant_id, location, place_label, "
                "confidence, primary_source) VALUES (:id, current_tenant_id(), "
                "'SRID=4326;POINT(36.8195 -1.2985)', 'In transit · Haile Selassie Ave', 91, "
                "'MOBILE_GPS')"
            ),
            {"id": peter},
        )
        await session.execute(
            text(
                "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id) VALUES (:id, current_tenant_id(), "
                "'INC-T', 'Unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
                "'SRID=4326;POINT(36.8245 -1.2838)', :m)"
            ),
            {"id": incident, "m": nbo},
        )
        await session.commit()
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.par": [("HEAD_OF_MISSION", par)],
        "viewer": [("VIEWER", None)],
        "desk": [("TRAVEL_DESK", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, par, peter, incident, ids)


async def test_the_directory_and_coverage(world: World) -> None:
    listed = (await world.client.get("/api/partners", headers=world.idp.headers("viewer"))).json()
    assert [(p["code"], p["simulated"]) for p in listed] == [
        ("KES", True),
        ("MER", True),
        ("SEN", True),
    ]
    gaps = (
        await world.client.get("/api/partners/coverage", headers=world.idp.headers("viewer"))
    ).json()
    assert {g["code"]: g["missing"] for g in gaps} == {
        "NBO": ["EVACUATION", "WELFARE"],
        "PAR": ["EVACUATION", "WELFARE"],
    }


async def test_the_sos_suggestion_is_the_nearest_capable_partner_shortest_sla_first(
    world: World,
) -> None:
    """AS-06, plan §6: Peter in Nairobi -> Sentinel (30 min) before Meridian (60 min)."""
    response = await world.client.get(
        f"/api/partners/suggest?person_id={world.peter}", headers=world.idp.headers("viewer")
    )
    body = response.json()
    assert (body["mission_code"], body["country_code"], body["service"]) == (
        "NBO",
        "KE",
        "SECURE_TRANSPORT",
    )
    assert [p["code"] for p in body["partners"]] == ["SEN", "MER"]
    # In Paris (located there, G-4), only Meridian offers secure transport.
    await world.sql(
        "UPDATE person_location_current SET location = 'SRID=4326;POINT(2.36 48.87)' "
        "WHERE person_id = :p",
        p=world.peter,
    )
    body = (
        await world.client.get(
            f"/api/partners/suggest?person_id={world.peter}", headers=world.idp.headers("viewer")
        )
    ).json()
    assert (body["mission_code"], [p["code"] for p in body["partners"]]) == ("PAR", ["MER"])
    bad = await world.client.get(
        f"/api/partners/suggest?person_id={world.peter}&service=MASSAGE",
        headers=world.idp.headers("viewer"),
    )
    assert bad.status_code == 422


async def test_a_request_is_tracked_to_completion_live_and_audited(world: World) -> None:
    created = await world.ask()
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["reference"].startswith("REQ-")
    assert (req["status"], req["partner_name"], req["mission_code"], req["person_name"]) == (
        "REQUESTED",
        "Sentinel Secure Transport",
        "NBO",
        "Fictional Driver",
    )
    assert req["place_label"] == "In transit · Haile Selassie Ave"  # AS-08: the place, no more
    assert [e.type for e in world.publisher.events] == ["PARTNER_REQUEST_UPDATED"]

    # The worker answers as the partner would (AS-04): accepted with an ETA, then en route.
    now = datetime.now(UTC)
    assert await world.tick(now) == []  # too early
    [accepted] = await world.tick(now + timedelta(seconds=15))
    assert (accepted.status, accepted.eta) == ("ACCEPTED", now + timedelta(seconds=15, minutes=30))
    assert accepted.accepted_at is not None
    early = await world.post("duty", f"/api/partner-requests/{req['id']}/complete")
    assert early.status_code == 409
    assert "once the partner is en route" in early.text
    [en_route] = await world.tick(now + timedelta(seconds=40))
    assert en_route.status == "EN_ROUTE"

    # Only a person completes it, with the right role for the mission.
    assert (
        await world.post("viewer", f"/api/partner-requests/{req['id']}/complete")
    ).status_code == 403
    done = await world.post("hom.nbo", f"/api/partner-requests/{req['id']}/complete")
    assert done.status_code == 200
    assert (done.json()["status"], done.json()["completed_at"] is not None) == ("COMPLETED", True)
    again = await world.post("duty", f"/api/partner-requests/{req['id']}/cancel")
    assert again.status_code == 409

    assert await world.audited("PARTNER_REQUEST.") == [
        "PARTNER_REQUEST.CREATE",
        "PARTNER_REQUEST.ACCEPT",
        "PARTNER_REQUEST.EN_ROUTE",
        "PARTNER_REQUEST.COMPLETE",
    ]
    assert [e.payload["status"] for e in world.publisher.events] == [
        "REQUESTED",
        "ACCEPTED",
        "EN_ROUTE",
        "COMPLETED",
    ]
    listed = (
        await world.client.get(
            f"/api/partner-requests?incident_id={world.incident}",
            headers=world.idp.headers("viewer"),
        )
    ).json()
    assert [r["status"] for r in listed] == ["COMPLETED"]


@pytest.mark.parametrize(
    ("who", "code"),
    [
        ("duty", 201),
        ("security", 201),
        ("hom.nbo", 201),  # their own mission
        ("hom.par", 403),  # another mission (D-05)
        ("desk", 403),
        ("viewer", 403),
    ],
)
async def test_who_may_request(world: World, who: str, code: int) -> None:
    """§33 Q2; no second person (Q3)."""
    response = await world.ask(who)
    assert response.status_code == code, response.text
    if code == 403:
        assert await world.audited("PARTNER_REQUEST.") == []


async def test_a_request_is_cancelled_by_a_person_with_the_role(world: World) -> None:
    req = (await world.ask()).json()
    assert (
        await world.post("hom.par", f"/api/partner-requests/{req['id']}/cancel")
    ).status_code == 403
    cancelled = await world.post("security", f"/api/partner-requests/{req['id']}/cancel")
    assert cancelled.json()["status"] == "CANCELLED"
    assert await world.tick(datetime.now(UTC) + timedelta(minutes=5)) == []  # the partner stops


@pytest.mark.parametrize(
    ("body", "code", "message"),
    [
        ({"partner_id": "KES"}, 409, "KES does not offer SECURE_TRANSPORT"),
        ({"service": "MASSAGE"}, 422, "service is one of"),
        ({"note": "x" * 501}, 422, ""),
        ({"partner_id": str(uuid.uuid4())}, 404, "No such partner"),
        ({"person_id": str(uuid.uuid4())}, 404, "No such person"),
        ({"incident_id": str(uuid.uuid4())}, 404, "No such incident"),
        ({"person_id": None, "incident_id": None}, 422, "A request is for a mission"),
    ],
)
async def test_bad_requests_are_refused(
    world: World, body: dict[str, Any], code: int, message: str
) -> None:
    if body.get("partner_id") == "KES":
        body = {**body, "partner_id": str(world.partners["KES"])}
    response = await world.ask(**body)
    assert response.status_code == code, response.text
    assert message in response.text


async def test_coverage_is_the_missions_country(world: World) -> None:
    """Sentinel covers KE only: a Paris request is refused (409)."""
    response = await world.ask(mission_id=str(world.par), person_id=None, incident_id=None)
    assert response.status_code == 409
    assert "SEN does not cover FR" in response.text


async def test_a_restricted_traveller_is_never_named(world: World) -> None:
    """AS-08, G-5."""
    trip = uuid.uuid4()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO trip (id, tenant_id, reference, origin, destination, starts_on, "
                "ends_on, approval_status, restricted) VALUES (:t, current_tenant_id(), 'TRP-V', "
                "'A', 'B', current_date, current_date + 2, 'APPROVED', true)"
            ),
            {"t": trip},
        )
        await session.execute(
            text(
                "INSERT INTO trip_traveller (tenant_id, trip_id, person_id) "
                "VALUES (current_tenant_id(), :t, :p)"
            ),
            {"t": trip, "p": world.peter},
        )
        await session.commit()
    response = await world.ask()
    assert response.status_code == 409
    assert "restricted traveller" in response.text


# --- PB-07 step 6 (AS-05, plan §5, G-1) -------------------------------------------------------


async def test_standby_falls_back_without_the_partner_or_without_coverage(world: World) -> None:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        incident = await session.get_one(Incident, world.incident)
        actor = Actor(type="SYSTEM", id="playbook.engine")
        run = uuid.uuid4()
        unknown = await service.standby(
            session, incident, {"partner": "Nobody Assistance"}, run, actor
        )
        assert unknown is None  # the engine keeps the Phase 1 text
        not_offered = await service.standby(
            session,
            incident,
            {"partner": "Kestrel Medical Assistance", "service_code": "EVACUATION"},
            run,
            actor,
        )
        assert not_offered is None
        tracked = await service.standby(
            session, incident, {"partner": "Kestrel Medical Assistance"}, run, actor
        )
        assert tracked is not None
        assert tracked[1]["request_reference"].startswith("REQ-")
        incident.mission_id = world.par
        await session.flush()
        uncovered = await service.standby(
            session,
            incident,
            {"partner": "Sentinel Secure Transport", "service_code": "SECURE_TRANSPORT"},
            run,
            actor,
        )
        assert uncovered is not None
        assert uncovered[0] == "no partner covers FR for SECURE_TRANSPORT (simulated)"
        requests = await session.scalars(select(PartnerRequest))
        assert [(r.created_by_type, r.created_by, r.note) for r in requests] == [
            ("PLAYBOOK", str(run), "Standby · INC-T")
        ]
