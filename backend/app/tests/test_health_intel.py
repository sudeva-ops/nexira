"""Health Intelligence (HL-01..07, HL-09; D-39; docs/plan-pilot-hl.md): the advisory feed
and its updates, the missions an advisory affects, facilities with the Avoid flag,
readiness counts, entry requirements (also on the trip), sending a health advisory as a
Mass Notification draft, and the Communications agent's PREPARE_HEALTH_ADVISORY proposal,
whose campaign still needs a second person (G-2). Against real PostgreSQL, as nexira_api."""

import json
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
from app.modules.agents.agents.communications import Communications
from app.modules.agents.runner import run_agents
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.audit.models import AuditLog
from app.modules.health_intel import consumer
from app.modules.health_intel import service as health
from app.modules.notifications.templates import TemplateIn, ensure_templates
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

NAIROBI = (-1.2950, 36.8080)
CHOLERA = {
    "external_id": "who-don:cholera-ke",
    "topic": "Cholera",
    "topic_code": "CHOLERA",
    "countries": ["KE"],
    "region_label": "Kenya · Coast & Nairobi counties",
    "level": "MODERATE",
    "guidance": "Case increase in informal settlements; water-safety advice for staff.",
    "source": "WHO Disease Outbreak News (simulated)",
}
DENGUE = {
    **CHOLERA,
    "external_id": "who-don:dengue-bd",
    "topic": "Dengue fever",
    "topic_code": "DENGUE",
    "countries": ["BD"],
    "region_label": "Bangladesh · Dhaka division",
}
NBO_CHOLERA = (
    "Health advisory: Cholera cases are rising in {city}. Drink bottled or boiled water only, "
    "avoid street food, and seek care quickly if symptoms appear."
)
TEMPLATES = [
    TemplateIn(
        "HEALTH_CHOLERA",
        "ADVISORY",
        "NBO",
        "Cholera (Nairobi)",
        {"en": NBO_CHOLERA, "sw": "REVIEW REQUIRED · Ushauri wa afya: kipindupindu {city}."},
        {"sw": False},
    ),
    TemplateIn(
        "HEALTH_GENERAL",
        "ADVISORY",
        None,
        "Health advisory",
        {"en": "A health advisory is in force for {city}. Follow the mission's guidance."},
        {},
    ),
]


