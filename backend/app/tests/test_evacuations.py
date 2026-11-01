"""Evacuation Management (EV-02..09; D-40; docs/plan-pilot-ev.md): activation by two
people from the screen (request and confirm, G-1) or from a START_EVACUATION proposal
(G-3); the manifest locked at activation (§4); partners asked and the movement message
prepared for a third person (§7, G-4); check-in and seats (§5, G-10); the sequence (§6,
G-2); stand-down (§8, G-11); names by scope (G-8); permissions. Against real PostgreSQL,
as nexira_api."""

import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.agents import proposals
from app.modules.agents.actions import MessagePayload
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.audit.models import AuditLog
from app.modules.evacuations import service as evacuations
from app.modules.notifications import compose
from app.modules.notifications.models import NotificationCampaign
from app.modules.notifications.service import CampaignIn, create_campaign
from app.modules.notifications.templates import TemplateIn, ensure_templates
from app.modules.tenancy.service import SYSTEM, ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

MOVE = "Evacuation of {city}: go to the muster point now and bring your passport."
PEOPLE = [  # (type, name): who is evacuated (§4) and who is not
    ("DIPLOMAT", "Fictional Diplomat A"),
    ("DIPLOMAT", "Fictional Diplomat B"),
    ("DELEGATE", "Fictional Delegate"),
    ("DEPENDANT", "Fictional Child"),
    ("LOCAL_STAFF", "Fictional Local Staff"),  # stays (§53 Q3)
    ("CONTRACTOR", "Fictional Contractor"),  # stays
    ("CITIZEN", "Fictional Citizen Safe"),  # confirmed safe: stays
    ("CITIZEN", "Fictional Citizen Help"),  # needs help: evacuated
    ("CITIZEN", "Fictional Citizen Silent"),  # no reply: evacuated
]


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    cai: uuid.UUID
    incident: uuid.UUID
    people: dict[str, uuid.UUID]

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def get(self, who: str, url: str) -> Any:
        return await self.client.get(url, headers=self.idp.headers(who))

    async def post(self, who: str, url: str, body: dict[str, Any] | None = None) -> Any:
        return await self.client.post(url, json=body, headers=self.idp.headers(who))

    async def requested(self, who: str = "hom.nbo") -> dict[str, Any]:
        response = await self.post(who, "/api/evacuations", {"mission_id": str(self.nbo)})
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    async def active(self) -> dict[str, Any]:
        evacuation = await self.requested()
        response = await self.post("hq", f"/api/evacuations/{evacuation['id']}/confirm")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def detail(self, who: str, evacuation_id: str) -> dict[str, Any]:
        response = await self.get(who, f"/api/evacuations/{evacuation_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

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


async def _mission(idp: Idp, code: str, city: str, country: str) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :city, :cc, 'SRID=4326;POINT(36.82 -1.29)')"
            ),
            {"id": mission_id, "code": code, "city": city, "cc": country},
        )
        await session.commit()
    return mission_id


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo = await _mission(idp, "NBO", "Nairobi", "KE")
    cai = await _mission(idp, "CAI", "Cairo", "EG")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "hq": [("HQ_CRISIS_DIRECTOR", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "dual": [("HEAD_OF_MISSION", nbo), ("HQ_CRISIS_DIRECTOR", None)],
        # Activators who can also approve citizen messages (review of Prompt 67, M2).
        "hom.consul": [("HEAD_OF_MISSION", nbo), ("CONSULAR_OFFICER", None)],
        "hq.consul": [("HQ_CRISIS_DIRECTOR", None), ("CONSULAR_OFFICER", None)],
        "security.cai": [("SECURITY_OFFICER", cai)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    people: dict[str, uuid.UUID] = {}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        for prefix, with_year, last in (("INC", True, 1041), ("NTF", False, 3100)):
            await ensure_reference_counter(
                session, prefix=prefix, with_year=with_year, last_value=last
            )
        await ensure_agents(session, [AgentIn("RESPONSE_PLANNER", "Response Planner", "", 2)])
        await ensure_policies(
            session,
            [PolicyIn("START_EVACUATION", 3, ["HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"], False)],
        )
        await ensure_templates(
            session,
            [
                TemplateIn(
                    "EVACUATION_MOVE",
                    "ALERT",
                    None,
                    "Evacuation · movement",
                    {"en": MOVE, "fr": "REVIEW REQUIRED · Évacuation de {city}."},
                    {"fr": False},
                )
            ],
        )
        for ptype, name in PEOPLE:
            people[name] = await session.scalar(
                text(
                    "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
                    "VALUES (current_tenant_id(), :m, :t, :n) RETURNING id"
                ),
                {"m": nbo, "t": ptype, "n": name},
            )
        partner_ids = {}
        for code, name, service, coverage in (
            ("ATL", "Atlas Air Evacuation (simulated)", "EVACUATION", ["KE"]),
            ("SEN", "Sentinel Secure Transport (simulated)", "SECURE_TRANSPORT", ["KE", "EG"]),
        ):
            partner_ids[code] = await session.scalar(
                text(
                    "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
                    "VALUES (current_tenant_id(), :c, :n, ARRAY[:s], :cov, 60) "
                    "RETURNING id"
                ),
                {"c": code, "n": name, "s": service, "cov": coverage},
            )
        options = [
            {
                "role": "PRIMARY",
                "kind": "CHARTER",
                "label": "Wilson Airport → Dubai",
                "seats": 3,  # fewer than the manifest: seats run out (G-10)
                "partner_id": str(partner_ids["ATL"]),
            },
            {"role": "BACKUP", "kind": "COMMERCIAL", "label": "JKIA · 30 seats held", "seats": 30},
            {
                "role": "CONTINGENCY",
                "kind": "ROAD",
                "label": "Namanga border → Arusha",
                "partner_id": str(partner_ids["SEN"]),
            },
        ]
        await session.execute(
            text(
                "INSERT INTO evacuation_plan (tenant_id, mission_id, reference, muster_name, "
                "muster_location, route_label, destination, options) VALUES (current_tenant_id(), "
                ":m, 'EVP-NBO', 'Embassy courtyard', 'SRID=4326;POINT(36.82 -1.29)', 'Route B', "
                "'Dubai', CAST(:o AS jsonb))"
            ),
            {"m": nbo, "o": json.dumps(options)},
        )
        incident = await session.scalar(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id, status) VALUES (current_tenant_id(), "
                "'INC-2026-1042', 'Civil unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
                "'SRID=4326;POINT(36.82 -1.29)', :m, 'ACTIVE') RETURNING id"
            ),
            {"m": nbo},
        )
        # The incident's check-in: one citizen safe, one needing help, one silent (§4).
        checkin = await session.scalar(
            text(
                "INSERT INTO notification_campaign (tenant_id, reference, incident_id, "
                "campaign_type, message, channels, created_by_type, status) VALUES "
                "(current_tenant_id(), 'NTF-3001', :i, 'CHECKIN', 'Are you safe?', '{APP}', "
                "'PLAYBOOK', 'SENDING') RETURNING id"
            ),
            {"i": incident},
        )
        for name in (
            "Fictional Citizen Safe",
            "Fictional Citizen Help",
            "Fictional Citizen Silent",
        ):
            await session.execute(
                text(
                    "INSERT INTO notification_delivery (tenant_id, campaign_id, person_id, "
                    "channel) VALUES (current_tenant_id(), :c, :p, 'APP')"
                ),
                {"c": checkin, "p": people[name]},
            )
        for name, answer in (
            ("Fictional Citizen Safe", "SAFE"),
            ("Fictional Citizen Help", "NEED_HELP"),
        ):
            await session.execute(
                text(
                    "INSERT INTO checkin_response (tenant_id, campaign_id, person_id, status) "
                    "VALUES (current_tenant_id(), :c, :p, :s)"
                ),
                {"c": checkin, "p": people[name], "s": answer},
            )
        # Diplomat B's passport runs out within six months: "could block evacuation" (DX-03).
        await session.execute(
            text(
                "INSERT INTO travel_document (tenant_id, person_id, doc_type, issuing_country, "
                "valid_until) VALUES (current_tenant_id(), :p, 'DIPLOMATIC_PASSPORT', 'KE', :d)"
            ),
            {"p": people["Fictional Diplomat B"], "d": date.today() + timedelta(days=21)},
        )
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, cai, incident, people)


# --- activation from the screen (EV-02, G-1) ---------------------------------------------------


async def test_a_head_of_mission_requests_and_the_hq_crisis_director_confirms(
    world: World,
) -> None:
    evacuation = await world.requested()
    assert (evacuation["status"], evacuation["requested_role"]) == (
        "PENDING_ACTIVATION",
        "HEAD_OF_MISSION",
    )
    assert evacuation["plan_reference"] == "EVP-NBO"
    url = f"/api/evacuations/{evacuation['id']}/confirm"
    refused = await world.post("hom.nbo", url)
    assert refused.status_code == 403  # the requester cannot also activate (D-40)
    assert "same person" in refused.json()["detail"]
    # "dual" holds HQ_CRISIS_DIRECTOR too, and is not the requester: a valid second person.
    assert (await world.post("dual", url)).status_code == 200
    row = (await world.sql("SELECT status, activated_by FROM evacuation")).one()
    assert row.status == "ACTIVE"
    assert row.activated_by == await world.user_id("dual")


async def test_the_confirmer_holds_the_role_the_requester_did_not_use(world: World) -> None:
    evacuation = await world.requested()
    url = f"/api/evacuations/{evacuation['id']}/confirm"
    for who in ("duty", "consular", "security", "viewer", "hom.cai"):
        assert (await world.post(who, url)).status_code == 403, who
    assert (await world.post("hq", url)).json()["status"] == "ACTIVE"
    assert (await world.post("hq", url)).status_code == 409  # already decided


async def test_an_hq_crisis_director_may_ask_first_and_a_head_of_mission_confirm(
    world: World,
) -> None:
    evacuation = await world.requested("hq")
    assert evacuation["requested_role"] == "HQ_CRISIS_DIRECTOR"
    url = f"/api/evacuations/{evacuation['id']}/confirm"
    assert (await world.post("hom.cai", url)).status_code == 403  # another mission's (D-05)
    assert (await world.post("hq", url)).status_code == 403  # the requester
    assert (await world.post("hom.nbo", url)).json()["status"] == "ACTIVE"


async def test_only_heads_of_mission_and_hq_request_and_only_where_there_is_cause(
    world: World,
) -> None:
    body = {"mission_id": str(world.nbo)}
    for who in ("duty", "consular", "security", "viewer", "hom.cai"):
        assert (await world.post(who, "/api/evacuations", body)).status_code == 403, who
    cairo = await world.post("hq", "/api/evacuations", {"mission_id": str(world.cai)})
    assert cairo.status_code == 409
    assert "no evacuation plan" in cairo.json()["detail"]
    await world.requested()
    again = await world.post("hq", "/api/evacuations", body)
    assert (again.status_code, "live evacuation" in again.json()["detail"]) == (409, True)


async def test_without_an_active_incident_there_is_nothing_to_activate(world: World) -> None:
    await world.sql("UPDATE incident SET status = 'MONITORING'")
    refused = await world.post("hom.nbo", "/api/evacuations", {"mission_id": str(world.nbo)})
    assert (refused.status_code, "no active incident" in refused.json()["detail"]) == (409, True)


# --- the manifest, partners and the message (EV-03, EV-06) ------------------------------------


async def test_without_a_checkin_the_exposed_citizens_are_evacuated(world: World) -> None:
    """G-6: an incident with no check-in yet takes its exposed citizens instead."""
    await world.sql("UPDATE incident SET status = 'MONITORING'")
    newer = (
        await world.sql(
            "INSERT INTO incident (tenant_id, reference, title, category, severity, "
            "signal_severity, location, mission_id, status) VALUES (current_tenant_id(), "
            "'INC-2026-1043', 'Unrest spreads', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
            "'SRID=4326;POINT(36.82 -1.29)', :m, 'ACTIVE') RETURNING id",
            m=world.nbo,
        )
    ).scalar_one()
    await world.sql(
        "INSERT INTO incident_exposure (tenant_id, incident_id, subject_type, subject_id) "
        "VALUES (current_tenant_id(), :i, 'PERSON', :p)",
        i=newer,
        p=world.people["Fictional Citizen Safe"],
    )
    evacuation = await world.active()
    assert evacuation["incident_id"] == str(newer)
    assert evacuation["counts"]["CITIZEN"] == 1
    names = [e["name"] for e in (await world.detail("hq", evacuation["id"]))["manifest"]]
    assert names[-1] == "Fictional Citizen Safe"


async def test_activation_locks_the_manifest_from_who_is_there_and_who_is_not_safe(
    world: World,
) -> None:
    evacuation = await world.active()
    assert evacuation["counts"] == {"STAFF": 2, "DELEGATE": 1, "DEPENDANT": 1, "CITIZEN": 2}
    assert evacuation["step"] == 2
    assert [s["at"] is not None for s in evacuation["steps"]] == [True, True] + [False] * 4
    detail = await world.detail("hom.nbo", evacuation["id"])
    assert [(e["category"], e["name"]) for e in detail["manifest"]] == [
        ("STAFF", "Fictional Diplomat A"),
        ("STAFF", "Fictional Diplomat B"),
        ("DELEGATE", "Fictional Delegate"),
        ("DEPENDANT", "Fictional Child"),
        ("CITIZEN", "Fictional Citizen Help"),
        ("CITIZEN", "Fictional Citizen Silent"),
    ]
    assert [e["document_flag"] for e in detail["manifest"]] == [
        False, True, False, False, False, False
    ]  # fmt: skip
    assert detail["documents_flagged"] == 1


async def test_activation_asks_the_plans_partners_with_no_names(world: World) -> None:
    evacuation = await world.active()
    rows = (
        await world.sql(
            "SELECT p.code, r.service, r.created_by_type, r.created_by, r.person_id, r.note "
            "FROM partner_request r JOIN partner p ON p.id = r.partner_id ORDER BY p.code"
        )
    ).all()
    hq = str(await world.user_id("hq"))
    assert [(r.code, r.service, r.created_by_type, r.created_by, r.person_id) for r in rows] == [
        ("ATL", "EVACUATION", "USER", hq, None),
        ("SEN", "SECURE_TRANSPORT", "USER", hq, None),
    ]
    for r in rows:
        assert r.note.startswith(f"{evacuation['reference']} · 6 people · muster Embassy courtyard")
        assert "Fictional" not in r.note  # AS-08
    assert [p["partner_name"] for p in evacuation["partner_requests"]] == [
        "Atlas Air Evacuation (simulated)",
        "Sentinel Secure Transport (simulated)",
    ]


async def test_the_movement_message_waits_for_a_third_person(world: World) -> None:
    evacuation = await world.active()
    assert evacuation["message_status"] == "PENDING_APPROVAL"
    campaign = (
        await world.sql(
            "SELECT id, campaign_type, message, created_by_type, audience_filter "
            "FROM notification_campaign WHERE reference = :r",
            r=evacuation["message_reference"],
        )
    ).one()
    assert (campaign.campaign_type, campaign.created_by_type) == ("ALERT", "USER")
    assert campaign.message == MOVE.replace("{city}", "Nairobi")
    assert campaign.audience_filter == {"evacuation_id": evacuation["id"]}
    url = f"/api/campaigns/{campaign.id}/approve"
    for who in ("hom.nbo", "hq"):  # neither activator (D-31, plan §7)
        assert (await world.post(who, url)).status_code == 403, who
    sent = await world.post("consular", url)
    assert sent.status_code == 200, sent.text
    deliveries = (
        await world.sql(
            "SELECT count(DISTINCT person_id) FROM notification_delivery WHERE campaign_id = :c",
            c=campaign.id,
        )
    ).scalar_one()
    assert deliveries == 6  # everyone on the manifest, and no one else


# --- check-in and seats (EV-04) ----------------------------------------------------------------


async def test_check_in_gives_the_next_seat_until_they_run_out(world: World) -> None:
    evacuation = await world.active()
    entries = (await world.detail("security", evacuation["id"]))["manifest"]
    url = f"/api/evacuations/{evacuation['id']}/manifest/{{}}/check-in"
    assert (await world.post("viewer", url.format(entries[0]["id"]))).status_code == 403
    for entry in entries[:4]:
        response = await world.post("security", url.format(entry["id"]))
        assert response.status_code == 200, response.text
    again = await world.post("security", url.format(entries[0]["id"]))
    assert again.status_code == 409
    seats = [e["seat"] for e in (await world.detail("security", evacuation["id"]))["manifest"]]
    assert seats[:4] == ["1A", "1B", "1C", None]  # three seats on the charter (G-10)


async def test_the_scanner_checks_in_the_rest_and_assembly_is_reached(world: World) -> None:
    evacuation = await world.active()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        first = await evacuations.scan(session, "NBO", 4)
        await session.commit()
    assert first is not None
    assert first.evacuation.step == 2
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        rest = await evacuations.scan(session, "NBO", 10)
        await session.commit()
    assert rest is not None
    assert rest.evacuation.step == 3
    detail = await world.detail("hom.nbo", evacuation["id"])
    assert detail["checked_in"] == 6
    assert {e["status"] for e in detail["manifest"]} == {"CHECKED_IN"}
    by = (
        await world.sql(
            "SELECT DISTINCT checked_in_by_type, checked_in_by FROM evacuation_manifest"
        )
    ).all()
    assert [tuple(r) for r in by] == [("SCANNER", "muster-scanner (simulated)")]
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await evacuations.scan(session, "CAI", 5) is None  # nothing live there


# --- the sequence and stand-down (EV-05, EV-07) ------------------------------------------------


async def test_the_sequence_moves_one_step_at_a_time_and_arrival_completes_it(
    world: World,
) -> None:
    evacuation = await world.active()
    url = f"/api/evacuations/{evacuation['id']}/advance"
    assert (await world.post("consular", url, {"step": 3})).status_code == 403
    assert (await world.post("security", url, {"step": 4})).status_code == 409
    for step in (3, 4, 5):
        response = await world.post("security", url, {"step": step})
        assert response.json()["step"] == step
    # The partner took the charter request and is en route: arrival completes it.
    await world.sql(
        "UPDATE partner_request SET status = 'ACCEPTED', eta = now() WHERE service = 'EVACUATION'"
    )
    await world.sql("UPDATE partner_request SET status = 'EN_ROUTE' WHERE service = 'EVACUATION'")
    refused = await world.post(
        "hq", f"/api/evacuations/{evacuation['id']}/stand-down", {"reason": "x"}
    )
    assert (refused.status_code, "flight has departed" in refused.json()["detail"]) == (409, True)
    done = await world.post("hom.nbo", url, {"step": 6})
    assert (done.json()["status"], done.json()["step"]) == ("COMPLETED", 6)
    statuses = (
        await world.sql("SELECT service, status FROM partner_request ORDER BY service")
    ).all()
    assert [tuple(r) for r in statuses] == [
        ("EVACUATION", "COMPLETED"),
        ("SECURE_TRANSPORT", "REQUESTED"),  # never en route: left as it is
    ]


async def test_simulated_progress_moves_steps_only_from_the_step_before(world: World) -> None:
    await world.active()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert await evacuations.progress(session, "NBO", 4) is None  # not at step 3 yet
        moved = await evacuations.progress(session, "NBO", 3)
        await session.commit()
    assert moved is not None
    assert moved.evacuation.step == 3
    actor = (
        await world.sql(
            "SELECT actor_type, actor_id FROM audit_log WHERE action = 'EVACUATION.STEP'"
        )
    ).one()
    assert tuple(actor) == ("SYSTEM", "evacuation-progress (simulated)")


async def test_a_stand_down_cancels_the_partners_and_the_unsent_message(world: World) -> None:
    evacuation = await world.active()
    url = f"/api/evacuations/{evacuation['id']}/stand-down"
    for who in ("hom.nbo", "security", "duty"):
        assert (await world.post(who, url, {"reason": "Routes closed"})).status_code == 403
    assert (await world.post("hq", url, {"reason": ""})).status_code == 422
    stood = await world.post("hq", url, {"reason": "The unrest has eased"})
    assert stood.json()["status"] == "STOOD_DOWN"
    assert stood.json()["stood_down_reason"] == "The unrest has eased"
    assert stood.json()["message_status"] == "CANCELLED"
    assert {p["status"] for p in stood.json()["partner_requests"]} == {"CANCELLED"}
    entry = (await world.detail("hq", evacuation["id"]))["manifest"][0]
    late = await world.post(
        "security", f"/api/evacuations/{evacuation['id']}/manifest/{entry['id']}/check-in"
    )
    assert late.status_code == 409


async def test_a_pending_request_is_withdrawn_by_its_requester(world: World) -> None:
    evacuation = await world.requested()
    url = f"/api/evacuations/{evacuation['id']}/stand-down"
    assert (await world.post("security", url, {"reason": "x"})).status_code == 403
    withdrawn = await world.post("hom.nbo", url, {"reason": "Asked too early"})
    assert withdrawn.json()["status"] == "STOOD_DOWN"
    await world.requested("hq")  # the mission may be asked for again


# --- from a START_EVACUATION proposal (plan §3, G-3) -------------------------------------------


async def _propose(world: World) -> uuid.UUID:
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        outcome = await proposals.create(
            session,
            proposals.ProposalIn(
                agent_code="RESPONSE_PLANNER",
                proposal_key=str(uuid.uuid4()),
                action_type="START_EVACUATION",
                title="Evacuate Embassy staff via route B",
                proposed_action="Move personnel in the zone to the airport via route B.",
                action_payload={"route": "B"},
                incident_id=world.incident,
                evidence=[{"text": "test", "source": "test"}],
            ),
            undo_window_s=300,
        )
        await session.commit()
        return outcome.proposal.id


async def _approve(world: World, proposal_id: uuid.UUID) -> dict[str, Any]:
    for who in ("hom.nbo", "hq"):
        response = await world.post(who, f"/api/proposals/{proposal_id}/approve")
        assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_an_approved_evacuation_proposal_activates_the_plan(world: World) -> None:
    proposal_id = await _propose(world)
    assert (await _approve(world, proposal_id))["status"] == "APPROVED"
    row = (await world.sql("SELECT * FROM evacuation WHERE proposal_id = :p", p=proposal_id)).one()
    assert (row.status, row.requested_role) == ("ACTIVE", "HEAD_OF_MISSION")
    assert (row.requested_by, row.activated_by) == (
        await world.user_id("hom.nbo"),
        await world.user_id("hq"),
    )
    note = (
        await world.sql("SELECT summary FROM incident_event WHERE summary LIKE 'Evacuation EVN-%'")
    ).scalar_one()
    assert note == f"Evacuation {row.reference} (EVP-NBO) activated, via B."
    campaign = (
        await world.sql(
            "SELECT id, created_by_type, created_by FROM notification_campaign "
            "WHERE campaign_type = 'ALERT'"
        )
    ).one()
    assert (campaign.created_by_type, campaign.created_by) == ("AGENT", str(proposal_id))
    for who in ("hom.nbo", "hq"):
        assert (await world.post(who, f"/api/campaigns/{campaign.id}/approve")).status_code == 403
    assert any(e.type == "EVACUATION_UPDATED" for e in world.publisher.events)


async def test_a_second_evacuation_proposal_returns_the_live_one(world: World) -> None:
    await _approve(world, await _propose(world))
    second = await _propose(world)
    assert (await _approve(world, second))["status"] == "APPROVED"  # not FAILED (G-3)
    assert (await world.sql("SELECT count(*) FROM evacuation")).scalar_one() == 1
    note = (
        await world.sql(
            "SELECT summary FROM incident_event WHERE summary LIKE '%was already active%'"
        )
    ).scalar_one()
    assert "EVP-NBO" in note


async def test_a_proposal_supersedes_a_pending_screen_request(world: World) -> None:
    pending = await world.requested("hq")
    await _approve(world, await _propose(world))
    rows = (
        await world.sql("SELECT id, status, stood_down_reason FROM evacuation ORDER BY created_at")
    ).all()
    assert next((str(r.id), r.status) for r in rows) == (pending["id"], "STOOD_DOWN")
    assert rows[0].stood_down_reason.startswith("Superseded by an approved evacuation proposal")
    assert rows[1].status == "ACTIVE"


# --- who sees what and may do what (EV-08, EV-09) ---------------------------------------------


async def test_names_only_within_scope_counts_for_everyone(world: World) -> None:
    evacuation = await world.active()
    for who in ("viewer", "hom.cai"):
        detail = await world.detail(who, evacuation["id"])
        assert detail["names_shown"] is False
        assert {e["name"] for e in detail["manifest"]} == {None}
        assert {e["document_flag"] for e in detail["manifest"]} == {None}
        assert detail["counts"]["CITIZEN"] == 2
        assert detail["documents_flagged"] == 1  # a count, not who
        assert "Fictional" not in json.dumps(detail)
    assert (await world.detail("consular", evacuation["id"]))["names_shown"] is True
    listed = (await world.get("viewer", f"/api/evacuations?mission_id={world.nbo}")).json()
    assert [e["reference"] for e in listed] == [evacuation["reference"]]
    plans = (await world.get("viewer", "/api/evacuations/plans")).json()
    assert [(p["reference"], [o["covered"] for o in p["options"]]) for p in plans] == [
        ("EVP-NBO", [True, False, True])
    ]
    for event in world.publisher.events:
        assert "Fictional" not in json.dumps(event.payload)


async def test_permissions_follow_the_same_checks(world: World) -> None:
    url = f"/api/me/permissions?entity_type=evacuation&entity_id={world.nbo}"

    async def may(who: str) -> dict[str, bool]:
        body = (await world.get(who, url)).json()
        keys = ("activate", "confirm", "check_in", "advance", "stand_down")
        names = (
            "activate_evacuation",
            "confirm_evacuation",
            "check_in_evacuee",
            "advance_evacuation",
            "stand_down_evacuation",
        )
        return {k: body[n] for k, n in zip(keys, names, strict=True)}

    assert (await may("hom.nbo"))["activate"] is True
    assert (await may("viewer")) == dict.fromkeys(
        ("activate", "confirm", "check_in", "advance", "stand_down"), False
    )
    evacuation = await world.requested()
    assert (await may("hq"))["confirm"] is True
    assert (await may("hom.nbo")) == {
        "activate": False,
        "confirm": False,
        "check_in": False,
        "advance": False,
        "stand_down": True,  # its requester may withdraw it
    }
    await world.post("hq", f"/api/evacuations/{evacuation['id']}/confirm")
    assert await may("security") == {
        "activate": False,
        "confirm": False,
        "check_in": True,
        "advance": True,
        "stand_down": False,
    }
    assert (await may("hq"))["stand_down"] is True


async def test_every_step_is_audited(world: World) -> None:
    evacuation = await world.active()
    entry = (await world.detail("hq", evacuation["id"]))["manifest"][0]
    await world.post(
        "security", f"/api/evacuations/{evacuation['id']}/manifest/{entry['id']}/check-in"
    )
    await world.post("security", f"/api/evacuations/{evacuation['id']}/advance", {"step": 3})
    await world.post("hq", f"/api/evacuations/{evacuation['id']}/stand-down", {"reason": "Eased"})
    assert await world.actions("EVACUATION.") == [
        "EVACUATION.REQUEST",
        "EVACUATION.ACTIVATE",
        "EVACUATION.CHECK_IN",
        "EVACUATION.STEP",
        "EVACUATION.STAND_DOWN",
    ]
    details = (
        await world.sql("SELECT details FROM audit_log WHERE action LIKE 'EVACUATION.%'")
    ).all()
    assert "Fictional" not in json.dumps([d.details for d in details])


# --- review of Prompt 67 -------------------------------------------------------------------------


async def _message(world: World, evacuation: dict[str, Any]) -> uuid.UUID:
    found: uuid.UUID = (
        await world.sql(
            "SELECT id FROM notification_campaign WHERE reference = :r",
            r=evacuation["message_reference"],
        )
    ).scalar_one()
    return found


async def test_activators_who_may_approve_messages_still_cannot_send_this_one(
    world: World,
) -> None:
    """M2: the requester and the activator are excluded as people, not only by role."""
    evacuation = await world.requested("hom.consul")
    await world.post("hq.consul", f"/api/evacuations/{evacuation['id']}/confirm")
    evacuation = await world.detail("hq", evacuation["id"])
    url = f"/api/campaigns/{await _message(world, evacuation)}/approve"
    for who in ("hom.consul", "hq.consul"):
        refused = await world.post(who, url)
        assert refused.status_code == 403, who
    assert (await world.post("consular", url)).status_code == 200


async def test_a_rejected_movement_message_keeps_both_activators_out(
    world: World,
) -> None:
    evacuation = await world.requested("hom.consul")
    await world.post("hq.consul", f"/api/evacuations/{evacuation['id']}/confirm")
    campaign = await _message(world, await world.detail("hq", evacuation["id"]))
    rejected = await world.post(
        "consular", f"/api/campaigns/{campaign}/reject", {"reason": "Wrong muster point"}
    )
    assert rejected.status_code == 200, rejected.text
    # The database keeps the first submitter (PC-10), so the requester cannot re-submit it
    # as their own; the gate excludes both activators anyway (review of Prompt 67, M2).
    resubmitted = await world.post("hom.consul", f"/api/campaigns/{campaign}/submit")
    assert resubmitted.status_code == 409
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        row = await session.get_one(NotificationCampaign, campaign)
        gate = await compose.gate(session, row)
    assert gate.deciders_of_other_steps >= {
        await world.user_id("hom.consul"),
        await world.user_id("hq.consul"),
    }


async def test_no_agent_or_playbook_message_names_a_manifest(world: World) -> None:
    """M1: SEND_EXTERNAL_MESSAGE, and the service behind it, refuse the audience."""
    evacuation = await world.active()
    audience = {"evacuation_id": evacuation["id"]}
    with pytest.raises(ValueError, match="cannot name a trip, documents or an evacuation"):
        MessagePayload.model_validate({"message": "m", "channels": ["SMS"], "audience": audience})
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        with pytest.raises(ValueError, match="only by Evacuation Management"):
            await create_campaign(
                session,
                incident_id=world.incident,
                campaign=CampaignIn(
                    campaign_type="ADVISORY", message="m", channels=["SMS"], audience=audience
                ),
                created_by_type="PLAYBOOK",
                created_by="x",
                actor=SYSTEM,
            )


async def test_a_request_with_a_look_alike_note_is_not_the_evacuations(world: World) -> None:
    """M3: matched by the activator and the activating transaction, not the note alone."""
    evacuation = await world.active()
    atlas = (await world.sql("SELECT id FROM partner WHERE code = 'ATL'")).scalar_one()
    crafted = await world.post(
        "duty",
        "/api/partner-requests",
        {
            "partner_id": str(atlas),
            "service": "EVACUATION",
            "mission_id": str(world.nbo),
            "note": f"{evacuation['reference']} · not the evacuation's",
        },
    )
    assert crafted.status_code == 201, crafted.text
    shown = (await world.detail("viewer", evacuation["id"]))["partner_requests"]
    assert len(shown) == 2
    await world.post("hq", f"/api/evacuations/{evacuation['id']}/stand-down", {"reason": "Eased"})
    still = (
        await world.sql("SELECT status FROM partner_request WHERE id = :i", i=crafted.json()["id"])
    ).scalar_one()
    assert still == "REQUESTED"


async def test_a_draft_checkin_does_not_empty_the_citizens(world: World) -> None:
    """L4: only a check-in that was sent counts."""
    await world.sql(
        "INSERT INTO notification_campaign (tenant_id, reference, incident_id, campaign_type, "
        "message, channels, created_by_type, created_by, status) VALUES (current_tenant_id(), "
        "'NTF-3002', :i, 'CHECKIN', 'Are you safe?', '{APP}', 'USER', 'x', 'DRAFT')",
        i=world.incident,
    )
    assert (await world.active())["counts"]["CITIZEN"] == 2


async def test_arrival_withdraws_a_movement_message_never_sent(world: World) -> None:
    """L5."""
    evacuation = await world.active()
    for step in (3, 4, 5, 6):
        await world.post("security", f"/api/evacuations/{evacuation['id']}/advance", {"step": step})
    done = await world.detail("viewer", evacuation["id"])
    assert (done["status"], done["message_status"]) == ("COMPLETED", "CANCELLED")


async def test_a_proposal_cannot_evacuate_for_an_incident_no_longer_active(world: World) -> None:
    """L6 (G-6)."""
    proposal_id = await _propose(world)
    await world.post("hom.nbo", f"/api/proposals/{proposal_id}/approve")
    await world.sql("UPDATE incident SET status = 'MONITORING'")
    second = await world.post("hq", f"/api/proposals/{proposal_id}/approve")
    assert second.json()["status"] == "FAILED"
    assert (await world.sql("SELECT count(*) FROM evacuation")).scalar_one() == 0


async def test_another_missions_responder_cannot_check_in_or_move_the_sequence(
    world: World,
) -> None:
    evacuation = await world.active()
    entry = (await world.detail("hq", evacuation["id"]))["manifest"][0]
    base = f"/api/evacuations/{evacuation['id']}"
    check_in = await world.post("security.cai", f"{base}/manifest/{entry['id']}/check-in")
    assert check_in.status_code == 403
    assert (await world.post("security.cai", f"{base}/advance", {"step": 3})).status_code == 403
    for field in ("category", "seat", "name"):
        assert {
            e[field] for e in (await world.detail("security.cai", evacuation["id"]))["manifest"]
        } == {None}, field
