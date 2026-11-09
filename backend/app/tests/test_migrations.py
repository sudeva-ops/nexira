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
    # partner_request (0006), travel_document (0007), mission_climate_risk (0008), the four
    # health tables (0009), the three evacuation tables (0010), the two fleet tables (0011),
    # the four VIP tables (0012), the five Site Twin tables (0013), the three supply tables
    # (0014), the two predictive tables (0015), the two review tables (0016), and
    # alembic_version.
    assert (
        len(upgraded["tables"] - before["tables"])
        == 33 + 1 + 2 + 3 + 1 + 2 + 1 + 1 + 4 + 3 + 2 + 4 + 5 + 3 + 2 + 2 + 1
    )
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


async def _document_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        tables = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname = 'travel_document'"
        )
        functions = await conn.fetchval(
            "SELECT count(*) FROM pg_proc WHERE proname = 'travel_document_guard'"
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename = 'travel_document'"
        )
        columns = await conn.fetch(
            "SELECT a.attname, a.attacl::text AS acl FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid WHERE c.relname = 'travel_document' "
            "AND a.attacl IS NOT NULL ORDER BY a.attname"
        )
        search_path = await conn.fetchval(
            "SELECT proconfig::text FROM pg_proc WHERE proname = 'travel_document_guard'"
        )
        # Everything in public, so a leftover of 0007 shows (review of Prompt 49, L4).
        public = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "        WHERE n.nspname = 'public') AS relations, "
            "       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "        WHERE n.nspname = 'public') AS functions, "
            "       (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers, "
            "       (SELECT count(*) FROM pg_policy) AS policies"
        )
    finally:
        await conn.close()
    return {
        "tables": [tuple(t) for t in tables],
        "functions": functions,
        "policies": policies,
        "columns": [tuple(c) for c in columns],
        "search_path": search_path,
        "public": tuple(public or ()),
    }


def test_downgrading_0007_restores_0006_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0006")
    at_0006 = asyncio.run(_document_shape(admin))
    at_0006_partners = asyncio.run(_partner_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_document_shape(admin))
    command.downgrade(cfg, "0006")
    assert asyncio.run(_document_shape(admin)) == at_0006
    assert asyncio.run(_partner_shape(admin)) == at_0006_partners
    assert at_0006["tables"] == []
    # The app reads and adds documents and moves their renewal; never deletes them; nothing
    # else (no TRUNCATE, REFERENCES or TRIGGER). The backup role reads it.
    assert at_head["tables"] == [
        (
            "travel_document",
            True,
            "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
            "nexira_app=ar/nexira_owner}",
        ),
    ]
    # UPDATE only of the renewal: status, new date and who did each step (plan G-1).
    assert at_head["columns"] == [
        (column, "{nexira_app=w/nexira_owner}")
        for column in (
            "renewal_requested_by",
            "renewal_started_by",
            "renewal_status",
            "renewed_by",
            "valid_until",
        )
    ]
    assert (at_head["functions"], at_head["policies"]) == (1, 1)
    assert at_head["search_path"] == '{"search_path=pg_catalog, public, pg_temp"}'
    command.upgrade(cfg, "head")


async def _hazard_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        run_columns = await conn.fetch(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'playbook_run' ORDER BY column_name"
        )
        run_checks = await conn.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conrelid = 'playbook_run'::regclass ORDER BY conname"
        )
        run_indexes = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'playbook_run' "
            "ORDER BY indexname"
        )
        run_acl = await conn.fetchval(
            "SELECT relacl::text FROM pg_class WHERE relname = 'playbook_run'"
        )
        climate = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname = 'mission_climate_risk'"
        )
        search_paths = await conn.fetch(
            "SELECT proname, proconfig::text AS config FROM pg_proc "
            "WHERE proname IN ('playbook_run_guard', 'mission_climate_risk_guard') ORDER BY proname"
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename = 'mission_climate_risk'"
        )
        # Everything in public, so a leftover of 0008 shows (review of Prompt 49, L4).
        public = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "        WHERE n.nspname = 'public') AS relations, "
            "       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "        WHERE n.nspname = 'public') AS functions, "
            "       (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers, "
            "       (SELECT count(*) FROM pg_policy) AS policies"
        )
    finally:
        await conn.close()
    return {
        "run_columns": [tuple(c) for c in run_columns],
        "run_checks": [tuple(c) for c in run_checks],
        "run_indexes": [tuple(i) for i in run_indexes],
        "status_check": next(
            r["def"] for r in run_checks if r["conname"] == "playbook_run_status_check"
        ),
        "live_index": next(
            r["indexdef"] for r in run_indexes if r["indexname"] == "playbook_run_live_uq"
        ),
        "run_acl": run_acl,
        "climate": [tuple(t) for t in climate],
        "search_paths": [tuple(f) for f in search_paths],
        "policies": policies,
        "public": tuple(public or ()),
    }


