"""Migration 0002 (PC-07, PC-08, PC-10, PC-11; D-31), checked as nexira_api: the
database refuses self-approval in every form the reviews of Prompt 18 tried, binds an
approval to the content that is sent, keeps one generic template per code, and the API
can delete neither templates nor campaigns, deliveries or check-in answers."""

import json
import uuid

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

REFUSED = asyncpg.RaiseError  # the trigger's RAISE EXCEPTION (P0001)
SELF = "the author cannot approve their own campaign"


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


async def campaign(
    conn: asyncpg.Connection,
    *,
    created_by: str,
    submitted_by: uuid.UUID | None,
    status: str = "PENDING_APPROVAL",
    approved_by: uuid.UUID | None = None,
) -> uuid.UUID:
    campaign_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO notification_campaign (id, tenant_id, reference, campaign_type, message, "
        "channels, created_by_type, created_by, submitted_by, status, approved_by) VALUES ($1, "
        "current_tenant_id(), $2, 'ADVISORY', 'm', '{SMS}', 'USER', $3, $4, $5, $6)",
        campaign_id,
        f"NTF-{campaign_id.hex[:6]}",
        created_by,
        submitted_by,
        status,
        approved_by,
    )
    return campaign_id


async def pending(conn: asyncpg.Connection, author: uuid.UUID) -> uuid.UUID:
    return await campaign(conn, created_by=str(author), submitted_by=author)


async def approve(conn: asyncpg.Connection, campaign_id: uuid.UUID, by: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE notification_campaign SET approved_by = $2, status = 'SENDING' WHERE id = $1",
        campaign_id,
        by,
    )


async def approved_by(conn: asyncpg.Connection, campaign_id: uuid.UUID) -> uuid.UUID | None:
    value: uuid.UUID | None = await conn.fetchval(
        "SELECT approved_by FROM notification_campaign WHERE id = $1", campaign_id
    )
    return value


# --- what must work ---------------------------------------------------------------


async def test_a_second_person_approves_once(tenant: asyncpg.Connection) -> None:
    author, second, third = await user(tenant), await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    await approve(tenant, campaign_id, second)
    assert await approved_by(tenant, campaign_id) == second
    with pytest.raises(REFUSED, match="approved_by cannot change once set"):
        await approve(tenant, campaign_id, third)


async def test_playbook_campaigns_are_unaffected(tenant: asyncpg.Connection) -> None:
    """Phase 1 campaigns (PB-07, agents) are created SENDING and completed by the
    dispatcher; the guard never gets in their way."""
    await tenant.execute(
        "INSERT INTO notification_campaign (tenant_id, reference, campaign_type, message, "
        "channels, created_by_type, created_by, status) VALUES (current_tenant_id(), 'NTF-PB', "
        "'CHECKIN', 'm', '{APP}', 'PLAYBOOK', 'PB-07', 'SENDING')"
    )
    await tenant.execute(
        "UPDATE notification_campaign SET status = 'SENT', sent_at = now(), "
        "escalate_after_s = 120 WHERE reference = 'NTF-PB'"
    )


# --- self-approval, in every form the review tried ---------------------------------


async def test_the_author_cannot_approve(tenant: asyncpg.Connection) -> None:
    author = await user(tenant)
    with pytest.raises(REFUSED, match=SELF):
        await approve(tenant, await pending(tenant, author), author)


async def test_the_submitter_cannot_approve(tenant: asyncpg.Connection) -> None:
    author, submitter = await user(tenant), await user(tenant)
    campaign_id = await campaign(tenant, created_by=str(author), submitted_by=submitter)
    with pytest.raises(REFUSED, match=SELF):
        await approve(tenant, campaign_id, submitter)