@dataclass
class World:
    idp: Idp
    client: AsyncClient
    publisher: ListPublisher
    nbo: uuid.UUID
    dac: uuid.UUID

    async def sql(self, statement: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            result = await session.execute(text(statement), params)
            await session.commit()
            return result

    async def get(self, who: str, url: str) -> Any:
        return await self.client.get(url, headers=self.idp.headers(who))

    async def post(self, who: str, url: str, body: dict[str, Any] | None = None) -> Any:
        return await self.client.post(url, json=body, headers=self.idp.headers(who))

    async def bulletin(self, **change: Any) -> None:
        """A HEALTH_ADVISORY scene event through the worker's handler."""
        event = Event("HEALTH_ADVISORY", self.idp.tenant_id, {**CHOLERA, **change}, "scenario")
        await consumer.advisory_handler(self.idp.engine, self.publisher)(event)

    async def advisory(self, external_id: str = "who-don:cholera-ke") -> dict[str, Any]:
        found = await self.sql(
            "SELECT * FROM health_advisory WHERE external_id = :e", e=external_id
        )
        return dict(found.mappings().one())

    async def observe(self) -> list[dict[str, Any]]:
        """The Communications agent on the last HEALTH_ADVISORY_UPDATED published."""
        [event] = [e for e in self.publisher.events if e.type == "HEALTH_ADVISORY_UPDATED"][-1:]
        await run_agents(
            self.idp.engine, self.publisher, event, undo_window_s=300, agents=[Communications()]
        )
        return await self.proposals()

    async def proposals(self) -> list[dict[str, Any]]:
        rows = await self.sql(
            "SELECT id, proposal_key, title, effective_level, status, action_payload, evidence "
            "FROM agent_proposal WHERE action_type = 'PREPARE_HEALTH_ADVISORY' "
            "ORDER BY created_at"
        )
        return [dict(r) for r in rows.mappings()]

    async def actions(self, prefix: str) -> list[str]:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return list(
                await session.scalars(
                    select(AuditLog.action)
                    .where(AuditLog.action.like(f"{prefix}%"))
                    .order_by(AuditLog.id)
                )
            )


async def _mission(
    idp: Idp, code: str, city: str, country: str, where: tuple[float, float]
) -> uuid.UUID:
    mission_id = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) VALUES "
                "(:id, current_tenant_id(), :code, :city, :cc, "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
            ),
            {
                "id": mission_id,
                "code": code,
                "city": city,
                "cc": country,
                "lat": where[0],
                "lon": where[1],
            },
        )
        for ptype, name in (("DIPLOMAT", "Fictional Diplomat"), ("CITIZEN", "Fictional Citizen")):
            await session.execute(
                text(
                    "INSERT INTO person (tenant_id, mission_id, person_type, full_name) "
                    "VALUES (current_tenant_id(), :m, :t, :n)"
                ),
                {"m": mission_id, "t": ptype, "n": f"{name} {code}"},
            )
        await session.commit()
    return mission_id


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo = await _mission(idp, "NBO", "Nairobi", "KE", NAIROBI)
    dac = await _mission(idp, "DAC", "Dhaka", "BD", (23.81, 90.41))
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "security.dac": [("SECURITY_OFFICER", dac)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await ensure_templates(session, TEMPLATES)
        await ensure_agents(session, [AgentIn("COMMUNICATIONS", "Communications", "", 2)])
        await ensure_policies(
            session,
            [
                PolicyIn(
                    "PREPARE_HEALTH_ADVISORY", 2, ["DUTY_OFFICER|CONSULAR_OFFICER"], False, 3600
                )
            ],
        )
        kestrel = await session.scalar(
            text(
                "INSERT INTO partner (tenant_id, code, name, services, coverage, sla_minutes) "
                "VALUES (current_tenant_id(), 'KES', 'Kestrel Medical Assistance (simulated)', "
                "'{MEDICAL}', '{KE}', 15) RETURNING id"
            )
        )
        await health.ensure_reference_data(
            session,
            facilities=[
                health.FacilityIn(
                    nbo,
                    "Nairobi Central Medical Centre (sample)",
                    -1.2836,
                    36.8172,
                    ["EMERGENCY"],
                    True,
                ),
                health.FacilityIn(
                    nbo,
                    "Karen Specialist Hospital (sample)",
                    -1.3200,
                    36.7100,
                    ["SURGERY", "ICU", "HELIPAD"],
                    True,
                    vetted_by=kestrel,
                ),
                health.FacilityIn(
                    nbo,
                    "Highland Private Hospital (sample)",
                    -1.2600,
                    36.7800,
                    ["EMERGENCY", "TRAUMA", "ICU"],
                    True,
                    1,
                    kestrel,
                ),
            ],
            requirements=[
                (
                    "KE",
                    "Yellow fever certificate if arriving from risk country",
                    "Hep A · Typhoid · Cholera (optional)",
                ),
                (
                    "BD",
                    "Yellow fever certificate if arriving from risk country",
                    "Hep A · Typhoid · Japanese encephalitis",
                ),
            ],
            readiness=[
                health.ReadinessIn(nbo, 14, 14, 14, 6, {"CHOLERA": 9}, date(2026, 10, 1)),
                health.ReadinessIn(dac, 15, 15, 13, 4, {"DENGUE": 15}, date(2026, 10, 1)),
            ],
        )
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, client, publisher, nbo, dac)


# --- the feed (HL-01, plan §2) ------------------------------------------------------------------


