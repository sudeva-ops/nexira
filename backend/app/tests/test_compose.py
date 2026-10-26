"""Mass Notification composer through the API (Prompt 20; MN-01..10, MN-12; D-31).

The world: missions NBO (two staff) and PAR (two citizens), and one user per role.
Every decision is made through the API as a logged-in user; the database rules
(PC-08..PC-12) back the service, and nothing here talks to the database directly
except to check what was queued and audited."""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.notifications.models import NotificationDelivery
from app.modules.notifications.templates import TemplateIn, ensure_templates
from app.modules.people.service import PersonIn, load_persons
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher


@dataclass
class World:
    nbo: uuid.UUID
    par: uuid.UUID
    users: dict[str, uuid.UUID]
    publisher: ListPublisher


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo, par = await idp.mission("NBO"), await idp.mission("PAR")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "duty2": [("DUTY_OFFICER", None)],
        "security": [("SECURITY_OFFICER", None)],
        "consular.par": [("CONSULAR_OFFICER", par)],
        "consular.nbo": [("CONSULAR_OFFICER", nbo)],
        "admin": [("ADMIN", None)],
        "viewer": [("VIEWER", None)],
    }
    users = {sub: await idp.user(sub, roles) for sub, roles in grants.items()}
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await load_persons(
            session,
            [
                PersonIn(uuid.uuid4(), nbo, "DIPLOMAT", "Staff One"),
                PersonIn(uuid.uuid4(), nbo, "LOCAL_STAFF", "Staff Two"),
                PersonIn(uuid.uuid4(), par, "CITIZEN", "Citizen One"),
                PersonIn(uuid.uuid4(), par, "CITIZEN", "Citizen Two"),
            ],
        )
        await ensure_templates(
            session,
            [
                TemplateIn(
                    "SHELTER",
                    "ADVISORY",
                    "PAR",
                    "Paris",
                    {"en": "Stay indoors in Paris.", "fr": "Restez à l'intérieur à Paris."},
                    {"fr": True},
                )
            ],
        )
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(nbo, par, users, publisher)


def body(w: World, *, citizens: bool, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "ADVISORY" if citizens else "ALERT",
        "message": "Stay indoors." if citizens else "Shelter in place.",
        "channels": ["SMS", "APP"],
        "missions": [str(w.par if citizens else w.nbo)],
        **extra,
    }


async def draft(client: AsyncClient, idp: Idp, w: World, sub: str = "duty", **kw: Any) -> str:
    response = await client.post("/api/campaigns", json=body(w, **kw), headers=idp.headers(sub))
    assert response.status_code == 201, response.text
    campaign_id: str = response.json()["id"]
    return campaign_id


async def act(client: AsyncClient, idp: Idp, campaign_id: str, verb: str, sub: str) -> Any:
    return await client.post(f"/api/campaigns/{campaign_id}/{verb}", headers=idp.headers(sub))


async def queued(idp: Idp, campaign_id: str) -> int:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        count: int = (
            await session.scalar(
                select(func.count()).where(
                    NotificationDelivery.campaign_id == uuid.UUID(campaign_id)
                )
            )
            or 0
        )
    return count


async def audited(idp: Idp, action: str) -> int:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        count: int = (
            await session.scalar(select(func.count()).where(AuditLog.action == action)) or 0
        )
    return count


# --- drafts (MN-01) ---------------------------------------------------------------------


