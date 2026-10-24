"""app/core/security.py: token validation, tenant from issuer, first login (D-04)."""

import base64
import hashlib
import hmac
import json
import time
import uuid

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.tests.auth_helpers import Idp, new_rsa_key, public_pem
from app.tests.conftest import DbUrls, set_tenant


async def test_valid_token_returns_me_and_creates_user_on_first_login(
    client: AsyncClient, idp: Idp, db: DbUrls
) -> None:
    response = await client.get("/api/me", headers=idp.headers("kc-sub-1"))
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "User kc-sub-1"
    assert body["roles"] == []

    again = await client.get("/api/me", headers=idp.headers("kc-sub-1"))
    assert again.json()["id"] == body["id"]

    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, idp.tenant_id)
        assert await conn.fetchval("SELECT count(*) FROM app_user") == 1
        actions = await conn.fetch("SELECT action, entity_id FROM audit_log")
    finally:
        await conn.close()
    assert [(r["action"], r["entity_id"]) for r in actions] == [
        ("USER.CREATE_ON_FIRST_LOGIN", body["id"])
    ]


async def test_existing_user_is_found_by_subject(client: AsyncClient, idp: Idp) -> None:
    user_id = await idp.user("kc-sub-2", roles=[("VIEWER", None)])
    body = (await client.get("/api/me", headers=idp.headers("kc-sub-2"))).json()
    assert body["id"] == str(user_id)
    assert body["roles"] == [{"code": "VIEWER", "mission_id": None, "mission_code": None}]


async def test_missing_token_is_401(client: AsyncClient) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def _unsigned(claims: dict[str, object], header: dict[str, object]) -> str:
    def b64(data: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{b64(header)}.{b64(claims)}."


def _bad_tokens(idp: Idp) -> dict[str, str]:
    now = int(time.time())
    claims = {"iss": idp.issuer, "aud": "nexira-api", "sub": "x", "iat": now, "exp": now + 300}
    return {
        "expired": idp.token("x", lifetime_s=-120),  # beyond the 30 s leeway
        "wrong_issuer": idp.token("x", iss="https://evil.test/realms/x"),
        "wrong_audience": idp.token("x", aud="account"),
        "other_key_same_kid": idp.token("x", key=new_rsa_key()),
        "unknown_kid": idp.token("x", kid="not-a-key"),
        "no_sub": idp.token("x", drop=("sub",)),
        "no_exp": idp.token("x", drop=("exp",)),
        "alg_none": _unsigned(claims, {"alg": "none", "kid": idp.kid}),
        # Algorithm confusion: HS256 keyed with the public key.
        "hs256_with_public_key": _hs256(claims, public_pem(idp.key), idp.kid),
        "garbage": "not.a.token",
    }


def _hs256(claims: dict[str, object], secret: bytes, kid: str) -> str:
    """Hand-signed, because PyJWT itself refuses to use a PEM key as an HMAC secret."""
    header = {"alg": "HS256", "typ": "JWT", "kid": kid}

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = f"{b64(json.dumps(header).encode())}.{b64(json.dumps(claims).encode())}"
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(signature)}"


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "wrong_issuer",
        "wrong_audience",
        "other_key_same_kid",
        "unknown_kid",
        "no_sub",
        "no_exp",
        "alg_none",
        "hs256_with_public_key",
        "garbage",
    ],
)
async def test_invalid_tokens_are_401(client: AsyncClient, idp: Idp, case: str) -> None:
    token = _bad_tokens(idp)[case]
    response = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_trusted_issuer_without_a_tenant_is_401(api_engine: AsyncEngine) -> None:
    orphan = Idp(
        issuer="https://kc.test/realms/no-such-tenant", tenant_id=uuid.uuid4(), engine=api_engine
    )
    async for c in orphan.client():
        response = await c.get("/api/me", headers=orphan.headers("x"))
        assert response.status_code == 401


async def test_inactive_user_is_403(client: AsyncClient, idp: Idp, db: DbUrls) -> None:
    await idp.user("kc-sub-3")
    conn = await asyncpg.connect(db.api_plain)
    try:
        await set_tenant(conn, idp.tenant_id)
        await conn.execute("UPDATE app_user SET is_active = false WHERE external_id = 'kc-sub-3'")
    finally:
        await conn.close()
    response = await client.get("/api/me", headers=idp.headers("kc-sub-3"))
    assert response.status_code == 403


async def test_role_claims_in_the_token_grant_nothing(client: AsyncClient, idp: Idp) -> None:
    """D-04: roles come from user_role only."""
    headers = idp.headers(
        "kc-sub-4",
        roles=["ADMIN"],
        realm_access={"roles": ["ADMIN", "HQ_CRISIS_DIRECTOR"]},
        resource_access={"nexira-api": {"roles": ["ADMIN"]}},
        groups=["/admins"],
    )
    me = await client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["roles"] == []
    assert (await client.get("/api/audit", headers=headers)).status_code == 403
    assert (await client.get("/api/audit/verify", headers=headers)).status_code == 403
