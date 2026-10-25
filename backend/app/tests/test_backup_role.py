"""The backup role (infra/postgres/backup-role.sql and backup-grants.sql, Prompt 16):
it reads every tenant's NEXIRA rows for pg_dump and can change nothing. The role is
created by the cluster bootstrap; the test databases get the same grants as init.sql.
Checked from the catalogue as the superuser, and by acting as the role."""

import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant


@pytest.fixture
async def admin(db: DbUrls) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(db.plain(db.admin))
    yield conn
    await conn.close()


async def test_the_backup_role_has_no_more_than_it_needs(admin: asyncpg.Connection) -> None:
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
    member_of = await admin.fetch(
        "SELECT r.rolname FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
        "WHERE m.member = 'nexira_backup'::regrole"
    )
    assert member_of == []  # not pg_read_all_data, nexira_app or nexira_owner
    # pg_read_all_data would expose every role's password hash (pg_authid).
    assert not await admin.fetchval(
        "SELECT has_table_privilege('nexira_backup', 'pg_authid', 'SELECT')"
    )
    writable = await admin.fetch(
        """
        SELECT c.relname FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'S')
           AND (has_table_privilege('nexira_backup', c.oid, 'INSERT')
             OR has_table_privilege('nexira_backup', c.oid, 'UPDATE')
             OR has_table_privilege('nexira_backup', c.oid, 'DELETE')
             OR has_table_privilege('nexira_backup', c.oid, 'TRUNCATE'))
        """
    )
    assert writable == []
    unreadable = await admin.fetch(
        "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace "
        "AND c.relkind IN ('r', 'p', 'S') "
        "AND NOT has_table_privilege('nexira_backup', c.oid, 'SELECT')"
    )
    assert unreadable == []  # every table and sequence, including alembic_version
    create = "SELECT has_schema_privilege('nexira_backup', 'public', 'CREATE')"
    assert not await admin.fetchval(create)


async def test_acting_as_the_backup_role_reads_all_tenants_and_writes_nothing(
    db: DbUrls, admin: asyncpg.Connection
) -> None:
    a = await create_tenant(db, "Backup A")
    b = await create_tenant(db, "Backup B")
    async with admin.transaction():
        await admin.execute("SET LOCAL ROLE nexira_backup")
        seen = {r["id"] for r in await admin.fetch("SELECT id FROM tenant")}
        assert {a, b} <= seen  # BYPASSRLS: no tenant setting needed
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await admin.execute(
                "INSERT INTO tenant (id, name, oidc_issuer) VALUES ($1, 'x', 'https://x')",
                uuid.uuid4(),
            )


async def test_tables_created_later_by_the_owner_are_readable_too(
    db: DbUrls, admin: asyncpg.Connection
) -> None:
    owner = await asyncpg.connect(db.owner_plain)
    try:
        await owner.execute("CREATE TABLE backup_grant_probe (id int)")
        assert await admin.fetchval(
            "SELECT has_table_privilege('nexira_backup', 'backup_grant_probe', 'SELECT')"
        )
        assert not await admin.fetchval(
            "SELECT has_table_privilege('nexira_backup', 'backup_grant_probe', 'INSERT')"
        )
    finally:
        await owner.execute("DROP TABLE IF EXISTS backup_grant_probe")
        await owner.close()
