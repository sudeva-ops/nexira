"""Prompt 2 (d) audit log and (e) reference numbers under concurrency (D-18, D-20)."""

import asyncio
import re

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant


@pytest.mark.parametrize("privilege", ["UPDATE", "DELETE", "TRUNCATE"])
async def test_api_has_no_mutating_privilege_on_audit_log(
    api: asyncpg.Connection, privilege: str
) -> None:
    assert await api.fetchval("SELECT has_table_privilege('audit_log', $1)", privilege) is False


@pytest.mark.parametrize(
    ("statement", "error"),
    [
        ("UPDATE audit_log SET action = 'X'", asyncpg.InsufficientPrivilegeError),
        ("DELETE FROM audit_log", asyncpg.InsufficientPrivilegeError),
        ("TRUNCATE audit_log", asyncpg.InsufficientPrivilegeError),
    ],
)
async def test_api_cannot_mutate_audit_log(
    db: DbUrls, api: asyncpg.Connection, statement: str, error: type[Exception]
) -> None:
    tenant = await create_tenant(db)
    await set_tenant(api, tenant)
    await api.execute(
        "INSERT INTO audit_log (tenant_id, actor_type, action, entity_type) "
        "VALUES (current_tenant_id(), 'SYSTEM', 'TEST', 'test')"
    )
    with pytest.raises(error):
        await api.execute(statement)
    assert await api.fetchval("SELECT count(*) FROM audit_log") == 1


async def _insert_audit(db: DbUrls, tenant: object, n: int) -> None:
    conn = await asyncpg.connect(db.api_plain)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await conn.execute(
                "INSERT INTO audit_log (tenant_id, actor_type, action, entity_type, details) "
                "VALUES (current_tenant_id(), 'USER', 'TEST.CONCURRENT', 'test', "
                "jsonb_build_object('n', $1::int))",
                n,
            )
    finally:
        await conn.close()


async def test_audit_chain_verifies_after_50_concurrent_inserts(
    db: DbUrls, api: asyncpg.Connection
) -> None:
    tenant = await create_tenant(db)
    await asyncio.gather(*(_insert_audit(db, tenant, n) for n in range(50)))

    await set_tenant(api, tenant)
    seqs = [r["chain_seq"] for r in await api.fetch("SELECT chain_seq FROM audit_log")]
    assert sorted(seqs) == list(range(1, 51))  # gap-free, no duplicates
    assert await api.fetchval("SELECT audit_verify_chain()") is None


async def test_audit_chains_are_per_tenant(db: DbUrls, api: asyncpg.Connection) -> None:
    a, b = await create_tenant(db), await create_tenant(db)
    await asyncio.gather(
        *(_insert_audit(db, a, n) for n in range(10)), *(_insert_audit(db, b, n) for n in range(10))
    )
    for tenant in (a, b):
        await set_tenant(api, tenant)
        assert await api.fetchval("SELECT max(chain_seq) FROM audit_log") == 10
        assert await api.fetchval("SELECT audit_verify_chain()") is None


async def test_audit_verify_chain_detects_tampering(db: DbUrls, api: asyncpg.Connection) -> None:
    """Only a superuser can bypass the triggers; verify_chain must catch what it does."""
    tenant = await create_tenant(db)
    for n in range(3):
        await _insert_audit(db, tenant, n)
    admin = await asyncpg.connect(DbUrls.plain(db.admin))
    try:
        async with admin.transaction():
            await admin.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update")
            await admin.execute(
                "UPDATE audit_log SET details = '{\"n\": 99}' "
                "WHERE tenant_id = $1 AND chain_seq = 2",
                tenant,
            )
            await admin.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update")
    finally:
        await admin.close()
    await set_tenant(api, tenant)
    assert await api.fetchval("SELECT audit_verify_chain()") == 2


async def _next_reference(db: DbUrls, tenant: object) -> str:
    conn = await asyncpg.connect(db.api_plain)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            value: str = await conn.fetchval("SELECT next_reference('INC', true)")
            return value
    finally:
        await conn.close()


async def test_next_reference_is_unique_under_20_concurrent_callers(db: DbUrls) -> None:
    tenant = await create_tenant(db)
    refs = await asyncio.gather(*(_next_reference(db, tenant) for _ in range(20)))
    assert len(set(refs)) == 20
    assert all(re.fullmatch(r"INC-\d{4}-\d{4}", r) for r in refs)
    assert sorted(int(r.rsplit("-", 1)[1]) for r in refs) == list(range(1, 21))


async def test_next_reference_requires_a_tenant(api: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.RaiseError, match=r"app\.tenant_id is not set"):
        await api.fetchval("SELECT next_reference('INC', true)")
