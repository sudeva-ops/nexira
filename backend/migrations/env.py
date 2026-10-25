"""Alembic environment. Migrations run as nexira_owner, never as nexira_api (D-01)."""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # Tests pass their own database through config.attributes["url"]. The Helm
    # migrate Job has only the owner DSN (no DATABASE_URL), so read it directly.
    url = (
        context.config.attributes.get("url")
        or os.environ.get("MIGRATIONS_DATABASE_URL")
        or get_settings().migrations_database_url
    )
    if not url:
        raise SystemExit("MIGRATIONS_DATABASE_URL (nexira_owner) is required to run migrations.")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against the database.")

asyncio.run(run_async_migrations())
