import json
import uuid

import asyncpg
import pytest
from app.core.db import create_engine
from app.modules.tenancy.service import ROLES
from app.tests.conftest import DbUrls, set_tenant

from nexira_sim.seed import identities
from nexira_sim.seed.identities import DEMO_ROLES, REALM_FILE, realm_users


def test_every_realm_user_has_roles_and_every_mapping_has_a_user() -> None:
    assert {u.username for u in realm_users()} == set(DEMO_ROLES)


def test_role_codes_and_missions_exist() -> None:
    for grants in DEMO_ROLES.values():
        for code, mission in grants:
            assert code in ROLES
            assert mission is None or mission in identities.MISSIONS


def test_one_demo_user_per_role_plus_scope_and_dual_role_users() -> None:
    held = {code for grants in DEMO_ROLES.values() for code, _ in grants}
    assert held == set(ROLES)
    assert ("HEAD_OF_MISSION", "NBO") in DEMO_ROLES["hom.nairobi"]
    assert ("HEAD_OF_MISSION", "CAI") in DEMO_ROLES["hom.cairo"]
    assert {c for c, _ in DEMO_ROLES["dual.role"]} == {"HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"}


def test_realm_has_no_literal_passwords_and_fixed_ids() -> None:
    realm = json.loads(REALM_FILE.read_text())
    for user in realm["users"]:
        uuid.UUID(user["id"])  # fixed, valid id = token sub
        assert user["email"].endswith(".invalid")
        assert [c["value"] for c in user["credentials"]] == ["${DEMO_USER_PASSWORD}"]


def test_realm_clients_put_the_api_audience_in_access_tokens() -> None:
    realm = json.loads(REALM_FILE.read_text())
    for client in realm["clients"]:
        mappers = [
            m for m in client["protocolMappers"] if m["protocolMapper"] == "oidc-audience-mapper"
        ]
        assert mappers[0]["config"]["included.custom.audience"] == "nexira-api"
    web = next(c for c in realm["clients"] if c["clientId"] == "nexira-web")
    assert web["publicClient"] is True
    assert web["directAccessGrantsEnabled"] is False
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"


@pytest.fixture
def issuer() -> str:
    return f"https://kc.test/realms/seed-{uuid.uuid4()}"


async def _snapshot(db: DbUrls, tenant_id: uuid.UUID) -> dict[str, object]:
    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, tenant_id)
        return {
            "users": await conn.fetch("SELECT id, external_id, email FROM app_user ORDER BY 2"),
            "grants": await conn.fetch(
                "SELECT u.external_id, r.code, m.code AS mission FROM user_role ur "
                "JOIN app_user u ON u.id = ur.user_id JOIN role r ON r.id = ur.role_id "
                "LEFT JOIN mission m ON m.id = ur.mission_id ORDER BY 1, 2, 3"
            ),
            "missions": await conn.fetch("SELECT id, code FROM mission ORDER BY code"),
            "audit": await conn.fetchval("SELECT count(*) FROM audit_log"),
            "verify": await conn.fetchval("SELECT audit_verify_chain()"),
        }
    finally:
        await conn.close()


async def test_seeding_twice_gives_identical_data(
    db: DbUrls, issuer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(identities, "DEMO_TENANT_ID", tenant_id)
    engine = create_engine(db.api)
    try:
        assert await identities.bootstrap_tenant(db.owner, issuer) == tenant_id
        await identities.seed_identities(engine, tenant_id)
        first = await _snapshot(db, tenant_id)
        await identities.bootstrap_tenant(db.owner, issuer)
        second_run = await identities.seed_identities(engine, tenant_id)
        second = await _snapshot(db, tenant_id)
    finally:
        await engine.dispose()
    assert second_run["new_grants"] == 0
    assert first == second  # includes the audit row count: nothing re-audited
    assert len(first["users"]) == 10  # type: ignore[arg-type]
    assert first["verify"] is None


async def test_bootstrap_refuses_an_issuer_change(
    db: DbUrls, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(identities, "DEMO_TENANT_ID", uuid.uuid4())
    await identities.bootstrap_tenant(db.owner, "https://kc.test/realms/a-" + str(uuid.uuid4()))
    with pytest.raises(RuntimeError, match="reset-demo"):
        await identities.bootstrap_tenant(db.owner, "https://kc.test/realms/other")
