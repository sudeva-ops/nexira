"""The backup role (infra/postgres/backup-role.sql, Prompt 16): it can read every
tenant's rows for pg_dump and can change nothing. Checked from the catalogue, as
the superuser, because the role is created by the cluster bootstrap."""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.tests.conftest import DbUrls


@pytest.fixture
async def admin(db: DbUrls) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(db.plain(db.admin))
    yield conn
    await conn.close()


async def test_the_backup_role_reads_everything_and_nothing_more(
    admin: asyncpg.Connection,
) -> None:
    role = await admin.fetchrow(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolcanlogin "
        "FROM pg_roles WHERE rolname = 'nexira_backup'"
    )
    assert role is not None, "nexira_backup is missing: see infra/postgres/backup-role.sql"
    assert dict(role) == {
        "rolsuper": False,
        "rolbypassrls": True,  # a whole-database dump under FORCE RLS
        "rolcreaterole": False,
        "rolcreatedb": False,
        "rolcanlogin": True,
    }
    assert await admin.fetchval("SELECT pg_has_role('nexira_backup', 'pg_read_all_data', 'MEMBER')")
    assert not await admin.fetchval("SELECT pg_has_role('nexira_backup', 'nexira_app', 'MEMBER')")
    assert not await admin.fetchval("SELECT pg_has_role('nexira_backup', 'nexira_owner', 'MEMBER')")
    writable = await admin.fetch(
        """
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
           AND (has_table_privilege('nexira_backup', c.oid, 'INSERT')
             OR has_table_privilege('nexira_backup', c.oid, 'UPDATE')
             OR has_table_privilege('nexira_backup', c.oid, 'DELETE')
             OR has_table_privilege('nexira_backup', c.oid, 'TRUNCATE'))
        """
    )
    assert writable == []
    readable = await admin.fetchval(
        "SELECT bool_and(has_table_privilege('nexira_backup', c.oid, 'SELECT')) FROM pg_class c "
        "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')"
    )
    assert readable
    assert not await admin.fetchval(
        "SELECT has_schema_privilege('nexira_backup', 'public', 'CREATE')"
    )
