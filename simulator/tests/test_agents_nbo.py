"""The four agents on the NBO-CIVIL-UNREST scenes 1-3 (decisions.md §7, Prompt 13).

A small in-memory bus routes every published event to the handlers the worker
runs (fusion, exposure, playbook engine, agents), until nothing is left. Replaying
the same scene events twice must give exactly one proposal per agent per trigger.
"""

import uuid
from collections import Counter, deque
from datetime import UTC, date, datetime

from app.core.db import create_engine, tenant_session
from app.core.events import Event, Handler
from app.core.security import CurrentUser
from app.modules.agents import proposals
from app.modules.agents.models import Agent, AgentProposal
from app.modules.agents.runner import agents_handler, observed_types
from app.modules.intel.consumer import exposure_handler, raw_signal_handler
from app.modules.intel.models import Incident
from app.modules.notifications.consumer import dispatch_all
from app.modules.notifications.models import NotificationCampaign
from app.modules.playbooks import service as playbooks
from app.modules.playbooks.consumer import run_handler
from app.modules.playbooks.models import PlaybookRun
from app.modules.tenancy.models import AppUser
from app.modules.tenancy.service import Actor
from app.tests.conftest import DbUrls
from app.tests.fakes import ListPublisher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexira_sim.scenarios import nbo_civil_unrest as nbo
from nexira_sim.seed import world
from tests.scene_helpers import DAY, seed


class Bus:
    """Delivers events in order to the worker's handlers, as the stream would."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.publisher = ListPublisher()
        self.seen = 0
        on_incident = exposure_handler(engine, self.publisher)
        on_run = run_handler(engine, self.publisher, 0)
        on_agents = agents_handler(engine, self.publisher, 300)
        self.routes: dict[str, list[Handler]] = {}
        for kind, handler in [
            ("RAW_SIGNAL", raw_signal_handler(engine, self.publisher)),
            ("INCIDENT_CREATED", on_incident),
            ("INCIDENT_UPDATED", on_incident),
            ("PLAYBOOK_RUN_STARTED", on_run),
            ("PLAYBOOK_STEP_APPROVED", on_run),
        ]:
            self.routes.setdefault(kind, []).append(handler)
        for kind in observed_types():
            self.routes.setdefault(kind, []).append(on_agents)

    async def deliver(self, events: list[Event]) -> None:
        queue = deque(events)
        while queue:
            event = queue.popleft()
            for handler in self.routes.get(event.type, []):
                await handler(event)
            fresh = self.publisher.events[self.seen :]
            self.seen = len(self.publisher.events)
            queue.extend(fresh)


def scene_1(tenant_id: uuid.UUID, day: date = DAY) -> list[Event]:
    """The scenario's RAW_SIGNAL events (Nairobi and Paris), as the player sends them."""
    return [
        Event("RAW_SIGNAL", tenant_id, dict(e.payload), "scenario")
        for e in nbo.build_events(world.build(day, tenant_id), tenant_id)
        if e.event_type == "RAW_SIGNAL"
    ]


async def user(engine: AsyncEngine, tenant_id: uuid.UUID, username: str) -> CurrentUser:
    async with tenant_session(tenant_id, engine) as session:
        row = await session.scalar(
            select(AppUser).where(AppUser.email == f"{username}@demo.nexira.invalid")
        )
        assert row is not None
        return CurrentUser(row.id, row.tenant_id, row.external_id, row.email, row.display_name)


async def all_proposals(
    engine: AsyncEngine, tenant_id: uuid.UUID
) -> list[tuple[str, str, str, int]]:
    async with tenant_session(tenant_id, engine) as session:
        rows = await session.execute(
            select(
                Agent.code,
                AgentProposal.action_type,
                AgentProposal.status,
                AgentProposal.effective_level,
            )
            .join(Agent, Agent.id == AgentProposal.agent_id)
            .order_by(AgentProposal.created_at)
        )
        return [(code, action, status, level) for code, action, status, level in rows]