async def test_a_bulletin_creates_an_advisory_and_a_newer_one_moves_its_level(
    world: World,
) -> None:
    await world.bulletin()
    first = await world.advisory()
    assert (first["reference"], first["level"], first["status"]) == ("HA-0001", "MODERATE", "OPEN")
    await world.bulletin(level="HIGH", guidance="Bottled or boiled water only.")
    second = await world.advisory()
    assert (second["id"], second["level"], second["guidance"]) == (
        first["id"],
        "HIGH",
        "Bottled or boiled water only.",
    )
    assert second["updated_at"] >= first["updated_at"]
    events = [e.payload for e in world.publisher.events if e.type == "HEALTH_ADVISORY_UPDATED"]
    assert [(e["level"], e["previous_level"], e["status"]) for e in events] == [
        ("MODERATE", None, "OPEN"),
        ("HIGH", "MODERATE", "OPEN"),
    ]
    assert await world.actions("HEALTH_ADVISORY.") == [
        "HEALTH_ADVISORY.CREATE",
        "HEALTH_ADVISORY.UPDATE",
    ]


async def test_the_same_bulletin_twice_changes_nothing(world: World) -> None:
    await world.bulletin()
    await world.bulletin()
    assert len([e for e in world.publisher.events if e.type == "HEALTH_ADVISORY_UPDATED"]) == 1
    assert await world.actions("HEALTH_ADVISORY.") == ["HEALTH_ADVISORY.CREATE"]


async def test_a_closed_advisory_stays_closed(world: World) -> None:
    await world.bulletin()
    await world.bulletin(status="CLOSED")
    await world.bulletin(level="CRITICAL")  # a later bulletin for it is ignored
    assert ((await world.advisory())["level"], (await world.advisory())["status"]) == (
        "MODERATE",
        "CLOSED",
    )
    await world.bulletin(external_id="who-don:never-seen", status="CLOSED")
    assert await world.actions("HEALTH_ADVISORY.") == [
        "HEALTH_ADVISORY.CREATE",
        "HEALTH_ADVISORY.CLOSE",
    ]


async def test_a_bulletin_cannot_move_an_advisory_to_other_countries(world: World) -> None:
    await world.bulletin()
    await world.bulletin(countries=["BD"], level="HIGH")
    advisory = await world.advisory()
    assert (advisory["countries"], advisory["level"]) == (["KE"], "HIGH")


@pytest.mark.parametrize(
    "change",
    [{"level": "SEVERE"}, {"topic_code": "cholera"}, {"countries": []}, {"guidance": ""}],
)
async def test_a_malformed_bulletin_is_refused(world: World, change: dict[str, Any]) -> None:
    await world.bulletin(**change)
    assert (await world.sql("SELECT count(*) FROM health_advisory")).scalar() == 0
    assert world.publisher.events == []


async def test_seeded_advisories_publish_nothing(world: World) -> None:
    """§2: seeding sends no event, so no agent reacts at `make reset-demo`."""
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        made = await health.ensure_advisories(
            session, [health.AdvisoryIn.model_validate(b) for b in (CHOLERA, DENGUE)]
        )
        again = await health.ensure_advisories(session, [health.AdvisoryIn.model_validate(CHOLERA)])
        await session.commit()
    assert (made, again) == (2, 0)
    assert world.publisher.events == []
    assert await world.actions("HEALTH_ADVISORY.") == ["HEALTH_ADVISORY.SEED"]


# --- reading (HL-02..05, HL-09) -----------------------------------------------------------------


async def test_every_role_reads_advisories_with_the_missions_they_affect(world: World) -> None:
    await world.bulletin()
    await world.bulletin(**DENGUE)
    response = await world.get("viewer", "/api/health/advisories")
    assert response.status_code == 200
    rows = {a["topic"]: a for a in response.json()}
    assert [m["code"] for m in rows["Cholera"]["missions"]] == ["NBO"]
    assert [m["code"] for m in rows["Dengue fever"]["missions"]] == ["DAC"]
    assert all(a["simulated"] for a in rows.values())