async def test_a_duty_officer_drafts_and_a_viewer_cannot(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    response = await client.post(
        "/api/campaigns", json=body(world, citizens=False), headers=idp.headers("duty")
    )
    assert response.status_code == 201
    out = response.json()
    assert (out["status"], out["created_by"], out["created_by_name"]) == (
        "DRAFT",
        str(world.users["duty"]),
        "User duty",
    )
    assert await queued(idp, out["id"]) == 0  # nothing queued until it is sent
    viewer = await client.post(
        "/api/campaigns", json=body(world, citizens=False), headers=idp.headers("viewer")
    )
    assert viewer.status_code == 403


async def test_the_author_fields_cannot_be_written_from_a_request(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=False)
    for field, value in (
        ("created_by", str(world.users["duty2"])),
        ("created_by_type", "PLAYBOOK"),
        ("submitted_by", str(world.users["duty2"])),
    ):
        response = await client.patch(
            f"/api/campaigns/{campaign_id}",
            json={**body(world, citizens=False), field: value},
            headers=idp.headers("duty"),
        )
        assert response.status_code == 422  # extra fields are refused
    out = (await client.get(f"/api/campaigns/{campaign_id}", headers=idp.headers("duty"))).json()
    assert (out["created_by"], out["created_by_type"], out["submitted_by"]) == (
        str(world.users["duty"]),
        "USER",
        None,
    )


async def test_only_the_author_edits_and_only_a_draft(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    other = await client.patch(
        f"/api/campaigns/{campaign_id}",
        json=body(world, citizens=True, message="Changed"),
        headers=idp.headers("duty2"),
    )
    assert other.status_code == 403
    assert (await act(client, idp, campaign_id, "submit", "duty")).status_code == 200
    frozen = await client.patch(
        f"/api/campaigns/{campaign_id}",
        json=body(world, citizens=True, message="Swapped while pending"),
        headers=idp.headers("duty"),
    )
    assert frozen.status_code == 409


async def test_unknown_missions_and_bad_audiences_are_refused(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    for bad in (
        {**body(world, citizens=True), "missions": [str(uuid.uuid4())]},  # not this tenant's
        {**body(world, citizens=True), "missions": []},  # no audience
        {**body(world, citizens=True), "exposed_to_incident": True},  # both kinds
        {**body(world, citizens=True), "channels": ["PIGEON"]},
        {**body(world, citizens=True), "translations": {"de": "Bleiben Sie drinnen."}},
        {**body(world, citizens=True), "message": " "},
    ):
        response = await client.post("/api/campaigns", json=bad, headers=idp.headers("duty"))
        assert response.status_code == 422, bad


# --- preview and test send (MN-02, MN-08) -------------------------------------------------


async def test_preview_counts_who_the_audience_selects(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    shown = (await act(client, idp, campaign_id, "preview", "duty")).json()
    assert shown == {"recipients": 2, "by_person_type": {"CITIZEN": 2}, "by_mission": {"PAR": 2}}


async def test_test_send_shows_each_channel_and_queues_nothing(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=True, message="x" * 200)
    shown = (await act(client, idp, campaign_id, "test-send", "duty")).json()
    assert set(shown) == {"SMS", "APP"}
    assert shown["SMS"]["sms_segments"] == 2
    assert await queued(idp, campaign_id) == 0
    assert await audited(idp, "CAMPAIGN.TEST_SEND") == 1
    assert (await act(client, idp, campaign_id, "test-send", "duty2")).status_code == 403


# --- sending to staff, and the second person for citizens (MN-05, D-31) --------------------


async def test_a_staff_only_campaign_is_sent_by_its_author(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=False)
    response = await act(client, idp, campaign_id, "submit", "duty")
    assert response.json()["status"] == "SENDING"
    assert await queued(idp, campaign_id) == 2 * 2  # two staff, two channels
    assert [e.type for e in world.publisher.events] == ["CAMPAIGN_QUEUED"]


async def test_a_consular_officer_cannot_send_to_staff(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, "consular.nbo", citizens=False)
    assert (await act(client, idp, campaign_id, "submit", "consular.nbo")).status_code == 403
    assert await queued(idp, campaign_id) == 0


async def test_citizens_need_a_second_person(client: AsyncClient, idp: Idp, world: World) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    submitted = await act(client, idp, campaign_id, "submit", "duty")
    assert submitted.json()["status"] == "PENDING_APPROVAL"
    assert await queued(idp, campaign_id) == 0

    author = await act(client, idp, campaign_id, "approve", "duty")
    assert author.status_code == 403  # submitting was the first step (plan G-2)
    assert (await act(client, idp, campaign_id, "approve", "viewer")).status_code == 403
    assert (await act(client, idp, campaign_id, "approve", "security")).status_code == 403
    # A Consular Officer of another mission is out of scope (D-05).
    assert (await act(client, idp, campaign_id, "approve", "consular.nbo")).status_code == 403

    approved = await act(client, idp, campaign_id, "approve", "duty2")
    assert approved.status_code == 200
    out = approved.json()
    assert (out["status"], out["approved_by"], out["approved_by_name"]) == (
        "SENDING",
        str(world.users["duty2"]),
        "User duty2",
    )
    assert out["approved_at"] is not None  # set by the database (PC-11)
    assert await queued(idp, campaign_id) == 2 * 2  # two citizens, two channels
    assert (await act(client, idp, campaign_id, "approve", "admin")).status_code in (403, 409)


async def test_a_consular_officer_of_the_mission_approves(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    await act(client, idp, campaign_id, "submit", "duty")
    response = await act(client, idp, campaign_id, "approve", "consular.par")
    assert response.json()["status"] == "SENDING"


async def test_a_rejection_returns_the_draft_to_its_author(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    await act(client, idp, campaign_id, "submit", "duty")
    rejected = await client.post(
        f"/api/campaigns/{campaign_id}/reject",
        json={"reason": "Too broad"},
        headers=idp.headers("duty2"),
    )
    assert (rejected.json()["status"], rejected.json()["rejection_reason"]) == (
        "DRAFT",
        "Too broad",
    )
    edited = await client.patch(
        f"/api/campaigns/{campaign_id}",
        json=body(world, citizens=True, message="Narrower"),
        headers=idp.headers("duty"),
    )
    assert edited.status_code == 200
    await act(client, idp, campaign_id, "submit", "duty")
    approved = await act(client, idp, campaign_id, "approve", "duty2")
    assert approved.json()["message"] == "Narrower"  # what is approved is what is sent


async def test_cancel_queues_nothing_and_only_before_sending(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    pending = await draft(client, idp, world, citizens=True)
    await act(client, idp, pending, "submit", "duty")
    assert (await act(client, idp, pending, "cancel", "duty2")).status_code == 403
    assert (await act(client, idp, pending, "cancel", "duty")).json()["status"] == "CANCELLED"
    assert await queued(idp, pending) == 0
    sent = await draft(client, idp, world, citizens=False)
    await act(client, idp, sent, "submit", "duty")
    assert (await act(client, idp, sent, "cancel", "admin")).status_code == 409


async def test_every_step_is_audited(client: AsyncClient, idp: Idp, world: World) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    await act(client, idp, campaign_id, "submit", "duty")
    await act(client, idp, campaign_id, "approve", "duty2")
    for action in ("CAMPAIGN.DRAFT", "CAMPAIGN.SUBMIT", "CAMPAIGN.APPROVE", "CAMPAIGN.SEND"):
        assert await audited(idp, action) == 1, action


# --- translations in a pilot (MN-06, plan G-11) ----------------------------------------------


@pytest.fixture
def pilot(idp: Idp) -> None:
    app.dependency_overrides[get_settings] = lambda: idp.settings().model_copy(
        update={"app_env": "pilot"}
    )


async def template_id(idp: Idp) -> str:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        value = await session.scalar(text("SELECT id FROM message_template WHERE code = 'SHELTER'"))
    return str(value)


async def test_a_pilot_refuses_an_unreviewed_translation(
    client: AsyncClient, idp: Idp, world: World, pilot: None
) -> None:
    campaign_id = await draft(
        client, idp, world, citizens=True, translations={"sw": "Kaeni ndani."}
    )
    await act(client, idp, campaign_id, "submit", "duty")
    refused = await act(client, idp, campaign_id, "approve", "duty2")
    assert refused.status_code == 409
    assert "sw" in refused.json()["detail"]
    assert await queued(idp, campaign_id) == 0


async def test_a_pilot_sends_a_reviewed_template_translation(
    client: AsyncClient, idp: Idp, world: World, pilot: None
) -> None:
    reviewed = {"fr": "Restez à l'intérieur à Paris."}
    campaign_id = await draft(
        client,
        idp,
        world,
        citizens=True,
        message="Stay indoors in Paris.",
        translations=reviewed,
        template_id=await template_id(idp),
    )
    await act(client, idp, campaign_id, "submit", "duty")
    assert (await act(client, idp, campaign_id, "approve", "duty2")).json()["status"] == "SENDING"
    # The same text, edited by one character, is no longer the reviewed one.
    edited = await draft(
        client,
        idp,
        world,
        citizens=True,
        translations={"fr": reviewed["fr"] + "!"},
        template_id=await template_id(idp),
    )
    await act(client, idp, edited, "submit", "duty")
    assert (await act(client, idp, edited, "approve", "duty2")).status_code == 409


# --- permissions (plan G-07) and templates (MN-03) -------------------------------------------


async def permissions(client: AsyncClient, idp: Idp, campaign_id: str, sub: str) -> Any:
    response = await client.get(
        "/api/me/permissions",
        params={"entity_type": "notification_campaign", "entity_id": campaign_id},
        headers=idp.headers(sub),
    )
    return response.json()


async def test_permissions_match_what_is_allowed(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    campaign_id = await draft(client, idp, world, citizens=True)
    mine = await permissions(client, idp, campaign_id, "duty")
    assert (mine["edit_campaign"], mine["submit_campaign"], mine["approve_campaign"]) == (
        True,
        True,
        False,
    )
    await act(client, idp, campaign_id, "submit", "duty")
    assert (await permissions(client, idp, campaign_id, "duty"))["approve_campaign"] is False
    assert (await permissions(client, idp, campaign_id, "duty2"))["approve_campaign"] is True
    assert (await permissions(client, idp, campaign_id, "viewer"))["approve_campaign"] is False


async def test_templates_editing_clears_review_and_viewers_cannot_edit(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    tid = await template_id(idp)
    viewer = await client.patch(
        f"/api/templates/{tid}", json={"name": "x"}, headers=idp.headers("viewer")
    )
    assert viewer.status_code == 403
    edited = await client.patch(
        f"/api/templates/{tid}",
        json={"texts": {"fr": "Restez chez vous."}},
        headers=idp.headers("consular.par"),
    )
    assert edited.json()["reviewed"] == {"fr": False}  # a changed text is not reviewed
    marked = await client.patch(
        f"/api/templates/{tid}", json={"reviewed": {"fr": True}}, headers=idp.headers("admin")
    )
    assert marked.json()["reviewed"] == {"fr": True}
    assert await audited(idp, "MESSAGE_TEMPLATE.UPDATE") == 2
