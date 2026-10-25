"""Safety check-in: answers, summary, escalation, API and simulator events
(CHK-01..03, D-07, D-28, plan G-19, Prompt 10)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.db import tenant_session
from app.core.events import Event, get_publisher
from app.main import app
from app.modules.audit.models import AuditLog
from app.modules.checkin import service
from app.modules.checkin.consumer import clock_handler, response_handler
from app.modules.intel import exposure
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.intel.service import ensure_sources
from app.modules.notifications.service import CampaignIn, create_campaign, dispatch
from app.modules.people import location
from app.modules.people.service import ObservationIn, PersonIn, add_observations, load_persons
from app.modules.scenarios.service import EventIn, active_run, ensure_scenario, get_scenario
from app.modules.tenancy.service import SYSTEM, Actor, ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import EPICENTRE, SOURCES, ingest, signal

NOW = datetime.now(UTC)
PEOPLE = [
    ("Hana", "DIPLOMAT"),
    ("Peter", "LOCAL_STAFF"),
    ("Grace", "DIPLOMAT"),
    ("Citizen A", "CITIZEN"),
    ("Citizen B", "CITIZEN"),
    ("Citizen C", "CITIZEN"),
]


@dataclass
class World:
    incident_id: uuid.UUID
    campaign_id: uuid.UUID
    reference: str
    ids: dict[str, uuid.UUID]
    publisher: ListPublisher


async def make_world(
    idp: Idp, *, demo_run: str | None = None, clock_scene: int | None = None
) -> World:
    """demo_run: the status of a demo scenario run to create (None = no run).
    clock_scene: the scene that starts the check-in clock (the run is at scene 0)."""
    nbo, cai = await idp.mission("NBO"), await idp.mission("CAI")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "viewer": [("VIEWER", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    ids = {name: uuid.uuid4() for name, _ in PEOPLE}
    outsider = uuid.uuid4()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await ensure_reference_counter(session, prefix="NTF", with_year=False, last_value=3100)
        await load_persons(
            session,
            [PersonIn(ids[n], nbo, t, n) for n, t in PEOPLE]
            + [PersonIn(outsider, cai, "DIPLOMAT", "Outsider")],
        )
        await add_observations(
            session,
            [
                ObservationIn(ids[n], "MANUAL", *EPICENTRE, NOW - timedelta(minutes=5))
                for n, _ in PEOPLE
            ]
            + [ObservationIn(outsider, "MANUAL", 30.0, 31.0, NOW - timedelta(minutes=5))],
        )
        await location.recompute(session, NOW)
        if demo_run is not None:
            await ensure_scenario(
                session,
                code="DEMO",
                name="Demo",
                description="",
                events=[
                    EventIn(
                        0,
                        0,
                        "SCENARIO_SETTINGS",
                        {"checkin_escalate_after_s": 20}
                        | ({} if clock_scene is None else {"checkin_clock_scene": clock_scene}),
                    )
                ],
            )
            scenario = await get_scenario(session, "DEMO")
            assert scenario is not None
            run = await active_run(session, scenario.id, None)
            run.status = demo_run
        await session.commit()
    now_signal = signal("DATAMINR", "High")
    now_signal.payload["occurred_at"] = NOW.isoformat()
    fused = (await ingest(idp.engine, idp.tenant_id, now_signal)).fused
    assert fused is not None
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await exposure.compute(session, fused.incident_id)
        # Exposure takes the mission from sites; this test has none, so set it.
        await session.execute(update(Incident).values(mission_id=nbo))
        row, recipients = await create_campaign(
            session,
            incident_id=fused.incident_id,
            campaign=CampaignIn(
                campaign_type="CHECKIN",
                message="Are you safe?",
                channels=["APP", "SMS"],
                audience={"exposed": True},
            ),
            created_by_type="PLAYBOOK",
            created_by="test",
            actor=SYSTEM,
        )
        assert recipients == 6
        await dispatch(session, NOW)
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(fused.incident_id, row.id, row.reference, ids, publisher)


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    return await make_world(idp)


def respond_url(w: World) -> str:
    return f"/api/checkin/{w.campaign_id}/respond"


async def answer(
    client: AsyncClient, idp: Idp, w: World, name: str, status: str, sub: str = "duty"
) -> int:
    response = await client.post(
        respond_url(w),
        json={"person_id": str(w.ids[name]), "status": status},
        headers=idp.headers(sub),
    )
    return response.status_code


async def summary(client: AsyncClient, idp: Idp, w: World) -> dict[str, object]:
    response = await client.get(
        f"/api/checkin/{w.campaign_id}/summary", headers=idp.headers("viewer")
    )
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


async def test_the_latest_answer_counts(client: AsyncClient, idp: Idp, world: World) -> None:
    assert await answer(client, idp, world, "Peter", "SAFE") == 201
    assert await answer(client, idp, world, "Peter", "NEED_HELP") == 201  # D-07
    assert await answer(client, idp, world, "Grace", "SAFE") == 201
    assert await answer(client, idp, world, "Citizen A", "SAFE", "consular") == 201
    body = await summary(client, idp, world)
    assert body["personnel"] == {
        "recipients": 3,
        "safe": 1,
        "need_help": 1,
        "pending": 1,
        "accounted_pct": 66.7,
    }
    assert body["citizens"] == {
        "recipients": 3,
        "safe": 1,
        "need_help": 0,
        "pending": 2,
        "accounted_pct": 33.3,
    }
    people = (
        await client.get(
            f"/api/checkin/{world.campaign_id}/people",
            params={"group": "personnel"},
            headers=idp.headers("viewer"),
        )
    ).json()
    assert [(p["full_name"], p["status"]) for p in people] == [
        ("Peter", "NEED_HELP"),
        ("Hana", "PENDING"),
        ("Grace", "SAFE"),
    ]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        responses = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "CHECKIN.RESPOND")
        )
        help_events = list(
            await session.scalars(
                select(IncidentEvent.summary).where(IncidentEvent.event_type == "CHECKIN")
            )
        )
    assert responses == 4  # history kept and audited
    assert help_events == [f"Peter needs help ({world.reference}, APP)."]
    assert [e.type for e in world.publisher.events] == ["CHECKIN_UPDATED"] * 4


async def test_who_may_record_an_answer(client: AsyncClient, idp: Idp, world: World) -> None:
    assert await answer(client, idp, world, "Hana", "SAFE", "viewer") == 403
    assert await answer(client, idp, world, "Hana", "SAFE", "hom.cai") == 403  # D-05
    assert await answer(client, idp, world, "Hana", "SAFE", "hom.nbo") == 201
    stranger = await client.post(
        respond_url(world),
        json={"person_id": str(uuid.uuid4()), "status": "SAFE"},
        headers=idp.headers("duty"),
    )
    assert stranger.status_code == 409  # not a recipient
    bad = await client.post(
        respond_url(world),
        json={"person_id": str(world.ids["Hana"]), "status": "MAYBE"},
        headers=idp.headers("duty"),
    )
    assert bad.status_code == 422


async def escalate(idp: Idp, at: datetime) -> list[service.Escalated]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        result = await service.escalate_due(session, at)
        await session.commit()
    return result


async def escalations(idp: Idp) -> list[dict[str, object]]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        return list(
            await session.scalars(
                select(AuditLog.details)
                .where(AuditLog.action == "CHECKIN.ESCALATE")
                .order_by(AuditLog.chain_seq)
            )
        )


async def test_non_responders_are_escalated_once(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await answer(client, idp, world, "Peter", "NEED_HELP")
    await answer(client, idp, world, "Grace", "SAFE")
    await answer(client, idp, world, "Citizen A", "SAFE")
    assert await escalate(idp, NOW + timedelta(seconds=599)) == []  # D-07: 600 s default
    first = await escalate(idp, NOW + timedelta(seconds=600))
    assert [(r.personnel, r.citizens) for r in first] == [(["Hana"], 2)]  # plan G-19
    assert await escalate(idp, NOW + timedelta(seconds=900)) == []  # once
    assert await escalations(idp) == [
        {"scope": "person", "person_id": str(world.ids["Hana"])},
        {"scope": "citizens", "count": 2},
    ]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        events = list(
            await session.scalars(
                select(IncidentEvent.summary).where(IncidentEvent.event_type == "ESCALATION")
            )
        )
    assert len(events) == 2
    assert events[0].startswith("Hana has not answered")
    people = (
        await client.get(
            f"/api/checkin/{world.campaign_id}/people",
            params={"status": "PENDING"},
            headers=idp.headers("viewer"),
        )
    ).json()
    assert {p["full_name"]: p["escalated"] for p in people} == {
        "Hana": True,
        "Citizen B": False,  # citizens are escalated as an aggregate
        "Citizen C": False,
    }


async def test_a_demo_scenario_run_shortens_escalation_to_20_seconds(
    client: AsyncClient, idp: Idp
) -> None:
    w = await make_world(idp, demo_run="PAUSED")
    summary_body = await summary(client, idp, w)
    assert summary_body["escalate_after_s"] == 20
    assert await escalate(idp, NOW + timedelta(seconds=19)) == []
    assert len(await escalate(idp, NOW + timedelta(seconds=20))) == 1


def sim_event(idp: Idp, person: uuid.UUID, status: str, **extra: object) -> Event:
    return Event(
        "CHECKIN_RESPONSE",
        idp.tenant_id,
        {
            "person_id": str(person),
            "status": status,
            "channel": "SMS",
            "campaign": "latest_open_checkin",
            **extra,
        },
        "scenario:test",
    )


async def test_an_idle_presenter_run_does_not_shorten_escalation(
    client: AsyncClient, idp: Idp
) -> None:
    w = await make_world(idp, demo_run="IDLE")  # opened, never played
    assert (await summary(client, idp, w))["escalate_after_s"] == 600


def clock_event(idp: Idp, seconds: object = 20) -> Event:
    return Event("CHECKIN_CLOCK", idp.tenant_id, {"escalate_in_s": seconds}, "scenario:test")


async def test_before_the_clock_scene_the_demo_does_not_shorten_escalation(
    client: AsyncClient, idp: Idp
) -> None:
    w = await make_world(idp, demo_run="PAUSED", clock_scene=4)  # still on scene 0
    assert (await summary(client, idp, w))["escalate_after_s"] == 600


async def test_the_clock_scene_starts_escalation_once(client: AsyncClient, idp: Idp) -> None:
    w = await make_world(idp, demo_run="PAUSED", clock_scene=4)
    handle = clock_handler(idp.engine, w.publisher, now=lambda: NOW + timedelta(seconds=100))
    event = clock_event(idp)
    await handle(event)
    await handle(event)  # redelivered: the clock is not pushed back
    assert (await summary(client, idp, w))["escalate_after_s"] == 120  # 100 s sent + 20 s
    assert await escalate(idp, NOW + timedelta(seconds=119)) == []
    assert [sorted(r.personnel) for r in await escalate(idp, NOW + timedelta(seconds=120))] == [
        ["Grace", "Hana", "Peter"]
    ]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        started = list(
            await session.scalars(
                select(AuditLog.details).where(AuditLog.action == "CHECKIN.CLOCK_START")
            )
        )
    assert started == [{"before": 600, "after": 120}]
    assert [e.type for e in w.publisher.events][-1:] == ["CHECKIN_UPDATED"]


async def rejections(idp: Idp) -> int:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        count = await session.scalar(
            select(func.count()).where(AuditLog.action == "CHECKIN.REJECT")
        )
    return count or 0


async def test_clock_events_need_a_running_demo(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await clock_handler(idp.engine, world.publisher)(clock_event(idp))
    assert (await summary(client, idp, world))["escalate_after_s"] == 600
    assert await rejections(idp) == 1


async def test_clock_events_need_a_valid_time(client: AsyncClient, idp: Idp) -> None:
    w = await make_world(idp, demo_run="PLAYING", clock_scene=4)
    handle = clock_handler(idp.engine, w.publisher)
    for bad in ("20", 0, 3601):
        await handle(clock_event(idp, bad))
    assert (await summary(client, idp, w))["escalate_after_s"] == 600
    assert await rejections(idp) == 3


async def test_simulated_answers_need_a_running_demo(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await response_handler(idp.engine, world.publisher)(sim_event(idp, world.ids["Hana"], "SAFE"))
    personnel = (await summary(client, idp, world))["personnel"]
    assert isinstance(personnel, dict)
    assert personnel["safe"] == 0  # a stray or forged event cannot mark anyone SAFE


async def test_simulator_answers_go_to_the_latest_open_check_in(
    client: AsyncClient, idp: Idp
) -> None:
    world = await make_world(idp, demo_run="PLAYING")
    handle = response_handler(idp.engine, world.publisher)
    first = sim_event(idp, world.ids["Hana"], "SAFE")
    await handle(first)
    await handle(first)  # redelivered after a crash: recorded once
    await handle(sim_event(idp, uuid.uuid4(), "SAFE"))  # no open check-in: rejected
    await handle(sim_event(idp, world.ids["Grace"], "MAYBE"))  # bad status: rejected
    await handle(sim_event(idp, world.ids["Grace"], "SAFE", channel="PIGEON"))  # rejected
    await handle(sim_event(idp, world.ids["Grace"], "SAFE", note="x" * 1001))  # rejected
    personnel = (await summary(client, idp, world))["personnel"]
    assert isinstance(personnel, dict)
    assert personnel["safe"] == 1
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        actions = list(
            await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.action.like("CHECKIN.%"))
                .order_by(AuditLog.chain_seq)
            )
        )
        actor = await session.scalar(
            select(AuditLog.actor_id).where(AuditLog.action == "CHECKIN.RESPOND")
        )
    assert actions == ["CHECKIN.RESPOND"] + ["CHECKIN.REJECT"] * 4
    assert actor == "channel.simulated"


async def test_the_service_refuses_non_checkin_campaigns(idp: Idp, world: World) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        with pytest.raises(service.CheckinError):
            await service.record_response(
                session,
                campaign_id=uuid.uuid4(),
                person_id=world.ids["Hana"],
                status="SAFE",
                channel=None,
                note=None,
                actor=Actor(type="SYSTEM", id="test"),
            )


async def test_users_can_escalate_now_and_only_once(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await answer(client, idp, world, "Peter", "SAFE")
    url = f"/api/checkin/{world.campaign_id}/escalate"
    assert (await client.post(url, headers=idp.headers("viewer"))).status_code == 403
    assert (await client.post(url, headers=idp.headers("hom.cai"))).status_code == 403
    first = await client.post(url, headers=idp.headers("hom.nbo"))
    assert first.status_code == 200
    assert first.json() == {"personnel": ["Grace", "Hana"], "citizens": 3}
    again = await client.post(url, headers=idp.headers("duty"))
    assert again.json() == {"personnel": [], "citizens": 0}  # once
    assert await escalate(idp, NOW + timedelta(days=1)) == []  # the timer adds nothing
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        actors = set(
            await session.scalars(
                select(AuditLog.actor_type).where(AuditLog.action == "CHECKIN.ESCALATE")
            )
        )
    assert actors == {"USER"}


async def test_live_responses_are_newest_first(client: AsyncClient, idp: Idp, world: World) -> None:
    await answer(client, idp, world, "Peter", "SAFE")
    await answer(client, idp, world, "Grace", "NEED_HELP")
    await answer(client, idp, world, "Peter", "NEED_HELP")
    rows = (
        await client.get(
            f"/api/checkin/{world.campaign_id}/responses", headers=idp.headers("viewer")
        )
    ).json()
    assert [(r["full_name"], r["status"]) for r in rows] == [
        ("Peter", "NEED_HELP"),
        ("Grace", "NEED_HELP"),
    ]
