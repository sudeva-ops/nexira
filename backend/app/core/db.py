"""Database access for the API and workers.

- Connects only as nexira_api (DATABASE_URL), never as the owner or a superuser,
  because those bypass row-level security (D-01). verify_connection_role() runs
  at startup and refuses to continue otherwise.
- Every transaction starts with SELECT set_config('app.tenant_id', :tid, true)
  (D-02). The tenant is stored in session.info["tenant_id"]; with no tenant the
  setting is empty and every tenant table returns zero rows. Request sessions
  come from app/core/security.get_db, which takes the tenant from the token.
- READ COMMITTED isolation, which the audit chain relies on (D-20).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import get_settings
from app.core.model_base import Base

TENANT_KEY = "tenant_id"


class TenantSession(Session):
    """Sync session class behind AsyncSession; carries the tenant listeners."""


@event.listens_for(TenantSession, "after_begin")
def _set_tenant(session: Session, _tx: SessionTransaction, connection: Connection) -> None:
    tenant_id = session.info.get(TENANT_KEY)
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id) if tenant_id else ""},
    )


class ServerGeneratedColumnError(RuntimeError):
    pass


@event.listens_for(TenantSession, "before_flush")
def _reject_server_generated_writes(session: Session, _ctx: Any, _instances: Any) -> None:
    """Columns set by triggers (effective_level, deadline_at, chain_seq, prev_hash,
    row_hash) must never be written by the app (D-12, D-20)."""
    for obj in (*session.new, *session.dirty):
        if not isinstance(obj, Base):
            continue
        state = inspect(obj)
        for attr in type(obj).__server_generated__:
            if state.attrs[attr].history.added:
                raise ServerGeneratedColumnError(
                    f"{type(obj).__name__}.{attr} is set by the database and cannot be written"
                )


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, isolation_level="READ COMMITTED", pool_pre_ping=True)


@lru_cache
def get_engine() -> AsyncEngine:
    return create_engine(get_settings().database_url)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine, sync_session_class=TenantSession, expire_on_commit=False, autoflush=False
    )


@asynccontextmanager
async def tenant_session(
    tenant_id: uuid.UUID | None, engine: AsyncEngine | None = None
) -> AsyncIterator[AsyncSession]:
    """A session whose every transaction is scoped to tenant_id (None = no tenant)."""
    factory = session_factory(engine or get_engine())
    async with factory(info={TENANT_KEY: tenant_id}) as session:
        yield session


def engine_dependency() -> AsyncEngine:
    """FastAPI dependency for the API engine; tests override it."""
    return get_engine()


class UnsafeDatabaseRoleError(RuntimeError):
    pass


async def verify_connection_role(engine: AsyncEngine) -> None:
    """Fail fast if the API's role could bypass row-level security (D-01)."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT current_user AS name, r.rolsuper, r.rolbypassrls,
                           EXISTS (SELECT 1 FROM pg_class c
                                    WHERE c.relowner = r.oid
                                      AND c.relnamespace = 'public'::regnamespace) AS owns_objects,
                           pg_has_role(current_user, 'nexira_owner', 'MEMBER') AS is_owner
                      FROM pg_roles r WHERE r.rolname = current_user
                    """
                )
            )
        ).one()
    problems = [
        label
        for label, bad in (
            ("is a superuser", row.rolsuper),
            ("has BYPASSRLS", row.rolbypassrls),
            ("owns objects in schema public", row.owns_objects),
            ("is or is a member of nexira_owner", row.is_owner),
        )
        if bad
    ]
    if problems:
        raise UnsafeDatabaseRoleError(
            f"Refusing to start: database role {row.name!r} " + ", ".join(problems) + " (D-01)."
        )