def test_downgrading_0008_restores_0007_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0007")
    at_0007 = asyncio.run(_hazard_shape(admin))
    at_0007_documents = asyncio.run(_document_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_hazard_shape(admin))
    command.downgrade(cfg, "0007")
    assert asyncio.run(_hazard_shape(admin)) == at_0007
    assert asyncio.run(_document_shape(admin)) == at_0007_documents
    assert at_0007["climate"] == []
    # PC-24: grants on playbook_run unchanged; the armed statuses and G-8's live index.
    assert at_head["run_acl"] == at_0007["run_acl"]
    assert ("scheduled_for", "timestamp with time zone", "YES", None) in cast(
        list[tuple[object, ...]], at_head["run_columns"]
    )
    assert "'SCHEDULED'" in str(at_head["status_check"])
    assert "'SCHEDULED'" in str(at_head["live_index"])
    assert "'SCHEDULED'" not in str(at_0007["live_index"])
    # PC-25: read and added by the app, never changed or deleted; the backup role reads it.
    assert at_head["climate"] == [
        (
            "mission_climate_risk",
            True,
            "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
            "nexira_app=ar/nexira_owner}",
        ),
    ]
    assert at_head["policies"] == 1
    assert at_head["search_paths"] == [
        ("mission_climate_risk_guard", '{"search_path=pg_catalog, public, pg_temp"}'),
        ("playbook_run_guard", '{"search_path=pg_catalog, public, pg_temp"}'),
    ]
    command.upgrade(cfg, "head")


def test_downgrading_0008_refuses_while_a_run_is_armed(fresh: DbUrls) -> None:
    """SCHEDULED and DISARMED do not exist in 0007: the downgrade fails, nothing is rewritten."""
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.upgrade(cfg, "head")

    async def arm() -> None:
        conn = await asyncpg.connect(admin)
        try:
            tenant = await conn.fetchval(
                "INSERT INTO tenant (name, oidc_issuer) VALUES ('Armed', 'https://idp.test/armed') "
                "RETURNING id"
            )
            playbook = await conn.fetchval(
                "INSERT INTO playbook (tenant_id, code, name, category) "
                "VALUES ($1, 'PB-06', 'Severe weather', 'WEATHER') RETURNING id",
                tenant,
            )
            await conn.execute(
                "INSERT INTO playbook_run (tenant_id, playbook_id, status, scheduled_for) "
                "VALUES ($1, $2, 'SCHEDULED', now() + interval '1 day')",
                tenant,
                playbook,
            )
        finally:
            await conn.close()

    async def clean() -> None:
        conn = await asyncpg.connect(admin)
        try:
            # The guard keeps armed runs, so the superuser skips triggers to clean up.
            await conn.execute("SET session_replication_role = replica")
            await conn.execute("DELETE FROM playbook_run")
            await conn.execute("DELETE FROM playbook")
            await conn.execute("DELETE FROM tenant WHERE name = 'Armed'")
        finally:
            await conn.close()

    # One transaction per migration (migrations/env.py): step down to 0008 first, so the
    # refused step is the only one taken.
    command.downgrade(cfg, "0008")
    at_0008 = asyncio.run(_hazard_shape(admin))
    asyncio.run(arm())
    try:
        with pytest.raises(Exception, match="playbook_run_status_check"):
            command.downgrade(cfg, "0007")
        assert asyncio.run(_hazard_shape(admin)) == at_0008  # rolled back, nothing dropped
    finally:
        asyncio.run(clean())
    command.downgrade(cfg, "0007")
    command.upgrade(cfg, "head")


