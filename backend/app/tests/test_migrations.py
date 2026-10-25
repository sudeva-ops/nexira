"""Prompt 2 (a): the initial migration reproduces the schema file and downgrades cleanly."""

import asyncio
from pathlib import Path

import asyncpg
import pytest
from alembic import command

from app.tests.conftest import BACKEND_DIR, DbUrls, alembic_config, create_empty_database

REPO_DIR = BACKEND_DIR.parent
SCHEMA_DOC = REPO_DIR / "docs" / "schema" / "nexira_schema.sql"
MIGRATION_SQL = BACKEND_DIR / "migrations" / "sql" / "0001_nexira_schema_v0_2.sql"


def test_migration_sql_is_identical_to_schema_v0_2() -> None:
    """Do not change the schema in place (AGENTS.md): the migration runs the docs file verbatim."""
    assert MIGRATION_SQL.read_bytes() == SCHEMA_DOC.read_bytes()


async def _snapshot(url: str) -> dict[str, set[str]]:
    conn = await asyncpg.connect(url)
    try:
        tables = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        views = await conn.fetch(
            "SELECT viewname FROM pg_views WHERE schemaname = 'public' "
            "AND viewowner = 'nexira_owner'"
        )
        functions = await conn.fetch(
            "SELECT p.proname FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner "
            "WHERE r.rolname = 'nexira_owner'"
        )
        extensions = await conn.fetch("SELECT extname FROM pg_extension")
    finally:
        await conn.close()
    return {
        "tables": {r["tablename"] for r in tables},
        "views": {r["viewname"] for r in views},
        "functions": {r["proname"] for r in functions},
        "extensions": {r["extname"] for r in extensions},
    }


@pytest.fixture(scope="module")
def fresh(server_urls: DbUrls) -> DbUrls:
    return create_empty_database(server_urls, "nexira_test_migrations")


def test_upgrade_downgrade_upgrade(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    before = asyncio.run(_snapshot(admin))

    command.upgrade(cfg, "head")
    upgraded = asyncio.run(_snapshot(admin))
    # The schema's 33 tables, message_template (0002) and alembic_version.
    assert len(upgraded["tables"] - before["tables"]) == 33 + 1 + 1
    assert upgraded["views"] == {"v_incident_people_in_zone", "v_checkin_latest"}
    assert {"audit_log_chain", "audit_verify_chain", "next_reference"} <= upgraded["functions"]

    command.downgrade(cfg, "base")
    downgraded = asyncio.run(_snapshot(admin))
    assert downgraded["tables"] == before["tables"] | {"alembic_version"}
    assert downgraded["views"] == set()
    assert downgraded["functions"] == set()
    # Extensions belong to init.sql (superuser) and survive the downgrade (plan G-27).
    assert downgraded["extensions"] == before["extensions"]

    command.upgrade(cfg, "head")
    assert asyncio.run(_snapshot(admin)) == upgraded


async def test_api_cannot_touch_alembic_version(db: DbUrls) -> None:
    conn = await asyncpg.connect(db.api_plain)
    try:
        privileges = await conn.fetchrow(
            "SELECT has_table_privilege('alembic_version', 'SELECT') AS s, "
            "has_table_privilege('alembic_version', 'UPDATE') AS u, "
            "has_table_privilege('alembic_version', 'DELETE') AS d"
        )
    finally:
        await conn.close()
    assert privileges is not None
    assert not any(privileges.values())


def test_migration_file_reads_the_copied_sql() -> None:
    source = (BACKEND_DIR / "migrations" / "versions" / "0001_initial_schema_v0_2.py").read_text()
    assert Path(MIGRATION_SQL).name in source


async def _campaign_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        columns = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'notification_campaign' ORDER BY column_name"
        )
        checks = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conrelid = 'notification_campaign'::regclass AND contype = 'c' ORDER BY conname"
        )
        triggers = await conn.fetch(
            "SELECT tgname FROM pg_trigger "
            "WHERE tgrelid = 'notification_campaign'::regclass AND NOT tgisinternal"
        )
        template = await conn.fetchval("SELECT to_regclass('message_template') IS NOT NULL")
        can_delete = await conn.fetchval(
            "SELECT has_table_privilege('nexira_app', 'notification_campaign', 'DELETE')"
        )
    finally:
        await conn.close()
    return {
        "columns": [r["column_name"] for r in columns],
        "checks": [(r["conname"], r["def"]) for r in checks],
        "triggers": [r["tgname"] for r in triggers],
        "message_template": template,
        "api_can_delete": can_delete,  # revoked by PC-10, restored by the downgrade
    }


def test_downgrading_0002_restores_0001_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0001")
    at_0001 = asyncio.run(_campaign_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_campaign_shape(admin))
    command.downgrade(cfg, "0001")
    assert asyncio.run(_campaign_shape(admin)) == at_0001
    assert at_head["message_template"] is True
    assert at_0001["api_can_delete"] is True
    assert at_head["api_can_delete"] is False
    assert "notification_campaign_approval_guard" in str(at_head["triggers"])
    command.upgrade(cfg, "head")
