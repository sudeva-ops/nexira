"""app/core/audit.py and the audit API (PLT-04, D-20, plan G-06)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import audit
from app.core.db import tenant_session
from app.modules.audit.models import AuditLog
from app.tests.auth_helpers import Idp


async def test_audit_write_rows_chain(idp: Idp) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        rows = [
            await audit.write(
                session, actor_type="SYSTEM", actor_id="test", action=f"T.{n}", entity_type="t"
            )
            for n in range(3)
        ]
        await session.commit()
    assert [r.chain_seq for r in rows] == [1, 2, 3]
    assert rows[0].prev_hash is None
    assert rows[1].prev_hash == rows[0].row_hash
    assert rows[2].prev_hash == rows[1].row_hash


async def test_audit_rolls_back_with_the_change(idp: Idp) -> None:
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        await audit.write(session, actor_type="SYSTEM", actor_id="t", action="T", entity_type="t")
        await session.rollback()
    async with tenant_session(idp.tenant_id, idp.engine) as session:
        assert (await session.scalars(select(AuditLog))).all() == []


async def test_audit_write_needs_a_tenant(idp: Idp) -> None:
    async with tenant_session(None, idp.engine) as session:
        with pytest.raises(RuntimeError, match="tenant-scoped"):
            await audit.write(
                session, actor_type="SYSTEM", actor_id="t", action="T", entity_type="t"
            )


@pytest.fixture
async def people(idp: Idp) -> None:
    await idp.user("admin", [("ADMIN", None)])
    await idp.user("viewer", [("VIEWER", None)])
    await idp.user("duty", [("DUTY_OFFICER", None)])
    await idp.user("nobody")


async def test_unfiltered_audit_list_is_admin_only(
    client: AsyncClient, idp: Idp, people: None
) -> None:
    admin = await client.get("/api/audit", headers=idp.headers("admin"))
    assert admin.status_code == 200
    seqs = [e["chain_seq"] for e in admin.json()]
    assert seqs == sorted(seqs, reverse=True)
    assert len(seqs) > 0  # seeding the users wrote ROLE.CREATE / USER.CREATE / ROLE.GRANT
    for sub in ("viewer", "duty"):
        assert (await client.get("/api/audit", headers=idp.headers(sub))).status_code == 403


async def test_entity_filtered_audit_is_open_to_any_role(
    client: AsyncClient, idp: Idp, people: None
) -> None:
    viewer_id = (await client.get("/api/me", headers=idp.headers("viewer"))).json()["id"]
    params = {"entity_type": "app_user", "entity_id": viewer_id}
    response = await client.get("/api/audit", params=params, headers=idp.headers("duty"))
    assert response.status_code == 200
    assert [e["action"] for e in response.json()] == ["USER.CREATE"]
    no_role = await client.get("/api/audit", params=params, headers=idp.headers("nobody"))
    assert no_role.status_code == 403


async def test_audit_list_pages_with_before_seq(
    client: AsyncClient, idp: Idp, people: None
) -> None:
    first = (await client.get("/api/audit?limit=2", headers=idp.headers("admin"))).json()
    assert len(first) == 2
    before = first[-1]["chain_seq"]
    page = await client.get(f"/api/audit?limit=2&before_seq={before}", headers=idp.headers("admin"))
    assert all(e["chain_seq"] < before for e in page.json())


async def test_verify_is_admin_only_and_reports_intact(
    client: AsyncClient, idp: Idp, people: None
) -> None:
    response = await client.get("/api/audit/verify", headers=idp.headers("admin"))
    assert response.status_code == 200
    body = response.json()
    assert body["intact"] is True
    assert body["first_broken_seq"] is None
    assert body["rows"] > 0
    duty = await client.get("/api/audit/verify", headers=idp.headers("duty"))
    assert duty.status_code == 403
