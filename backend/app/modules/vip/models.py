import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import (
    Base,
    GeoPoint,
    created_at,
    geo_point,
    tenant_fk,
    updated_at,
    uuid_pk,
)


class VipVisit(Base):
    """A senior visit or delegation (PC-35, VIP-01, VIP-04). Illustrative (D-19); the principal
    by role only (§63 Q3); seen only by the protection roles (VIP-06). Never a position."""

    __tablename__ = "vip_visit"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # VV-<year>-<n>
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    principal_role: Mapped[str] = mapped_column(Text, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("trip.id"))
    # PLANNED, LIVE, COMPLETED, CANCELLED
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PLANNED'"))
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative visit (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class VipSegment(Base):
    """One segment of a visit's programme (PC-36). Its risk is worked out on read (VIP-02);
    its time and "virtual" change only with an approved change (PC-38)."""

    __tablename__ = "vip_segment"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vip_visit.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # ARRIVAL, MOTORCADE, MEETING, EVENT, SITE_VISIT, DEPARTURE
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    venue_name: Mapped[str] = mapped_column(Text, nullable=False)
    venue_location: Mapped[GeoPoint] = geo_point()
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attendees: Mapped[int | None] = mapped_column(Integer)
    virtual: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # PLANNED, IN_PROGRESS, COMPLETED
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PLANNED'"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class VipSegmentChange(Base):
    """A programme change proposed by one person and decided by another (PC-38, VIP-05)."""

    __tablename__ = "vip_segment_change"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vip_segment.id"), nullable=False
    )
    new_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    make_virtual: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    proposed_at: Mapped[datetime] = created_at()
    # PENDING, APPROVED, REJECTED
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING'"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


class VipChecklistItem(Base):
    """A pre-visit checklist item (PC-37, VIP-03): done once, by a person of the tenant."""

    __tablename__ = "vip_checklist_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vip_visit.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    done_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
