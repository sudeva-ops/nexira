"""MN-04 (Prompt 19, D-31): in the France scenario, PB-07 v2 and the Communications
agent use the Paris templates. Nothing sent for Paris mentions Nairobi, the CBD or
Upper Hill. Same in-memory bus as the Nairobi agents test."""

import uuid

from app.core.db import create_engine, tenant_session
from app.core.events import Event
from app.modules.agents import proposals
from app.modules.agents.models import AgentProposal
from app.modules.notifications.models import NotificationCampaign
from app.modules.playbooks.models import Playbook
from app.tests.conftest import DbUrls
from sqlalchemy import select

from nexira_sim.scenarios import fra_national_protests as fra
from nexira_sim.seed import world
from tests.scene_helpers import DAY, seed
from tests.test_agents_nbo import Bus, user

NAIROBI_WORDS = ("Nairobi", "CBD", "Upper Hill")


def paris_march(tenant_id: uuid.UUID) -> list[Event]:
    """Scene 1: the three reports of the Paris march."""
    return [
        Event("RAW_SIGNAL", tenant_id, dict(e.payload), "scenario")
        for e in fra.build_events(world.build(DAY, tenant_id), tenant_id)
        if e.event_type == "RAW_SIGNAL" and e.scene_no == 1
    ]


async def test_paris_gets_paris_words_from_pb07_v2(db: DbUrls) -> None:
    tenant_id = uuid.uuid4()
    engine = create_engine(db.api)
    try:
        await seed(db, engine, tenant_id)
        bus = Bus(engine)
        await bus.deliver(paris_march(tenant_id))

        async with tenant_session(tenant_id, engine) as session:
            active = await session.scalars(select(Playbook).where(Playbook.is_active))
            # PB-07 v1 is retired; PB-06 (D-35) never matches unrest.
            assert sorted((p.code, p.version) for p in active) == [("PB-06", 1), ("PB-07", 2)]
            planner = await session.scalar(
                select(AgentProposal).where(AgentProposal.action_type == "START_PLAYBOOK")
            )
            assert planner is not None  # the embassy is exposed: PB-07 is proposed
            outcome = await proposals.approve(
                session, await user(engine, tenant_id, "duty.officer"), planner.id
            )
            await session.commit()
        await bus.deliver(outcome.events)

        async with tenant_session(tenant_id, engine) as session:
            alerts = list(
                await session.scalars(
                    select(NotificationCampaign.message).where(
                        NotificationCampaign.campaign_type == "ALERT"
                    )
                )
            )
            advisory = await session.scalar(
                select(AgentProposal).where(AgentProposal.action_type == "SEND_EXTERNAL_MESSAGE")
            )
    finally:
        await engine.dispose()

    assert "Shelter in place. Avoid République, Bastille and Nation." in alerts  # step 4
    assert not any(word in text for text in alerts for word in NAIROBI_WORDS)
    assert advisory is not None
    payload = advisory.action_payload
    assert "Paris" in payload["message"]
    texts = [payload["message"], *payload["translations"].values()]
    assert not any(word in text for text in texts for word in NAIROBI_WORDS)
    assert sorted(payload["translations"]) == ["ar", "fr", "sw"]
    assert payload["translations"]["fr"].startswith("[REVIEW REQUIRED]")  # D-15