HEALTH_TABLES = (
    "country_health_requirement",
    "health_advisory",
    "medical_facility",
    "mission_health_readiness",
)


async def _health_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        tables = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname = ANY($1::text[]) AND relkind = 'r' ORDER BY relname",
            list(HEALTH_TABLES),
        )
        columns = await conn.fetch(
            "SELECT column_name, privilege_type FROM information_schema.column_privileges "
            "WHERE table_name = 'health_advisory' AND grantee = 'nexira_app' "
            "AND privilege_type = 'UPDATE' ORDER BY column_name"
        )
        search_paths = await conn.fetch(
            "SELECT proname, proconfig::text AS config FROM pg_proc "
            "WHERE proname LIKE '%health%guard' OR proname = 'medical_facility_guard' "
            "ORDER BY proname"
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename = ANY($1::text[])",
            list(HEALTH_TABLES),
        )
        # Everything in public, so a leftover of 0009 shows (review of Prompt 49, L4).
        public = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "        WHERE n.nspname = 'public') AS relations, "
            "       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "        WHERE n.nspname = 'public') AS functions, "
            "       (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers, "
            "       (SELECT count(*) FROM pg_policy) AS policies"
        )
    finally:
        await conn.close()
    return {
        "tables": [tuple(t) for t in tables],
        "columns": [c["column_name"] for c in columns],
        "search_paths": [tuple(f) for f in search_paths],
        "policies": policies,
        "public": tuple(public or ()),
    }


def test_downgrading_0009_restores_0008_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0008")
    at_0008 = asyncio.run(_health_shape(admin))
    at_0008_hazards = asyncio.run(_hazard_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_health_shape(admin))
    command.downgrade(cfg, "0008")
    assert asyncio.run(_health_shape(admin)) == at_0008
    assert asyncio.run(_hazard_shape(admin)) == at_0008_hazards
    assert at_0008["tables"] == []
    # PC-26..29: FORCE RLS; read and added by the app; the backup role reads them.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in HEALTH_TABLES]
    # PC-26: a newer bulletin moves only these columns.
    assert at_head["columns"] == ["guidance", "level", "status", "updated_at"]
    assert at_head["policies"] == 4
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in (
            "health_advisory_guard",
            "medical_facility_guard",
            "mission_health_readiness_guard",
        )
    ]
    command.upgrade(cfg, "head")


EVACUATION_TABLES = ("evacuation", "evacuation_manifest", "evacuation_plan")


async def _evacuation_shape(admin_url: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        tables = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname = ANY($1::text[]) AND relkind = 'r' ORDER BY relname",
            list(EVACUATION_TABLES),
        )
        columns = await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.column_privileges "
            "WHERE table_name = ANY($1::text[]) AND grantee = 'nexira_app' "
            "AND privilege_type = 'UPDATE' ORDER BY table_name, column_name",
            list(EVACUATION_TABLES),
        )
        search_paths = await conn.fetch(
            "SELECT proname, proconfig::text AS config FROM pg_proc "
            "WHERE proname LIKE 'evacuation%guard' ORDER BY proname"
        )
        live = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'evacuation_live_uq'"
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename = ANY($1::text[])",
            list(EVACUATION_TABLES),
        )
        # Everything in public, so a leftover of 0010 shows (review of Prompt 49, L4).
        public = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "        WHERE n.nspname = 'public') AS relations, "
            "       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "        WHERE n.nspname = 'public') AS functions, "
            "       (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers, "
            "       (SELECT count(*) FROM pg_policy) AS policies"
        )
    finally:
        await conn.close()
    return {
        "tables": [tuple(t) for t in tables],
        "columns": [tuple(c) for c in columns],
        "search_paths": [tuple(f) for f in search_paths],
        "live": live,
        "policies": policies,
        "public": tuple(public or ()),
    }


