"""Audit log read API (PLT-04). The log itself is written only via app/core/audit.py.

- GET /api/audit with entity_type and entity_id: any user with a role. Screens
  such as the playbook run's audit trail panel need it (plan G-06).
- GET /api/audit without that filter, and GET /api/audit/verify: ADMIN only.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles, user_has_role
from app.core.security import CurrentUser, get_db
from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import AuditEntryOut, AuditVerifyOut
from app.modules.tenancy.service import ROLES

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def list_audit(
    user: Annotated[CurrentUser, Depends(require_roles(*ROLES))],
    session: Annotated[AsyncSession, Depends(get_db)],
    entity_type: str | None = None,
    entity_id: str | None = None,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEntryOut]:
    """Newest first. Page with before_seq = the last chain_seq you received."""
    filtered = entity_type is not None and entity_id is not None
    if not filtered and not await user_has_role(session, user, "ADMIN"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only ADMIN may list the audit log without an entity filter"
        )
    query = select(AuditLog).order_by(AuditLog.chain_seq.desc()).limit(limit)
    if entity_type is not None:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if before_seq is not None:
        query = query.where(AuditLog.chain_seq < before_seq)
    rows = await session.scalars(query)
    return [AuditEntryOut.model_validate(r) for r in rows]


@router.get("/verify")
async def verify_audit(
    _admin: Annotated[CurrentUser, Depends(require_roles("ADMIN"))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuditVerifyOut:
    """Recompute the tenant's hash chain in the database (D-20)."""
    broken = await session.scalar(text("SELECT audit_verify_chain()"))
    rows = await session.scalar(select(func.count()).select_from(AuditLog))
    return AuditVerifyOut(intact=broken is None, first_broken_seq=broken, rows=rows or 0)