async def test_scenes_1_to_3_give_one_proposal_per_agent_per_trigger(db: DbUrls) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        # Seeded for today (review of Prompt 35, H1): Travel & Air reads the real date.
        today = datetime.now(UTC).date()
        await seed(db, engine, tenant_id, today)
        bus = Bus(engine)
        await bus.deliver(scene_1(tenant_id, today))
        await bus.deliver(scene_1(tenant_id, today))  # the same events again: nothing new

        found = await all_proposals(engine, tenant_id)
        # Travel & Air (pilot module 4, D-34) adds exactly the two cards of plan-pilot-ta
        # G-5: TRP-8812's delegates are in the zone; Kenya rose to CRITICAL while TRP-8818
        # (approved at MODERATE) is under way. Nothing for the future Paris trip TRP-8811.
        async with tenant_session(tenant_id, engine) as session:
            travel = sorted(
                (p.title, p.status, p.effective_level)
                for p in await session.scalars(
                    select(AgentProposal)
                    .join(Agent, Agent.id == AgentProposal.agent_id)
                    .where(Agent.code == "TRAVEL_AIR")
                )
            )
        year = today.year
        assert travel == [
            ("Notify TRP-8818 travellers · risk now CRITICAL", "PENDING", 2),
            (f"Safety message to TRP-8812 travellers · INC-{year}-1042", "PENDING", 2),
        ]
        assert Counter(
            (agent, action, status, level)
            for agent, action, status, level in found
            if agent != "TRAVEL_AIR"
        ) == {
            # Scene 1: the Watch Officer logs both incidents (Nairobi, Paris; plan G-12).
            ("WATCH_OFFICER", "LOG_INFO", "AUTO_EXECUTED", 0): 2,
            # Scene 2: one exposure note each, although exposure ran after every signal.
            ("EXPOSURE", "POST_INTERNAL_NOTE", "AUTO_EXECUTED", 0): 2,
            # PB-07 for Nairobi only: Paris is MODERATE (plan G-12).
            ("RESPONSE_PLANNER", "START_PLAYBOOK", "PENDING", 2): 1,
        }

        # Scene 3: the Duty Officer approves; PB-07 runs; step 4 triggers Communications.
        async with tenant_session(tenant_id, engine) as session:
            planner = await session.scalar(
                select(AgentProposal).where(AgentProposal.action_type == "START_PLAYBOOK")
            )
            assert planner is not None
            assert planner.alternatives[0]["action_type"] == "POST_INTERNAL_NOTE"  # D-14
            assert {e["source"] for e in planner.evidence} >= {"Dataminr (simulated)"}
            outcome = await proposals.approve(
                session, await user(engine, tenant_id, "duty.officer"), planner.id
            )
            await session.commit()
        assert outcome.proposal.status == "APPROVED"
        await bus.deliver(outcome.events)
        await bus.deliver(outcome.events)  # redelivered: still one advisory

        async with tenant_session(tenant_id, engine) as session:
            advisory = await session.scalar(
                select(AgentProposal).where(AgentProposal.action_type == "SEND_EXTERNAL_MESSAGE")
            )
            assert advisory is not None
            assert (advisory.status, advisory.effective_level) == ("PENDING", 2)
            payload = advisory.action_payload
            assert payload["audience"] == {"exposed": True, "person_types": ["CITIZEN"]}
            assert sorted(payload["translations"]) == ["ar", "fr", "sw"]  # D-15 templates
            assert all(t.startswith("[REVIEW REQUIRED]") for t in payload["translations"].values())
            sent = await proposals.approve(
                session, await user(engine, tenant_id, "duty.officer"), advisory.id
            )
            await session.commit()
        # The worker's dispatcher sends what is queued: PB-07's campaigns (2, 17 and 229
        # people x 3 channels = 744; this bus has no notifications handler) and the
        # advisory (212 citizens x 3 channels = 636).
        assert await dispatch_all(engine, tenant_id, bus.publisher) == 744 + 636
        async with tenant_session(tenant_id, engine) as session:
            campaign = await session.scalar(
                select(NotificationCampaign).where(NotificationCampaign.campaign_type == "ADVISORY")
            )
        assert sent.proposal.status == "APPROVED"
        assert campaign is not None
        assert campaign.status == "SENT"  # through the simulated adapter only
        counted = Counter(
            agent for agent, *_ in await all_proposals(engine, tenant_id) if agent != "TRAVEL_AIR"
        )  # Travel & Air is checked above
        assert counted == {
            "WATCH_OFFICER": 2,
            "EXPOSURE": 2,
            "RESPONSE_PLANNER": 1,
            "COMMUNICATIONS": 1,
        }
    finally:
        await engine.dispose()


async def test_paused_agents_propose_nothing_and_playbooks_still_start(db: DbUrls) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seed(db, engine, tenant_id)
        async with tenant_session(tenant_id, engine) as session:
            await proposals.set_paused(session, await user(engine, tenant_id, "admin"), True)
            await session.commit()
        bus = Bus(engine)
        await bus.deliver(scene_1(tenant_id))
        assert await all_proposals(engine, tenant_id) == []  # D-17

        async with tenant_session(tenant_id, engine) as session:
            incident = await session.scalar(
                select(Incident).where(Incident.category == "CIVIL_UNREST")
            )
            assert incident is not None
            duty = await user(engine, tenant_id, "duty.officer")
            run = await playbooks.start_run(
                session,
                playbook_code="PB-07",
                incident_id=incident.id,
                actor=Actor(type="USER", id=str(duty.id)),
                started_by=duty.id,
            )
            await session.commit()
        await bus.deliver([playbooks.run_started_event(run)])
        async with tenant_session(tenant_id, engine) as session:
            run_status = await session.scalar(
                select(PlaybookRun.status).where(PlaybookRun.id == run.id)
            )
        assert run_status == "AWAITING_APPROVAL"  # PB-07 ran to step 7 by hand
        assert await all_proposals(engine, tenant_id) == []  # step 4 proposed nothing either
    finally:
        await engine.dispose()
