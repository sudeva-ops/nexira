import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, Date, DateTime, FetchedValue, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, tenant_fk, uuid_pk

DOC_TYPES = (
    "PASSPORT",
    "DIPLOMATIC_PASSPORT",
    "VISA",
    "RESIDENCE_PERMIT",
    "ACCREDITATION",
    "SECURITY_CLEARANCE",
)
RENEWAL = ("NONE", "REQUESTED", "IN_PROGRESS", "RENEWED")


class TravelDocument(Base):
    """A staff member's or dependant's travel or status document (PC-23, D-37): simulated,
    and never its number, scan or photo. The guard trigger enforces the forward-only
    renewal, who did each step and the database-written times (plan-pilot-dx §6, G-1)."""

    __tablename__ = "travel_document"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    issuing_country: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    renewal_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'NONE'"))
    renewal_requested_by: Mapped[str | None] = mapped_column(Text)
    renewal_started_by: Mapped[str | None] = mapped_column(Text)
    renewed_by: Mapped[str | None] = mapped_column(Text)
    # Written by the guard trigger: the ORM reads them back (as partner_request).
    renewal_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    renewal_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )
