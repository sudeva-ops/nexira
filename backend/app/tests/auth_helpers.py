"""Test identity provider: RSA keys, a static JWKS and token minting.

Tokens are signed like Keycloak's (RS256 with a kid) so the real validation
code in app/core/security.py runs unchanged; only the key source is replaced.
"""

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.db import engine_dependency, tenant_session
from app.core.security import JwksCache, get_jwks
from app.main import app
from app.modules.tenancy import service as tenancy

AUDIENCE = "nexira-api"


class StaticJwks(JwksCache):
    def __init__(self, jwk_set: dict[str, Any]) -> None:
        super().__init__("unused://jwks")
        self._jwk_set = jwk_set

    async def _fetch(self) -> dict[str, Any]:
        return self._jwk_set


def new_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    jwk: dict[str, Any] = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


def public_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


@dataclass
class Idp:
    issuer: str
    tenant_id: uuid.UUID
    engine: AsyncEngine
    key: rsa.RSAPrivateKey = field(default_factory=new_rsa_key)
    kid: str = "test-key-1"

    def token(
        self,
        sub: str,
        *,
        key: rsa.RSAPrivateKey | None = None,
        kid: str | None = None,
        lifetime_s: int = 300,
        drop: tuple[str, ...] = (),
        **claims: Any,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": self.issuer,
            "aud": AUDIENCE,
            "sub": sub,
            "iat": now,
            "exp": now + lifetime_s,
            "email": f"{sub}@demo.invalid",
            "name": f"User {sub}",
            **claims,
        }
        for name in drop:
            payload.pop(name, None)
        return jwt.encode(
            payload, key or self.key, algorithm="RS256", headers={"kid": kid or self.kid}
        )

    def headers(self, sub: str, **kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(sub, **kwargs)}"}

    def settings(self) -> Settings:
        return Settings(
            _env_file=None,
            database_url="unused",
            oidc_issuer=self.issuer,
            oidc_jwks_url="unused://jwks",
            oidc_audience=AUDIENCE,
        )

    async def client(self) -> AsyncIterator[AsyncClient]:
        jwks = StaticJwks({"keys": [public_jwk(self.key, self.kid)]})
        app.dependency_overrides[engine_dependency] = lambda: self.engine
        app.dependency_overrides[get_settings] = self.settings
        app.dependency_overrides[get_jwks] = lambda: jwks
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client
        finally:
            app.dependency_overrides.clear()

    async def user(
        self, sub: str, roles: list[tuple[str, uuid.UUID | None]] | None = None
    ) -> uuid.UUID:
        """Create an app_user for sub with (role_code, mission_id) grants."""
        async with tenant_session(self.tenant_id, self.engine) as session:
            role_ids = await tenancy.ensure_roles(session)
            user_id = await tenancy.ensure_user(
                session, external_id=sub, email=f"{sub}@demo.invalid", display_name=f"User {sub}"
            )
            for code, mission_id in roles or []:
                await tenancy.grant_role(
                    session, user_id=user_id, role_id=role_ids[code], mission_id=mission_id
                )
            await session.commit()
        return user_id

    async def mission(self, code: str) -> uuid.UUID:
        mission_id = uuid.uuid4()
        async with tenant_session(self.tenant_id, self.engine) as session:
            await session.execute(
                text(
                    "INSERT INTO mission (id, tenant_id, code, city, country_code, location) "
                    "VALUES (:id, current_tenant_id(), :code, :code, 'XX', "
                    "'SRID=4326;POINT(0 0)')"
                ),
                {"id": mission_id, "code": code},
            )
            await session.commit()
        return mission_id
