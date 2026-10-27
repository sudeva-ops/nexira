"""Travel & Air agent actions and policies (Prompt 34; TA-05, TA-06, TA-07; D-34,
docs/plan-pilot-ta.md §3, G-1, G-2, G-4). Each proposal is decided through the API as a
logged-in user, exactly as the Decision Queue does."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.agents import proposals
from app.modules.agents.actions import ActionError
from app.modules.agents.models import AgentProposal
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.notifications.models import NotificationCampaign, NotificationDelivery
from app.modules.people.service import PersonIn, load_persons
from app.modules.tenancy.service import ensure_reference_counter
from app.modules.travel.models import Trip
from app.modules.travel.service import ensure_trip
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

POLICIES = [  # the seed (plan-pilot-ta §6)
    PolicyIn("NOTIFY_TRAVELLERS", 2, ["TRAVEL_DESK|SECURITY_OFFICER"], False, 3600),
    PolicyIn("CANCEL_TRIP", 2, ["SECURITY_OFFICER"], False, 3600),
]


@dataclass
class World:
    idp: Idp
    staff: list[uuid.UUID]
    citizen: uuid.UUID
    publisher: ListPublisher

    async def trip(
        self,
        travellers: list[uuid.UUID] | None = None,
        *,
        starts_in_days: int = 5,
        status: str = "APPROVED",
        restricted: bool = False,
    ) -> uuid.UUID:
        trip_id = uuid.uuid4()
        start = date.today() + timedelta(days=starts_in_days)
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            await ensure_trip(
                session,
                trip_id=trip_id,
                reference=f"TRP-{trip_id.hex[:6]}",
                purpose="Consultations",
                origin="HQ",
                destination="Paris",
                destination_country="FR",
                starts_on=start,
                ends_on=start + timedelta(days=2),
                traveller_ids=travellers if travellers is not None else self.staff,
                approval_status=status,
                restricted=restricted,
            )
            await session.commit()
        return trip_id

    async def propose(self, action_type: str, payload: dict[str, Any]) -> AgentProposal:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            outcome = await proposals.create(
                session,
                proposals.ProposalIn(
                    agent_code="TRAVEL_AIR",
                    proposal_key=str(uuid.uuid4()),
                    action_type=action_type,
                    title=f"{action_type} proposal",
                    proposed_action=action_type,
                    action_payload=payload,
                    evidence=[{"text": "test", "source": "test"}],
                ),
                undo_window_s=300,
            )
            await session.commit()
            return outcome.proposal

    async def stored(self, proposal_id: uuid.UUID) -> AgentProposal:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return await session.get_one(AgentProposal, proposal_id)

    async def sql(self, query: str, **params: Any) -> Any:
        async with tenant_session(self.idp.tenant_id, self.idp.engine) as session:
            return (await session.execute(text(query), params)).all()


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    mission = await idp.mission("PAR")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "desk": [("TRAVEL_DESK", None)],
        "security": [("SECURITY_OFFICER", None)],
        "duty": [("DUTY_OFFICER", None)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    staff = [uuid.uuid4(), uuid.uuid4()]
    citizen = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_reference_counter(session, prefix="NTF", with_year=False, last_value=3100)
        await ensure_agents(session, [AgentIn("TRAVEL_AIR", "Travel & Air", "", 2)])
        await ensure_policies(session, POLICIES)
        await load_persons(
            session,
            [
                PersonIn(staff[0], mission, "DIPLOMAT", "Fictional Staff A"),
                PersonIn(staff[1], mission, "LOCAL_STAFF", "Fictional Staff B"),
                PersonIn(citizen, mission, "CITIZEN", "Fictional Citizen"),
            ],
        )
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(idp, staff, citizen, publisher)


async def approve(client: AsyncClient, w: World, proposal_id: uuid.UUID, sub: str) -> Response:
    return await client.post(
        f"/api/proposals/{proposal_id}/approve", json={}, headers=w.idp.headers(sub)
    )


def notify(trip_id: uuid.UUID) -> dict[str, Any]:
    return {"trip_id": str(trip_id), "message": "Your flight is holding near Nairobi."}


# --- policies (TA-06, D-12, D-16) -------------------------------------------------------------


async def test_both_actions_are_level_2_and_advice_is_level_4(world: World) -> None:
    trip_id = await world.trip()
    for action_type, payload in (
        ("NOTIFY_TRAVELLERS", notify(trip_id)),
        ("CANCEL_TRIP", {"trip_id": str(trip_id)}),
    ):
        proposal = await world.propose(action_type, payload)
        assert (proposal.effective_level, proposal.status) == (2, "PENDING"), action_type
    advice = await world.propose("ADVISE_REBOOKING", {"trip_id": str(trip_id), "at": "MBA"})
    assert advice.effective_level == 4  # no policy: advice only, never executed (D-12)


async def test_who_approves_each_action(client: AsyncClient, world: World) -> None:
    trip_id = await world.trip()
    message = await world.propose("NOTIFY_TRAVELLERS", notify(trip_id))
    for sub in ("duty", "viewer"):
        assert (await approve(client, world, message.id, sub)).status_code == 403, sub
    assert (await approve(client, world, message.id, "desk")).status_code == 200
    cancel = await world.propose("CANCEL_TRIP", {"trip_id": str(trip_id)})
    for sub in ("desk", "duty"):
        assert (await approve(client, world, cancel.id, sub)).status_code == 403, sub
    assert (await approve(client, world, cancel.id, "security")).status_code == 200


async def test_advice_is_never_executed(client: AsyncClient, world: World) -> None:
    advice = await world.propose("ADVISE_REBOOKING", {"trip_id": str(await world.trip())})
    for sub in ("desk", "security", "duty"):
        response = await approve(client, world, advice.id, sub)
        assert response.status_code in (403, 409), sub
    assert (await world.stored(advice.id)).status == "PENDING"


# --- NOTIFY_TRAVELLERS (TA-05, G-1, G-2) ---------------------------------------------------------


async def test_notify_sends_a_staff_alert_to_the_trips_travellers(
    client: AsyncClient, world: World
) -> None:
    trip_id = await world.trip()
    proposal = await world.propose("NOTIFY_TRAVELLERS", notify(trip_id))
    assert (await approve(client, world, proposal.id, "desk")).status_code == 200
    stored = await world.stored(proposal.id)
    assert stored.status == "APPROVED"
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        campaign = await session.scalar(select(NotificationCampaign))
        assert campaign is not None
        recipients = set(
            await session.scalars(
                select(NotificationDelivery.person_id).where(
                    NotificationDelivery.campaign_id == campaign.id
                )
            )
        )
    assert (campaign.campaign_type, campaign.incident_id, campaign.created_by_type) == (
        "ALERT",
        None,  # no incident needed (G-1)
        "AGENT",
    )
    assert campaign.audience_filter == {"trip_id": str(trip_id)}
    assert recipients == set(world.staff)
    assert any(e.type == "CAMPAIGN_QUEUED" for e in world.publisher.events)


@pytest.mark.parametrize("case", ["restricted", "citizen"])
async def test_notify_refuses_restricted_trips_and_citizens(
    client: AsyncClient, world: World, case: str
) -> None:
    """TA-07, D-31: the audience fails closed; the execution is FAILED, nothing sent."""
    trip_id = (
        await world.trip(restricted=True)
        if case == "restricted"
        else await world.trip([*world.staff, world.citizen])
    )
    proposal = await world.propose("NOTIFY_TRAVELLERS", notify(trip_id))
    await approve(client, world, proposal.id, "desk")
    assert (await world.stored(proposal.id)).status == "FAILED"
    assert (await world.sql("SELECT count(*) FROM notification_campaign"))[0][0] == 0
    failed = await world.sql(
        "SELECT count(*) FROM audit_log WHERE action = 'PROPOSAL.FAIL' AND details::text LIKE :why",
        why="%restricted%" if case == "restricted" else "%citizen%",
    )
    assert failed[0][0] == 1


# --- CANCEL_TRIP (TA-05, G-4) -------------------------------------------------------------------


async def test_cancel_cancels_an_approved_trip_that_has_not_started(
    client: AsyncClient, world: World
) -> None:
    trip_id = await world.trip()
    proposal = await world.propose("CANCEL_TRIP", {"trip_id": str(trip_id)})
    assert (await approve(client, world, proposal.id, "security")).status_code == 200
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        trip = await session.get_one(Trip, trip_id)
    assert trip.approval_status == "CANCELLED"
    audited = await world.sql(
        "SELECT actor_type, details->>'approved_by' FROM audit_log WHERE action = 'TRIP.CANCEL'"
    )
    security = await world.sql("SELECT id FROM app_user WHERE external_id = 'security'")
    assert audited == [("AGENT", str(security[0][0]))]
    assert any(e.type == "TRIP_UPDATED" for e in world.publisher.events)


@pytest.mark.parametrize(
    ("kind", "why"),
    [
        ("restricted", "restricted"),
        ("started", "has started"),
        ("pending", "not APPROVED"),
    ],
)
async def test_cancel_refuses_what_it_must_not_touch(
    client: AsyncClient, world: World, kind: str, why: str
) -> None:
    trip_id = await world.trip(
        restricted=kind == "restricted",
        starts_in_days=0 if kind == "started" else 5,
        status="PENDING" if kind == "pending" else "APPROVED",
    )
    proposal = await world.propose("CANCEL_TRIP", {"trip_id": str(trip_id)})
    await approve(client, world, proposal.id, "security")
    assert (await world.stored(proposal.id)).status == "FAILED"
    async with tenant_session(world.idp.tenant_id, world.idp.engine) as session:
        trip = await session.get_one(Trip, trip_id)
    assert trip.approval_status != "CANCELLED"
    failed = await world.sql(
        "SELECT count(*) FROM audit_log WHERE action = 'PROPOSAL.FAIL' AND details::text LIKE :why",
        why=f"%{why}%",
    )
    assert failed[0][0] == 1


async def test_payloads_are_strict(world: World) -> None:
    trip_id = await world.trip()
    for action_type, payload in (
        ("NOTIFY_TRAVELLERS", {**notify(trip_id), "audience": {"missions": []}}),  # no override
        ("NOTIFY_TRAVELLERS", {"trip_id": "not-a-uuid", "message": "x"}),
        ("CANCEL_TRIP", {"trip_id": str(trip_id), "force": True}),
    ):
        with pytest.raises((proposals.ProposalError, ActionError)):
            await world.propose(action_type, payload)
