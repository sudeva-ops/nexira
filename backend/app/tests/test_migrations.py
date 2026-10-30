"""Prompt 2 (a): the initial migration reproduces the schema file and downgrades cleanly."""

import asyncio
from pathlib import Path
from typing import cast

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
    # The schema's 33 tables, message_template (0002), trip_segment and country_risk
    # (0003), airport, flight and flight_event (0004), weather_current (0005), partner and
    # partner_request (0006), and alembic_version.
    assert len(upgraded["tables"] - before["tables"]) == 33 + 1 + 2 + 3 + 1 + 2 + 1
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


async def _trip_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        columns = await conn.fetch(
            "SELECT column_name, column_default FROM information_schema.columns "
            "WHERE table_name = 'trip' ORDER BY column_name"
        )
        checks = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conrelid = 'trip'::regclass AND contype = 'c' ORDER BY conname"
        )
        triggers = await conn.fetch(
            "SELECT tgrelid::regclass::text AS t, tgname FROM pg_trigger WHERE NOT tgisinternal "
            "AND tgrelid IN ('trip'::regclass, 'trip_traveller'::regclass) ORDER BY 1, 2"
        )
        tables = await conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relname IN ('trip_segment', 'country_risk')"
        )
        can_delete = await conn.fetchval(
            "SELECT has_table_privilege('nexira_app', 'trip', 'DELETE')"
        )
        security = await conn.fetch(
            "SELECT relname, relrowsecurity, relforcerowsecurity, relacl::text AS acl "
            "FROM pg_class "
            "WHERE relname IN ('trip', 'trip_traveller') ORDER BY relname"
        )
        policies = await conn.fetch(
            "SELECT tablename, policyname, qual, with_check FROM pg_policies "
            "WHERE tablename IN ('trip', 'trip_traveller') ORDER BY 1, 2"
        )
    finally:
        await conn.close()
    return {
        "columns": [(r["column_name"], r["column_default"]) for r in columns],
        "checks": [(r["conname"], r["def"]) for r in checks],
        "triggers": [(r["t"], r["tgname"]) for r in triggers],
        "new_tables": tables,
        "api_can_delete": can_delete,
        "security": [tuple(r) for r in security],
        "policies": [tuple(r) for r in policies],
    }


def test_downgrading_0003_restores_0002_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0002")
    at_0002 = asyncio.run(_trip_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_trip_shape(admin))
    command.downgrade(cfg, "0002")
    assert asyncio.run(_trip_shape(admin)) == at_0002
    assert (at_head["new_tables"], at_head["api_can_delete"]) == (2, False)
    triggers = at_head["triggers"]
    assert isinstance(triggers, list)
    assert ("trip", "trip_guard") in triggers
    command.upgrade(cfg, "head")


async def _air_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        columns = await conn.fetch(
            "SELECT table_name, column_name, column_default FROM information_schema.columns "
            "WHERE table_name IN ('trip', 'trip_segment') ORDER BY 1, 2"
        )
        constraints = await conn.fetch(
            "SELECT conrelid::regclass::text AS t, conname, pg_get_constraintdef(oid) AS def "
            "FROM pg_constraint WHERE conrelid IN ('trip'::regclass, 'trip_segment'::regclass) "
            "ORDER BY 1, 2"
        )
        triggers = await conn.fetch(
            "SELECT tgrelid::regclass::text AS t, tgname FROM pg_trigger WHERE NOT tgisinternal "
            "AND tgrelid IN ('trip'::regclass, 'trip_segment'::regclass) ORDER BY 1, 2"
        )
        tables = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname IN ('airport', 'flight', 'flight_event') ORDER BY 1"
        )
        functions = await conn.fetch(
            "SELECT proname FROM pg_proc WHERE proname IN "
            "('flight_guard', 'flight_event_guard', 'trip_restricted_guard') ORDER BY 1"
        )
    finally:
        await conn.close()
    return {
        "columns": [tuple(r) for r in columns],
        "constraints": [tuple(r) for r in constraints],
        "triggers": [tuple(r) for r in triggers],
        "tables": [tuple(r) for r in tables],
        "functions": [r["proname"] for r in functions],
    }