async def test_the_summary_counts_missions_by_level_and_staff_not_offered(world: World) -> None:
    await world.bulletin(level="HIGH")
    await world.bulletin(**DENGUE)
    body = (await world.get("viewer", "/api/health/summary")).json()
    assert (
        body["open_advisories"],
        body["affecting_missions"],
        body["missions_with_advisory"],
    ) == (
        2,
        2,
        2,
    )
    assert body["by_level"] == [
        {"level": "HIGH", "missions": 1},
        {"level": "MODERATE", "missions": 1},
    ]
    # G-3: Nairobi 14 - 9 not offered the cholera vaccine; Dhaka 15 - 15 dengue.
    assert body["staff_not_offered"] == 5
    assert body["vetted_facilities"] == 2


async def test_a_facility_inside_an_active_incident_is_flagged_avoid(world: World) -> None:
    """HL-04: Nairobi Central is 1.4 km from the Embassy, inside the incident's 5 km."""
    incident = await world.sql(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        "location, impact_radius_m) VALUES (current_tenant_id(), 'INC-2026-1042', 'Unrest', "
        "'CIVIL_UNREST', 'CRITICAL', 'CRITICAL', 'SRID=4326;POINT(36.8219 -1.2864)', 5000) "
        "RETURNING id"
    )
    incident_id = incident.scalar()
    detail = (await world.get("viewer", f"/api/health/missions/{world.nbo}")).json()
    by_name = {f["name"]: f for f in detail["facilities"]}
    central = by_name["Nairobi Central Medical Centre (sample)"]
    assert (central["avoid"], central["avoid_incident"]) == (True, "INC-2026-1042")
    assert by_name["Karen Specialist Hospital (sample)"]["avoid"] is False
    assert [f["distance_m"] for f in detail["facilities"]] == sorted(
        f["distance_m"] for f in detail["facilities"]
    )
    assert by_name["Karen Specialist Hospital (sample)"]["vetted_by"] == (
        "Kestrel Medical Assistance (simulated)"
    )
    await world.sql("UPDATE incident SET status = 'MONITORING' WHERE id = :i", i=incident_id)
    detail = (await world.get("viewer", f"/api/health/missions/{world.nbo}")).json()
    assert not any(f["avoid"] for f in detail["facilities"])  # ACTIVE incidents only


async def test_readiness_is_counts_only_and_names_nobody(world: World) -> None:
    await world.bulletin()
    response = await world.get("viewer", f"/api/health/missions/{world.nbo}")
    body = response.json()
    assert body["level"] == "MODERATE"
    assert body["readiness"]["staff"] == 14
    assert body["readiness"]["vaccines"] == [
        {"topic_code": "CHOLERA", "offered": 9, "open_advisory": True}
    ]
    assert body["requirement"]["mandatory"].startswith("Yellow fever")
    assert "Fictional" not in response.text  # no names (D-39, HL-09)
    assert (await world.get("viewer", f"/api/health/missions/{uuid.uuid4()}")).status_code == 404


async def test_requirements_list_and_the_trip_shows_its_destination(world: World) -> None:
    body = (await world.get("viewer", "/api/health/requirements")).json()
    assert [r["country_code"] for r in body] == ["BD", "KE"]
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        assert (await health.requirement_for(session, "ke")) is not None
        assert (await health.requirement_for(session, "FR")) is None
        assert (await health.requirement_for(session, None)) is None


async def test_the_trip_detail_carries_its_destinations_requirement(world: World) -> None:
    trip = await world.sql(
        "INSERT INTO trip (tenant_id, reference, origin, destination, destination_country, "
        "starts_on, ends_on) VALUES (current_tenant_id(), 'TRP-9001', 'Dubai', 'Nairobi', 'KE', "
        "current_date, current_date + 3) RETURNING id"
    )
    response = await world.get("duty", f"/api/trips/{trip.scalar()}")
    assert response.status_code == 200
    assert response.json()["health_requirement"]["recommended"] == (
        "Hep A · Typhoid · Cholera (optional)"
    )


