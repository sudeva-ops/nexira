"""Agent proposals: policy levels, decisions, execution, undo, expiry, kill switch
(AGT-01..08, D-12..D-17, PC-05, plan G-18, G-21, Prompt 12)."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db import tenant_session
from app.core.events import get_publisher
from app.main import app
from app.modules.agents import proposals
from app.modules.agents.actions import ActionError
from app.modules.agents.models import Agent, AgentProposal
from app.modules.agents.service import AgentIn, PolicyIn, ensure_agents, ensure_policies
from app.modules.audit.models import AuditLog
from app.modules.intel.models import Incident, IncidentEvent
from app.modules.intel.service import ensure_sources
from app.modules.playbooks.models import PlaybookRun
from app.modules.playbooks.service import StepIn, ensure_playbook
from app.modules.tenancy.service import ensure_reference_counter
from app.tests.auth_helpers import Idp
from app.tests.fakes import ListPublisher
from app.tests.intel_helpers import SOURCES, ingest, signal

UNDO_S = 300
AGENTS = [
    AgentIn("WATCH_OFFICER", "Watch Officer", "", 0),
    AgentIn("EXPOSURE", "Exposure", "", 0),
    AgentIn("RESPONSE_PLANNER", "Response Planner", "", 2),
    AgentIn("COMMUNICATIONS", "Communications", "", 2),
]
POLICIES = [  # the Phase 1 seed (decisions.md §3)
    PolicyIn("LOG_INFO", 0, [], True),
    PolicyIn("POST_INTERNAL_NOTE", 0, [], True),
    PolicyIn("START_PLAYBOOK", 2, ["DUTY_OFFICER|SECURITY_OFFICER"], False),
    PolicyIn("SEND_EXTERNAL_MESSAGE", 2, ["DUTY_OFFICER|CONSULAR_OFFICER"], False),
    PolicyIn("START_EVACUATION", 3, ["HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"], False),
]
MESSAGE = {
    "campaign_type": "ADVISORY",
    "message": "Shelter in place.",
    "translations": {"fr": "Restez à l'abri."},
    "channels": ["SMS", "APP"],
    "audience": {"exposed": True, "person_types": ["CITIZEN"]},
}


@dataclass
class World:
    incident_id: uuid.UUID
    publisher: ListPublisher


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    nbo, cai = await idp.mission("NBO"), await idp.mission("CAI")
    grants: dict[str, list[tuple[str, uuid.UUID | None]]] = {
        "duty": [("DUTY_OFFICER", None)],
        "consular": [("CONSULAR_OFFICER", None)],
        "hq": [("HQ_CRISIS_DIRECTOR", None)],
        "hom.nbo": [("HEAD_OF_MISSION", nbo)],
        "hom.cai": [("HEAD_OF_MISSION", cai)],
        "dual": [("HEAD_OF_MISSION", nbo), ("HQ_CRISIS_DIRECTOR", None)],
        "admin": [("ADMIN", None)],
        "viewer": [("VIEWER", None)],
    }
    for sub, roles in grants.items():
        await idp.user(sub, roles)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await ensure_sources(session, SOURCES)
        await ensure_reference_counter(session, prefix="INC", with_year=True, last_value=1041)
        await ensure_reference_counter(session, prefix="NTF", with_year=False, last_value=3100)
        await ensure_agents(session, AGENTS)
        await ensure_policies(session, POLICIES)
        await ensure_playbook(
            session,
            playbook_id=uuid.uuid4(),
            code="PB-T",
            name="Test",
            category="CIVIL_UNREST",
            trigger_rules={},
            steps=[StepIn(1, "Confirm", "TASK", {"summary": "ok"})],
            step_ids=[uuid.uuid4()],
        )
        await session.commit()
    fused = (await ingest(idp.engine, idp.tenant_id, signal("DATAMINR", "High"))).fused
    assert fused is not None
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Incident).values(mission_id=nbo))  # as exposure would
        await session.commit()
    publisher = ListPublisher()
    app.dependency_overrides[get_publisher] = lambda: publisher
    return World(fused.incident_id, publisher)


async def propose(
    idp: Idp,
    w: World,
    agent: str,
    action_type: str,
    payload: dict[str, Any],
    *,
    key: str | None = None,
    alternatives: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> AgentProposal:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        outcome = await proposals.create(
            session,
            proposals.ProposalIn(
                agent_code=agent,
                proposal_key=key or str(uuid.uuid4()),
                action_type=action_type,
                title=f"{action_type} proposal",
                proposed_action=action_type,
                action_payload=payload,
                incident_id=w.incident_id,
                evidence=[{"text": "test", "source": "test"}],
                alternatives=alternatives or [],
            ),
            undo_window_s=UNDO_S,
            now=now,
        )
        await session.commit()
        return outcome.proposal


async def set_level(idp: Idp, agent: str, level: int) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Agent).where(Agent.code == agent).values(autonomy_level=level))
        await session.commit()


async def stored(idp: Idp, proposal_id: uuid.UUID) -> AgentProposal:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        return await session.get_one(AgentProposal, proposal_id)


async def post(client: AsyncClient, idp: Idp, path: str, sub: str, body: object = None) -> Response:
    return await client.post(f"/api{path}", json=body or {}, headers=idp.headers(sub))


async def actions(idp: Idp, proposal_id: uuid.UUID) -> list[str]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        rows = await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_type == "agent_proposal", AuditLog.entity_id == str(proposal_id))
            .order_by(AuditLog.chain_seq)
        )
        return list(rows)


# --- the policy engine (database) ---------------------------------------------------------


async def test_an_auto_agent_still_needs_approval_for_external_messages(
    idp: Idp, world: World
) -> None:
    await set_level(idp, "COMMUNICATIONS", 0)  # AGT-02: "Auto"
    p = await propose(idp, world, "COMMUNICATIONS", "SEND_EXTERNAL_MESSAGE", MESSAGE)
    assert (p.effective_level, p.status) == (2, "PENDING")  # max(0, floor 2)
    assert p.deadline_at is not None


async def test_an_unknown_action_type_is_advise_only(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "WATCH_OFFICER", "CLOSE_AIRSPACE", {"anything": 1})
    assert (p.effective_level, p.status, p.deadline_at) == (4, "PENDING", None)  # D-12
    response = await post(client, idp, f"/proposals/{p.id}/approve", "duty")
    assert response.status_code == 409
    assert "Advise-only" in response.json()["detail"]
    listed = (await client.get("/api/proposals", headers=idp.headers("duty"))).json()
    assert listed[0]["can_decide"] is False


async def test_level_0_executes_through_the_note_service(idp: Idp, world: World) -> None:
    p = await propose(idp, world, "WATCH_OFFICER", "LOG_INFO", {"text": "Signals fused."})
    assert (p.effective_level, p.status, p.undo_until) == (0, "AUTO_EXECUTED", None)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        note = await session.scalar(select(IncidentEvent).where(IncidentEvent.event_type == "NOTE"))
    assert note is not None
    assert (note.summary, note.actor_type, note.actor_id) == (
        "Signals fused.",
        "AGENT",
        "WATCH_OFFICER",
    )
    assert await actions(idp, p.id) == ["PROPOSAL.CREATE", "PROPOSAL.EXECUTE"]


async def test_the_same_key_is_one_proposal(idp: Idp, world: World) -> None:
    first = await propose(
        idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"}, key="K"
    )
    again = await propose(
        idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"}, key="K"
    )
    assert first.id == again.id


# --- approvals -------------------------------------------------------------------------------


async def test_evacuation_needs_two_people_in_order(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})
    assert p.effective_level == 3
    # Step 2's role cannot go first: step 1 needs the Head of Mission.
    assert (await post(client, idp, f"/proposals/{p.id}/approve", "hq")).status_code == 403
    # D-05: the Cairo Head of Mission cannot approve a Nairobi incident.
    assert (await post(client, idp, f"/proposals/{p.id}/approve", "hom.cai")).status_code == 403
    one = await post(client, idp, f"/proposals/{p.id}/approve", "hom.nbo")
    assert one.status_code == 200
    assert one.json()["status"] == "PENDING"  # AGT-04: one approval does not execute
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        orders = await session.scalar(
            select(IncidentEvent.id).where(IncidentEvent.summary.like("Evacuation ordered%"))
        )
    assert orders is None
    two = await post(client, idp, f"/proposals/{p.id}/approve", "hq")
    assert two.json()["status"] == "APPROVED"
    assert [s["decision"] for s in two.json()["approvals"]] == ["APPROVE", "APPROVE"]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        orders = await session.scalar(
            select(IncidentEvent.id).where(IncidentEvent.summary.like("Evacuation ordered%"))
        )
    assert orders is not None  # the Phase 1 stub writes an incident event only


async def test_one_person_cannot_approve_both_steps(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})
    assert (await post(client, idp, f"/proposals/{p.id}/approve", "dual")).status_code == 200
    second = await post(client, idp, f"/proposals/{p.id}/approve", "dual")
    assert second.status_code == 403  # D-16, although "dual" holds HQ_CRISIS_DIRECTOR
    assert "same person" in second.json()["detail"]


async def test_the_database_refuses_step_2_before_step_1(idp: Idp, world: World) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        user_id = await session.scalar(text("SELECT id FROM app_user LIMIT 1"))
        with pytest.raises(DBAPIError, match="earlier steps must be approved first"):
            await session.execute(
                text(
                    "UPDATE proposal_approval SET decision = 'APPROVE', decided_by = :u, "
                    "decided_at = now() WHERE proposal_id = :p AND step_no = 2"
                ),
                {"u": user_id, "p": p.id},
            )


async def test_approval_starts_the_playbook_through_the_same_service(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    assert (await post(client, idp, f"/proposals/{p.id}/approve", "consular")).status_code == 403
    approved = await post(client, idp, f"/proposals/{p.id}/approve", "duty")
    assert (approved.json()["status"], approved.json()["executed_at"] is not None) == (
        "APPROVED",
        True,
    )
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        run = await session.scalar(select(PlaybookRun))
        duty_id = await session.scalar(text("SELECT id FROM app_user WHERE external_id = 'duty'"))
    assert run is not None
    assert (run.started_by_type, run.proposal_id, run.started_by) == ("AGENT", p.id, duty_id)
    assert "PLAYBOOK_RUN_STARTED" in [e.type for e in world.publisher.events]


async def test_a_failing_action_marks_the_proposal_failed(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(
        idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-NOPE"}
    )
    response = await post(client, idp, f"/proposals/{p.id}/approve", "duty")
    assert response.json()["status"] == "FAILED"
    assert await actions(idp, p.id) == ["PROPOSAL.CREATE", "PROPOSAL.APPROVE", "PROPOSAL.FAIL"]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert await session.scalar(select(PlaybookRun)) is None


async def test_edit_approve_keeps_the_original_payload(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "COMMUNICATIONS", "SEND_EXTERNAL_MESSAGE", MESSAGE)
    wider = {**MESSAGE, "audience": {"exposed": True}}
    refused = await post(
        client, idp, f"/proposals/{p.id}/edit-approve", "consular", {"edited_payload": wider}
    )
    assert refused.status_code == 409  # plan G-21: cannot widen the audience
    edited = {**MESSAGE, "message": "Shelter in place. Avoid the CBD.", "channels": ["SMS"]}
    response = await post(
        client, idp, f"/proposals/{p.id}/edit-approve", "consular", {"edited_payload": edited}
    )
    body = response.json()
    assert (body["status"], body["action_payload"], body["edited_payload"]) == (
        "EDITED_APPROVED",
        MESSAGE,
        edited,
    )
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        details = await session.scalar(
            select(AuditLog.details).where(AuditLog.action == "PROPOSAL.EDIT_APPROVE")
        )
        campaign_message = await session.scalar(text("SELECT message FROM notification_campaign"))
    assert details is not None
    assert (details["original_payload"], details["edited_payload"]) == (MESSAGE, edited)
    assert campaign_message == "Shelter in place. Avoid the CBD."  # the edit is what ran


async def test_reject_stores_the_reason(client: AsyncClient, idp: Idp, world: World) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    no_reason = await post(client, idp, f"/proposals/{p.id}/reject", "duty", {"reason": ""})
    assert no_reason.status_code == 422
    assert (
        await post(client, idp, f"/proposals/{p.id}/reject", "viewer", {"reason": "x"})
    ).status_code == 403
    rejected = await post(
        client, idp, f"/proposals/{p.id}/reject", "duty", {"reason": "Already handled"}
    )
    assert (rejected.json()["status"], rejected.json()["rejection_reason"]) == (
        "REJECTED",
        "Already handled",
    )
    assert (await post(client, idp, f"/proposals/{p.id}/approve", "duty")).status_code == 409


async def test_an_alternative_with_a_higher_floor_gets_the_higher_level(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(
        idp,
        world,
        "RESPONSE_PLANNER",
        "START_PLAYBOOK",
        {"playbook_code": "PB-T"},
        alternatives=[
            {
                "label": "Evacuate instead",
                "action_type": "START_EVACUATION",
                "action_payload": {"route": "B"},
                "rationale": "Crowd is growing",
            }
        ],
    )
    response = await post(client, idp, f"/proposals/{p.id}/use-alternative", "duty", {"index": 0})
    new = response.json()
    assert (new["action_type"], new["effective_level"], new["status"]) == (
        "START_EVACUATION",
        3,
        "PENDING",
    )
    old = await stored(idp, p.id)
    assert (old.status, old.superseded_by) == ("SUPERSEDED", uuid.UUID(new["id"]))  # D-14


# --- undo, expiry, kill switch, autonomy ------------------------------------------------------


async def test_undo_works_only_before_undo_until(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await set_level(idp, "WATCH_OFFICER", 1)
    t0 = datetime.now(UTC)
    p = await propose(idp, world, "WATCH_OFFICER", "LOG_INFO", {"text": "Note A"}, now=t0)
    assert (p.effective_level, p.status) == (1, "AUTO_EXECUTED")
    assert p.undo_until == t0 + timedelta(seconds=UNDO_S)
    undone = await post(client, idp, f"/proposals/{p.id}/undo", "duty")
    assert undone.json()["status"] == "UNDONE"
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        note = await session.scalar(
            select(IncidentEvent).where(IncidentEvent.summary.like("%Note A"))
        )
    assert note is not None
    assert (note.summary, note.data.get("retracted")) == ("[Retracted] Note A", True)

    late = await propose(
        idp, world, "WATCH_OFFICER", "LOG_INFO", {"text": "Note B"}, now=t0 - timedelta(hours=1)
    )
    response = await post(client, idp, f"/proposals/{late.id}/undo", "duty")
    assert response.status_code == 409
    assert "closed" in response.json()["detail"]


async def test_level_1_is_raised_to_2_for_actions_that_cannot_be_undone(
    idp: Idp, world: World
) -> None:
    await set_level(idp, "RESPONSE_PLANNER", 1)
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    assert (p.effective_level, p.status) == (2, "PENDING")  # D-13


async def test_overdue_proposals_expire_and_escalate(idp: Idp, world: World) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    assert p.deadline_at is not None
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert await proposals.expire_overdue(session, p.deadline_at - timedelta(seconds=1)) == []
        expired = await proposals.expire_overdue(session, p.deadline_at)
        await session.commit()
        escalation = await session.scalar(
            select(IncidentEvent.summary).where(IncidentEvent.event_type == "ESCALATION")
        )
    assert [o.proposal.status for o in expired] == ["EXPIRED"]
    assert expired[0].events[0].payload["required_role"] == "DUTY_OFFICER|SECURITY_OFFICER"
    assert escalation is not None
    assert "DUTY_OFFICER or SECURITY_OFFICER" in escalation
    assert await actions(idp, p.id) == ["PROPOSAL.CREATE", "PROPOSAL.EXPIRE"]


async def test_pause_all_stops_new_proposals_but_not_decisions(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    pending = await propose(
        idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"}
    )
    assert (await post(client, idp, "/agents/pause-all", "duty")).status_code == 403
    paused = await post(client, idp, "/agents/pause-all", "admin")
    assert paused.json()["paused"] is True
    with pytest.raises(proposals.AgentsPausedError):
        await propose(idp, world, "WATCH_OFFICER", "LOG_INFO", {"text": "x"})
    # D-17: pending proposals can still be decided by people.
    assert (await post(client, idp, f"/proposals/{pending.id}/approve", "duty")).status_code == 200
    resumed = await post(client, idp, "/agents/resume-all", "admin")
    assert resumed.json()["paused"] is False
    assert (
        await propose(idp, world, "WATCH_OFFICER", "LOG_INFO", {"text": "y"})
    ).status == "AUTO_EXECUTED"
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        audited = list(
            await session.scalars(select(AuditLog.action).where(AuditLog.action.like("AGENTS.%")))
        )
    assert audited == ["AGENTS.PAUSE", "AGENTS.RESUME"]


async def test_admins_set_autonomy_and_it_is_audited(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    roster = (await client.get("/api/agents", headers=idp.headers("viewer"))).json()
    assert [a["code"] for a in roster["agents"]] == [
        "COMMUNICATIONS",
        "EXPOSURE",
        "RESPONSE_PLANNER",
        "WATCH_OFFICER",
    ]
    patch = {"autonomy_level": 3}
    url = "/api/agents/COMMUNICATIONS"
    assert (await client.patch(url, json=patch, headers=idp.headers("duty"))).status_code == 403
    assert (
        await client.patch(url, json={"autonomy_level": 5}, headers=idp.headers("admin"))
    ).status_code == 422
    updated = (await client.patch(url, json=patch, headers=idp.headers("admin"))).json()
    assert (
        next(a for a in updated["agents"] if a["code"] == "COMMUNICATIONS")["autonomy_level"] == 3
    )
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        details = await session.scalar(
            select(AuditLog.details).where(AuditLog.action == "AGENT.UPDATE")
        )
    assert details == {
        "before": {"autonomy_level": 2, "is_enabled": True},
        "after": {"autonomy_level": 3, "is_enabled": True},
    }


async def test_permissions_for_a_proposal(client: AsyncClient, idp: Idp, world: World) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})

    async def may(sub: str) -> bool:
        response = await client.get(
            "/api/me/permissions",
            params={"entity_type": "agent_proposal", "entity_id": str(p.id)},
            headers=idp.headers(sub),
        )
        allowed: bool = response.json()["decide_proposal"]
        return allowed

    assert (await may("hom.nbo"), await may("hom.cai"), await may("hq")) == (True, False, False)


# --- review of Prompt 12 -----------------------------------------------------------------


async def test_nothing_can_be_decided_after_the_deadline(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        # The expiry job has not run yet; the deadline has passed.
        await session.execute(
            text(
                "UPDATE agent_proposal SET deadline_at = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": p.id},
        )
        await session.commit()
    late = await post(client, idp, f"/proposals/{p.id}/approve", "duty")
    assert late.status_code == 409
    assert "deadline" in late.json()["detail"]
    listed = (await client.get(f"/api/proposals/{p.id}", headers=idp.headers("duty"))).json()
    assert listed["can_decide"] is False


@pytest.mark.parametrize(
    ("change", "allowed"),
    [
        ({"campaign_type": "CHECKIN"}, False),  # would start check-in tracking
        ({"translations": {"fr": "Autre texte"}}, False),  # D-15: reviewed templates
        ({"translations": {"ar": "نص"}}, False),  # adding a language
        ({"translations": {}}, True),  # dropping a language
        ({"message": "Reworded by the approver."}, True),
    ],
)
async def test_what_an_edit_may_change(
    client: AsyncClient, idp: Idp, world: World, change: dict[str, Any], allowed: bool
) -> None:
    p = await propose(idp, world, "COMMUNICATIONS", "SEND_EXTERNAL_MESSAGE", MESSAGE)
    response = await post(
        client,
        idp,
        f"/proposals/{p.id}/edit-approve",
        "duty",
        {"edited_payload": {**MESSAGE, **change}},
    )
    assert (response.status_code == 200) is allowed


async def test_an_evacuation_route_cannot_be_edited(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})
    response = await post(
        client,
        idp,
        f"/proposals/{p.id}/edit-approve",
        "hom.nbo",
        {"edited_payload": {"route": "C"}},
    )
    assert response.status_code == 409


async def test_alternatives_must_be_well_formed(idp: Idp, world: World) -> None:
    with pytest.raises(ActionError, match="each alternative needs"):
        await propose(
            idp,
            world,
            "RESPONSE_PLANNER",
            "START_PLAYBOOK",
            {"playbook_code": "PB-T"},
            alternatives=[{"label": "No type", "action_payload": {}}],
        )


async def test_an_alternative_already_proposed_is_refused(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    alt = {
        "label": "Note",
        "action_type": "START_EVACUATION",
        "action_payload": {"route": "B"},
        "rationale": "r",
    }
    p = await propose(
        idp,
        world,
        "RESPONSE_PLANNER",
        "START_PLAYBOOK",
        {"playbook_code": "PB-T"},
        key="K1",
        alternatives=[alt],
    )
    # Something else already holds the alternative's key.
    await propose(
        idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"}, key="K1:alt:0"
    )
    response = await post(client, idp, f"/proposals/{p.id}/use-alternative", "duty", {"index": 0})
    assert response.status_code == 409
    assert (await stored(idp, p.id)).status == "PENDING"


async def test_without_a_mission_only_unscoped_holders_decide(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await idp.user("hom.hq", [("HEAD_OF_MISSION", None)])
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(update(Incident).values(mission_id=None))
        await session.commit()
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})
    assert (
        await post(client, idp, f"/proposals/{p.id}/approve", "hom.nbo")
    ).status_code == 403  # D-06
    assert (await post(client, idp, f"/proposals/{p.id}/approve", "hom.hq")).status_code == 200


async def test_concurrent_approvals_execute_once(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await idp.user("sec", [("SECURITY_OFFICER", None)])
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    results = await asyncio.gather(
        post(client, idp, f"/proposals/{p.id}/approve", "duty"),
        post(client, idp, f"/proposals/{p.id}/approve", "sec"),
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        runs = list(await session.scalars(select(PlaybookRun)))
    assert len(runs) == 1


async def test_a_mission_scoped_admin_cannot_pause_the_tenant(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        nbo = await session.scalar(text("SELECT id FROM mission WHERE code = 'NBO'"))
    await idp.user("admin.nbo", [("ADMIN", nbo)])
    assert (await post(client, idp, "/agents/pause-all", "admin.nbo")).status_code == 403


# --- Prompt 14: what the screens are told ---------------------------------------------------


async def test_undo_and_dismiss_are_reported_by_the_same_checks(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    await set_level(idp, "WATCH_OFFICER", 1)
    noticed = await propose(idp, world, "WATCH_OFFICER", "LOG_INFO", {"text": "Note"})
    advice = await propose(idp, world, "WATCH_OFFICER", "CLOSE_AIRSPACE", {"x": 1})

    async def flags(sub: str, proposal_id: uuid.UUID) -> tuple[bool, bool, bool]:
        body = (await client.get(f"/api/proposals/{proposal_id}", headers=idp.headers(sub))).json()
        return body["can_decide"], body["can_dismiss"], body["can_undo"]

    assert await flags("duty", noticed.id) == (False, False, True)
    assert await flags("viewer", noticed.id) == (False, False, False)
    assert await flags("duty", advice.id) == (False, True, False)
    assert await flags("consular", advice.id) == (False, False, False)
    perms = await client.get(
        "/api/me/permissions",
        params={"entity_type": "agent_proposal", "entity_id": str(noticed.id)},
        headers=idp.headers("duty"),
    )
    assert perms.json()["undo_proposal"] is True
    await post(client, idp, f"/proposals/{noticed.id}/undo", "duty")
    assert await flags("duty", noticed.id) == (False, False, False)  # undone: nothing left


async def test_activity_log_names_agents_not_people(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    p = await propose(idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"})
    await post(client, idp, f"/proposals/{p.id}/reject", "duty", {"reason": "Not needed"})
    log = (await client.get("/api/agents/activity", headers=idp.headers("viewer"))).json()
    assert [(e["actor"], e["text"]) for e in log[:2]] == [
        ("Human", "rejected START_PLAYBOOK proposal"),
        ("Response Planner", "proposed START_PLAYBOOK proposal"),
    ]


async def test_the_roster_shows_watches_and_acceptance(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    for reason in ("a", None):
        p = await propose(
            idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"}
        )
        if reason:
            await post(client, idp, f"/proposals/{p.id}/reject", "duty", {"reason": reason})
        else:
            async with tenant_session(idp.tenant_id, idp.engine) as session:
                await session.execute(update(Incident).values(status="ACTIVE"))
                await session.commit()
            await post(client, idp, f"/proposals/{p.id}/approve", "duty")
    roster = (await client.get("/api/agents", headers=idp.headers("viewer"))).json()["agents"]
    planner = next(a for a in roster if a["code"] == "RESPONSE_PLANNER")
    assert planner["watches"] == ["EXPOSURE_COMPUTED"]
    assert (planner["proposals_total"], planner["accepted_pct"]) == (2, 50.0)


async def test_an_edit_must_change_what_runs(client: AsyncClient, idp: Idp, world: World) -> None:
    """Review of Prompt 14: a new description alone would let the approvers read
    one thing while another executes."""
    evac = await propose(idp, world, "RESPONSE_PLANNER", "START_EVACUATION", {"route": "B"})
    text_only = await post(
        client,
        idp,
        f"/proposals/{evac.id}/edit-approve",
        "hom.nbo",
        {"edited_action": "Evacuate via route A"},
    )
    assert text_only.status_code == 409
    assert (await stored(idp, evac.id)).edited_action is None
    message = await propose(idp, world, "COMMUNICATIONS", "SEND_EXTERNAL_MESSAGE", MESSAGE)
    playbook = await propose(
        idp, world, "RESPONSE_PLANNER", "START_PLAYBOOK", {"playbook_code": "PB-T"}
    )

    async def can_edit(sub: str, proposal_id: uuid.UUID) -> bool:
        body = (await client.get(f"/api/proposals/{proposal_id}", headers=idp.headers(sub))).json()
        allowed: bool = body["can_edit"]
        return allowed

    assert await can_edit("duty", message.id) is True
    assert await can_edit("viewer", message.id) is False
    assert await can_edit("duty", playbook.id) is False  # use an alternative instead
    assert await can_edit("hom.nbo", evac.id) is False
