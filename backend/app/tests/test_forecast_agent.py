"""The Forecast agent (PRD-06; D-46; plan-pilot-prd §8, G-1 option B): when calendar events take a
mission's forecast to 70 or above, an advice-only ADVISE_READINESS_CHECK (level 4, never
executed, dismissed by a reviewer); nothing below the threshold or without an event at the peak;
one per mission and peak day; no VIP visit, segment, venue or time in it; every role can read it.
Against real PostgreSQL, as nexira_api."""

import uuid
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.core.events import Event
from app.modules.agents.agents.forecast import Forecast
from app.modules.agents.models import AgentProposal
from app.modules.agents.runner import run_agents
from app.modules.agents.service import AgentIn, ensure_agents
from app.modules.predictive import service as predictive
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher

AGENT = Forecast()
# What a restricted visit is made of (D-42, VIP-06); none of it may be in the advice.
VISIT_WORDS = ("visit", "VV-", "Minister", "segment", "Industrial park", "motorcade")


async def _world(idp: Idp, *weights: int) -> dict[str, Any]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_agents(session, [AgentIn("FORECAST", "Forecast", "", 4)])
        mission = await session.scalar(
            text(
                "INSERT INTO mission (tenant_id, code, city, country_code, location) VALUES "
                "(current_tenant_id(), 'ADD', 'Addis Ababa', 'ET', "
                "'SRID=4326;POINT(38.74 9.03)') RETURNING id"
            )
        )
        today = await predictive.db_today(session)
        for n, weight in enumerate(weights):
            await session.execute(
                text(
                    "INSERT INTO mission_event (tenant_id, mission_id, kind, title, place_label, "
                    "starts_on, ends_on, attendance, weight) VALUES (current_tenant_id(), :m, "
                    "'RALLY', :t, 'Industrial park access road', :d, :d, 5000, :w)"
                ),
                {
                    "m": mission,
                    "t": "Rally near the industrial park" if n == 0 else "Counter-demonstration",
                    "d": today + timedelta(days=5),
                    "w": weight,
                },
            )
        await session.commit()
    for sub, role in (("duty", "DUTY_OFFICER"), ("viewer", "VIEWER")):
        await idp.user(sub, [(role, None)])
    return {"mission": mission, "today": today}


async def _observe(idp: Idp, mission: uuid.UUID) -> None:
    event = Event("MISSION_EVENT_ADDED", idp.tenant_id, {"mission_id": str(mission)}, "test")
    await run_agents(idp.engine, ListPublisher(), event, undo_window_s=300, agents=[AGENT])


async def _proposals(idp: Idp) -> list[AgentProposal]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        return list(await session.scalars(select(AgentProposal)))


async def test_a_rally_over_the_threshold_raises_advice_only(client: AsyncClient, idp: Idp) -> None:
    w = await _world(idp, 30, 10)
    await _observe(idp, w["mission"])
    [p] = await _proposals(idp)
    peak_day = w["today"] + timedelta(days=5)
    assert (p.action_type, p.effective_level, p.status, p.is_proactive) == (
        "ADVISE_READINESS_CHECK",
        4,  # no action_policy row: advice only, never executed (D-12)
        "PENDING",
        True,
    )
    assert p.title == f"Addis Ababa risk forecast 35 → 75 by {peak_day.strftime('%d %b')}"
    assert p.proposed_action == (
        "Review movements and venues in Addis Ababa in the next 14 days: Rally near the "
        f"industrial park on {peak_day.strftime('%d %b')}."
    )
    assert p.proposal_key == f"PRD:{w['mission']}:{peak_day.isoformat()}"
    evidence = [e["text"] for e in p.evidence]
    assert evidence[0].startswith("ADD risk index 35 today, 75 on")
    assert any("about 5,000 people · weight 30" in t for t in evidence)
    assert evidence[-1] == "Drivers on that day: events +40"
    # Every role reads the Decision Queue, so nothing of a restricted visit is in it (G-1).
    response = await client.get(f"/api/proposals/{p.id}", headers=idp.headers("viewer"))
    assert response.status_code == 200
    body = response.text
    assert not [word for word in VISIT_WORDS if word in body.replace("industrial park", "")]
    assert response.json()["can_dismiss"] is False


async def test_advice_is_dismissed_by_a_reviewer_not_the_viewer(
    client: AsyncClient, idp: Idp
) -> None:
    w = await _world(idp, 30, 10)
    await _observe(idp, w["mission"])
    [p] = await _proposals(idp)
    reason = {"reason": "Readiness check scheduled"}
    refused = await client.post(
        f"/api/proposals/{p.id}/reject", json=reason, headers=idp.headers("viewer")
    )
    assert refused.status_code == 403
    done = await client.post(
        f"/api/proposals/{p.id}/reject", json=reason, headers=idp.headers("duty")
    )
    assert done.status_code == 200, done.text
    [after] = await _proposals(idp)
    assert after.status == "REJECTED"


async def test_one_proposal_per_mission_and_peak(idp: Idp) -> None:
    w = await _world(idp, 30, 10)
    await _observe(idp, w["mission"])
    await _observe(idp, w["mission"])  # the same calendar seen again
    assert len(await _proposals(idp)) == 1


async def test_nothing_below_the_threshold_or_without_an_event(idp: Idp) -> None:
    w = await _world(idp, 20)  # 35 + 20 = 55
    await _observe(idp, w["mission"])
    await _observe(idp, uuid.uuid4())  # no such mission
    assert await _proposals(idp) == []
    # Over 70 because of an incident, not the calendar: not this agent's advice.
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO incident (tenant_id, reference, title, category, severity, "
                "signal_severity, location, mission_id) VALUES (current_tenant_id(), "
                "'INC-2026-1050', 'Unrest', 'CIVIL_UNREST', 'CRITICAL', 'HIGH', "
                "'SRID=4326;POINT(38.74 9.03)', :m)"
            ),
            {"m": w["mission"]},
        )
        await session.commit()
    found = None
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        found = await predictive.outlook(session, w["mission"])
    assert found is not None
    assert found.peak.value >= 70  # the incident's first day
    assert found.events_at_peak == []
    await _observe(idp, w["mission"])
    assert await _proposals(idp) == []


def test_it_watches_only_the_calendar() -> None:
    """It does not observe incidents, so no other scenario gains a proposal."""
    assert AGENT.observes == frozenset({"MISSION_EVENT_ADDED"})
    assert AGENT.proposes == ("ADVISE_READINESS_CHECK",)