# --- sending (HL-06) ----------------------------------------------------------------------------


async def test_a_duty_officer_drafts_the_mission_health_advisory(world: World) -> None:
    await world.bulletin()
    advisory = await world.advisory()
    response = await world.post(
        "duty",
        f"/api/health/advisories/{advisory['id']}/campaign",
        {"mission_id": str(world.nbo)},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["template"]) == ("DRAFT", "HEALTH_CHOLERA")
    campaign = (
        (
            await world.sql(
                "SELECT campaign_type, message, translations, channels, audience_filter, "
                "created_by_type FROM notification_campaign WHERE id = :i",
                i=body["campaign_id"],
            )
        )
        .mappings()
        .one()
    )
    assert campaign["message"] == NBO_CHOLERA.replace("{city}", "Nairobi")
    assert list(campaign["translations"]) == ["sw"]
    assert campaign["audience_filter"] == {
        "missions": [str(world.nbo)],
        "person_types": ["CITIZEN", "DEPENDANT", "DIPLOMAT", "LOCAL_STAFF"],
    }
    assert (campaign["campaign_type"], campaign["created_by_type"]) == ("ADVISORY", "USER")
    assert await world.actions("HEALTH_ADVISORY.CAMPAIGN") == ["HEALTH_ADVISORY.CAMPAIGN"]
    # Then D-31 as for any campaign: submitted, it waits for a second person.
    submit = await world.post("duty", f"/api/campaigns/{body['campaign_id']}/submit")
    assert submit.json()["status"] == "PENDING_APPROVAL"


async def test_a_topic_with_no_template_uses_the_general_one(world: World) -> None:
    await world.bulletin(**DENGUE)
    advisory = await world.advisory("who-don:dengue-bd")
    response = await world.post(
        "duty", f"/api/health/advisories/{advisory['id']}/campaign", {"mission_id": str(world.dac)}
    )
    assert response.json()["template"] == "HEALTH_GENERAL"


@pytest.mark.parametrize(
    ("who", "status"), [("viewer", 403), ("hom.nbo", 403), ("security.dac", 403)]
)
async def test_only_composers_for_the_mission_send(world: World, who: str, status: int) -> None:
    await world.bulletin()
    advisory = await world.advisory()
    response = await world.post(
        who, f"/api/health/advisories/{advisory['id']}/campaign", {"mission_id": str(world.nbo)}
    )
    assert response.status_code == status
    permission = (
        await world.get(who, f"/api/me/permissions?entity_type=health&entity_id={world.nbo}")
    ).json()
    assert permission["send_advisory"] is False


async def test_the_permission_follows_the_open_advisories(world: World) -> None:
    url = f"/api/me/permissions?entity_type=health&entity_id={world.nbo}"
    assert (await world.get("consular", url)).json()["send_advisory"] is False  # nothing open
    await world.bulletin()
    assert (await world.get("consular", url)).json()["send_advisory"] is True
    dhaka = f"/api/me/permissions?entity_type=health&entity_id={world.dac}"
    assert (await world.get("consular", dhaka)).json()["send_advisory"] is False


async def test_a_closed_advisory_or_an_unaffected_mission_is_refused(world: World) -> None:
    await world.bulletin()
    advisory = await world.advisory()
    url = f"/api/health/advisories/{advisory['id']}/campaign"
    assert (await world.post("duty", url, {"mission_id": str(world.dac)})).status_code == 409
    await world.bulletin(status="CLOSED")
    assert (await world.post("duty", url, {"mission_id": str(world.nbo)})).status_code == 409
    unknown = f"/api/health/advisories/{uuid.uuid4()}/campaign"
    assert (await world.post("duty", unknown, {"mission_id": str(world.nbo)})).status_code == 404


