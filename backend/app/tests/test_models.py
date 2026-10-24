"""The SQLAlchemy models mirror the migrated schema (tables, columns, nullability, keys)."""

import asyncpg
import pytest

from app.models import Base
from app.tests.conftest import DbUrls


@pytest.fixture
async def catalogue(db: DbUrls) -> dict[str, dict[str, bool]]:
    conn = await asyncpg.connect(db.owner_plain)
    try:
        rows = await conn.fetch(
            """
            SELECT c.table_name, c.column_name, c.is_nullable = 'YES' AS nullable
              FROM information_schema.columns c
              JOIN information_schema.tables t USING (table_schema, table_name)
             WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
               AND c.table_name NOT IN ('spatial_ref_sys', 'alembic_version')
            """
        )
    finally:
        await conn.close()
    tables: dict[str, dict[str, bool]] = {}
    for r in rows:
        tables.setdefault(r["table_name"], {})[r["column_name"]] = r["nullable"]
    return tables


async def test_every_table_has_a_model(catalogue: dict[str, dict[str, bool]]) -> None:
    assert set(Base.metadata.tables) == set(catalogue)


async def test_model_columns_and_nullability_match(
    catalogue: dict[str, dict[str, bool]],
) -> None:
    mismatches = []
    for name, table in Base.metadata.tables.items():
        model = {c.name: bool(c.nullable) for c in table.columns}
        if model != catalogue[name]:
            mismatches.append((name, model, catalogue[name]))
    assert mismatches == []


async def test_model_primary_keys_match(db: DbUrls) -> None:
    conn = await asyncpg.connect(db.owner_plain)
    try:
        rows = await conn.fetch(
            """
            SELECT tc.table_name, kcu.column_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                USING (constraint_schema, constraint_name, table_name)
             WHERE tc.table_schema = 'public' AND tc.constraint_type = 'PRIMARY KEY'
            """
        )
    finally:
        await conn.close()
    db_pks: dict[str, set[str]] = {}
    for r in rows:
        db_pks.setdefault(r["table_name"], set()).add(r["column_name"])
    for name, table in Base.metadata.tables.items():
        assert {c.name for c in table.primary_key.columns} == db_pks[name], name
