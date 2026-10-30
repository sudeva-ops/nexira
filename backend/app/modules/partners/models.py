import uuid
from datetime import datetime

from sqlalchemy import CHAR, Boolean, DateTime, FetchedValue, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, GeoPoint, created_at, geo_point, tenant_fk, uuid_pk

SERVICES = ("MEDICAL", "EVACUATION", "SECURE_TRANSPORT", "WELFARE", "RELOCATION")
STATUSES = ("REQUESTED", "ACCEPTED", "EN_ROUTE", "COMPLETED", "DECLINED", "CANCELLED")


class Partner(Base):
    """A contracted assistance partner (PC-21, D-36): fictional and simulated (D-19)."""

    __tablename__ = "partner"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    services: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    coverage: Mapped[list[str]] = mapped_column(ARRAY(CHAR(2)), nullable=False)
    sla_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    hours: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'24/7'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()


class PartnerRequest(Base):
    """A request for support and its tracking (PC-22). The guard trigger enforces the
    status table, frozen content and database-written timestamps (plan-pilot-ast §2, §7)."""

    __tablename__ = "partner_request"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner.id"), nullable=False
    )
    service: Mapped[str] = mapped_column(Text, nullable=False)
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id")
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("person.id"))
    place_label: Mapped[str | None] = mapped_column(Text)
    location: Mapped[GeoPoint | None] = geo_point(nullable=True)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'REQUESTED'"))
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_type: Mapped[str] = mapped_column(Text, nullable=False)  # USER, PLAYBOOK
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    # Written by the guard trigger: the ORM reads them back rather than trusting its own
    # values (review of Prompt 44, N9).
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=FetchedValue()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=FetchedValue(),
        server_onupdate=FetchedValue(),
    )
