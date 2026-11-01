import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, SmallInteger, Text, text
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


class EvacuationPlan(Base):
    """A mission's evacuation plan (PC-30, EV-01): muster point, route, destination and up
    to three transport options, PRIMARY first. Illustrative (D-19); seeded, never changed."""

    __tablename__ = "evacuation_plan"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # EVP-<mission code>
    muster_name: Mapped[str] = mapped_column(Text, nullable=False)
    muster_location: Mapped[GeoPoint] = geo_point()
    route_label: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"role", "kind", "label", "seats", "partner_id"}], checked by the guard
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative evacuation plan (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()


class Evacuation(Base):
    """One evacuation of a mission (PC-31, EV-02, EV-05, EV-07): requested by one person,
    activated by another (D-40), then its six steps until complete or stood down. The
    database writes the times; status and step move forward only."""

    __tablename__ = "evacuation"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # EVN-<n>
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evacuation_plan.id"), nullable=False
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id")
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_proposal.id")
    )
    # PENDING_ACTIVATION, ACTIVE, COMPLETED, STOOD_DOWN
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING_ACTIVATION'")
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    requested_role: Mapped[str] = mapped_column(Text, nullable=False)  # plan-pilot-ev G-1
    requested_at: Mapped[datetime] = created_at()
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    step: Mapped[int | None] = mapped_column(SmallInteger)  # 1..6 once activated
    step_times: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    stood_down_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    stood_down_reason: Mapped[str | None] = mapped_column(Text)
    stood_down_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class EvacuationManifestEntry(Base):
    """One person on an evacuation's manifest (PC-32, EV-03, EV-04). Built at activation and
    never changed except by one check-in, which gives the seat."""

    __tablename__ = "evacuation_manifest"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    evacuation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evacuation.id"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # STAFF, DELEGATE, DEPENDANT, CITIZEN
    seat: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'EXPECTED'"))
    checked_in_by_type: Mapped[str | None] = mapped_column(Text)  # USER, SCANNER
    checked_in_by: Mapped[str | None] = mapped_column(Text)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