# --- the Communications agent (HL-07, plan §7) --------------------------------------------------


async def test_a_rise_to_high_proposes_the_advisory_for_each_affected_mission(
    world: World,
) -> None:
    await world.bulletin()
    assert await world.observe() == []  # MODERATE: nothing
    await world.bulletin(level="HIGH")
    [proposal] = await world.observe()
    advisory = await world.advisory()
    assert proposal["title"] == "Health advisory recommended for Nairobi staff and citizens"
    assert (proposal["effective_level"], proposal["status"]) == (2, "PENDING")
    assert proposal["proposal_key"] == (
        f"PREPARE_HEALTH_ADVISORY:{advisory['id']}:{world.nbo}:HIGH"
    )
    assert proposal["action_payload"]["message"] == NBO_CHOLERA.replace("{city}", "Nairobi")
    assert proposal["action_payload"]["mission_id"] == str(world.nbo)
    texts = [e["text"] for e in proposal["evidence"]]
    assert "9 of 14 staff offered the cholera vaccine" in texts
    # The same bulletin again, or a rise while one is pending: still one proposal (G-6).
    await world.bulletin(level="CRITICAL")
    assert len(await world.observe()) == 1


async def test_approving_creates_a_campaign_a_second_person_must_approve(world: World) -> None:
    """G-2: the proposal's approver submits; neither they nor the agent may approve it."""
    await world.bulletin(level="HIGH")
    [proposal] = await world.observe()
    assert (await world.post("viewer", f"/api/proposals/{proposal['id']}/approve")).status_code in (
        403,
        409,
    )
    approved = await world.post("duty", f"/api/proposals/{proposal['id']}/approve")
    assert approved.status_code == 200, approved.text
    [done] = await world.proposals()
    assert done["status"] == "APPROVED", done
    found = await world.sql(
        "SELECT id, status, created_by_type, submitted_by FROM notification_campaign "
        "WHERE created_by = :p",
        p=str(proposal["id"]),
    )
    campaign = found.mappings().one()
    campaign_id = campaign["id"]
    duty = (await world.sql("SELECT id FROM app_user WHERE external_id = 'duty'")).scalar()
    assert (campaign["status"], campaign["created_by_type"], campaign["submitted_by"]) == (
        "PENDING_APPROVAL",
        "AGENT",
        duty,
    )
    assert (await world.sql("SELECT count(*) FROM notification_delivery")).scalar() == 0
    refused = await world.post("duty", f"/api/campaigns/{campaign_id}/approve")
    assert refused.status_code == 403
    sent = await world.post("consular", f"/api/campaigns/{campaign_id}/approve")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "SENDING"
    assert "CAMPAIGN.PREPARE" in await world.actions("CAMPAIGN.")


async def test_a_closed_advisory_proposes_nothing_and_cannot_be_executed(world: World) -> None:
    await world.bulletin(level="HIGH")
    [proposal] = await world.observe()
    await world.bulletin(status="CLOSED")
    assert len(await world.observe()) == 1  # CLOSED: no new proposal
    approved = await world.post("duty", f"/api/proposals/{proposal['id']}/approve")
    assert approved.status_code == 200
    [failed] = await world.proposals()
    assert failed["status"] == "FAILED"
    assert (await world.sql("SELECT count(*) FROM notification_campaign")).scalar() == 0


async def test_the_english_only_alternative_drops_the_translations(world: World) -> None:
    await world.bulletin(level="HIGH")
    [proposal] = await world.observe()
    alternatives = (
        await world.sql("SELECT alternatives FROM agent_proposal WHERE id = :i", i=proposal["id"])
    ).scalar()
    assert [a["label"] for a in alternatives] == ["English only"]
    assert alternatives[0]["action_payload"]["translations"] == {}
    assert json.dumps(proposal["action_payload"]["translations"]).count("REVIEW REQUIRED") == 1
