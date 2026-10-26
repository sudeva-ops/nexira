"""Message templates per mission and kind, with a generic fallback (D-31, PC-07).

Pre-written texts only (D-15): each language is marked reviewed or not. resolve()
picks the mission's template, or the generic one, and fills in {city} (MN-03).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import approvals, audit
from app.core.security import CurrentUser
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


LANGUAGES = ("en", "ar", "fr", "sw")  # D-15
TEXT_MAX = 2000


TEMPLATE_EDITORS = "ADMIN|CONSULAR_OFFICER"


class TemplateError(ValueError):
    pass


class TemplateScopeError(TemplateError):
    """The editor's role does not cover the template's mission (D-05)."""


async def _may_edit(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID | None) -> None:
    """Within the template's mission; a generic template (no mission) applies to every
    mission, so only HQ-level holders edit it or mark it reviewed (review of Prompt 20,
    finding 3)."""
    if not await approvals.user_has_role(session, user, TEMPLATE_EDITORS, mission_id):
        scope = "this mission" if mission_id else "HQ (a generic template)"
        raise TemplateScopeError(f"Editing templates needs ADMIN or CONSULAR_OFFICER for {scope}")


def _check_texts(texts: dict[str, str]) -> None:
    for lang, value in texts.items():
        if lang not in LANGUAGES:
            raise TemplateError(f"languages are {', '.join(LANGUAGES)} only")
        if not value.strip() or len(value) > TEXT_MAX:
            raise TemplateError(f"the {lang} text must be 1 to {TEXT_MAX} characters")


async def create_template(
    session: AsyncSession,
    user: CurrentUser,
    *,
    code: str,
    kind: str,
    mission_id: uuid.UUID | None,
    name: str,
    texts: dict[str, str],
) -> MessageTemplate:
    """A new template; nothing is reviewed yet (D-15)."""
    if kind not in KINDS:
        raise TemplateError(f"unknown kind {kind}")
    if "en" not in texts:
        raise TemplateError("a template needs English text")
    _check_texts(texts)
    if mission_id is not None and await session.get(Mission, mission_id) is None:
        raise TemplateError("unknown mission")  # RLS: another tenant's mission is unknown
    await _may_edit(session, user, mission_id)
    actor = Actor(type="USER", id=str(user.id))
    template = MessageTemplate(
        tenant_id=session.info["tenant_id"],
        code=code,
        kind=kind,
        mission_id=mission_id,
        name=name,
        texts=texts,
        reviewed={lang: False for lang in texts if lang != "en"},
    )
    session.add(template)
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="MESSAGE_TEMPLATE.CREATE",
        entity_type="message_template",
        entity_id=str(template.id),
        details={"code": code, "kind": kind, "languages": sorted(texts)},
    )
    return template


async def update_template(
    session: AsyncSession,
    user: CurrentUser,
    template_id: uuid.UUID,
    *,
    name: str | None = None,
    texts: dict[str, str] | None = None,
    reviewed: dict[str, bool] | None = None,
    is_active: bool | None = None,
) -> MessageTemplate:
    """Edit a template. A changed text loses its reviewed flag, so an edit can never
    pass as reviewed; marking a language reviewed is a separate, audited act (D-15)."""
    template = await session.scalar(
        select(MessageTemplate).where(MessageTemplate.id == template_id).with_for_update()
    )
    if template is None:
        raise LookupError("Template not found")
    await _may_edit(session, user, template.mission_id)
    actor = Actor(type="USER", id=str(user.id))
    changes: dict[str, object] = {}
    flags = dict(template.reviewed)
    if texts is not None:
        _check_texts(texts)
        merged = {**template.texts, **texts}
        for lang, value in texts.items():
            if template.texts.get(lang) != value and lang != "en":
                flags[lang] = False
        template.texts = merged
        changes["texts"] = sorted(texts)
    if reviewed is not None:
        for lang, flag in reviewed.items():
            if lang == "en" or lang not in template.texts:
                raise TemplateError(f"{lang} is not a translation of this template")
            if texts is not None and lang in texts and flag:
                raise TemplateError(f"review the {lang} text after saving it, not with it")
            flags[lang] = flag
        changes["reviewed"] = reviewed
    template.reviewed = flags
    if name is not None:
        template.name = name
        changes["name"] = name
    if is_active is not None:
        template.is_active = is_active
        changes["is_active"] = is_active
    await session.flush()
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="MESSAGE_TEMPLATE.UPDATE",
        entity_type="message_template",
        entity_id=str(template.id),
        details=changes,
    )
    return template
