"""Authentication. Changes need human sign-off (D-29).

- Validates Keycloak OIDC access tokens: RS256 signature against the realm's
  JWKS, exact issuer, audience, expiry (D-04).
- The tenant comes from resolve_tenant_by_issuer(iss), the only cross-tenant
  read the API performs. The user is app_user (tenant, sub), created on first login.
- Role claims in the token are ignored. Roles and mission scope come from
  user_role through app/core/approvals.py (D-04).

Phase 1 trusts exactly one issuer (OIDC_ISSUER) and its JWKS (OIDC_JWKS_URL).
The JWKS URL is never derived from a token, so a forged issuer cannot point
the API at an attacker's keys.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import audit
from app.core.config import Settings, get_settings
from app.core.db import engine_dependency, tenant_session
from app.modules.tenancy.models import AppUser

ALGORITHMS = ["RS256"]
LEEWAY_S = 30


class JwksCache:
    """Signing keys from the configured JWKS URL, refreshed on an unknown kid."""

    def __init__(self, url: str, ttl_s: int = 300, min_refresh_s: int = 10) -> None:
        self._url = url
        self._ttl_s = ttl_s
        self._min_refresh_s = min_refresh_s
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _fetch(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(self._url)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    async def _refresh(self) -> None:
        async with self._lock:
            if time.monotonic() - self._fetched_at < self._min_refresh_s and self._keys:
                return
            jwk_set = jwt.PyJWKSet.from_dict(await self._fetch())
            self._keys = {k.key_id: k for k in jwk_set.keys if k.key_id}
            self._fetched_at = time.monotonic()

    async def key(self, kid: str) -> jwt.PyJWK:
        stale = time.monotonic() - self._fetched_at > self._ttl_s
        if kid not in self._keys or stale:
            await self._refresh()
        try:
            return self._keys[kid]
        except KeyError:
            raise jwt.InvalidTokenError("unknown signing key") from None


@lru_cache
def get_jwks() -> JwksCache:
    return JwksCache(get_settings().oidc_jwks_url)


@dataclass(frozen=True)
class Principal:
    """A validated token, resolved to a tenant. Not yet an app_user."""

    tenant_id: uuid.UUID
    subject: str
    email: str | None
    name: str | None
    expires_at: float  # the token's exp claim (seconds since the epoch)


class InvalidCredentialsError(Exception):
    """The token is invalid or expired, or its issuer is not a known tenant."""


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    tenant_id: uuid.UUID
    external_id: str
    email: str
    display_name: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def decode_token(token: str, jwks: JwksCache, settings: Settings) -> dict[str, Any]:
    """Return the verified claims, or raise jwt.InvalidTokenError."""
    header = jwt.get_unverified_header(token)
    if header.get("alg") not in ALGORITHMS or not header.get("kid"):
        raise jwt.InvalidTokenError("unsupported token header")
    key = await jwks.key(str(header["kid"]))
    claims: dict[str, Any] = jwt.decode(
        token,
        key.key,
        algorithms=ALGORITHMS,
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
        leeway=LEEWAY_S,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )
    return claims


bearer = HTTPBearer(auto_error=False)


async def principal_from_token(
    token: str, *, settings: Settings, jwks: JwksCache, engine: AsyncEngine
) -> Principal:
    """Validate a bearer token and resolve its tenant. The one implementation used
    by HTTP requests (authenticate) and by the WebSocket (app/core/realtime.py)."""
    try:
        claims = await decode_token(token, jwks, settings)
    except (jwt.InvalidTokenError, httpx.HTTPError):
        raise InvalidCredentialsError from None

    async with tenant_session(None, engine) as session:
        tenant_id = await session.scalar(
            text("SELECT resolve_tenant_by_issuer(:iss)"), {"iss": claims["iss"]}
        )
    if tenant_id is None:
        raise InvalidCredentialsError

    return Principal(
        tenant_id=tenant_id,
        subject=str(claims["sub"]),
        email=claims.get("email"),
        name=claims.get("name") or claims.get("preferred_username"),
        expires_at=float(claims["exp"]),
    )


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    jwks: Annotated[JwksCache, Depends(get_jwks)],
    engine: Annotated[AsyncEngine, Depends(engine_dependency)],
) -> Principal:
    if credentials is None:
        raise _unauthorized()
    try:
        principal = await principal_from_token(
            credentials.credentials, settings=settings, jwks=jwks, engine=engine
        )
    except InvalidCredentialsError:
        raise _unauthorized() from None
    request.state.tenant_id = principal.tenant_id
    return principal


async def get_db(
    principal: Annotated[Principal, Depends(authenticate)],
    engine: Annotated[AsyncEngine, Depends(engine_dependency)],
) -> AsyncIterator[AsyncSession]:
    """A session scoped to the caller's tenant, one per request (D-02)."""
    async with tenant_session(principal.tenant_id, engine) as session:
        yield session


async def current_user(
    principal: Annotated[Principal, Depends(authenticate)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    """The app_user for this token, created (and audited) on first login."""
    created_id = await session.scalar(
        insert(AppUser)
        .values(
            tenant_id=principal.tenant_id,
            external_id=principal.subject,
            email=principal.email or f"{principal.subject}@users.invalid",
            display_name=principal.name or principal.subject,
        )
        .on_conflict_do_nothing()
        .returning(AppUser.id)
    )
    if created_id is not None:
        await audit.write(
            session,
            actor_type="USER",
            actor_id=str(created_id),
            action="USER.CREATE_ON_FIRST_LOGIN",
            entity_type="app_user",
            entity_id=str(created_id),
            details={"external_id": principal.subject, "email": principal.email},
        )
        await session.commit()

    user = await active_user(session, principal)
    if user is None:
        # No row: the email already belongs to another account in this tenant.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No active account for this login")
    return user


async def active_user(session: AsyncSession, principal: Principal) -> CurrentUser | None:
    """The active app_user for a principal, without creating one. The session must
    be scoped to principal.tenant_id."""
    user = await session.scalar(select(AppUser).where(AppUser.external_id == principal.subject))
    if user is None or not user.is_active:
        return None
    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        external_id=user.external_id,
        email=user.email,
        display_name=user.display_name,
    )
