import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
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


class FleetAsset(Base):
    """A mission's vehicle or critical equipment (PC-33, FLT-01). Illustrative (D-19); seeded,
    and only its position, fuel and status change. Blocked, in an impact zone and assigned to
    an evacuation are worked out on read, not stored (§58 Q3)."""

    __tablename__ = "fleet_asset"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)  # VH-nn or <KIND>-<mission code>
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # VEHICLE, EQUIPMENT
    type_label: Mapped[str] = mapped_column(Text, nullable=False)
    armoured: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    seats: Mapped[int | None] = mapped_column(SmallInteger)  # passenger seats, vehicles only
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("person.id"))
    location: Mapped[GeoPoint] = geo_point()
    location_label: Mapped[str] = mapped_column(Text, nullable=False)
    fuel_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # AVAILABLE, IN_USE, MAINTENANCE
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'AVAILABLE'"))
    status_reason: Mapped[str | None] = mapped_column(Text)  # required for MAINTENANCE
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative asset register (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class FleetMaintenance(Base):
    """A maintenance item on an asset (PC-34, FLT-04): done once, by a person or the
    simulated workshop; the database writes the time."""

    __tablename__ = "fleet_maintenance"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fleet_asset.id"), nullable=False
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by_type: Mapped[str | None] = mapped_column(Text)  # USER, WORKSHOP
    done_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
