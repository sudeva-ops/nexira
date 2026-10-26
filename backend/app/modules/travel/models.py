import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CHAR, Date, DateTime, ForeignKey, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, GeoPoint, created_at, geo_point, tenant_fk, uuid_pk


class Trip(Base):
    __tablename__ = "trip"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    destination_country: Mapped[str | None] = mapped_column(CHAR(2))
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'LOW'"))
    approval_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'DRAFT'")
    )  # DRAFT, PENDING, APPROVED, CANCELLED (REJECTED: 0001 rows only)
    created_at: Mapped[datetime] = created_at()
    # PC-15 (D-32): approval and checklist. requested_by NULL: a seeded trip.
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id")
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_risk_level: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    checklist: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class TripTraveller(Base):
    __tablename__ = "trip_traveller"

    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id"), primary_key=True
    )


class TripSegment(Base):
    """The itinerary (PC-14): one flight, stay, meeting or ground leg."""

    __tablename__ = "trip_segment"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trip.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # FLIGHT, STAY, MEETING, GROUND
    title: Mapped[str] = mapped_column(Text, nullable=False)
    place_label: Mapped[str | None] = mapped_column(Text)
    location: Mapped[GeoPoint] = geo_point(nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CountryRisk(Base):
    """Simulated base risk per country (PC-16, D-19)."""

    __tablename__ = "country_risk"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id"), primary_key=True
    )
    country_code: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)  # D-08
    security: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    unrest: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    health: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    transport: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
