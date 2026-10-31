"""Document Expiry: urgency and readiness, who sees and does what, the forward-only renewal,
reminders, the trip warning, and the Compliance agent with its executor (Prompt 50;
DX-01..07, DX-09; D-37, docs/plan-pilot-dx.md). Dates are relative to today (UTC), as the
API reads them."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.agents import proposals
from app.modules.agents.agents.compliance import Compliance
from app.modules.agents.models import AgentProposal
from app.modules.agents.runner import run_agents
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.audit.models import AuditLog
from app.modules.documents import service
from app.modules.documents.service import DocumentIn
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.notifications.service import AudienceError, resolve_audience
from app.modules.people.service import PersonIn, load_persons
from app.modules.tenancy.service import ensure_reference_counter
from app.modules.travel.service import ensure_trip
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

TODAY = datetime.now(UTC).date()
AGENT = Compliance()

# --- urgency and readiness at the boundaries (DX-02, DX-03) ------------------------------------


@pytest.mark.parametrize(
    ("doc_type", "days", "expected"),
    [
        ("PASSPORT", -1, "EXPIRED"),
        ("VISA", 0, "CRITICAL"),
        ("VISA", 29, "CRITICAL"),
        ("VISA", 30, "HIGH"),
        ("PASSPORT", 89, "HIGH"),
        ("PASSPORT", 90, "MODERATE"),
        ("VISA", 90, "OK"),
        ("DIPLOMATIC_PASSPORT", 179, "MODERATE"),
        ("ACCREDITATION", 179, "OK"),
        ("PASSPORT", 180, "OK"),
    ],
)
def test_urgency_at_the_boundaries(doc_type: str, days: int, expected: str) -> None:
    assert service.urgency(doc_type, days) == expected


def test_travel_ready_needs_a_passport_with_180_days() -> None:
    day = date(2026, 11, 1)
    assert not service.ready_by("PASSPORT", day + timedelta(days=179), day)
    assert service.ready_by("PASSPORT", day + timedelta(days=180), day)
    assert service.ready_by("DIPLOMATIC_PASSPORT", day + timedelta(days=400), day)
    assert not service.ready_by("VISA", day + timedelta(days=4000), day)


# --- the world ----------------------------------------------------------------------------------


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    par: uuid.UUID
    people: dict[str, uuid.UUID]
    docs: dict[str, uuid.UUID]

    async def sql(self, query: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(query), params)
            rows = result.all() if query.lstrip().upper().startswith("SELECT") else []
            await session.commit()
            return rows

    async def get(self, who: str, path: str) -> Any:
        return await self.client.get(path, headers=self.idp.headers(who))

    async def post(self, who: str, path: str, **body: Any) -> Any:
        return await self.client.post(path, json=body, headers=self.idp.headers(who))

    async def step(self, who: str, doc: str, step: str, valid_until: date | None = None) -> Any:
        body: dict[str, Any] = {"step": step}
        if valid_until is not None:
            body["valid_until"] = valid_until.isoformat()
        return await self.post(who, f"/api/documents/{self.docs[doc]}/renewal", **body)

    async def incident(self, mission: uuid.UUID, status: str = "ACTIVE") -> uuid.UUID:
        incident_id = uuid.uuid4()
        await self.sql(
            "INSERT INTO incident (id, tenant_id, reference, title, category, severity, "
            "signal_severity, location, mission_id, status) VALUES (:id, current_tenant_id(), "
            ":ref, 'Unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
            "'SRID=4326;POINT(36.8245 -1.2838)', :m, :status)",
            id=incident_id,
            ref=f"INC-{incident_id.hex[:6]}",
            m=mission,
            status=status,
        )
        return incident_id

    async def observe(self, incident_id: uuid.UUID, kind: str = "EXPOSURE_COMPUTED") -> list[Any]:
        event = Event(kind, self.idp.tenant_id, {"incident_id": str(incident_id)}, "test")
        await run_agents(self.idp.engine, self.publisher, event, undo_window_s=300, agents=[AGENT])
        return list(
            await self.sql(
                "SELECT proposal_key, effective_level, status, action_payload, is_proactive "
                "FROM agent_proposal ORDER BY created_at"
            )
        )

    async def audited(self, prefix: str) -> list[tuple[str, str, str | None, Any]]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            rows = await session.execute(
                select(AuditLog.action, AuditLog.actor_type, AuditLog.actor_id, AuditLog.details)
                .where(AuditLog.action.like(f"{prefix}%"))
                .order_by(AuditLog.id)
            )
            return [tuple(r) for r in rows]


async def _mission(idp: Idp, code: str, country: str, lon: float, lat: float) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :city, :cc, "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
            ),
            {"id": mission_id, "code": code, "city": code.title(), "cc": country, "lon": lon,
             "lat": lat},
        )  # fmt: skip
        await session.commit()
    return mission_id


# (key, mission, person type, name) and (key, holder, type, days left)
PEOPLE = [
    ("hana", "nbo", "DIPLOMAT", "Fictional Hana"),
    ("aiko", "nbo", "DEPENDANT", "Fictional Aiko"),
    ("peter", "nbo", "LOCAL_STAFF", "Fictional Peter"),
    ("citizen", "nbo", "CITIZEN", "Fictional Citizen"),
    ("paul", "par", "DIPLOMAT", "Fictional Paul"),
]
DOCS = [
    ("hana.dp", "hana", "DIPLOMATIC_PASSPORT", 21),
    ("hana.acc", "hana", "ACCREDITATION", 15),
    ("aiko.pp", "aiko", "PASSPORT", 12),
    ("peter.pp", "peter", "PASSPORT", 400),
    ("paul.dp", "paul", "DIPLOMATIC_PASSPORT", 60),
]


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo = await _mission(idp, "NBO", "KE", 36.82, -1.29)
    par = await _mission(idp, "PAR", "FR", 2.35, 48.86)
    missions = {"nbo": nbo, "par": par}
    people = {key: uuid.uuid4() for key, *_ in PEOPLE}
    docs = {key: uuid.uuid4() for key, *_ in DOCS}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await load_persons(
            session,
            [PersonIn(people[k], missions[m], t, name) for k, m, t, name in PEOPLE],
        )
        await service.ensure_documents(
            session,
            [
                DocumentIn(docs[k], people[holder], t, "AE", TODAY + timedelta(days=days))
                for k, holder, t, days in DOCS
            ],
        )
        await ensure_reference_counter(session, prefix="NTF", with_year=False, last_value=3100)
        await ensure_agents(session, [AgentIn("COMPLIANCE", "Compliance", "", 2)])
        await ensure_policies(
            session,
            [PolicyIn("START_DOCUMENT_RENEWAL", 2, ["CONSULAR_OFFICER|DUTY_OFFICER"], False, 3600)],
        )
        await session.commit()
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "desk": [("TRAVEL_DESK", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.par": [("HEAD_OF_MISSION", par)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, par, people, docs)


# --- who sees what (DX-09) ----------------------------------------------------------------------


async def test_the_list_is_most_urgent_first_and_scoped_by_role(world: World) -> None:
    listed = (await world.get("duty", "/api/documents")).json()
    assert [d["id"] for d in listed] == [
        str(world.docs[k]) for k in ("aiko.pp", "hana.acc", "hana.dp", "paul.dp", "peter.pp")
    ]
    first = listed[0]
    assert (first["holder_name"], first["mission_code"], first["days_left"]) == (
        "Fictional Aiko",
        "NBO",
        12,
    )
    assert (first["urgency"], first["simulated"], first["can_act"]) == ("CRITICAL", True, True)
    assert "number" not in first  # D-37: never a document number

    nbo_only = (await world.get("hom.nbo", "/api/documents")).json()
    assert {d["mission_code"] for d in nbo_only} == {"NBO"}
    assert all(d["can_act"] for d in nbo_only)
    par_only = (await world.get("hom.par", "/api/documents")).json()
    assert [d["holder_name"] for d in par_only] == ["Fictional Paul"]  # none of Nairobi's
    desk = (await world.get("desk", "/api/documents")).json()
    assert len(desk) == 5
    assert not any(d["can_act"] for d in desk)  # reads all, renews nothing
    assert (await world.get("viewer", "/api/documents")).status_code == 403

    filtered = (await world.get("duty", "/api/documents?urgency=CRITICAL&doc_type=PASSPORT")).json()
    assert [d["id"] for d in filtered] == [str(world.docs["aiko.pp"])]
    assert (await world.get("duty", "/api/documents?urgency=SOON")).status_code == 422


async def test_the_summary_has_counts_and_no_names(world: World) -> None:
    viewer = (await world.get("viewer", "/api/documents/summary")).json()
    assert {k: viewer[k] for k in ("tracked", "expiring_30", "expiring_90", "could_block")} == {
        "tracked": 5,
        "expiring_30": 3,
        "expiring_90": 4,
        "could_block": 0,  # no mission at risk yet
    }
    # Readiness: Peter only (Hana 21 days, Aiko 12, Paul 60); the citizen is not counted.
    assert (viewer["people"], viewer["ready"], viewer["ready_pct"]) == (4, 1, 25.0)
    assert {m["code"]: m["ready_pct"] for m in viewer["missions"]} == {"NBO": 33.3, "PAR": 0.0}
    assert "Fictional" not in str(viewer)
    hom = (await world.get("hom.par", "/api/documents/summary")).json()
    assert (hom["tracked"], [m["code"] for m in hom["missions"]]) == (1, ["PAR"])


async def test_permissions_for_the_register(world: World) -> None:
    async def perms(who: str) -> Any:
        response = await world.get(who, "/api/me/permissions?entity_type=documents")
        assert response.status_code == 200
        return response.json()

    duty = await perms("duty")
    assert (duty["read_documents"], duty["act_documents"]) == (True, True)
    assert (duty["read_document_missions"], duty["act_document_missions"]) == (None, None)
    hom = await perms("hom.nbo")
    assert hom["read_document_missions"] == hom["act_document_missions"] == [str(world.nbo)]
    desk = await perms("desk")
    assert (desk["read_documents"], desk["act_documents"]) == (True, False)
    viewer = await perms("viewer")
    assert (viewer["read_documents"], viewer["act_documents"]) == (False, False)
    missing = await world.get("duty", "/api/me/permissions?entity_type=trip")
    assert missing.status_code == 422


# --- could block evacuation (DX-03, G-4) --------------------------------------------------------


async def test_an_active_incident_flags_passports_of_people_not_travel_ready(world: World) -> None:
    await world.incident(world.nbo)
    listed = {d["id"]: d for d in (await world.get("duty", "/api/documents")).json()}
    flagged = {k for k, d in world.docs.items() if listed[str(d)]["could_block_evacuation"]}
    assert flagged == {"hana.dp", "aiko.pp"}  # not the accreditation, not Peter, not Paris
    summary = (await world.get("viewer", "/api/documents/summary")).json()
    assert summary["could_block"] == 2


async def test_a_high_risk_mission_flags_without_an_incident(world: World) -> None:
    await world.sql("UPDATE mission SET risk_level = 'HIGH' WHERE id = :m", m=world.par)
    listed = (await world.get("duty", "/api/documents")).json()
    assert [d["holder_name"] for d in listed if d["could_block_evacuation"]] == ["Fictional Paul"]


# --- renewal (DX-04) ----------------------------------------------------------------------------


async def test_the_renewal_only_moves_forward(world: World) -> None:
    requested = await world.step("consular", "hana.dp", "REQUESTED")
    assert requested.status_code == 200
    body = requested.json()
    assert (body["renewal_status"], body["renewal_requested_at"] is not None) == ("REQUESTED", True)
    again = await world.step("consular", "hana.dp", "REQUESTED")
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "This document's renewal is already requested",
    )
    early = await world.step("consular", "hana.dp", "RENEWED", TODAY + timedelta(days=3650))
    assert early.status_code == 409
    assert (await world.step("duty", "hana.dp", "IN_PROGRESS")).status_code == 200
    assert (await world.step("duty", "hana.dp", "REQUESTED")).status_code == 409  # never back
    assert (await world.step("duty", "hana.dp", "RENEWED")).status_code == 422  # no date
    earlier = await world.step("duty", "hana.dp", "RENEWED", TODAY + timedelta(days=5))
    assert earlier.status_code == 422
    renewed = await world.step("duty", "hana.dp", "RENEWED", TODAY + timedelta(days=3650))
    assert renewed.status_code == 200
    out = renewed.json()
    assert (out["renewal_status"], out["days_left"], out["urgency"]) == ("RENEWED", 3650, "OK")
    assert out["holder_ready"]  # only a renewed date makes the holder travel-ready (§3)
    final = await world.step("duty", "hana.dp", "IN_PROGRESS")
    assert (final.status_code, final.json()["detail"]) == (409, "This document is already renewed")

    audited = await world.audited("DOCUMENT.")
    assert [(a, t) for a, t, _, _ in audited] == [
        ("DOCUMENT.RENEWAL_REQUESTED", "USER"),
        ("DOCUMENT.RENEWAL_STARTED", "USER"),
        ("DOCUMENT.RENEWED", "USER"),
    ]
    assert audited[2][3]["valid_until"]["to"] == (TODAY + timedelta(days=3650)).isoformat()
    events = [e for e in world.publisher.events if e.type == "DOCUMENT_UPDATED"]
    assert [e.payload["renewal_status"] for e in events] == ["REQUESTED", "IN_PROGRESS", "RENEWED"]
    assert {e.payload["mission_id"] for e in events} == {str(world.nbo)}
    who = await world.sql(
        "SELECT renewal_requested_by, renewal_started_by, renewed_by FROM travel_document "
        "WHERE id = :d",
        d=world.docs["hana.dp"],
    )
    consular, duty = (
        str(r[0])
        for r in [
            *(await world.sql("SELECT id FROM app_user WHERE external_id = 'consular'")),
            *(await world.sql("SELECT id FROM app_user WHERE external_id = 'duty'")),
        ]
    )
    assert tuple(who[0]) == (consular, duty, duty)


async def test_a_renewal_can_start_without_a_request(world: World) -> None:
    started = await world.step("hom.nbo", "aiko.pp", "IN_PROGRESS")
    assert started.status_code == 200
    assert started.json()["renewal_requested_at"] is None


@pytest.mark.parametrize("who", ["hom.par", "desk", "security", "viewer"])
async def test_who_may_not_renew_a_nairobi_document(world: World, who: str) -> None:
    assert (await world.step(who, "hana.dp", "REQUESTED")).status_code == 403
    assert await world.audited("DOCUMENT.") == []


async def test_an_unknown_document_or_step_is_refused(world: World) -> None:
    unknown = await world.post("duty", f"/api/documents/{uuid.uuid4()}/renewal", step="REQUESTED")
    assert unknown.status_code == 404
    assert (await world.step("duty", "hana.dp", "CANCELLED")).status_code == 422
    with_date = await world.step("duty", "hana.dp", "REQUESTED", TODAY + timedelta(days=900))
    assert with_date.status_code == 422


# --- reminders (DX-05) --------------------------------------------------------------------------


async def test_reminders_are_one_staff_campaign_to_the_holders(world: World) -> None:
    ids = [str(world.docs[k]) for k in ("hana.dp", "hana.acc", "aiko.pp")]
    response = await world.post("consular", "/api/documents/reminders", document_ids=ids)
    assert response.status_code == 201
    body = response.json()
    assert (body["recipients"], body["documents"]) == (2, 3)  # Hana once, and Aiko
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        campaign = await session.get_one(NotificationCampaign, uuid.UUID(body["campaign_id"]))
        deliveries = list(
            await session.scalars(
                select(NotificationDelivery.channel).where(
                    NotificationDelivery.campaign_id == campaign.id
                )
            )
        )
    assert (campaign.campaign_type, campaign.channels, campaign.created_by_type) == (
        "ADVISORY",
        ["APP", "EMAIL"],
        "USER",
    )
    assert campaign.message == service.REMINDER
    assert sorted(campaign.audience_filter["document_ids"]) == sorted(ids)
    assert sorted(deliveries) == ["APP", "APP", "EMAIL", "EMAIL"]
    assert [a for a, *_ in await world.audited("DOCUMENT.")] == ["DOCUMENT.REMINDERS"]
    assert "CAMPAIGN_QUEUED" in [e.type for e in world.publisher.events]


async def test_who_may_send_reminders(world: World) -> None:
    ids = [str(world.docs["hana.dp"])]
    for who in ("hom.par", "desk", "viewer"):
        response = await world.post(who, "/api/documents/reminders", document_ids=ids)
        assert response.status_code == 403, who
    mixed = [str(world.docs["hana.dp"]), str(world.docs["paul.dp"])]
    hom = await world.post("hom.nbo", "/api/documents/reminders", document_ids=mixed)
    assert hom.status_code == 403  # Paris is not theirs
    assert (
        await world.post("hom.nbo", "/api/documents/reminders", document_ids=ids)
    ).status_code == 201
    unknown = await world.post("duty", "/api/documents/reminders", document_ids=[str(uuid.uuid4())])
    assert unknown.status_code == 404
    assert (
        await world.post("duty", "/api/documents/reminders", document_ids=[])
    ).status_code == 422


async def test_the_document_holders_audience_never_reaches_citizens(world: World) -> None:
    """§5: a backstop behind the guard, which refuses a citizen's document."""
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        holders = await resolve_audience(
            session, None, {"document_ids": [str(world.docs["aiko.pp"])]}
        )
        assert holders == [world.people["aiko"]]
        for bad in ([], [str(uuid.uuid4())], ["not an id"]):
            with pytest.raises(AudienceError):
                await resolve_audience(session, None, {"document_ids": bad})
    for person_type in ("CITIZEN", "DELEGATE"):
        await world.sql(
            "UPDATE person SET person_type = :t WHERE id = :p",
            t=person_type,
            p=world.people["aiko"],
        )
        async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
            with pytest.raises(AudienceError, match="staff and dependants only"):
                await resolve_audience(
                    session, None, {"document_ids": [str(world.docs["aiko.pp"])]}
                )
    await world.sql("UPDATE person SET person_type = 'DEPENDANT', is_active = false WHERE id = :p",
                    p=world.people["aiko"])  # fmt: skip
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        with pytest.raises(AudienceError, match="no active holders"):
            await resolve_audience(session, None, {"document_ids": [str(world.docs["aiko.pp"])]})