def test_downgrading_0004_restores_0003_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0003")
    at_0003 = asyncio.run(_air_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_air_shape(admin))
    command.downgrade(cfg, "0003")
    assert asyncio.run(_air_shape(admin)) == at_0003
    assert at_0003["tables"] == []
    tables = at_head["tables"]
    assert isinstance(tables, list)
    assert [(t[0], t[1]) for t in tables] == [  # FORCE RLS on each
        ("airport", True),
        ("flight", True),
        ("flight_event", True),
    ]
    assert at_head["functions"] == ["flight_event_guard", "flight_guard", "trip_restricted_guard"]
    command.upgrade(cfg, "head")


async def _weather_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        table = await conn.fetchrow(
            "SELECT relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname = 'weather_current'"
        )
        functions = await conn.fetchval(
            "SELECT count(*) FROM pg_proc WHERE proname = 'weather_current_guard'"
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename = 'weather_current'"
        )
        mission = await conn.fetch(
            "SELECT conname FROM pg_constraint WHERE confrelid = 'mission'::regclass ORDER BY 1"
        )
    finally:
        await conn.close()
    return {
        "table": tuple(table) if table else None,
        "functions": functions,
        "policies": policies,
        "mission_fks": [r["conname"] for r in mission],
    }


def test_downgrading_0005_restores_0004_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0004")
    at_0004 = asyncio.run(_weather_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_weather_shape(admin))
    command.downgrade(cfg, "0004")
    assert asyncio.run(_weather_shape(admin)) == at_0004
    assert at_0004["table"] is None
    table = at_head["table"]
    assert isinstance(table, tuple)
    assert table[0] is True  # FORCE RLS
    # The app reads, inserts and updates; nothing more (no DELETE, TRUNCATE, REFERENCES).
    assert table[1] == (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=arw/nexira_owner}"
    )
    assert "weather_current_mission_id_fkey" in cast(list[str], at_head["mission_fks"])
    assert (at_head["functions"], at_head["policies"]) == (1, 1)
    command.upgrade(cfg, "head")


async def _partner_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        tables = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname IN ('partner', 'partner_request') ORDER BY relname"
        )
        functions = await conn.fetchval(
            "SELECT count(*) FROM pg_proc WHERE proname = 'partner_request_guard'"
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename IN ('partner', 'partner_request')"
        )
        columns = await conn.fetch(
            "SELECT a.attname, a.attacl::text AS acl FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid WHERE c.relname = 'partner_request' "
            "AND a.attacl IS NOT NULL ORDER BY a.attname"
        )
    finally:
        await conn.close()
    return {
        "tables": [tuple(t) for t in tables],
        "functions": functions,
        "policies": policies,
        "columns": [tuple(c) for c in columns],
    }


def test_downgrading_0006_restores_0005_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0005")
    at_0005 = asyncio.run(_partner_shape(admin))
    at_0005_weather = asyncio.run(_weather_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_partner_shape(admin))
    command.downgrade(cfg, "0005")
    assert asyncio.run(_partner_shape(admin)) == at_0005
    assert asyncio.run(_weather_shape(admin)) == at_0005_weather
    assert at_0005["tables"] == []
    # The app reads and seeds partners only; requests are read and made, and only their
    # status and ETA move; never deleted; nothing else (no TRUNCATE, REFERENCES or TRIGGER).
    assert at_head["tables"] == [
        (
            "partner",
            True,
            "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
            "nexira_app=ar/nexira_owner}",
        ),
        (
            "partner_request",
            True,
            "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
            "nexira_app=ar/nexira_owner}",
        ),
    ]
    # UPDATE only of status and ETA (review of Prompt 44, M3).
    assert at_head["columns"] == [
        ("eta", "{nexira_app=w/nexira_owner}"),
        ("status", "{nexira_app=w/nexira_owner}"),
    ]
    assert (at_head["functions"], at_head["policies"]) == (1, 2)
    command.upgrade(cfg, "head")
