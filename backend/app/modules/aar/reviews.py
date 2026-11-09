"""Starting, deciding, finalising and exporting a review (AAR-01, AAR-05..07; D-47;
docs/plan-pilot-aar.md §5-§7). Role checks through app/core/approvals.py (D-05), with the
incident's mission as scope (D-06); every change through app/core/audit.py (D-20); the
database's guards hold the same rules (PC-49, PC-50). AAR_UPDATED carries the review's id only."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.approvals import user_has_role
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.aar import rules, service
from app.modules.aar.models import AarItem, AfterActionReview
from app.modules.aar.schemas import (
    AcceptIn,
    ItemIn,
    ItemOut,
    MetricOut,
    ReadyOut,
    ReviewOut,
    ReviewsOut,
    ReviewSummaryOut,
)

REVIEWERS = "SECURITY_OFFICER|DUTY_OFFICER|HQ_CRISIS_DIRECTOR|HEAD_OF_MISSION"  # §5
FINALISERS = "SECURITY_OFFICER|HQ_CRISIS_DIRECTOR"
REVIEWABLE = ("MONITORING", "CLOSED")  # §88 Q2


class AarError(Exception):
    """The request cannot be done: status_code 403, 404, 409 or 422."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def updated_event(review: AfterActionReview) -> Event:
    return Event(
        type="AAR_UPDATED",
        tenant_id=review.tenant_id,
        payload={"review_id": str(review.id)},
        source="aar",
    )


async def _audit(
    session: AsyncSession,
    user: CurrentUser,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any],
) -> None:
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action=f"AAR.{action}",
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )


async def _may(
    session: AsyncSession, user: CurrentUser, roles: str, mission_id: uuid.UUID | None
) -> bool:
    return await user_has_role(session, user, roles, mission_id)


async def _incident(session: AsyncSession, incident_id: uuid.UUID) -> service.Incident:
    found = await service.incident(session, incident_id)
    if found is None:
        raise AarError(404, "Incident not found")
    return found


