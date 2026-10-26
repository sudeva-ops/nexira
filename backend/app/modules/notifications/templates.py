"""Message templates per mission and kind, with a generic fallback (D-31, PC-07).

Pre-written texts only (D-15): each language is marked reviewed or not. Resolving a
template for a campaign (MN-03) comes in Prompt 19; this module stores them.
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