async def test_rewriting_the_author_in_the_same_update_is_refused(
    tenant: asyncpg.Connection,
) -> None:
    author, other = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    rewrites: list[tuple[str, tuple[object, ...]]] = [
        ("created_by = $3, submitted_by = $4", (str(other), other)),
        ("created_by_type = 'PLAYBOOK'", ()),
        ("created_by = upper(created_by)", ()),
    ]
    for change, extra in rewrites:
        with pytest.raises(REFUSED, match="cannot change"):
            await tenant.execute(
                f"UPDATE notification_campaign SET {change}, approved_by = $2, "
                "status = 'SENDING' WHERE id = $1",
                campaign_id,
                author,
                *extra,
            )
    assert await approved_by(tenant, campaign_id) is None


async def test_an_upper_case_author_is_still_the_author(tenant: asyncpg.Connection) -> None:
    """The author is compared as a uuid, not as text."""
    author, submitter = await user(tenant), await user(tenant)
    campaign_id = await campaign(tenant, created_by=str(author).upper(), submitted_by=submitter)
    with pytest.raises(REFUSED, match=SELF):
        await approve(tenant, campaign_id, author)


async def test_an_author_that_is_not_a_uuid_cannot_be_approved(
    tenant: asyncpg.Connection,
) -> None:
    submitter, approver = await user(tenant), await user(tenant)
    campaign_id = await campaign(tenant, created_by="not-a-uuid", submitted_by=submitter)
    with pytest.raises(REFUSED, match="author is unknown"):
        await approve(tenant, campaign_id, approver)


# --- approval only from PENDING_APPROVAL, never rewritten --------------------------


async def test_a_campaign_cannot_be_created_approved(tenant: asyncpg.Connection) -> None:
    author, other = await user(tenant), await user(tenant)
    with pytest.raises(REFUSED, match="cannot be created approved"):
        await campaign(tenant, created_by=str(author), submitted_by=author, approved_by=other)


@pytest.mark.parametrize("status", ["DRAFT", "CANCELLED", "SENT"])
async def test_only_a_pending_campaign_can_be_approved(
    tenant: asyncpg.Connection, status: str
) -> None:
    author, other = await user(tenant), await user(tenant)
    campaign_id = await campaign(tenant, created_by=str(author), submitted_by=author, status=status)
    # DRAFT reaches the approval check; CANCELLED and SENT are final (PC-12).
    with pytest.raises(REFUSED, match=r"only a campaign pending approval|status cannot go"):
        await approve(tenant, campaign_id, other)


async def test_an_approval_cannot_be_cleared_or_redated(tenant: asyncpg.Connection) -> None:
    author, second = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    await approve(tenant, campaign_id, second)
    with pytest.raises(REFUSED, match="approved_by cannot change once set"):
        await tenant.execute(
            "UPDATE notification_campaign SET approved_by = NULL WHERE id = $1", campaign_id
        )
    with pytest.raises(REFUSED, match="approved_at cannot change once set"):
        await tenant.execute(
            "UPDATE notification_campaign SET approved_at = now() - interval '1 day' WHERE id = $1",
            campaign_id,
        )


async def test_the_submitter_cannot_be_rewritten(tenant: asyncpg.Connection) -> None:
    author, other = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    with pytest.raises(REFUSED, match="submitted_by cannot change once set"):
        await tenant.execute(
            "UPDATE notification_campaign SET submitted_by = $2 WHERE id = $1", campaign_id, other
        )


