"""templates.resolve (MN-03, D-31): the mission's own template, else the generic one
with {city} filled in; inactive templates are ignored; and another tenant's mission or
template is never used, whatever id is passed (RLS, review of Prompt 18, finding 5)."""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import tenant_session
from app.modules.notifications import templates
from app.modules.notifications.models import MessageTemplate
from app.modules.people.service import ensure_mission
from app.tests.conftest import DbUrls, create_tenant

CODE = "CIVIL_UNREST_SHELTER"
GENERIC = templates.TemplateIn(
    CODE, "ADVISORY", None, "Generic", {"en": "Unrest in {city}. {Stay} indoors."}, {}
)


async def setup_tenant(
    db: DbUrls, engine: AsyncEngine, city: str, own_text: str | None
) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await create_tenant(db, f"Templates {city}")
    async with tenant_session(tenant_id, engine) as session:
        mission_id = await ensure_mission(
            session, code="M1", city=city, country_code="XX", lat=0.0, lon=0.0
        )
        seeds = [GENERIC]
        if own_text is not None:
            seeds.append(templates.TemplateIn(CODE, "ADVISORY", "M1", city, {"en": own_text}, {}))
        await templates.ensure_templates(session, seeds)
        await session.commit()
    return tenant_id, mission_id


async def resolve(
    engine: AsyncEngine, tenant_id: uuid.UUID, mission_id: uuid.UUID | None
) -> str | None:
    async with tenant_session(tenant_id, engine) as session:
        resolved = await templates.resolve(session, CODE, mission_id)
    return resolved.texts["en"] if resolved else None


async def test_the_mission_template_wins_over_the_generic(
    db: DbUrls, api_engine: AsyncEngine
) -> None:
    tenant, mission = await setup_tenant(db, api_engine, "Paris", "Avoid République.")
    assert await resolve(api_engine, tenant, mission) == "Avoid République."


async def test_the_generic_template_fills_in_the_city_and_keeps_other_braces(
    db: DbUrls, api_engine: AsyncEngine
) -> None:
    tenant, mission = await setup_tenant(db, api_engine, "Tirana", None)
    assert await resolve(api_engine, tenant, mission) == "Unrest in Tirana. {Stay} indoors."
    assert await resolve(api_engine, tenant, None) == (
        "Unrest in the affected area. {Stay} indoors."
    )


async def test_an_inactive_template_is_ignored(db: DbUrls, api_engine: AsyncEngine) -> None:
    tenant, mission = await setup_tenant(db, api_engine, "Paris", "Avoid République.")
    async with tenant_session(tenant, api_engine) as session:
        await session.execute(
            update(MessageTemplate)
            .where(MessageTemplate.mission_id == mission)
            .values(is_active=False)
        )
        await session.commit()
    assert await resolve(api_engine, tenant, mission) == "Unrest in Paris. {Stay} indoors."


async def test_another_tenants_mission_is_never_used(db: DbUrls, api_engine: AsyncEngine) -> None:
    mine, _ = await setup_tenant(db, api_engine, "Lyon", None)
    _, theirs = await setup_tenant(db, api_engine, "Secret City", "Their own words.")
    # Their mission id: RLS hides both their mission and their template from us.
    assert await resolve(api_engine, mine, theirs) == "Unrest in the affected area. {Stay} indoors."
