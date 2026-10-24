"""Shared fixtures for database tests against real PostgreSQL 16 + PostGIS.

Setup uses a superuser (TEST_ADMIN_DATABASE_URL) only to create throwaway
databases and install extensions, exactly as infra/postgres/init.sql does.
The schema is applied by Alembic as nexira_owner, and every assertion runs as
nexira_api, the role the backend uses (D-01).

Roles are cluster-wide, so the server must already have them (`make up`, or
the CI container built from infra/postgres).
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DB = "nexira_test"


@dataclass(frozen=True)
class DbUrls:
    admin: str  # superuser, setup only
    owner: str  # nexira_owner, SQLAlchemy URL
    api: str  # nexira_api, SQLAlchemy URL

    @staticmethod
    def plain(url: str) -> str:
        """asyncpg wants a libpq URL without the +asyncpg driver suffix."""
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)

    @property
    def api_plain(self) -> str:
        return self.plain(self.api)

    @property
    def owner_plain(self) -> str:
        return self.plain(self.owner)

    def for_database(self, name: str) -> "DbUrls":
        return DbUrls(
            admin=make_url(self.admin).set(database=name).render_as_string(hide_password=False),
            owner=make_url(self.owner).set(database=name).render_as_string(hide_password=False),
            api=make_url(self.api).set(database=name).render_as_string(hide_password=False),
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(
            f"{name} is not set. Database tests need a running PostgreSQL + PostGIS "
            "(`make up`, then `make test`, which loads .env).",
            pytrace=False,
        )
    return value


@pytest.fixture(scope="session")
def server_urls() -> DbUrls:
    return DbUrls(
        admin=_required_env("TEST_ADMIN_DATABASE_URL"),
        owner=_required_env("MIGRATIONS_DATABASE_URL"),
        api=_required_env("DATABASE_URL"),
    )


async def _recreate_database(admin_url: str, name: str) -> None:
    conn = await asyncpg.connect(DbUrls.plain(admin_url))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}" OWNER nexira_owner')
    finally:
        await conn.close()
    db = await asyncpg.connect(
        DbUrls.plain(make_url(admin_url).set(database=name).render_as_string(hide_password=False))
    )
    try:
        await db.execute("CREATE EXTENSION postgis; CREATE EXTENSION pgcrypto;")
    finally:
        await db.close()


def alembic_config(owner_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["url"] = owner_url
    return cfg


def create_empty_database(server: DbUrls, name: str) -> DbUrls:
    asyncio.run(_recreate_database(server.admin, name))
    return server.for_database(name)


@pytest.fixture(scope="session")
def db(server_urls: DbUrls) -> DbUrls:
    """A fresh database migrated to head, shared by the session. Tests isolate
    themselves by creating their own tenants."""
    urls = create_empty_database(server_urls, TEST_DB)
    command.upgrade(alembic_config(urls.owner), "head")
    return urls


async def create_tenant(db: DbUrls, name: str = "Test tenant") -> uuid.UUID:
    """Tenants can only be created by nexira_owner (plan G-03)."""
    tenant_id = uuid.uuid4()
    conn = await asyncpg.connect(db.owner_plain)
    try:
        await conn.execute(
            "INSERT INTO tenant (id, name, oidc_issuer) VALUES ($1, $2, $3)",
            tenant_id,
            name,
            f"https://kc.test/realms/{tenant_id}",
        )
    finally:
        await conn.close()
    return tenant_id


async def set_tenant(conn: asyncpg.Connection, tenant_id: uuid.UUID | None) -> None:
    """Session-level tenant for raw test connections (the app uses per-transaction)."""
    await conn.execute(
        "SELECT set_config('app.tenant_id', $1, false)", str(tenant_id) if tenant_id else ""
    )


@pytest.fixture
async def api(db: DbUrls) -> AsyncIterator[asyncpg.Connection]:
    """A raw connection as nexira_api with no tenant set."""
    conn = await asyncpg.connect(db.api_plain)
    try:
        yield conn
    finally:
        await conn.close()
