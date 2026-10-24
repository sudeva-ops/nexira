"""app/core/approvals.py part 1: roles from user_role, '|' alternatives, mission scope
(D-04, D-05, D-06, D-16)."""

import uuid
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient
from sqlalchemy import text

from app.core.approvals import (
    ANY_MISSION,
    MissionScope,
    parse_role_codes,
    require_roles,
    user_has_role,
)
from app.core.db import tenant_session
from app.core.security import CurrentUser
from app.main import app
from app.tests.auth_helpers import Idp
from app.tests.conftest import DbUrls, create_tenant


def test_parse_role_codes_splits_alternatives() -> None:
    assert parse_role_codes("DUTY_OFFICER|SECURITY_OFFICER") == {
        "DUTY_OFFICER",
        "SECURITY_OFFICER",
    }
    assert parse_role_codes(["ADMIN", "HQ_CRISIS_DIRECTOR | VIEWER"]) == {
        "ADMIN",
        "HQ_CRISIS_DIRECTOR",
        "VIEWER",
    }
    with pytest.raises(ValueError, match="at least one"):
        parse_role_codes(" | ")


async def _has(idp: Idp, user: uuid.UUID, codes: str, mission: MissionScope = ANY_MISSION) -> bool:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        return await user_has_role(session, user, codes, mission)


async def test_mission_scope_matrix(idp: Idp) -> None:
    nbo, cai = await idp.mission("NBO"), await idp.mission("CAI")
    hom_nbo = await idp.user("hom-nbo", [("HEAD_OF_MISSION", nbo)])
    hom_cai = await idp.user("hom-cai", [("HEAD_OF_MISSION", cai)])
    hq_hom = await idp.user("hq-hom", [("HEAD_OF_MISSION", None)])  # unscoped

    # D-05: scoped to the incident's mission, or unscoped.
    assert await _has(idp, hom_nbo, "HEAD_OF_MISSION", nbo)
    assert not await _has(idp, hom_cai, "HEAD_OF_MISSION", nbo)
    assert await _has(idp, hq_hom, "HEAD_OF_MISSION", nbo)
    # D-06: no mission yet means only unscoped holders.
    assert not await _has(idp, hom_nbo, "HEAD_OF_MISSION", None)
    assert await _has(idp, hq_hom, "HEAD_OF_MISSION", None)
    # Endpoint gating: any scope.
    assert await _has(idp, hom_cai, "HEAD_OF_MISSION")


async def test_role_alternatives_and_wrong_role(idp: Idp) -> None:
    duty = await idp.user("duty", [("DUTY_OFFICER", None)])
    assert await _has(idp, duty, "DUTY_OFFICER|SECURITY_OFFICER")
    assert await _has(idp, duty, "SECURITY_OFFICER|DUTY_OFFICER", None)
    assert not await _has(idp, duty, "HEAD_OF_MISSION")
    assert not await _has(idp, duty, "ADMIN|HQ_CRISIS_DIRECTOR")


async def test_dual_role_user_holds_both_roles(idp: Idp) -> None:
    """The D-16 test user: HoM for Nairobi and HQ Crisis Director. Holding both is
    allowed; filling two steps of one proposal is blocked later by decide()."""
    nbo = await idp.mission("NBO")
    dual = await idp.user("dual", [("HEAD_OF_MISSION", nbo), ("HQ_CRISIS_DIRECTOR", None)])
    assert await _has(idp, dual, "HEAD_OF_MISSION", nbo)
    assert await _has(idp, dual, "HQ_CRISIS_DIRECTOR", nbo)


async def test_roles_are_tenant_scoped(idp: Idp, db: DbUrls) -> None:
    admin = await idp.user("admin", [("ADMIN", None)])
    other = await create_tenant(db)
    async with tenant_session(other, idp.engine) as session:
        assert not await user_has_role(session, admin, "ADMIN")


# --- require_roles as a FastAPI dependency ----------------------------------------------------

NBO_ID = uuid.UUID("00000000-0000-0000-0000-00000000a0b0")
probe = APIRouter()


@probe.get("/test-only/nairobi-gate")
async def nairobi_gate(
    user: Annotated[CurrentUser, Depends(require_roles("HEAD_OF_MISSION", mission_id=NBO_ID))],
) -> dict[str, str]:
    return {"ok": user.display_name}


@pytest.fixture
def gated_app() -> None:
    app.include_router(probe)


async def test_cairo_hom_cannot_pass_a_nairobi_scoped_check(
    gated_app: None, client: AsyncClient, idp: Idp
) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await session.execute(
            text(
                "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
                "VALUES (:id, current_tenant_id(), 'NBO', 'Nairobi', 'KE', 'SRID=4326;POINT(0 0)')"
            ),
            {"id": NBO_ID},
        )
        await session.commit()
    cai = await idp.mission("CAI")
    await idp.user("hom-nbo", [("HEAD_OF_MISSION", NBO_ID)])
    await idp.user("hom-cai", [("HEAD_OF_MISSION", cai)])
    await idp.user("viewer", [("VIEWER", None)])

    ok = await client.get("/test-only/nairobi-gate", headers=idp.headers("hom-nbo"))
    assert ok.status_code == 200
    for sub in ("hom-cai", "viewer"):
        denied = await client.get("/test-only/nairobi-gate", headers=idp.headers(sub))
        assert denied.status_code == 403, sub
