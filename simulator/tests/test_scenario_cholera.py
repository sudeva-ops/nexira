"""NBO-CHOLERA (D-39, HL-07, HL-10; docs/plan-pilot-hl.md §10): its content, and scenes 1-2
through the worker's real handlers on the same in-memory bus as the Nairobi agents test.
A Duty Officer approves the Communications agent's proposal; the campaign then waits for a
second person, the Consular Officer (G-2). Also: Nairobi Central shows Avoid while the
NBO-CIVIL-UNREST incident is ACTIVE (§47)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest
import pytest_asyncio
from app.core import approvals
from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents import proposals
from app.modules.agents.models import AgentProposal
from app.modules.health_intel import consumer
from app.modules.health_intel import service as health
from app.modules.health_intel.models import HealthAdvisory
from app.modules.notifications import compose
from app.modules.notifications.models import NotificationCampaign
from app.tests.conftest import DbUrls
from sqlalchemy import select

from nexira_sim.scenarios import nbo_cholera as cholera
from nexira_sim.seed import data, world
from tests.scene_helpers import seed
from tests.test_agents_nbo import Bus, scene_1, user

pytestmark = pytest.mark.asyncio(loop_scope="module")
TENANT = uuid.UUID("11111111-2222-3333-4444-777777777777")
EVENTS = cholera.build_events(world.build(date(2026, 10, 31), TENANT), TENANT)


# --- content -----------------------------------------------------------------------------------


def test_every_scene_has_a_marker_and_the_build_is_deterministic() -> None:
    assert sorted(e.scene_no for e in EVENTS if e.event_type == "SCENE_START") == [0, 1, 2]
    assert cholera.build_events(world.build(date(2026, 10, 31), TENANT), TENANT) == EVENTS
    assert [e.event_type for e in EVENTS if e.scene_no == 0] == ["SCENE_START"]


def test_every_bulletin_is_a_valid_update_of_a_seeded_advisory() -> None:
    seeded = {row[0] for row in data.HEALTH_ADVISORIES}
    bulletins = [e for e in EVENTS if e.event_type == "HEALTH_ADVISORY"]
    assert [(e.scene_no, e.payload["external_id"]) for e in bulletins] == [
        (1, "who-don:cholera-ke"),
        (2, "moh-bd:dengue-dhaka"),
    ]
    for e in bulletins:
        assert e.payload["external_id"] in seeded
        health.AdvisoryIn.model_validate(e.payload)
    assert bulletins[0].payload["level"] == "HIGH"
    assert bulletins[1].payload["status"] == "CLOSED"


# --- the play-through --------------------------------------------------------------------------


@dataclass
class Played:
    levels: dict[int, dict[str, tuple[str, str]]] = field(default_factory=dict)
    proposals: list[AgentProposal] = field(default_factory=list)
    campaign: dict[str, Any] = field(default_factory=dict)
    sent: dict[str, Any] = field(default_factory=dict)
    duty_refused: bool = False
    avoid: dict[str, bool] = field(default_factory=dict)


def scene(n: int, tenant_id: uuid.UUID) -> list[Event]:
    return [
        Event(e.event_type, tenant_id, dict(e.payload), "scenario")
        for e in cholera.build_events(world.build(datetime.now(UTC).date(), tenant_id), tenant_id)
        if e.scene_no == n and e.event_type != "SCENE_START"
    ]


async def levels(engine: Any, tenant_id: uuid.UUID) -> dict[str, tuple[str, str]]:
    async with tenant_session(tenant_id, engine) as session:
        rows = await session.scalars(select(HealthAdvisory))
        return {a.topic_code: (a.level, a.status) for a in rows}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def played(db: DbUrls) -> Played:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    result = Played()
    try:
        await seed(db, engine, tenant_id, datetime.now(UTC).date())
        bus = Bus(engine)
        bus.routes["HEALTH_ADVISORY"] = [consumer.advisory_handler(engine, bus.publisher)]
        result.levels[0] = await levels(engine, tenant_id)
        await bus.deliver(scene(1, tenant_id))
        result.levels[1] = await levels(engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            result.proposals = list(
                await session.scalars(
                    select(AgentProposal).where(
                        AgentProposal.action_type == "PREPARE_HEALTH_ADVISORY"
                    )
                )
            )
            [proposal] = result.proposals
            duty = await user(engine, tenant_id, "duty.officer")
            outcome = await proposals.approve(session, duty, proposal.id)
            await session.commit()
        await bus.deliver(outcome.events)
        async with tenant_session(tenant_id, engine) as session:
            campaign = await session.scalar(
                select(NotificationCampaign).where(
                    NotificationCampaign.created_by == str(proposal.id)
                )
            )
            assert campaign is not None
            campaign_id = campaign.id
            result.campaign = {
                "status": campaign.status,
                "type": campaign.created_by_type,
                "message": campaign.message,
                "languages": sorted(campaign.translations),
            }
            # The proposal's approver submitted it, so the gate refuses them (G-2).
            with pytest.raises(approvals.ApprovalDeniedError):
                await compose.approve(session, duty, campaign_id, "demo")
            result.duty_refused = True
            await session.rollback()
        async with tenant_session(tenant_id, engine) as session:
            consular = await user(engine, tenant_id, "consular.officer")
            sent = await compose.approve(session, consular, campaign_id, "demo")
            await session.commit()
            result.sent = {"status": sent.campaign.status}
        await bus.deliver(scene(2, tenant_id))
        result.levels[2] = await levels(engine, tenant_id)
        # §47: Nairobi Central is to be avoided while the unrest incident is ACTIVE.
        await bus.deliver(scene_1(tenant_id, datetime.now(UTC).date()))
        async with tenant_session(tenant_id, engine) as session:
            nbo = next(m for m in await health.mission_rows(session) if m.code == "NBO")
            detail = await health.mission_health(session, nbo.id)
            result.avoid = {f.name: f.avoid for f in detail.facilities}
    finally:
        await engine.dispose()
    return result


async def test_scene_0_has_the_six_seeded_advisories_and_cholera_moderate(played: Played) -> None:
    assert len(played.levels[0]) == 6
    assert played.levels[0]["CHOLERA"] == ("MODERATE", "OPEN")


async def test_scene_1_raises_cholera_and_the_agent_proposes_for_nairobi(played: Played) -> None:
    assert played.levels[1]["CHOLERA"] == ("HIGH", "OPEN")
    [proposal] = played.proposals
    assert proposal.title == "Health advisory recommended for Nairobi staff and citizens"
    assert proposal.effective_level == 2
    texts = [e["text"] for e in proposal.evidence]
    assert "9 of 14 staff offered the cholera vaccine" in texts


async def test_approving_creates_the_campaign_and_a_second_person_sends_it(
    played: Played,
) -> None:
    assert played.campaign == {
        "status": "PENDING_APPROVAL",
        "type": "AGENT",
        "message": data.HEALTH_CHOLERA_NBO["en"],
        "languages": ["ar", "fr", "sw"],
    }
    assert played.duty_refused is True  # the proposal's approver cannot release it (G-2)
    assert played.sent == {"status": "SENDING"}


async def test_scene_2_closes_dengue(played: Played) -> None:
    assert played.levels[2]["DENGUE"] == ("MODERATE", "CLOSED")
    assert played.levels[2]["CHOLERA"] == ("HIGH", "OPEN")


async def test_nairobi_central_is_avoided_while_the_unrest_is_active(played: Played) -> None:
    assert played.avoid == {
        "Nairobi Central Medical Centre (sample)": True,
        "Highland Private Hospital (sample)": False,
        "Westlands Clinic (sample)": False,
        "Karen Specialist Hospital (sample)": False,
    }
