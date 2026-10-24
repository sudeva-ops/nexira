"""app/core/db.py: tenant per transaction (D-02), role guard (D-01, Prompt 2 f),
and server-generated columns (D-12, D-20)."""

import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import (
    ServerGeneratedColumnError,
    UnsafeDatabaseRoleError,
    create_engine,
    tenant_session,
    verify_connection_role,
)
from app.models import ActionPolicy, Agent, AgentProposal, AuditLog, Mission
from app.tests.conftest import DbUrls, create_tenant


def _mission(tenant: uuid.UUID, code: str) -> Mission:
    return Mission(
        tenant_id=tenant,
        code=code,
        city="Nairobi",
        country_code="KE",
        location="SRID=4326;POINT(36.8080 -1.2950)",
    )


# --- role guard ----------------------------------------------------------------------------


async def test_api_role_passes_the_startup_guard(api_engine: AsyncEngine) -> None:
    await verify_connection_role(api_engine)


@pytest.mark.parametrize("who", ["owner", "admin"])
async def test_owner_and_superuser_are_refused(db: DbUrls, who: str) -> None:
    url = db.owner if who == "owner" else db.admin.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_engine(url)
    try:
        with pytest.raises(UnsafeDatabaseRoleError, match="D-01"):
            await verify_connection_role(engine)
    finally:
        await engine.dispose()


# --- tenant per transaction ------------------------------------------------------------------


async def test_session_sets_tenant_for_every_transaction(
    db: DbUrls, api_engine: AsyncEngine
) -> None:
    tenant = await create_tenant(db)
    async with tenant_session(tenant, api_engine) as session:
        session.add(_mission(tenant, "NBO"))
        await session.commit()
        # A new transaction after commit must have the tenant again.
        assert await session.scalar(select(func.count()).select_from(Mission)) == 1
        setting = await session.scalar(text("SELECT current_setting('app.tenant_id')"))
        assert setting == str(tenant)
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(Mission)) == 1


async def test_tenant_setting_does_not_leak_between_sessions(
    db: DbUrls, api_engine: AsyncEngine
) -> None:
    """set_config(..., true) is transaction-local, so a pooled connection carries no
    tenant into the next session."""
    tenant = await create_tenant(db)
    async with tenant_session(tenant, api_engine) as session:
        session.add(_mission(tenant, "NBO"))
        await session.commit()
    async with tenant_session(None, api_engine) as session:
        assert await session.scalar(select(func.count()).select_from(Mission)) == 0
        assert await session.scalar(text("SELECT current_tenant_id()")) is None


async def test_other_tenant_session_sees_nothing(db: DbUrls, api_engine: AsyncEngine) -> None:
    a, b = await create_tenant(db), await create_tenant(db)
    async with tenant_session(a, api_engine) as session:
        session.add(_mission(a, "NBO"))
        await session.commit()
    async with tenant_session(b, api_engine) as session:
        assert await session.scalar(select(func.count()).select_from(Mission)) == 0


# --- server-generated columns -------------------------------------------------------------------


async def _agent_with_policy(session_tenant: uuid.UUID, api_engine: AsyncEngine) -> uuid.UUID:
    agent_id = uuid.uuid4()
    async with tenant_session(session_tenant, api_engine) as session:
        session.add(
            Agent(id=agent_id, tenant_id=session_tenant, code="RP", name="RP", autonomy_level=0)
        )
        session.add(
            ActionPolicy(
                tenant_id=session_tenant,
                action_type="START_PLAYBOOK",
                min_autonomy_level=2,
                approver_roles=["DUTY_OFFICER"],
            )
        )
        await session.commit()
    return agent_id


async def test_effective_level_and_deadline_come_from_the_database(
    db: DbUrls, api_engine: AsyncEngine
) -> None:
    tenant = await create_tenant(db)
    agent_id = await _agent_with_policy(tenant, api_engine)
    async with tenant_session(tenant, api_engine) as session:
        proposal = AgentProposal(
            tenant_id=tenant,
            agent_id=agent_id,
            proposal_key="k",
            action_type="START_PLAYBOOK",
            title="t",
            proposed_action="p",
        )
        session.add(proposal)
        await session.commit()
        assert proposal.effective_level == 2  # max(agent 0, policy floor 2)
        assert proposal.deadline_at is not None


@pytest.mark.parametrize("attr", ["effective_level", "deadline_at"])
async def test_app_cannot_write_proposal_server_columns(
    db: DbUrls, api_engine: AsyncEngine, attr: str
) -> None:
    tenant = await create_tenant(db)
    agent_id = await _agent_with_policy(tenant, api_engine)
    async with tenant_session(tenant, api_engine) as session:
        proposal = AgentProposal(
            tenant_id=tenant,
            agent_id=agent_id,
            proposal_key="k",
            action_type="START_PLAYBOOK",
            title="t",
            proposed_action="p",
        )
        setattr(proposal, attr, 0 if attr == "effective_level" else func.now())
        session.add(proposal)
        with pytest.raises(ServerGeneratedColumnError, match=attr):
            await session.flush()


async def test_app_cannot_change_effective_level_after_insert(
    db: DbUrls, api_engine: AsyncEngine
) -> None:
    tenant = await create_tenant(db)
    agent_id = await _agent_with_policy(tenant, api_engine)
    async with tenant_session(tenant, api_engine) as session:
        proposal = AgentProposal(
            tenant_id=tenant,
            agent_id=agent_id,
            proposal_key="k",
            action_type="START_PLAYBOOK",
            title="t",
            proposed_action="p",
        )
        session.add(proposal)
        await session.commit()
        proposal.effective_level = 0
        with pytest.raises(ServerGeneratedColumnError, match="effective_level"):
            await session.flush()


@pytest.mark.parametrize("attr", ["chain_seq", "prev_hash", "row_hash"])
async def test_app_cannot_write_audit_chain_columns(
    db: DbUrls, api_engine: AsyncEngine, attr: str
) -> None:
    tenant = await create_tenant(db)
    async with tenant_session(tenant, api_engine) as session:
        row = AuditLog(tenant_id=tenant, actor_type="SYSTEM", action="T", entity_type="t")
        setattr(row, attr, 1 if attr == "chain_seq" else "x")
        session.add(row)
        with pytest.raises(ServerGeneratedColumnError, match=attr):
            await session.flush()


async def test_audit_insert_reads_back_chain_columns(db: DbUrls, api_engine: AsyncEngine) -> None:
    tenant = await create_tenant(db)
    async with tenant_session(tenant, api_engine) as session:
        row = AuditLog(tenant_id=tenant, actor_type="SYSTEM", action="T", entity_type="t")
        session.add(row)
        await session.commit()
        assert row.chain_seq == 1
        assert row.prev_hash is None
        assert row.row_hash
        assert len(row.row_hash) == 64
