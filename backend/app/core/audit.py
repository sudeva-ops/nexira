"""Audit log writer. Changes need human sign-off (D-29).

Inserts rows only. The database assigns chain_seq and computes the hash chain
(D-20); this module never reads, hashes, updates or deletes audit rows.

The row is written in the caller's transaction, so an audited change and its
audit entry commit or roll back together.
"""

from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog

ActorType = Literal["USER", "AGENT", "SYSTEM"]


async def write(
    session: AsyncSession,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Insert one audit row and flush it. The caller commits."""
    tenant_id = session.info.get("tenant_id")
    if tenant_id is None:
        raise RuntimeError("audit.write needs a tenant-scoped session (D-02)")
    row = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    session.add(row)
    await session.flush()
    return row
