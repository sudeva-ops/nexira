"""Message templates per mission and kind, with a generic fallback (D-31, PC-07).

Pre-written texts only (D-15): each language is marked reviewed or not. resolve()
picks the mission's template, or the generic one, and fills in {city} (MN-03).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.notifications.models import MessageTemplate
from app.modules.people.models import Mission
from app.modules.tenancy.service import SYSTEM, Actor

KINDS = ("ALERT", "ADVISORY", "CHECKIN")
NO_MISSION_CITY = "the affected area"  # {city} for an incident with no mission (D-06)


@dataclass(frozen=True)
class Resolved:
    template_id: uuid.UUID
    texts: dict[str, str]  # {city} filled in; always has "en"
    reviewed: dict[str, bool]  # per translation (not English)


async def resolve(
    session: AsyncSession, code: str, mission_id: uuid.UUID | None
) -> Resolved | None:
    """The active template for code: the mission's own, else the generic one. Both the
    template and the mission are read through the tenant's session (RLS), so another
    tenant's rows are never used, whatever id is passed."""
    template = await session.scalar(
        select(MessageTemplate)
        .where(
            MessageTemplate.code == code,
            MessageTemplate.is_active,
            (MessageTemplate.mission_id == mission_id) | MessageTemplate.mission_id.is_(None),
        )
        .order_by(MessageTemplate.mission_id.is_(None))  # the mission's own first
        .limit(1)
    )
    if template is None:
        return None
    mission = await session.get(Mission, mission_id) if mission_id else None
    city = mission.city if mission is not None else NO_MISSION_CITY
    return Resolved(
        template_id=template.id,
        # str.replace, not format(): template text is data, and may contain braces.
        texts={lang: text.replace("{city}", city) for lang, text in template.texts.items()},
        reviewed=dict(template.reviewed),
    )


@dataclass(frozen=True)
class TemplateIn:
    code: str
    kind: str
    mission_code: str | None  # None = the generic template
    name: str
    texts: dict[str, str]  # must include "en"
    reviewed: dict[str, bool]


async def ensure_templates(
    session: AsyncSession, templates: list[TemplateIn], actor: Actor = SYSTEM
) -> list[str]:
    """Create templates whose (code, mission) is new; return "code@mission" for each
    one created (audited once each). Existing templates are never overwritten, so a
    reviewed or edited template survives a re-seed."""
    tenant_id = session.info["tenant_id"]
    missions = {m.code: m.id for m in await session.scalars(select(Mission))}
    rows: list[dict[str, object]] = []
    for t in templates:
        if t.kind not in KINDS or "en" not in t.texts:
            raise ValueError(f"template {t.code}: unknown kind or no English text")
        mission_id: uuid.UUID | None = None
        if t.mission_code is not None:
            mission_id = missions[t.mission_code]
        rows.append(
            {
                "tenant_id": tenant_id,
                "code": t.code,
                "kind": t.kind,
                "mission_id": mission_id,
                "name": t.name,
                "texts": t.texts,
                "reviewed": t.reviewed,
            }
        )
    created = await session.execute(
        insert(MessageTemplate)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["tenant_id", "code", "mission_id"])
        .returning(MessageTemplate.id, MessageTemplate.code, MessageTemplate.mission_id)
    )
    mission_codes = {mission_id: code for code, mission_id in missions.items()}
    made: list[str] = []
    for template_id, code, mission_id in created.all():
        where = mission_codes[mission_id] if mission_id else "generic"
        await audit.write(
            session,
            actor_type=actor.type,
            actor_id=actor.id,
            action="MESSAGE_TEMPLATE.CREATE",
            entity_type="message_template",
            entity_id=str(template_id),
            details={"code": code, "mission": where},
        )
        made.append(f"{code}@{where}")
    return sorted(made)
