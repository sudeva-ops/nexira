import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    text,
)
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


class IntelSource(Base):
    __tablename__ = "intel_source"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    connector_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'SIMULATED'")
    )
    reliability: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default=text("0.50")
    )  # D-10
    severity_map: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    category_map: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    takes_part_in_fusion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )  # D-09
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class RawSignal(Base):
    __tablename__ = "raw_signal"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intel_source.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text, server_default=text("'en'"))
    provider_category: Mapped[str | None] = mapped_column(Text)
    provider_severity: Mapped[str | None] = mapped_column(Text)
    location: Mapped[GeoPoint | None] = geo_point(nullable=True)
    place_label: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    norm_category: Mapped[str | None] = mapped_column(Text)
    norm_severity: Mapped[str | None] = mapped_column(Text)
    norm_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'NEW'"))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class Incident(Base):
    __tablename__ = "incident"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # next_reference('INC', true)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    signal_severity: Mapped[str] = mapped_column(Text, nullable=False)  # D-11
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ACTIVE'"))
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id")
    )  # D-06
    location: Mapped[GeoPoint] = geo_point()
    impact_radius_m: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5000")
    )
    place_label: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_signal_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )  # D-10
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class IncidentSignal(Base):
    __tablename__ = "incident_signal"

    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id", ondelete="CASCADE"), primary_key=True
    )
    signal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("raw_signal.id"), primary_key=True
    )


class IncidentExposure(Base):
    """subject_id is polymorphic (person / site / trip) and has no foreign key."""

    __tablename__ = "incident_exposure"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IncidentEvent(Base):
    __tablename__ = "incident_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
