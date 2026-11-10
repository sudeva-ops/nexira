"""AI Risk Copilot, simulated (COP-01..06; D-50; docs/plan-pilot-cop.md): the question types,
facts read as the asker with every sentence cited, names only to the roles that may record
check-in answers at the incident's mission (G-1: A), unknown questions declined, the audit
row holding the type and references but never the text, and no network code. Against real
PostgreSQL, as nexira_api, on the check-in tests' Nairobi world."""

import ast
import pathlib
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import tenant_session
from app.modules.audit.models import AuditLog
from app.modules.copilot.intents import Kind, classify
from app.tests.auth_helpers import Idp
from app.tests.test_checkin import World, answer, make_world


@pytest.fixture
async def world(client: AsyncClient, idp: Idp) -> World:
    w = await make_world(idp)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(text("UPDATE mission SET city = 'Nairobi' WHERE code = 'NBO'"))
        await session.commit()
    assert await answer(client, idp, w, "Peter", "SAFE") == 201
    assert await answer(client, idp, w, "Grace", "NEED_HELP") == 201
    return w


async def ask(client: AsyncClient, idp: Idp, question: str, sub: str = "duty") -> dict[str, Any]:
    response = await client.post(
        "/api/copilot/ask", json={"question": question}, headers=idp.headers(sub)
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["label"] == "Simulated copilot · rule-based wording · simulated data"
    return body


def texts(body: dict[str, Any]) -> str:
    return " ".join(s["text"] for s in body["sentences"])


@pytest.mark.parametrize(
    ("question", "kind"),
    [
        ("", Kind.HELP),
        ("What can you do?", Kind.HELP),
        ("Draft a situation report for Nairobi", Kind.REPORT),
        ("Who has not responded to the check-in?", Kind.PEOPLE),
        ("Which decisions are waiting for me?", Kind.DECISIONS),
        ("Any trips near INC-2026-1042?", Kind.TRAVEL),
        ("What is Nairobi's readiness?", Kind.READINESS),
        ("Which missions are at elevated risk this week?", Kind.RISK),
        ("Tell me about inc-2026-1042", Kind.INCIDENT),
        ("Summarise the Nairobi situation", Kind.SITUATION),
        ("What's the weather like in Lisbon?", Kind.UNKNOWN),
    ],
)
def test_question_types(question: str, kind: Kind) -> None:
    q = classify(question)
    assert q.kind is kind
    if "inc-2026-1042" in question.lower():
        assert q.reference == "INC-2026-1042"


async def test_the_nairobi_situation_is_cited_sentence_by_sentence(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    body = await ask(client, idp, "Summarise the Nairobi situation")
    assert body["kind"] == "SITUATION"
    assert all(s["sources"] for s in body["sentences"])  # every sentence cites (COP-02)
    said = texts(body)
    assert world.reference.startswith("NTF-")
    assert "INC-" in said
    assert "civil unrest" in said
    assert (
        f"Check-in {world.reference}: of 3 personnel, 1 safe, 1 need help and 1 not yet answered"
    ) in said
    kinds = {s["kind"] for s in body["sources"]}
    assert {"INCIDENT", "CHECKIN"} <= kinds
    incident = next(s for s in body["sources"] if s["kind"] == "INCIDENT")
    assert incident["href"] == f"/incidents?id={world.incident_id}"
    assert "Hana" not in said  # names only when people are asked about


@pytest.mark.parametrize(
    ("sub", "named"),
    [("duty", True), ("hom.nbo", True), ("hom.cai", False), ("viewer", False)],
)
async def test_names_only_for_roles_that_record_answers_at_the_mission(
    client: AsyncClient, idp: Idp, world: World, sub: str, named: bool
) -> None:
    body = await ask(client, idp, "Who has not responded to the check-in?", sub)
    said = texts(body)
    assert "of 3 personnel, 1 safe, 1 need help and 1 not yet answered" in said
    assert ("Not yet answered: Hana." in said) is named
    assert ("Asked for help: Grace." in said) is named
    assert all(s["sources"] for s in body["sentences"])


async def test_unknown_and_help_are_answered_without_a_source(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    unknown = await ask(client, idp, "What's the weather like in Lisbon?")
    assert unknown["kind"] == "UNKNOWN"
    assert texts(unknown).startswith("I can't answer that yet.")
    assert unknown["sources"] == []
    helped = await ask(client, idp, "help")
    assert "Summarise the Nairobi situation" in texts(helped)
    missing = await ask(client, idp, "Tell me about INC-1999-0001")
    assert texts(missing) == "I found no incident for INC-1999-0001."


async def test_decisions_risk_travel_readiness_and_report(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    assert texts(await ask(client, idp, "Which decisions are waiting?")) == (
        "No decision is waiting."
    )
    risk = await ask(client, idp, "Which missions are at elevated risk this week?")
    assert "Nairobi (NBO): high risk" in texts(risk)  # raised by its HIGH incident
    assert {s["kind"] for s in risk["sources"]} == {"MISSION"}
    travel = await ask(client, idp, "Any trips near the Nairobi incident?")
    assert texts(travel).startswith("No trip is in the zone of INC-")
    readiness = await ask(client, idp, "What is Nairobi's readiness?")
    assert texts(readiness) == "I found no exercise for that mission."
    report = await ask(client, idp, "Draft a situation report for Nairobi")
    assert report["incident_id"] == str(world.incident_id)
    assert texts(report).startswith("Here is a draft situation report for INC-")


async def test_each_question_is_audited_without_its_text(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    question = "Who has not responded to the check-in? Hana asked me to check"
    await ask(client, idp, question)
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        row = (
            await session.execute(
                select(AuditLog.actor_type, AuditLog.details).where(
                    AuditLog.action == "COPILOT.ASK"
                )
            )
        ).one()
    assert row.actor_type == "USER"
    assert row.details["kind"] == "PEOPLE"
    assert row.details["references"] == [world.reference]
    assert "Hana" not in str(row.details)
    assert question not in str(row.details)


async def test_every_role_may_ask_and_nobody_unauthenticated(
    client: AsyncClient, idp: Idp, world: World
) -> None:
    for sub in ("viewer", "consular", "hom.cai"):
        await ask(client, idp, "Summarise the Nairobi situation", sub)
    response = await client.post("/api/copilot/ask", json={"question": "help"})
    assert response.status_code == 401
    too_long = await client.post(
        "/api/copilot/ask", json={"question": "x" * 501}, headers=idp.headers("duty")
    )
    assert too_long.status_code == 422


def test_the_copilot_has_no_network_code() -> None:
    """COP-05: no model and no external call. The module imports no HTTP or socket library."""
    banned = {"httpx", "requests", "aiohttp", "urllib", "socket", "http"}
    root = pathlib.Path(__file__).parents[1] / "modules" / "copilot"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert name.split(".")[0] not in banned, f"{path.name} imports {name}"