async def test_pending_approval_needs_a_submitter(tenant: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await campaign(tenant, created_by=str(await user(tenant)), submitted_by=None)


async def test_the_api_cannot_delete_campaigns(tenant: asyncpg.Connection) -> None:
    await pending(tenant, await user(tenant))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("DELETE FROM notification_campaign")


# --- PC-11: what is approved is what is sent ---------------------------------------


async def set_message(conn: asyncpg.Connection, campaign_id: uuid.UUID, text: str) -> None:
    await conn.execute(
        "UPDATE notification_campaign SET message = $2 WHERE id = $1", campaign_id, text
    )


async def test_a_draft_can_be_edited(tenant: asyncpg.Connection) -> None:
    author = await user(tenant)
    campaign_id = await campaign(tenant, created_by=str(author), submitted_by=None, status="DRAFT")
    await set_message(tenant, campaign_id, "edited while a draft")


async def test_the_content_is_frozen_while_pending(tenant: asyncpg.Connection) -> None:
    campaign_id = await pending(tenant, await user(tenant))
    for change in (
        "message = 'swapped while pending'",
        'translations = \'{"fr": "x"}\'',
        "channels = '{SMS,EMAIL}'",
        'audience_filter = \'{"person_types": ["CITIZEN"]}\'',
        "campaign_type = 'ALERT'",
    ):
        with pytest.raises(REFUSED, match="content is frozen"):
            await tenant.execute(
                f"UPDATE notification_campaign SET {change} WHERE id = $1", campaign_id
            )


async def test_the_content_is_frozen_after_approval_and_cannot_go_back(
    tenant: asyncpg.Connection,
) -> None:
    author, second = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    await approve(tenant, campaign_id, second)
    with pytest.raises(REFUSED, match="content is frozen"):
        await set_message(tenant, campaign_id, "swapped after approval")
    for status in ("DRAFT", "PENDING_APPROVAL"):  # refused by PC-11 or PC-12, whichever is first
        with pytest.raises(REFUSED, match=r"an approved campaign cannot be|status cannot go"):
            await tenant.execute(
                "UPDATE notification_campaign SET status = $2 WHERE id = $1", campaign_id, status
            )


async def test_a_rejected_campaign_returns_to_draft_and_can_be_edited(
    tenant: asyncpg.Connection,
) -> None:
    campaign_id = await pending(tenant, await user(tenant))
    await tenant.execute(
        "UPDATE notification_campaign SET status = 'DRAFT', rejection_reason = 'too broad' "
        "WHERE id = $1",
        campaign_id,
    )
    await set_message(tenant, campaign_id, "narrower, resubmitted later")


async def test_the_approval_time_is_the_databases(tenant: asyncpg.Connection) -> None:
    author, second = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    await tenant.execute(
        "UPDATE notification_campaign SET approved_by = $2, status = 'SENDING', "
        "approved_at = now() - interval '30 days' WHERE id = $1",
        campaign_id,
        second,
    )
    age = await tenant.fetchval(
        "SELECT now() - approved_at FROM notification_campaign WHERE id = $1", campaign_id
    )
    assert age.total_seconds() < 60  # the backdated time was replaced


async def test_an_approval_time_needs_an_approver(tenant: asyncpg.Connection) -> None:
    campaign_id = await campaign(
        tenant, created_by=str(await user(tenant)), submitted_by=None, status="SENT"
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await tenant.execute(
            "UPDATE notification_campaign SET approved_at = now() WHERE id = $1", campaign_id
        )


# --- PC-12: status only moves forward; evidence is not rewritten -------------------


async def status(conn: asyncpg.Connection, campaign_id: uuid.UUID, to: str) -> None:
    await conn.execute(
        "UPDATE notification_campaign SET status = $2 WHERE id = $1", campaign_id, to
    )


@pytest.mark.parametrize(
    ("start", "to"),
    [
        ("SENDING", "DRAFT"),
        ("SENT", "DRAFT"),
        ("SENT", "PENDING_APPROVAL"),
        ("CANCELLED", "DRAFT"),
        ("SENT", "CANCELLED"),
        ("SENDING", "CANCELLED"),
        ("CANCELLED", "SENDING"),
    ],
)
async def test_sent_and_cancelled_campaigns_never_reopen(
    tenant: asyncpg.Connection, start: str, to: str
) -> None:
    author = await user(tenant)
    campaign_id = await campaign(tenant, created_by=str(author), submitted_by=None, status=start)
    with pytest.raises(REFUSED, match="status cannot go"):
        await status(tenant, campaign_id, to)


async def test_a_pending_campaign_is_sent_only_with_an_approval(
    tenant: asyncpg.Connection,
) -> None:
    campaign_id = await pending(tenant, await user(tenant))
    with pytest.raises(REFUSED, match="status cannot go from PENDING_APPROVAL to SENDING"):
        await status(tenant, campaign_id, "SENDING")


async def test_approving_goes_to_sending_and_nowhere_else(tenant: asyncpg.Connection) -> None:
    author, second = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    with pytest.raises(REFUSED):
        await tenant.execute(
            "UPDATE notification_campaign SET approved_by = $2, status = 'SENT' WHERE id = $1",
            campaign_id,
            second,
        )


async def test_the_forward_path_works(tenant: asyncpg.Connection) -> None:
    author, second = await user(tenant), await user(tenant)
    campaign_id = await campaign(tenant, created_by=str(author), submitted_by=None, status="DRAFT")
    await tenant.execute(
        "UPDATE notification_campaign SET status = 'PENDING_APPROVAL', submitted_by = $2 "
        "WHERE id = $1",
        campaign_id,
        author,
    )
    await approve(tenant, campaign_id, second)
    await tenant.execute(
        "UPDATE notification_campaign SET status = 'SENT', sent_at = now() WHERE id = $1",
        campaign_id,
    )
    with pytest.raises(REFUSED, match="sent_at cannot change"):
        await tenant.execute(
            "UPDATE notification_campaign SET sent_at = now() + interval '1 year' WHERE id = $1",
            campaign_id,
        )


async def test_reference_and_created_at_are_frozen(tenant: asyncpg.Connection) -> None:
    campaign_id = await pending(tenant, await user(tenant))
    for change in ("reference = 'NTF-FAKE'", "created_at = '2000-01-01'"):
        with pytest.raises(REFUSED, match="cannot change"):
            await tenant.execute(
                f"UPDATE notification_campaign SET {change} WHERE id = $1", campaign_id
            )


async def test_a_rejection_reason_only_on_rejection(tenant: asyncpg.Connection) -> None:
    author, second = await user(tenant), await user(tenant)
    campaign_id = await pending(tenant, author)
    await approve(tenant, campaign_id, second)
    with pytest.raises(REFUSED, match="rejection reason is written only on rejection"):
        await tenant.execute(
            "UPDATE notification_campaign SET rejection_reason = 'never approved' WHERE id = $1",
            campaign_id,
        )


async def test_the_escalation_time_must_be_positive(tenant: asyncpg.Connection) -> None:
    campaign_id = await campaign(
        tenant, created_by=str(await user(tenant)), submitted_by=None, status="SENT"
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await tenant.execute(
            "UPDATE notification_campaign SET escalate_after_s = -5 WHERE id = $1", campaign_id
        )


async def test_a_delivery_keeps_its_campaign_person_and_channel(
    tenant: asyncpg.Connection,
) -> None:
    author = await user(tenant)
    first = await campaign(tenant, created_by=str(author), submitted_by=None, status="SENDING")
    other = await campaign(tenant, created_by=str(author), submitted_by=None, status="SENDING")
    person = uuid.uuid4()
    await tenant.execute(
        "INSERT INTO person (id, tenant_id, person_type, full_name) "
        "VALUES ($1, current_tenant_id(), 'CITIZEN', 'Fictional Person')",
        person,
    )
    delivery = await tenant.fetchval(
        "INSERT INTO notification_delivery (tenant_id, campaign_id, person_id, channel) "
        "VALUES (current_tenant_id(), $1, $2, 'SMS') RETURNING id",
        first,
        person,
    )
    await tenant.execute(
        "UPDATE notification_delivery SET status = 'SENT', provider_ref = 'SIM-1' WHERE id = $1",
        delivery,
    )
    for change, value in (("campaign_id", other), ("channel", "EMAIL")):
        with pytest.raises(REFUSED, match="notification_delivery: campaign, person and channel"):
            await tenant.execute(
                f"UPDATE notification_delivery SET {change} = $2 WHERE id = $1", delivery, value
            )


async def test_check_in_answers_cannot_be_edited(tenant: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await tenant.execute("UPDATE checkin_response SET status = 'SAFE'")


# --- templates ---------------------------------------------------------------------


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