def test_downgrading_0010_restores_0009_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0009")
    at_0009 = asyncio.run(_evacuation_shape(admin))
    at_0009_health = asyncio.run(_health_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_evacuation_shape(admin))
    command.downgrade(cfg, "0009")
    assert asyncio.run(_evacuation_shape(admin)) == at_0009
    assert asyncio.run(_health_shape(admin)) == at_0009_health
    assert at_0009["tables"] == []
    # PC-30..32: FORCE RLS; read and added by the app; the backup role reads them. The app
    # updates evacuations and manifests through column grants only.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in EVACUATION_TABLES]
    assert at_head["columns"] == [
        ("evacuation", "activated_by"),
        ("evacuation", "status"),
        ("evacuation", "step"),
        ("evacuation", "stood_down_by"),
        ("evacuation", "stood_down_reason"),
        ("evacuation_manifest", "checked_in_by"),
        ("evacuation_manifest", "checked_in_by_type"),
        ("evacuation_manifest", "seat"),
        ("evacuation_manifest", "status"),
    ]
    assert at_head["live"] == (
        "CREATE UNIQUE INDEX evacuation_live_uq ON public.evacuation USING btree "
        "(tenant_id, mission_id) WHERE (status = ANY (ARRAY['PENDING_ACTIVATION'::text, "
        "'ACTIVE'::text]))"
    )
    assert at_head["policies"] == 3
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in ("evacuation_guard", "evacuation_manifest_guard", "evacuation_plan_guard")
    ]
    command.upgrade(cfg, "head")


FLEET_TABLES = ("fleet_asset", "fleet_maintenance")


async def _fleet_shape(admin_url: str) -> dict[str, object]:
    return await _shape(admin_url, FLEET_TABLES, "fleet%guard")


async def _shape(admin_url: str, names: tuple[str, ...], guards: str) -> dict[str, object]:
    conn = await asyncpg.connect(admin_url)
    try:
        tables = await conn.fetch(
            "SELECT relname, relforcerowsecurity, relacl::text AS acl FROM pg_class "
            "WHERE relname = ANY($1::text[]) AND relkind = 'r' ORDER BY relname",
            list(names),
        )
        columns = await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.column_privileges "
            "WHERE table_name = ANY($1::text[]) AND grantee = 'nexira_app' "
            "AND privilege_type = 'UPDATE' ORDER BY table_name, column_name",
            list(names),
        )
        search_paths = await conn.fetch(
            "SELECT proname, proconfig::text AS config FROM pg_proc "
            "WHERE proname LIKE $1 ORDER BY proname",
            guards,
        )
        policies = await conn.fetchval(
            "SELECT count(*) FROM pg_policies WHERE tablename = ANY($1::text[])",
            list(names),
        )
        # Everything in public, so a leftover shows (review of Prompt 49, L4).
        public = await conn.fetchrow(
            "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "        WHERE n.nspname = 'public') AS relations, "
            "       (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "        WHERE n.nspname = 'public') AS functions, "
            "       (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers, "
            "       (SELECT count(*) FROM pg_policy) AS policies"
        )
    finally:
        await conn.close()
    return {
        "tables": [tuple(t) for t in tables],
        "columns": [tuple(c) for c in columns],
        "search_paths": [tuple(f) for f in search_paths],
        "policies": policies,
        "public": tuple(public or ()),
    }


def test_downgrading_0011_restores_0010_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0010")
    at_0010 = asyncio.run(_fleet_shape(admin))
    at_0010_evacuation = asyncio.run(_evacuation_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_fleet_shape(admin))
    command.downgrade(cfg, "0010")
    assert asyncio.run(_fleet_shape(admin)) == at_0010
    assert asyncio.run(_evacuation_shape(admin)) == at_0010_evacuation
    assert at_0010["tables"] == []
    # PC-33..34: FORCE RLS; read and added by the app; the backup role reads them. The app
    # updates them through column grants only.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in FLEET_TABLES]
    assert at_head["columns"] == [
        ("fleet_asset", "fuel_pct"),
        ("fleet_asset", "location"),
        ("fleet_asset", "location_label"),
        ("fleet_asset", "position_at"),
        ("fleet_asset", "status"),
        ("fleet_asset", "status_reason"),
        ("fleet_maintenance", "done_by"),
        ("fleet_maintenance", "done_by_type"),
    ]
    assert at_head["policies"] == 2
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in ("fleet_asset_guard", "fleet_maintenance_guard")
    ]
    command.upgrade(cfg, "head")


