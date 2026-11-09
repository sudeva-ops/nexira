import uuid
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

from sqlalchemy import Date, DateTime, FetchedValue, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


def _user(nullable: bool) -> Mapped[Any]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=nullable)


def _written() -> Mapped[datetime | None]:
    """A time the guard writes on insert or update (review of Prompt 107, L4)."""
    return mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )


class AfterActionReview(Base):
    """One review per incident (PC-49, AAR-01, AAR-06): DRAFT, then FINAL once, with the metrics
    frozen. The database writes the reference from the incident's and the times."""

    __tablename__ = "after_action_review"
    __mapper_args__ = MappingProxyType({"eager_defaults": True})  # read what the guard writes

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id"), nullable=False, unique=True
    )
    # AAR-<year>-<n>, written by the guard from the incident's
    reference: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DRAFT'"))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # frozen when FINAL
    started_by: Mapped[uuid.UUID] = _user(nullable=False)
    started_at: Mapped[datetime] = created_at()
    finalised_by: Mapped[uuid.UUID | None] = _user(nullable=True)
    finalised_at: Mapped[datetime | None] = _written()


class AarItem(Base):
    """A lesson and its action (PC-50, AAR-04, AAR-05): a rule's draft that a person decides,
    or a reviewer's own, accepted when added. DRAFT → ACCEPTED or REJECTED, ACCEPTED → DONE."""

    __tablename__ = "aar_item"
    __mapper_args__ = MappingProxyType({"eager_defaults": True})  # read what the guard writes

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("after_action_review.id"), nullable=False
    )
    rule_code: Mapped[str | None] = mapped_column(Text)  # null for a reviewer's own
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    owner_team: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)  # HIGH, MEDIUM, LOW
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DRAFT'"))
    due_on: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)  # for a rejection
    decided_by: Mapped[uuid.UUID | None] = _user(nullable=True)
    decided_at: Mapped[datetime | None] = _written()
    done_by: Mapped[uuid.UUID | None] = _user(nullable=True)
    done_at: Mapped[datetime | None] = _written()
    created_at: Mapped[datetime] = created_at()
