"""Playbook services. Prompt 4: definitions. The run engine arrives in Prompt 9."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.modules.playbooks.models import Playbook, PlaybookStep
from app.modules.tenancy.service import SYSTEM, Actor


@dataclass(frozen=True)
class StepIn:
    seq: int
    name: str
    action_type: str  # NOTIFY, CHECKIN, TASK, PARTNER_REQUEST, APPROVAL_GATE, BRIEFING
    action_config: dict[str, Any] = field(default_factory=dict)
    requires_approval_role: str | None = None  # mission scope from incident.mission_id (D-06)


async def ensure_playbook(
    session: AsyncSession,
    *,
    playbook_id: uuid.UUID,
    code: str,
    name: str,
    category: str,
    trigger_rules: dict[str, Any],
    steps: list[StepIn],
    step_ids: list[uuid.UUID],
    version: int = 1,
    actor: Actor = SYSTEM,
) -> bool:
    """Create a playbook version with its steps if it does not exist. Audited on create."""
    if len(step_ids) != len(steps):
        raise ValueError("one step id per step")
    tenant_id = session.info["tenant_id"]
    created = await session.scalar(
        insert(Playbook)
        .values(
            id=playbook_id,
            tenant_id=tenant_id,
            code=code,
            name=name,
            category=category,
            trigger_rules=trigger_rules,
            version=version,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "code", "version"])
        .returning(Playbook.id)
    )
    if created is None:
        return False
    await session.execute(
        insert(PlaybookStep).values(
            [
                {
                    "id": step_id,
                    "tenant_id": tenant_id,
                    "playbook_id": playbook_id,
                    "seq": s.seq,
                    "name": s.name,
                    "action_type": s.action_type,
                    "action_config": s.action_config,
                    "requires_approval_role": s.requires_approval_role,
                }
                for s, step_id in zip(steps, step_ids, strict=True)
            ]
        )
    )
    await audit.write(
        session,
        actor_type=actor.type,
        actor_id=actor.id,
        action="PLAYBOOK.CREATE",
        entity_type="playbook",
        entity_id=str(playbook_id),
        details={"code": code, "version": version, "steps": len(steps)},
    )
    return True
