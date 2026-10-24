import json
import uuid

from app.modules.tenancy.service import ROLES

from nexira_sim.seed import data
from nexira_sim.seed.identities import DEMO_ROLES, REALM_FILE, realm_users


def test_every_realm_user_has_roles_and_every_mapping_has_a_user() -> None:
    assert {u.username for u in realm_users()} == set(DEMO_ROLES)


def test_role_codes_and_missions_exist() -> None:
    codes = {code for code, *_ in data.MISSIONS}
    for grants in DEMO_ROLES.values():
        for role, mission in grants:
            assert role in ROLES
            assert mission is None or mission in codes


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
        audience = [
            m for m in client["protocolMappers"] if m["protocolMapper"] == "oidc-audience-mapper"
        ]
        assert audience[0]["config"]["included.custom.audience"] == "nexira-api"
    web = next(c for c in realm["clients"] if c["clientId"] == "nexira-web")
    assert web["publicClient"] is True
    assert web["directAccessGrantsEnabled"] is False
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"
