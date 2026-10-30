"""The agent runner and the Response Planner's rules (Prompt 13). The scenario
replay is in simulator/tests/test_agents_nbo.py."""

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import tenant_session
from app.core.events import Event
from app.modules.agents.agents.response_planner import matches
from app.modules.agents.models import AgentProposal
from app.modules.agents.proposals import ProposalIn
from app.modules.agents.runner import run_agents
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.tests.conftest import DbUrls, create_tenant
from app.tests.fakes import ListPublisher

PB07 = {"category": "CIVIL_UNREST", "max_distance_m": 5000, "min_severity": "HIGH"}


@pytest.mark.parametrize(
    ("category", "severity", "nearest", "expected"),
    [
        ("CIVIL_UNREST", "CRITICAL", 2215, True),  # Nairobi
        ("CIVIL_UNREST", "HIGH", 5000, True),
        ("CIVIL_UNREST", "MODERATE", 100, False),  # below min_severity
        ("TRANSPORT_STRIKE", "CRITICAL", 100, False),  # Paris-like: another category
        ("CIVIL_UNREST", "CRITICAL", 5001, False),  # too far
        ("CIVIL_UNREST", "CRITICAL", None, False),  # no mission property exposed
    ],
)
def test_trigger_rules(category: str, severity: str, nearest: int | None, expected: bool) -> None:
    incident: Any = SimpleNamespace(category=category, severity=severity)
    assert matches(PB07, incident, nearest) is expected


PB06 = {"categories": ["STORM", "FLOOD"], "min_severity": "HIGH", "mission_site_exposed": True}


@pytest.mark.parametrize(
    ("category", "severity", "nearest", "expected"),
    [
        ("STORM", "CRITICAL", 40_000, True),  # Manila (WX-05)
        ("FLOOD", "HIGH", 6_000, True),
        ("STORM", "MODERATE", 1_000, False),  # below min_severity
        ("DUST_STORM", "CRITICAL", 1_000, False),  # not a PB-06 category
        ("EXTREME_HEAT", "CRITICAL", 1_000, False),
        ("CIVIL_UNREST", "CRITICAL", 1_000, False),  # unrest is PB-07's
        ("STORM", "CRITICAL", None, False),  # no mission site inside the radius
    ],
)
def test_pb06_trigger_rules(
    category: str, severity: str, nearest: int | None, expected: bool
) -> None:
    """WX §28 Q6: HIGH or CRITICAL storm or flood with a mission site in the radius."""
    incident: Any = SimpleNamespace(category=category, severity=severity)
    assert matches(PB06, incident, nearest) is expected
    if category != "CIVIL_UNREST":
        assert matches(PB07, incident, nearest) is False  # weather is never PB-07's


class WritingAgent:
    """Misbehaves: writes in observe(). The runner must discard it."""

    code = "WATCH_OFFICER"
    observes = frozenset({"TEST_EVENT"})
    proposes = ("LOG_INFO",)

    async def observe(self, session: AsyncSession, event: Event) -> list[ProposalIn]:
        await session.execute(text("UPDATE agent SET autonomy_level = 0"))
        return [
            ProposalIn(
                agent_code=self.code,
                proposal_key="k",
                action_type="LOG_INFO",
                title="t",
                proposed_action="p",
                action_payload={"text": "x"},
            )
        ]


@pytest.fixture
async def tenant(db: DbUrls, api_engine: AsyncEngine) -> uuid.UUID:
    tenant_id = await create_tenant(db)
    async with tenant_session(tenant_id, api_engine) as session:
        await ensure_agents(session, [AgentIn("WATCH_OFFICER", "Watch Officer", "", 2)])
        await ensure_policies(session, [PolicyIn("LOG_INFO", 0, [], True)])
        await session.commit()
    return tenant_id


async def test_agents_cannot_write_while_observing(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    event = Event("TEST_EVENT", tenant, {}, "test")
    outcomes = await run_agents(
        api_engine, ListPublisher(), event, undo_window_s=300, agents=[WritingAgent()]
    )
    async with tenant_session(tenant, api_engine) as session:
        level = await session.scalar(text("SELECT autonomy_level FROM agent"))
        proposal = await session.scalar(select(AgentProposal))
    assert level == 2  # the write in observe() was rolled back
    # The draft itself went through proposals.create(): level max(2, 0) = 2, waiting.
    assert proposal is not None
    assert (proposal.effective_level, proposal.status) == (2, "PENDING")
    assert len(outcomes) == 1


async def test_a_disabled_agent_proposes_nothing(
    api_engine: AsyncEngine, tenant: uuid.UUID
) -> None:
    async with tenant_session(tenant, api_engine) as session:
        await session.execute(text("UPDATE agent SET is_enabled = false"))
        await session.commit()
    event = Event("TEST_EVENT", tenant, {}, "test")
    assert (
        await run_agents(
            api_engine, ListPublisher(), event, undo_window_s=300, agents=[WritingAgent()]
        )
        == []
    )