async def _review(
    session: AsyncSession, review_id: uuid.UUID, *, lock: bool = False
) -> AfterActionReview:
    query = select(AfterActionReview).where(AfterActionReview.id == review_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    review = await session.scalar(query)
    if review is None:
        raise AarError(404, "Review not found")
    return review


def _item_out(item: AarItem) -> ItemOut:
    return ItemOut(
        id=item.id,
        rule_code=item.rule_code,
        finding=item.finding,
        action=item.action,
        owner_team=item.owner_team,
        priority=item.priority,
        evidence=item.evidence,
        status=item.status,
        due_on=item.due_on,
        reason=item.reason,
        decided_at=item.decided_at,
        done_at=item.done_at,
    )


# --- reading -----------------------------------------------------------------------------------

_SUMMARIES = text(
    """
    SELECT r.id, r.reference, i.reference AS incident_reference, i.title AS incident_title,
           r.status, r.started_at,
           count(a.id) FILTER (WHERE a.status IN ('ACCEPTED', 'DONE')) AS accepted,
           count(a.id) FILTER (WHERE a.status = 'DRAFT') AS drafts,
           count(a.id) AS items
      FROM after_action_review r
      JOIN incident i ON i.id = r.incident_id
      LEFT JOIN aar_item a ON a.review_id = r.id
     GROUP BY r.id, i.reference, i.title
     ORDER BY r.started_at DESC
    """
)

_READY = text(
    """
    SELECT i.id, i.reference, i.title, i.status, i.mission_id FROM incident i
     WHERE i.status IN ('MONITORING', 'CLOSED')
       AND NOT EXISTS (SELECT 1 FROM after_action_review r WHERE r.incident_id = i.id)
     ORDER BY coalesce(i.closed_at, i.updated_at) DESC, i.reference DESC
    """
)


async def list_reviews(session: AsyncSession, user: CurrentUser) -> ReviewsOut:
    reviews = [ReviewSummaryOut(**r._mapping) for r in await session.execute(_SUMMARIES)]
    ready = [
        ReadyOut(
            incident_id=r.id,
            reference=r.reference,
            title=r.title,
            status=r.status,
            can_start=await _may(session, user, REVIEWERS, r.mission_id),
        )
        for r in await session.execute(_READY)
    ]
    return ReviewsOut(reviews=reviews, ready=ready)


async def detail(
    session: AsyncSession, user: CurrentUser, review_id: uuid.UUID, now: datetime
) -> ReviewOut:
    review = await _review(session, review_id)
    found = await _incident(session, review.incident_id)
    final = review.status == "FINAL"
    # A final review shows the record as it was when it was finalised, and its frozen metrics.
    until = review.finalised_at if final and review.finalised_at else now
    metrics = (
        [MetricOut.model_validate(m) for m in (review.metrics or {}).get("metrics", [])]
        if final
        else await service.metrics(session, found, until)
    )
    items = await session.scalars(
        select(AarItem)
        .where(AarItem.review_id == review.id)
        .order_by(AarItem.rule_code.is_(None), AarItem.created_at, AarItem.rule_code)
    )
    return ReviewOut(
        id=review.id,
        reference=review.reference,
        incident_id=found.id,
        incident_reference=found.reference,
        incident_title=found.title,
        incident_status=found.status,
        status=review.status,
        started_at=review.started_at,
        finalised_at=review.finalised_at,
        label=rules.LABEL,
        metrics=metrics,
        timeline=await service.timeline(session, found, until),
        items=[_item_out(i) for i in items],
        can_act=await _may(session, user, REVIEWERS, found.mission_id),
        can_finalise=not final and await _may(session, user, FINALISERS, found.mission_id),
    )


# --- starting (AAR-01, AAR-04) -------------------------------------------------------------------


async def start(
    session: AsyncSession, user: CurrentUser, incident_id: uuid.UUID, now: datetime
) -> AfterActionReview:
    found = await _incident(session, incident_id)
    if not await _may(session, user, REVIEWERS, found.mission_id):
        raise AarError(403, "Starting a review needs a reviewer for this mission")
    if found.status not in REVIEWABLE:
        raise AarError(409, f"{found.reference} is still {found.status}")
    exists = await session.scalar(
        select(AfterActionReview.reference).where(AfterActionReview.incident_id == incident_id)
    )
    if exists is not None:
        raise AarError(409, f"{exists} already exists")
    review = AfterActionReview(
        tenant_id=session.info["tenant_id"], incident_id=incident_id, started_by=user.id
    )
    session.add(review)
    try:
        await session.flush()  # the guard writes the reference and started_at
    except IntegrityError:
        raise AarError(409, f"A review of {found.reference} already exists") from None
    drafts = await rules.draft(session, found, now)
    for d in drafts:
        session.add(
            AarItem(
                tenant_id=review.tenant_id,
                review_id=review.id,
                rule_code=d.rule_code,
                finding=d.finding,
                action=d.action,
                owner_team=d.owner_team,
                priority=d.priority,
                evidence=d.evidence,
            )
        )
    await session.flush()
    await _audit(
        session,
        user,
        "START",
        "after_action_review",
        review.reference,
        {"incident": found.reference, "drafts": [d.rule_code for d in drafts]},
    )
    return review


# --- deciding (AAR-05) ----------------------------------------------------------------------------


async def _item(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID
) -> tuple[AarItem, AfterActionReview]:
    item = await session.get(AarItem, item_id)
    if item is None:
        raise AarError(404, "Item not found")
    review = await _review(session, item.review_id)
    found = await _incident(session, review.incident_id)
    if not await _may(session, user, REVIEWERS, found.mission_id):
        raise AarError(403, "Deciding needs a reviewer for this mission")
    locked = await session.scalar(
        select(AarItem)
        .where(AarItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert locked is not None
    return locked, review


def _due(due_on: date, today: date) -> date:
    if due_on < today:
        raise AarError(422, "The due date is in the past")
    return due_on


async def accept(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID, body: AcceptIn, today: date
) -> AfterActionReview:
    item, review = await _item(session, user, item_id)
    if review.status != "DRAFT":
        raise AarError(409, f"{review.reference} is final")
    if item.status != "DRAFT":
        raise AarError(409, "Only a draft is accepted")
    item.status = "ACCEPTED"
    item.owner_team = body.owner_team
    item.due_on = _due(body.due_on, today)
    item.finding = body.finding or item.finding
    item.action = body.action or item.action
    item.priority = body.priority or item.priority
    item.decided_by = user.id
    await session.flush()
    await _audit(
        session,
        user,
        "ITEM_ACCEPT",
        "aar_item",
        str(item.id),
        {
            "review": review.reference,
            "rule": item.rule_code,
            "team": item.owner_team,
            "due_on": item.due_on.isoformat(),
            "reworded": bool(body.finding or body.action or body.priority),
        },
    )
    return review


async def reject(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID, reason: str
) -> AfterActionReview:
    item, review = await _item(session, user, item_id)
    if review.status != "DRAFT":
        raise AarError(409, f"{review.reference} is final")
    if item.status != "DRAFT":
        raise AarError(409, "Only a draft is rejected")
    item.status = "REJECTED"
    item.reason = reason.strip()
    item.decided_by = user.id
    await session.flush()
    await _audit(
        session,
        user,
        "ITEM_REJECT",
        "aar_item",
        str(item.id),
        {"review": review.reference, "rule": item.rule_code, "reason": item.reason},
    )
    return review


async def done(session: AsyncSession, user: CurrentUser, item_id: uuid.UUID) -> AfterActionReview:
    item, review = await _item(session, user, item_id)
    if item.status != "ACCEPTED":
        raise AarError(409, "Only an accepted action is marked done")
    item.status = "DONE"
    item.done_by = user.id
    await session.flush()
    await _audit(
        session,
        user,
        "ITEM_DONE",
        "aar_item",
        str(item.id),
        {"review": review.reference, "rule": item.rule_code},
    )
    return review


async def add(
    session: AsyncSession, user: CurrentUser, review_id: uuid.UUID, body: ItemIn, today: date
) -> AfterActionReview:
    review = await _review(session, review_id)
    found = await _incident(session, review.incident_id)
    if not await _may(session, user, REVIEWERS, found.mission_id):
        raise AarError(403, "Adding a lesson needs a reviewer for this mission")
    if review.status != "DRAFT":
        raise AarError(409, f"{review.reference} is final")
    item = AarItem(
        tenant_id=review.tenant_id,
        review_id=review.id,
        finding=body.finding.strip(),
        action=body.action.strip(),
        owner_team=body.owner_team,
        priority=body.priority,
        status="ACCEPTED",
        due_on=_due(body.due_on, today),
        decided_by=user.id,
    )
    session.add(item)
    await session.flush()
    await _audit(
        session,
        user,
        "ITEM_ADD",
        "aar_item",
        str(item.id),
        {"review": review.reference, "team": item.owner_team, "due_on": body.due_on.isoformat()},
    )
    return review


# --- finalising and exporting (AAR-06, AAR-07) ------------------------------------------------


async def finalise(
    session: AsyncSession, user: CurrentUser, review_id: uuid.UUID, now: datetime
) -> AfterActionReview:
    review = await _review(session, review_id)
    found = await _incident(session, review.incident_id)
    if not await _may(session, user, FINALISERS, found.mission_id):
        raise AarError(403, "Finalising needs a Security Officer or the HQ Crisis Director")
    review = await _review(session, review_id, lock=True)
    if review.status != "DRAFT":
        raise AarError(409, f"{review.reference} is already final")
    pending = await session.scalar(
        text("SELECT count(*) FROM aar_item WHERE review_id = :r AND status = 'DRAFT'"),
        {"r": review.id},
    )
    if pending:
        raise AarError(409, f"{pending} draft{'s' if pending != 1 else ''} still to be decided")
    metrics = await service.metrics(session, found, now)
    review.status = "FINAL"
    review.metrics = {"metrics": [m.model_dump(mode="json") for m in metrics]}
    review.finalised_by = user.id
    await session.flush()
    await _audit(
        session,
        user,
        "FINALISE",
        "after_action_review",
        review.reference,
        {"incident": found.reference, "metrics": [m.key for m in metrics if m.value is not None]},
    )
    return review


async def export(
    session: AsyncSession, user: CurrentUser, review_id: uuid.UUID, now: datetime
) -> ReviewOut:
    """AAR-07: the print-ready review's data; every export is audited, no file is kept."""
    out = await detail(session, user, review_id, now)
    await _audit(
        session,
        user,
        "EXPORT",
        "after_action_review",
        out.reference,
        {"status": out.status, "items": len(out.items)},
    )
    return out
