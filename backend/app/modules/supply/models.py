import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


def _status_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Supplier(Base):
    """A third party a mission depends on (PC-43, SUP-01). Illustrative (D-19); seeded, and only
    its reported status changes. ROUTE BLOCKED and "impacted" are worked out on read (§73 Q2)."""

    __tablename__ = "supplier"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(Text, nullable=False)  # SUP-nnn
    name: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    # None: Global, never impacted by a mission's incident.
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id")
    )
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1 critical .. 3 routine
    backup_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier.id")
    )
    in_bcp: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    vetting_valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    performance_score: Mapped[int | None] = mapped_column(SmallInteger)
    # NORMAL, WATCH, DELAYED, AT_RISK
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'NORMAL'"))
    status_detail: Mapped[str | None] = mapped_column(Text)
    status_at: Mapped[datetime] = _status_at()  # written by the database
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative supplier register (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()


class LogisticsRoute(Base):
    """A courier, fuel, staff or freight route of a mission, as a line (PC-44, SUP-02, §73 Q5);
    only its reported status changes. ALTERNATE is worked out on read."""

    __tablename__ = "logistics_route"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)  # R-<mission>-n
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # POUCH, FUEL, STAFF_TRANSPORT, FREIGHT
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier.id")
    )
    alternate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("logistics_route.id")
    )
    path: Mapped[Any] = mapped_column(
        Geography(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False
    )
    # OPEN, RESTRICTED, DELAYED, BLOCKED
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'OPEN'"))
    detail: Mapped[str | None] = mapped_column(Text)
    status_at: Mapped[datetime] = _status_at()  # written by the database
    created_at: Mapped[datetime] = created_at()


class SupplyMitigation(Base):
    """A mitigation recorded by a person (PC-45, SUP-04): the backup on standby and the
    alternate route in use. One active per supplier; stood down once. Nothing is sent."""

    __tablename__ = "supply_mitigation"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id")
    )
    backup_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier.id")
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("logistics_route.id")
    )
    note: Mapped[str | None] = mapped_column(Text)
    activated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    activated_at: Mapped[datetime] = created_at()  # written by the database
    stood_down_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    stood_down_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