# --- trips warn (DX-06) -------------------------------------------------------------------------


async def test_a_trip_warns_of_a_passport_short_of_180_days_after_it_ends(world: World) -> None:
    trip_id = uuid.uuid4()
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        await ensure_trip(
            session,
            trip_id=trip_id,
            reference="TRP-DX06",
            purpose="Consultations",
            origin="Nairobi",
            destination="Paris",
            destination_country="FR",
            starts_on=TODAY + timedelta(days=5),
            ends_on=TODAY + timedelta(days=7),
            traveller_ids=[world.people["peter"], world.people["paul"], world.people["citizen"]],
            approval_status="APPROVED",
        )
        await session.commit()
    detail = (await world.get("duty", f"/api/trips/{trip_id}")).json()
    # Paul's passport (60 days) is short; Peter's (400) is not; the citizen has no documents.
    assert detail["document_warnings"] == [
        {
            "person_id": str(world.people["paul"]),
            "full_name": "Fictional Paul",
            "valid_until": (TODAY + timedelta(days=60)).isoformat(),
        }
    ]
    assert detail["approval_status"] == "APPROVED"  # a warning, never a block (§38 Q6)
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        edge = await service.trip_warnings(
            session, [world.people["peter"]], TODAY + timedelta(days=400 - 180)
        )
        assert edge == []  # exactly 180 days after the trip ends is enough
        short = await service.trip_warnings(
            session, [world.people["peter"]], TODAY + timedelta(days=400 - 179)
        )
        assert [w.full_name for w in short] == ["Fictional Peter"]