VIP_TABLES = ("vip_checklist_item", "vip_segment", "vip_segment_change", "vip_visit")


def test_downgrading_0012_restores_0011_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0011")
    at_0011 = asyncio.run(_shape(admin, VIP_TABLES, "vip%guard"))
    at_0011_fleet = asyncio.run(_fleet_shape(admin))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_shape(admin, VIP_TABLES, "vip%guard"))
    command.downgrade(cfg, "0011")
    assert asyncio.run(_shape(admin, VIP_TABLES, "vip%guard")) == at_0011
    assert asyncio.run(_fleet_shape(admin)) == at_0011_fleet
    assert at_0011["tables"] == []
    # PC-35..38: FORCE RLS; read and added by the app; the backup role reads them. The app
    # updates them through column grants only.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in VIP_TABLES]
    assert at_head["columns"] == [
        ("vip_checklist_item", "done_by"),
        ("vip_segment", "ends_at"),
        ("vip_segment", "starts_at"),
        ("vip_segment", "status"),
        ("vip_segment", "virtual"),
        ("vip_segment_change", "decided_by"),
        ("vip_segment_change", "decision_note"),
        ("vip_segment_change", "status"),
        ("vip_visit", "cancel_reason"),
        ("vip_visit", "cancelled_by"),
        ("vip_visit", "started_by"),
        ("vip_visit", "status"),
    ]
    assert at_head["policies"] == 4
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in (
            "vip_checklist_item_guard",
            "vip_segment_change_guard",
            "vip_segment_guard",
            "vip_visit_guard",
        )
    ]
    command.upgrade(cfg, "head")


TWIN_TABLES = ("site_presence", "site_readiness_item", "site_route", "site_sensor", "site_zone")


def test_downgrading_0013_restores_0012_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0012")
    at_0012 = asyncio.run(_shape(admin, TWIN_TABLES, "site%guard"))
    at_0012_vip = asyncio.run(_shape(admin, VIP_TABLES, "vip%guard"))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_shape(admin, TWIN_TABLES, "site%guard"))
    command.downgrade(cfg, "0012")
    assert asyncio.run(_shape(admin, TWIN_TABLES, "site%guard")) == at_0012
    assert asyncio.run(_shape(admin, VIP_TABLES, "vip%guard")) == at_0012_vip
    assert at_0012["tables"] == []
    # PC-39..42: FORCE RLS; read and added by the app; the backup role reads them. Presence is
    # also deleted (a departure); the rest changes through column grants only.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    presence = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ard/nexira_owner}"
    )
    assert at_head["tables"] == [
        (table, True, presence if table == "site_presence" else seeded) for table in TWIN_TABLES
    ]
    assert at_head["columns"] == [
        ("site_presence", "zone_id"),
        ("site_readiness_item", "done_by"),
        ("site_sensor", "detail"),
        ("site_sensor", "status"),
    ]
    assert at_head["policies"] == 5
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in (
            "site_presence_guard",
            "site_readiness_item_guard",
            "site_route_guard",
            "site_sensor_guard",
            "site_zone_guard",
        )
    ]
    command.upgrade(cfg, "head")


SUPPLY_TABLES = ("logistics_route", "supplier", "supply_mitigation")


