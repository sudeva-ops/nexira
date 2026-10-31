import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, Boolean, Date, DateTime, ForeignKey, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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


class HealthAdvisory(Base):
    """An outbreak or health advisory for one or more countries (PC-26, HL-01). Reference
    intelligence, not an incident (D-39). Simulated (D-19). A newer bulletin moves only the
    level, guidance and status; a closed advisory is final; never deleted."""

    __tablename__ = "health_advisory"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    topic_code: Mapped[str] = mapped_column(Text, nullable=False)  # HEALTH_<code> (G-1)
    countries: Mapped[list[str]] = mapped_column(ARRAY(CHAR(2)), nullable=False)
    region_label: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    guidance: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'OPEN'"))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = updated_at()  # written by the guard


class MedicalFacility(Base):
    """A sample facility near a mission (PC-27, HL-04). Fictional; "Avoid" is computed."""

    __tablename__ = "medical_facility"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[GeoPoint] = geo_point()
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    trauma_level: Mapped[int | None] = mapped_column(SmallInteger)
    open_24_7: Mapped[bool] = mapped_column(Boolean, nullable=False)
    vetted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner.id")
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Sample facility (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()


class CountryHealthRequirement(Base):
    """Entry and vaccination requirements for a country (PC-28, HL-03). Illustrative."""

    __tablename__ = "country_health_requirement"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id"), primary_key=True
    )
    country_code: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    mandatory: Mapped[str] = mapped_column(Text, nullable=False)
    recommended: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative entry requirements (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()


class MissionHealthReadiness(Base):
    """Staff health readiness of a mission, counts only (PC-29, HL-05, D-39)."""

    __tablename__ = "mission_health_readiness"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id"), primary_key=True
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), primary_key=True
    )
    staff: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    blood_type_on_file: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    insurance_active: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    trauma_kits: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    vaccines_offered: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative readiness counts (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()
