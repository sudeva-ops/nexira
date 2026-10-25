"""Migration 0002 (PC-07, PC-08, D-31), checked as nexira_api: the database refuses
self-approval and a rewritten approval, keeps one generic template per code, and the
API can never delete a template."""

import json
import uuid

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)


@pytest.fixture
async def tenant(db: DbUrls, api: asyncpg.Connection) -> asyncpg.Connection:
    await set_tenant(api, await create_tenant(db, "Campaign approval"))
    return api


async def user(conn: asyncpg.Connection) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, 'U')",
        user_id,
        f"sub-{user_id}",
        f"{user_id}@users.invalid",
    )
    return user_id


async def draft(conn: asyncpg.Connection, author: uuid.UUID) -> uuid.UUID:
    campaign_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO notification_campaign (id, tenant_id, reference, campaign_type, message, "
        "channels, created_by_type, created_by, submitted_by, status) VALUES ($1, "
        "current_tenant_id(), $2, 'ADVISORY', 'm', '{SMS}', 'USER', $3, $4, 'PENDING_APPROVAL')",
        campaign_id,
        f"NTF-{campaign_id.hex[:6]}",
        str(author),
        author,
    )
    return campaign_id


async def approve(conn: asyncpg.Connection, campaign_id: uuid.UUID, by: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE notification_campaign SET approved_by = $2, approved_at = now() WHERE id = $1",
        campaign_id,
        by,
    )


async def test_the_author_cannot_approve_their_own_campaign(tenant: asyncpg.Connection) -> None:
    author = await user(tenant)
    campaign_id = await draft(tenant, author)
    with pytest.raises(REFUSED, match="notification_campaign: the author cannot approve"):
        await approve(tenant, campaign_id, author)


async def test_a_second_person_approves_once(tenant: asyncpg.Connection) -> None:
    author, second, third = await user(tenant), await user(tenant), await user(tenant)
    campaign_id = await draft(tenant, author)
    await approve(tenant, campaign_id, second)
    with pytest.raises(REFUSED, match="approved_by cannot change once set"):
        await approve(tenant, campaign_id, third)
    assert (
        await tenant.fetchval(
            "SELECT approved_by FROM notification_campaign WHERE id = $1", campaign_id
        )
        == second
    )


async def test_pending_approval_is_a_campaign_status(tenant: asyncpg.Connection) -> None:
    campaign_id = await draft(tenant, await user(tenant))
    assert (
        await tenant.fetchval("SELECT status FROM notification_campaign WHERE id = $1", campaign_id)
        == "PENDING_APPROVAL"
    )


async def template(conn: asyncpg.Connection, code: str, texts: dict[str, str]) -> None:
    await conn.execute(
        "INSERT INTO message_template (tenant_id, code, kind, name, texts) "
        "VALUES (current_tenant_id(), $1, 'ADVISORY', 'n', $2::jsonb)",
        code,
        json.dumps(texts),
    )


async def test_one_generic_template_per_code(tenant: asyncpg.Connection) -> None:
    await template(tenant, "CIVIL_UNREST_SHELTER", {"en": "Generic"})
    with pytest.raises(asyncpg.UniqueViolationError):
        await template(tenant, "CIVIL_UNREST_SHELTER", {"en": "Another generic"})


async def test_a_template_needs_english(tenant: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await template(tenant, "NO_ENGLISH", {"fr": "Seulement en français"})


async def test_the_api_cannot_delete_templates(tenant: asyncpg.Connection) -> None:
    await template(tenant, "KEEP", {"en": "Kept"})
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("DELETE FROM message_template")