def test_downgrading_0014_restores_0013_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0013")
    at_0013 = asyncio.run(_shape(admin, SUPPLY_TABLES, "supply%guard"))
    at_0013_twin = asyncio.run(_shape(admin, TWIN_TABLES, "site%guard"))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_shape(admin, SUPPLY_TABLES, "supply%guard"))
    command.downgrade(cfg, "0013")
    assert asyncio.run(_shape(admin, SUPPLY_TABLES, "supply%guard")) == at_0013
    assert asyncio.run(_shape(admin, TWIN_TABLES, "site%guard")) == at_0013_twin
    assert at_0013["tables"] == []
    # PC-43..45: FORCE RLS; read and added by the app; the backup role reads them. Nothing is
    # deleted; the app changes them through column grants only.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in SUPPLY_TABLES]
    assert at_head["columns"] == [
        ("logistics_route", "detail"),
        ("logistics_route", "status"),
        ("supplier", "status"),
        ("supplier", "status_detail"),
        ("supply_mitigation", "stood_down_by"),
    ]
    assert at_head["policies"] == 3
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in ("supply_mitigation_guard", "supply_route_guard", "supply_supplier_guard")
    ]
    command.upgrade(cfg, "head")


PREDICTIVE_TABLES = ("mission_event", "risk_index")


def test_downgrading_0015_restores_0014_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0014")
    at_0014 = asyncio.run(_shape(admin, PREDICTIVE_TABLES, "predictive%guard"))
    at_0014_supply = asyncio.run(_shape(admin, SUPPLY_TABLES, "supply%guard"))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_shape(admin, PREDICTIVE_TABLES, "predictive%guard"))
    command.downgrade(cfg, "0014")
    assert asyncio.run(_shape(admin, PREDICTIVE_TABLES, "predictive%guard")) == at_0014
    assert asyncio.run(_shape(admin, SUPPLY_TABLES, "supply%guard")) == at_0014_supply
    assert at_0014["tables"] == []
    # PC-46, PC-47: FORCE RLS; read and added by the app; the backup role reads them. Nothing is
    # deleted; only today's index row changes, through a column grant.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in PREDICTIVE_TABLES]
    assert at_head["columns"] == [("risk_index", "components"), ("risk_index", "value")]
    assert at_head["policies"] == 2
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in ("predictive_mission_event_guard", "predictive_risk_index_guard")
    ]
    command.upgrade(cfg, "head")


AAR_TABLES = ("aar_item", "after_action_review")


def test_downgrading_0016_restores_0015_exactly(fresh: DbUrls) -> None:
    cfg = alembic_config(fresh.owner)
    admin = DbUrls.plain(fresh.admin)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0015")
    at_0015 = asyncio.run(_shape(admin, AAR_TABLES, "aar%guard"))
    at_0015_predictive = asyncio.run(_shape(admin, PREDICTIVE_TABLES, "predictive%guard"))
    command.upgrade(cfg, "head")
    at_head = asyncio.run(_shape(admin, AAR_TABLES, "aar%guard"))
    command.downgrade(cfg, "0015")
    assert asyncio.run(_shape(admin, AAR_TABLES, "aar%guard")) == at_0015
    assert asyncio.run(_shape(admin, PREDICTIVE_TABLES, "predictive%guard")) == at_0015_predictive
    assert at_0015["tables"] == []
    # PC-49, PC-50: FORCE RLS; read and added by the app; the backup role reads them. Nothing is
    # deleted; a review is finalised and an item decided through column grants.
    seeded = (
        "{nexira_owner=arwdDxt/nexira_owner,nexira_backup=r/nexira_owner,"
        "nexira_app=ar/nexira_owner}"
    )
    assert at_head["tables"] == [(table, True, seeded) for table in AAR_TABLES]
    assert at_head["columns"] == [
        ("aar_item", column)
        for column in (
            "action",
            "decided_by",
            "done_by",
            "due_on",
            "finding",
            "owner_team",
            "priority",
            "reason",
            "status",
        )
    ] + [("after_action_review", column) for column in ("finalised_by", "metrics", "status")]
    assert at_head["policies"] == 2
    assert at_head["search_paths"] == [
        (name, '{"search_path=pg_catalog, public, pg_temp"}')
        for name in ("aar_item_guard", "aar_no_truncate_guard", "aar_review_guard")
    ]
    command.upgrade(cfg, "head")