# --- the Compliance agent (DX-07, §4) -----------------------------------------------------------


async def test_the_agent_proposes_once_for_a_mission_at_risk(world: World) -> None:
    assert await world.observe(await world.incident(world.par, status="CLOSED")) == []
    incident = await world.incident(world.nbo)
    found = await world.observe(incident)
    expected_ids = sorted(str(world.docs[k]) for k in ("hana.dp", "aiko.pp"))
    assert [(k, level, status, p, proactive) for k, level, status, p, proactive in found] == [
        (f"DX:{world.nbo}:{incident}", 2, "PENDING", {"document_ids": expected_ids}, True)
    ]
    assert await world.observe(incident, "INCIDENT_UPDATED") == found  # one open proposal
    assert await world.observe(incident) == found
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        proposal = await session.scalar(select(AgentProposal))
        assert proposal is not None
        assert proposal.title == "2 Nbo travel documents could block an evacuation"
        assert "F. Hana's diplomatic passport (21 days left)" in proposal.proposed_action
        assert proposal.alternatives[0]["action_type"] == "ADVISE_EMERGENCY_DOCUMENTS"
        assert any("180 days" in e["text"] for e in proposal.evidence)
        assert proposal.deadline_at is not None


async def test_the_agent_finds_nothing_where_everyone_is_travel_ready(world: World) -> None:
    for doc in ("hana.dp", "aiko.pp"):
        await world.sql(
            "UPDATE travel_document SET renewal_status = 'IN_PROGRESS', "
            "renewal_started_by = 'x' WHERE id = :d",
            d=world.docs[doc],
        )
        await world.sql(
            "UPDATE travel_document SET renewal_status = 'RENEWED', renewed_by = 'x', "
            "valid_until = :v WHERE id = :d",
            d=world.docs[doc],
            v=TODAY + timedelta(days=3000),
        )
    assert await world.observe(await world.incident(world.nbo)) == []
    assert await world.observe(await world.incident(world.par)) != []  # Paul's 60 days


