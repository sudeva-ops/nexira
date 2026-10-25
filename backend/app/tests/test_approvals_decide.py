"""app/core/approvals.py part 2: decide() / can_decide() (D-05, D-06, D-16, plan G-08)."""

import dataclasses
import uuid
from typing import Any

import pytest

from app.core.approvals import ApprovalDeniedError, Gate, can_decide, decide
from app.core.db import tenant_session
from app.tests.auth_helpers import Idp

BASE = Gate(
    subject="PB-07 step 7",
    required_role="HEAD_OF_MISSION",
    mission_id=None,
    decided=False,
    open=True,
    deciders_of_other_steps=frozenset(),
)


def gate(**overrides: Any) -> Gate:
    return dataclasses.replace(BASE, **overrides)


@pytest.fixture
async def people(idp: Idp) -> dict[str, uuid.UUID]:
    nbo, cai = await idp.mission("NBO"), await idp.mission("CAI")
    return {
        "nbo": nbo,
        "cai": cai,
        "hom_nbo": await idp.user("hom.nbo", [("HEAD_OF_MISSION", nbo)]),
        "hom_cai": await idp.user("hom.cai", [("HEAD_OF_MISSION", cai)]),
        "hq": await idp.user("hq", [("HQ_CRISIS_DIRECTOR", None)]),
        "duty": await idp.user("duty", [("DUTY_OFFICER", None)]),
        "sec": await idp.user("sec", [("SECURITY_OFFICER", None)]),
    }


async def verdict(idp: Idp, user: uuid.UUID, g: Gate) -> tuple[bool, int]:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        v = await can_decide(session, user, g)
    return v.allowed, v.status_code


async def test_mission_scope(idp: Idp, people: dict[str, uuid.UUID]) -> None:
    nbo_gate = gate(mission_id=people["nbo"])
    assert await verdict(idp, people["hom_nbo"], nbo_gate) == (True, 200)
    assert await verdict(idp, people["hom_cai"], nbo_gate) == (False, 403)  # D-05
    assert await verdict(idp, people["duty"], nbo_gate) == (False, 403)  # wrong role


async def test_no_mission_means_unscoped_holders_only(
    idp: Idp, people: dict[str, uuid.UUID]
) -> None:
    hq_gate = gate(required_role="HEAD_OF_MISSION|HQ_CRISIS_DIRECTOR", mission_id=None)
    assert await verdict(idp, people["hom_nbo"], hq_gate) == (False, 403)  # D-06
    assert await verdict(idp, people["hq"], hq_gate) == (True, 200)


async def test_alternative_roles(idp: Idp, people: dict[str, uuid.UUID]) -> None:
    g = gate(required_role="DUTY_OFFICER|SECURITY_OFFICER")
    assert await verdict(idp, people["duty"], g) == (True, 200)
    assert await verdict(idp, people["sec"], g) == (True, 200)
    assert await verdict(idp, people["hq"], g) == (False, 403)


async def test_refusal_order(idp: Idp, people: dict[str, uuid.UUID]) -> None:
    hom = people["hom_nbo"]
    base = {"mission_id": people["nbo"]}
    # Already decided and not yet open are 409, before any role check.
    assert await verdict(idp, people["duty"], gate(decided=True, **base)) == (False, 409)
    assert await verdict(idp, people["duty"], gate(open=False, **base)) == (False, 409)
    # D-16: the same person never fills two steps, even holding the role.
    two_steps = gate(deciders_of_other_steps=frozenset({hom}), **base)
    assert await verdict(idp, hom, two_steps) == (False, 403)


async def test_decide_raises_with_the_verdict(idp: Idp, people: dict[str, uuid.UUID]) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await decide(session, people["hom_nbo"], gate(mission_id=people["nbo"]))
        with pytest.raises(ApprovalDeniedError) as info:
            await decide(session, people["hom_cai"], gate(mission_id=people["nbo"]))
    assert info.value.verdict.status_code == 403
    assert "HEAD_OF_MISSION" in info.value.verdict.reason
