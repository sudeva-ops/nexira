"""Journey Management through the API (Prompt 25; JR-01..07, JR-09; D-32).

The world: missions PAR (FR), BGW (IQ), ADD (ET), and WAS and NYC (both US); simulated
country risk FR LOW, IQ HIGH, ET MODERATE, US MODERATE, SG LOW; staff to send; and one
user per role. Every decision is made through the API as a logged-in user; the database
rules (migration 0003) back the service."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, text

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.people.service import PersonIn, load_persons
from app.modules.tenancy.service import ensure_reference_counter
from app.modules.travel.models import Trip
from app.modules.travel.service import CountryRiskIn, ensure_country_risks, ensure_trip
from app.tests.auth_helpers import Idp
from app.tests.conftest import DbUrls, create_tenant
from app.tests.fakes import ListPublisher

GST = ZoneInfo("Asia/Dubai")
CHECK_ITEMS = ("security_briefing", "insurance_medical", "emergency_contacts", "checkin_schedule")


@dataclass
class World:
    missions: dict[str, uuid.UUID]
    staff: list[uuid.UUID]
    users: dict[str, uuid.UUID]
    publisher: ListPublisher
    idp: Idp

    async def incident(self, mission: str, severity: str, status: str = "ACTIVE") -> str:
        reference = f"INC-T-{uuid.uuid4().hex[:6]}"
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            await session.execute(
                text(
                    "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                    "signal_severity, status, mission_id, location) VALUES (current_tenant_id(), "
                    ":ref, 'Protest', 'CIVIL_UNREST', :sev, :sev, :status, :mission, "
                    "'SRID=4326;POINT(0 0)')"
                ),
                {
                    "ref": reference,
                    "sev": severity,
                    "status": status,
                    "mission": self.missions[mission],
                },
            )
            await session.commit()
        return reference

    async def expose(self, reference: str, person: uuid.UUID) -> None:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            await session.execute(
                text(
                    "INSERT INTO incident_exposure (tenant_id, incident_id, subject_type, "
                    "subject_id, distance_m, confidence) SELECT current_tenant_id(), id, "
                    "'PERSON', :person, 800, 90 FROM incident WHERE reference = :ref"
                ),
                {"person": person, "ref": reference},
            )
            await session.commit()


MISSIONS = [("PAR", "FR"), ("BGW", "IQ"), ("ADD", "ET"), ("WAS", "US"), ("NYC", "US")]
RISKS = {
    "FR": (25, 38, 8, 30),  # LOW
    "IQ": (78, 60, 35, 62),  # HIGH
    "ET": (55, 52, 38, 45),  # MODERATE
    "US": (50, 30, 20, 20),  # MODERATE
    "SG": (8, 6, 10, 8),  # LOW
}


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    missions = {code: uuid.uuid4() for code, _ in MISSIONS}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for code, country in MISSIONS:
            await session.execute(
                text(
                    "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
                    "VALUES (:id, current_tenant_id(), :code, :code, :cc, 'SRID=4326;POINT(0 0)')"
                ),
                {"id": missions[code], "code": code, "cc": country},
            )
        await ensure_country_risks(
            session, [CountryRiskIn(cc, *s, "Riskline (simulated)") for cc, s in RISKS.items()]
        )
        await ensure_reference_counter(session, prefix="TRP", with_year=False, last_value=8820)
        staff = [uuid.uuid4() for _ in range(3)]
        await load_persons(
            session,
            [
                PersonIn(p, missions["PAR"], "DIPLOMAT", f"Fictional Staff {n}")
                for n, p in enumerate(staff)
            ],
        )
        await session.commit()
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "desk": [("TRAVEL_DESK", None)],
        "desk2": [("TRAVEL_DESK", None)],
        "duty": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "security.bgw": [("SECURITY_OFFICER", missions["BGW"])],
        "security.par": [("SECURITY_OFFICER", missions["PAR"])],
        # Plans the trip and holds the approving role: still never approves it (D-32).
        "dual": [("TRAVEL_DESK", None), ("SECURITY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "admin": [("ADMIN", None)],
        "viewer": [("VIEWER", None)],
    }
    users = {sub: await idp.user(sub, roles) for sub, roles in grants.items()}
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(missions, staff, users, publisher, idp)


def plan(w: World, country: str = "FR", destination: str = "Paris", **extra: Any) -> dict[str, Any]:
    starts = date.today() + timedelta(days=5)
    stay = datetime.combine(starts, datetime.min.time(), GST) + timedelta(hours=15)
    return {
        "purpose": "Consultations",
        "origin": "HQ",
        "destination": destination,
        "destination_country": country,
        "starts_on": starts.isoformat(),
        "ends_on": (starts + timedelta(days=3)).isoformat(),
        "travellers": [str(p) for p in w.staff[:2]],
        "segments": [
            {
                "kind": "STAY",
                "title": "Hotel",
                "place_label": destination,
                "starts_at": stay.isoformat(),
                "ends_at": (stay + timedelta(days=2)).isoformat(),
            }
        ],
        **extra,
    }


async def draft(client: AsyncClient, w: World, sub: str = "desk", **kw: Any) -> str:
    response = await client.post("/api/trips", json=plan(w, **kw), headers=w.idp.headers(sub))
    assert response.status_code == 201, response.text
    trip_id: str = response.json()["id"]
    return trip_id


async def act(
    client: AsyncClient, w: World, trip_id: str, verb: str, sub: str, **body: Any
) -> Response:
    return await client.post(f"/api/trips/{trip_id}/{verb}", json=body, headers=w.idp.headers(sub))


async def tick_all(client: AsyncClient, w: World, trip_id: str, sub: str = "desk") -> None:
    for item in CHECK_ITEMS:
        response = await act(client, w, trip_id, "checklist", sub, item=item, done=True)
        assert response.status_code == 200, response.text


async def get(client: AsyncClient, w: World, trip_id: str, sub: str = "viewer") -> dict[str, Any]:
    response = await client.get(f"/api/trips/{trip_id}", headers=w.idp.headers(sub))
    assert response.status_code == 200, response.text
    out: dict[str, Any] = response.json()
    return out


async def audited(w: World, reference: str) -> list[str]:
    async with tenant_session(w.idp.tenant_id, w.idp.engine) as session:
        rows = await session.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == reference).order_by(AuditLog.id)
        )
        return list(rows)


# --- drafts (JR-01, JR-02) -------------------------------------------------------------


async def test_the_travel_desk_plans_a_draft_and_a_viewer_cannot(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    response = await client.post("/api/trips", json=plan(world), headers=idp.headers("desk"))
    assert response.status_code == 201
    out = response.json()
    assert (out["reference"], out["approval_status"], out["requested_by"]) == (
        "TRP-8821",
        "DRAFT",
        str(world.users["desk"]),
    )
    assert (out["requested_by_name"], out["travellers_count"], len(out["segments"])) == (
        "User desk",
        2,
        1,
    )
    await draft(client, world, "duty")  # a Duty Officer plans too
    for sub in ("viewer", "security", "consular", "admin"):
        refused = await client.post("/api/trips", json=plan(world), headers=idp.headers(sub))
        assert refused.status_code == 403, sub


@pytest.mark.parametrize(
    "field",
    [
        {"requested_by": None},
        {"requested_by": "00000000-0000-0000-0000-000000000000"},
        {"approval_status": "APPROVED"},
        {"approved_by": None},
        {"risk_level": "LOW"},
        {"checklist": {"security_briefing": True}},
    ],
)
async def test_author_risk_and_approval_fields_are_never_accepted(
    client: AsyncClient, idp: Idp, world: World, field: dict[str, Any]
) -> None:
    response = await client.post(
        "/api/trips", json=plan(world, **field), headers=idp.headers("desk")
    )
    assert response.status_code == 422


async def test_every_trip_planned_through_the_api_has_its_requester(
    client: AsyncClient, world: World
) -> None:
    # The condition of the Prompt 24 sign-off: the database cannot tell the seed from
    # the API, so the API must always record who asked for the trip.
    for sub in ("desk", "duty", "dual"):
        await draft(client, world, sub)
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        rows = (await session.execute(select(Trip.requested_by))).scalars().all()
    assert len(rows) == 3
    assert None not in rows
    assert set(rows) == {world.users["desk"], world.users["duty"], world.users["dual"]}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"travellers": []}, ""),
        ({"travellers": [str(uuid.uuid4())]}, "unknown traveller"),
        ({"destination_country": "fr"}, "two-letter"),
        ({"ends_on": date.today().isoformat()}, "ends before it starts"),
        (
            {
                "segments": [
                    {
                        "kind": "MEETING",
                        "title": "Too late",
                        "starts_at": "2099-01-01T10:00:00+04:00",
                        "ends_at": "2099-01-01T11:00:00+04:00",
                    }
                ]
            },
            "outside the trip's dates",
        ),
        (
            {
                "segments": [
                    {
                        "kind": "TELEPORT",
                        "title": "x",
                        "starts_at": "2099-01-01T10:00:00+04:00",
                        "ends_at": "2099-01-01T11:00:00+04:00",
                    }
                ]
            },
            "kind is one of",
        ),
    ],
)
async def test_a_plan_is_validated(
    client: AsyncClient, idp: Idp, world: World, change: dict[str, Any], message: str
) -> None:
    response = await client.post(
        "/api/trips", json=plan(world, **change), headers=idp.headers("desk")
    )
    assert response.status_code == 422
    assert message in response.text


async def test_only_the_requester_edits_and_only_a_draft(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    trip_id = await draft(client, world)
    changed = plan(world, destination="Lyon", travellers=[str(world.staff[2])], segments=[])
    for sub in ("desk2", "duty", "admin"):
        refused = await client.patch(
            f"/api/trips/{trip_id}", json=changed, headers=idp.headers(sub)
        )
        assert refused.status_code == 403, sub
    edited = await client.patch(f"/api/trips/{trip_id}", json=changed, headers=idp.headers("desk"))
    assert edited.status_code == 200
    out = edited.json()
    assert (out["destination"], out["travellers_count"], out["segments"]) == ("Lyon", 1, [])
    assert [t["id"] for t in out["travellers"]] == [str(world.staff[2])]
    await act(client, world, trip_id, "submit", "desk")
    late = await client.patch(f"/api/trips/{trip_id}", json=changed, headers=idp.headers("desk"))
    assert late.status_code == 409


# --- risk and approval (JR-03, JR-04) -------------------------------------------------------


async def test_a_low_trip_is_approved_on_submission(client: AsyncClient, world: World) -> None:
    trip_id = await draft(client, world, country="SG", destination="Singapore")
    for sub in ("desk2", "security"):
        assert (await act(client, world, trip_id, "submit", sub)).status_code == 403, sub
    response = await act(client, world, trip_id, "submit", "desk")
    assert response.status_code == 200
    out = response.json()
    assert (out["approval_status"], out["risk_level"], out["approved_by"]) == (
        "APPROVED",
        "LOW",
        None,
    )
    assert (out["approved_risk_level"], out["checklist"]["security_approval"]) == ("LOW", True)
    assert out["submitted_at"]
    assert out["approved_at"]
    assert await audited(world, out["reference"]) == [
        "TRIP.DRAFT",
        "TRIP.SUBMIT",
        "TRIP.AUTO_APPROVE",
    ]
    assert [e.type for e in world.publisher.events] == ["TRIP_UPDATED"] * 2  # draft, submit


async def test_a_moderate_trip_needs_a_second_person_from_the_travel_desk(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="ET", destination="Addis Ababa")
    submitted = (await act(client, world, trip_id, "submit", "desk")).json()
    assert (submitted["approval_status"], submitted["risk_level"]) == ("PENDING", "MODERATE")
    assert submitted["mission_id"] == str(world.missions["ADD"])  # plan G-2
    assert (await act(client, world, trip_id, "approve", "desk")).status_code == 403  # requester
    for sub in ("duty", "consular", "viewer", "admin"):
        assert (await act(client, world, trip_id, "approve", sub)).status_code == 403, sub
    approved = await act(client, world, trip_id, "approve", "desk2")
    assert approved.status_code == 200  # a MODERATE trip: no checklist needed
    out = approved.json()
    assert (out["approval_status"], out["approved_by_name"], out["approved_risk_level"]) == (
        "APPROVED",
        "User desk2",
        "MODERATE",
    )
    assert (await act(client, world, trip_id, "approve", "security")).status_code == 409


async def test_a_high_trip_needs_the_security_officer_and_the_checklist(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, sub="dual", country="IQ", destination="Baghdad")
    submitted = (await act(client, world, trip_id, "submit", "dual")).json()
    assert (submitted["risk_level"], submitted["mission_id"]) == (
        "HIGH",
        str(world.missions["BGW"]),
    )
    refused = {
        sub: (await act(client, world, trip_id, "approve", sub)).status_code
        for sub in ("dual", "desk", "desk2", "security.par")
    }
    assert refused == {"dual": 403, "desk": 403, "desk2": 403, "security.par": 403}
    blocked = await act(client, world, trip_id, "approve", "security.bgw")
    assert blocked.status_code == 409
    assert "security_briefing" in blocked.text
    await tick_all(client, world, trip_id, sub="security")
    approved = await act(client, world, trip_id, "approve", "security.bgw")
    assert approved.status_code == 200
    assert approved.json()["checklist"] == {
        **dict.fromkeys(CHECK_ITEMS, True),
        "security_approval": True,
    }


async def test_a_country_with_several_missions_is_decided_at_hq(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="US", destination="New York")
    submitted = (await act(client, world, trip_id, "submit", "desk")).json()
    assert (submitted["risk_level"], submitted["mission_id"]) == ("MODERATE", None)
    assert (await act(client, world, trip_id, "approve", "security.par")).status_code == 403
    assert (await act(client, world, trip_id, "approve", "security")).status_code == 200


async def test_an_active_incident_raises_the_destination_risk(
    client: AsyncClient, world: World
) -> None:
    calm = await draft(client, world)
    assert (await get(client, world, calm))["risk_level"] == "LOW"
    await world.incident("PAR", "CRITICAL", status="CLOSED")  # not active: does not count
    assert (await get(client, world, calm))["risk_level"] == "LOW"
    reference = await world.incident("PAR", "HIGH")
    detail = await get(client, world, calm)
    assert detail["country_risk"] == {
        "country_code": "FR",
        "level": "HIGH",
        "base_level": "LOW",
        "rated": True,
        "security": 25,
        "unrest": 38,
        "health": 8,
        "transport": 30,
        "source": "Riskline (simulated)",
        "incident_level": "HIGH",
        "incidents": [reference],
        "simulated": True,
    }
    submitted = (await act(client, world, calm, "submit", "desk")).json()
    assert (submitted["approval_status"], submitted["risk_level"]) == ("PENDING", "HIGH")


async def test_a_risk_that_rises_before_approval_raises_the_approver(
    client: AsyncClient, world: World
) -> None:
    # Plan G-7: approved at the higher of the submitted and the live risk.
    trip_id = await draft(client, world, country="ET", destination="Addis Ababa")
    await act(client, world, trip_id, "submit", "desk")
    await world.incident("ADD", "HIGH")
    assert (await act(client, world, trip_id, "approve", "desk2")).status_code == 403
    await tick_all(client, world, trip_id)
    approved = (await act(client, world, trip_id, "approve", "security")).json()
    assert (approved["risk_level"], approved["approved_risk_level"]) == ("MODERATE", "HIGH")


async def test_a_rejection_needs_a_reason_and_returns_the_draft(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, trip_id, "submit", "desk")
    assert (await act(client, world, trip_id, "reject", "security", reason="")).status_code == 422
    assert (await act(client, world, trip_id, "reject", "desk", reason="mine")).status_code == 403
    rejected = await act(client, world, trip_id, "reject", "security", reason="Postpone a week")
    assert rejected.status_code == 200
    out = rejected.json()
    assert (out["approval_status"], out["rejection_reason"]) == ("DRAFT", "Postpone a week")
    resubmitted = (await act(client, world, trip_id, "submit", "desk")).json()
    assert resubmitted["approval_status"] == "PENDING"


# --- checklist (JR-05) -------------------------------------------------------------------


async def test_the_checklist_is_ticked_by_planners_and_closes_on_approval(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="ET", destination="Addis Ababa")
    for sub in ("viewer", "consular"):
        refused = await act(
            client, world, trip_id, "checklist", sub, item="security_briefing", done=True
        )
        assert refused.status_code == 403, sub
    bad = await act(
        client, world, trip_id, "checklist", "desk", item="security_approval", done=True
    )
    assert bad.status_code == 422  # set by the approval only
    ticked = await act(
        client, world, trip_id, "checklist", "duty", item="security_briefing", done=True
    )
    assert ticked.json()["checklist"]["security_briefing"] is True
    untick = await act(
        client, world, trip_id, "checklist", "duty", item="security_briefing", done=False
    )
    assert untick.json()["checklist"]["security_briefing"] is False
    await act(client, world, trip_id, "submit", "desk")
    await act(client, world, trip_id, "approve", "desk2")
    late = await act(
        client, world, trip_id, "checklist", "desk", item="insurance_medical", done=True
    )
    assert late.status_code == 409
    reference = (await get(client, world, trip_id))["reference"]
    assert (await audited(world, reference)).count("TRIP.CHECK") == 2


# --- cancel ----------------------------------------------------------------------------


async def test_the_requester_travel_desk_or_admin_cancels(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="SG", destination="Singapore")
    await act(client, world, trip_id, "submit", "desk")  # APPROVED (LOW)
    for sub in ("duty", "security", "viewer"):
        assert (await act(client, world, trip_id, "cancel", sub)).status_code == 403, sub
    cancelled = await act(client, world, trip_id, "cancel", "desk2")
    assert cancelled.json()["approval_status"] == "CANCELLED"
    assert (await act(client, world, trip_id, "cancel", "admin")).status_code == 409
    own = await draft(client, world, sub="duty")
    assert (await act(client, world, own, "cancel", "duty")).status_code == 200  # the requester


# --- impacted and risk changed (JR-06, JR-07) ------------------------------------------------


async def test_a_trip_with_an_exposed_traveller_shows_the_incident(
    client: AsyncClient, world: World
) -> None:
    today = date.today()
    on_now: dict[str, Any] = {
        "starts_on": (today - timedelta(days=1)).isoformat(),
        "ends_on": (today + timedelta(days=3)).isoformat(),
        "segments": [],
    }
    impacted = await draft(client, world, country="SG", destination="Singapore", **on_now)
    await act(client, world, impacted, "submit", "desk")  # APPROVED
    planned = await draft(client, world, country="SG", destination="Singapore", **on_now)  # a DRAFT
    reference = await world.incident("PAR", "HIGH")
    await world.expose(reference, world.staff[0])
    assert (await get(client, world, impacted))["impacted_by"] == [reference]
    assert (await get(client, world, planned))["impacted_by"] == []  # plan G-3
    listed = await client.get("/api/trips?impacted=true", headers=world.idp.headers("viewer"))
    assert [t["id"] for t in listed.json()] == [impacted]


async def test_an_approved_trip_is_flagged_when_the_risk_rises(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world)  # Paris, LOW: approved on submission
    await act(client, world, trip_id, "submit", "desk")
    assert (await get(client, world, trip_id))["risk_changed"] is False
    await world.incident("PAR", "HIGH")
    flagged = await get(client, world, trip_id)
    assert (flagged["approval_status"], flagged["live_risk"], flagged["risk_changed"]) == (
        "APPROVED",
        "HIGH",
        True,
    )  # flagged, never revoked (D-32)


async def test_trips_are_listed_with_filters(client: AsyncClient, world: World) -> None:
    low = await draft(client, world, country="SG", destination="Singapore")
    high = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, high, "submit", "desk")
    headers = world.idp.headers("viewer")

    async def ids(query: str) -> set[str]:
        return {t["id"] for t in (await client.get(f"/api/trips?{query}", headers=headers)).json()}

    assert await ids("") == {low, high}
    assert await ids("status=PENDING") == {high}
    assert await ids("risk=HIGH") == {high}
    assert await ids(f"mission_id={world.missions['BGW']}") == {high}


# --- permissions and audit (plan G-07, JR-09) ------------------------------------------------


async def permissions(client: AsyncClient, w: World, trip_id: str, sub: str) -> dict[str, bool]:
    response = await client.get(
        "/api/me/permissions",
        params={"entity_type": "trip", "entity_id": trip_id},
        headers=w.idp.headers(sub),
    )
    assert response.status_code == 200
    out = response.json()
    return {
        k: out[k] for k in ("edit_trip", "submit_trip", "approve_trip", "check_trip", "cancel_trip")
    }


async def test_permissions_follow_the_rules(client: AsyncClient, world: World) -> None:
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    assert await permissions(client, world, trip_id, "desk") == {
        "edit_trip": True,
        "submit_trip": True,
        "approve_trip": False,
        "check_trip": True,
        "cancel_trip": True,
    }
    assert not any((await permissions(client, world, trip_id, "viewer")).values())
    await act(client, world, trip_id, "submit", "desk")
    assert (await permissions(client, world, trip_id, "desk"))["approve_trip"] is False
    assert (await permissions(client, world, trip_id, "desk2"))["approve_trip"] is False  # HIGH
    await tick_all(client, world, trip_id)
    assert (await permissions(client, world, trip_id, "security"))["approve_trip"] is True


async def test_every_step_is_audited(client: AsyncClient, world: World) -> None:
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    await client.patch(
        f"/api/trips/{trip_id}",
        json=plan(world, country="IQ", destination="Erbil"),
        headers=world.idp.headers("desk"),
    )
    await act(client, world, trip_id, "submit", "desk")
    await act(client, world, trip_id, "reject", "security", reason="Not now")
    await act(client, world, trip_id, "submit", "desk")
    await tick_all(client, world, trip_id)
    await act(client, world, trip_id, "approve", "security")
    await act(client, world, trip_id, "cancel", "desk")
    steps = await audited(world, (await get(client, world, trip_id))["reference"])
    assert steps == [
        "TRIP.DRAFT",
        "TRIP.EDIT",
        "TRIP.SUBMIT",
        "TRIP.REJECT",
        "TRIP.SUBMIT",
        *["TRIP.CHECK"] * 4,
        "TRIP.APPROVE",
        "TRIP.CANCEL",
    ]
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        actors = await session.scalar(
            select(func.count(func.distinct(AuditLog.actor_id))).where(
                AuditLog.action.like("TRIP.%")
            )
        )
    assert actors == 2  # the requester and the security officer


# --- review of Prompt 25 -----------------------------------------------------------------


async def test_a_country_without_a_simulated_level_needs_a_second_person(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    # M1: fail closed. A country with no country_risk row is MODERATE, never LOW.
    trip_id = await draft(client, world, country="ZZ", destination="Nowhere")
    detail = await get(client, world, trip_id)
    assert (detail["country_risk"]["rated"], detail["country_risk"]["base_level"]) == (
        False,
        "MODERATE",
    )
    submitted = (await act(client, world, trip_id, "submit", "desk")).json()
    assert (submitted["approval_status"], submitted["risk_level"], submitted["approved_by"]) == (
        "PENDING",
        "MODERATE",
        None,
    )
    for country in ("ÉÉ", "F1"):
        refused = await client.post(
            "/api/trips", json=plan(world, country=country), headers=idp.headers("desk")
        )
        assert refused.status_code == 422, country


async def test_a_nul_character_is_refused_not_a_server_error(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    for change in ({"purpose": "a\x00b"}, {"destination": "Pa\x00ris"}):
        refused = await client.post(
            "/api/trips", json=plan(world, **change), headers=idp.headers("desk")
        )
        assert refused.status_code == 422, change
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, trip_id, "submit", "desk")
    assert (
        await act(client, world, trip_id, "reject", "security", reason="x\x00")
    ).status_code == 422


async def test_a_risk_that_rises_to_high_needs_the_checklist(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="ET", destination="Addis Ababa")
    await act(client, world, trip_id, "submit", "desk")
    await world.incident("ADD", "HIGH")
    blocked = await act(client, world, trip_id, "approve", "security")
    assert blocked.status_code == 409
    assert "is HIGH" in blocked.text


async def test_permissions_hide_approve_while_the_checklist_is_open(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, trip_id, "submit", "desk")
    response = await client.get(
        "/api/me/permissions",
        params={"entity_type": "trip", "entity_id": trip_id},
        headers=world.idp.headers("security"),
    )
    assert (response.json()["approve_trip"], response.json()["reject_trip"]) == (False, True)
    await tick_all(client, world, trip_id)
    assert (await permissions(client, world, trip_id, "security"))["approve_trip"] is True
    unknown = await permissions(client, world, str(uuid.uuid4()), "security")
    assert not any(unknown.values())


async def test_a_trip_never_submitted_shows_the_live_risk(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, trip_id, "cancel", "desk")
    cancelled = await get(client, world, trip_id)
    assert (cancelled["approval_status"], cancelled["risk_level"]) == ("CANCELLED", "HIGH")


async def test_a_resubmission_takes_the_risk_and_scope_again(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    trip_id = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, trip_id, "submit", "desk")
    await act(client, world, trip_id, "reject", "security", reason="Go to Singapore instead")
    changed = plan(world, country="SG", destination="Singapore")
    await client.patch(f"/api/trips/{trip_id}", json=changed, headers=idp.headers("desk"))
    again = (await act(client, world, trip_id, "submit", "desk")).json()
    assert (again["approval_status"], again["risk_level"], again["mission_id"]) == (
        "APPROVED",
        "LOW",
        None,
    )


async def test_a_seeded_pending_trip_is_decided_through_the_api(
    client: AsyncClient, world: World
) -> None:
    trip_id = uuid.uuid4()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        await ensure_trip(
            session,
            trip_id=trip_id,
            reference="TRP-8814",
            purpose="Security assessment",
            origin="Amman",
            destination="Baghdad",
            destination_country="IQ",
            starts_on=date.today() + timedelta(days=5),
            ends_on=date.today() + timedelta(days=8),
            traveller_ids=[world.staff[0]],
            risk_level="HIGH",
            approval_status="PENDING",
            mission_id=world.missions["BGW"],
        )
        await session.commit()
    assert (await act(client, world, str(trip_id), "approve", "security.par")).status_code == 403
    assert (await act(client, world, str(trip_id), "approve", "security.bgw")).status_code == 409
    await tick_all(client, world, str(trip_id), sub="security.bgw")
    approved = (await act(client, world, str(trip_id), "approve", "security.bgw")).json()
    assert (approved["approval_status"], approved["approved_by"]) == (
        "APPROVED",
        str(world.users["security.bgw"]),
    )


async def test_a_mission_officer_neither_approves_nor_ticks_outside_their_scope(
    client: AsyncClient, world: World
) -> None:
    hq = await draft(client, world, country="US", destination="New York")  # two US missions
    await act(client, world, hq, "submit", "desk")
    assert (await act(client, world, hq, "approve", "security.bgw")).status_code == 403
    tick = await act(
        client, world, hq, "checklist", "security.bgw", item="security_briefing", done=True
    )
    assert tick.status_code == 403  # HQ only (D-06)
    baghdad = await draft(client, world, country="IQ", destination="Baghdad")
    await act(client, world, baghdad, "submit", "desk")
    tick = await act(
        client, world, baghdad, "checklist", "security.par", item="security_briefing", done=True
    )
    assert tick.status_code == 403
    tick = await act(
        client, world, baghdad, "checklist", "security.bgw", item="security_briefing", done=True
    )
    assert tick.status_code == 200


async def test_another_tenants_trip_is_not_found(
    client: AsyncClient, db: DbUrls, world: World
) -> None:
    other = await create_tenant(db, "Other ministry")
    trip_id = uuid.uuid4()
    async with tenant_session(other, world.idp.engine) as session:
        await ensure_trip(
            session,
            trip_id=trip_id,
            reference="TRP-1",
            purpose="",
            origin="A",
            destination="B",
            destination_country="FR",
            starts_on=date.today(),
            ends_on=date.today(),
            traveller_ids=[],
            approval_status="DRAFT",
        )
        await session.commit()
    headers = world.idp.headers("security")
    assert (await client.get(f"/api/trips/{trip_id}", headers=headers)).status_code == 404
    edited = await client.patch(
        f"/api/trips/{trip_id}", json=plan(world), headers=world.idp.headers("desk")
    )
    assert edited.status_code == 404
    for verb in ("submit", "approve", "cancel"):
        assert (await act(client, world, str(trip_id), verb, "admin")).status_code == 404, verb


async def test_an_approval_and_a_cancellation_at_once_end_consistently(
    client: AsyncClient, world: World
) -> None:
    trip_id = await draft(client, world, country="ET", destination="Addis Ababa")
    await act(client, world, trip_id, "submit", "desk")
    approve, cancel = await asyncio.gather(
        act(client, world, trip_id, "approve", "desk2"),
        act(client, world, trip_id, "cancel", "admin"),
    )
    final = await get(client, world, trip_id)
    assert final["approval_status"] == "CANCELLED"  # cancel always lands, before or after
    assert cancel.status_code == 200
    assert approve.status_code in (200, 409)
    assert (final["approved_by"] is not None) == (approve.status_code == 200)