# --- the executor (§4) ---------------------------------------------------------------------------


async def _approve(world: World, who: str) -> Any:
    [proposal_id] = [r[0] for r in await world.sql("SELECT id FROM agent_proposal")]
    return await world.post(who, f"/api/proposals/{proposal_id}/approve")


@pytest.mark.parametrize("who", ["hom.nbo", "desk", "security", "viewer"])
async def test_only_a_consular_or_duty_officer_approves(world: World, who: str) -> None:
    await world.observe(await world.incident(world.nbo))
    assert (await _approve(world, who)).status_code == 403


async def test_approving_starts_the_renewals_and_sends_reminders_as_a_person_would(
    world: World,
) -> None:
    # Aiko's renewal is already under way: skipped, and named in the result.
    assert (await world.step("duty", "aiko.pp", "IN_PROGRESS")).status_code == 200
    person_step = (await world.audited("DOCUMENT."))[0]
    incident = await world.incident(world.nbo)
    await world.observe(incident)
    response = await _approve(world, "consular")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "APPROVED"  # and executed: see PROPOSAL.EXECUTE

    rows = await world.sql(
        "SELECT id, renewal_status, renewal_requested_by FROM travel_document "
        "WHERE id IN (:a, :b) ORDER BY renewal_status",
        a=world.docs["hana.dp"],
        b=world.docs["aiko.pp"],
    )
    [(consular,)] = await world.sql("SELECT id FROM app_user WHERE external_id = 'consular'")
    assert [(r[1], r[2]) for r in rows] == [("IN_PROGRESS", None), ("REQUESTED", str(consular))]

    audited = await world.audited("DOCUMENT.")
    agent_step = audited[1]
    assert (agent_step[0], agent_step[1], agent_step[2]) == (
        "DOCUMENT.RENEWAL_REQUESTED",
        "AGENT",
        "COMPLIANCE",
    )
    # The same audit as a person's step, with the approver and the proposal added.
    assert set(agent_step[3]) == set(person_step[3]) | {"approved_by", "proposal_id"}
    assert agent_step[3]["approved_by"] == str(consular)
    assert [a for a, *_ in audited[2:]] == ["DOCUMENT.REMINDERS"]

    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        campaign = await session.scalar(select(NotificationCampaign))
        assert campaign is not None
        assert (campaign.created_by_type, campaign.campaign_type, campaign.incident_id) == (
            "AGENT",
            "ADVISORY",
            incident,
        )
        assert sorted(campaign.audience_filter["document_ids"]) == sorted(
            str(world.docs[k]) for k in ("hana.dp", "aiko.pp")
        )
        result = await session.scalar(
            select(AuditLog.details).where(AuditLog.action == "PROPOSAL.EXECUTE")
        )
    assert result is not None
    assert result["result"]["skipped"] == [str(world.docs["aiko.pp"])]
    assert result["result"]["recipients"] == 2
    kinds = [e.type for e in world.publisher.events]
    assert "DOCUMENT_UPDATED" in kinds
    assert "CAMPAIGN_QUEUED" in kinds


async def test_the_executor_refuses_a_document_of_another_mission(world: World) -> None:
    incident = await world.incident(world.nbo)
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        await proposals.create(
            session,
            proposals.ProposalIn(
                agent_code="COMPLIANCE",
                proposal_key="DX:test",
                action_type="START_DOCUMENT_RENEWAL",
                title="Renew",
                proposed_action="Renew",
                action_payload={"document_ids": [str(world.docs["paul.dp"])]},
                incident_id=incident,
            ),
            undo_window_s=300,
        )
        await session.commit()
    response = await _approve(world, "duty")
    assert response.json()["status"] == "FAILED"
    renewal = await world.sql(
        "SELECT renewal_status FROM travel_document WHERE id = :d", d=world.docs["paul.dp"]
    )
    assert renewal[0][0] == "NONE"
    assert await world.audited("DOCUMENT.") == []
