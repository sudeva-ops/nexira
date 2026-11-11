import uuid
from datetime import datetime
from types import MappingProxyType
from typing import Any, ClassVar

from geoalchemy2 import Geography
from sqlalchemy import DateTime, FetchedValue, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


def _ref(table: str, nullable: bool = True) -> Mapped[Any]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id"), nullable=nullable)


class MapAnnotation(Base):
    """A mark, line or area on the world map (PC-54, ANN-01..ANN-06): added ACTIVE; the label,
    note, shape and end time change; withdrawn once, with a reason; never deleted. The database
    writes the times; kind, author, incident and mission are fixed (the guard)."""

    __tablename__ = "map_annotation"
    __mapper_args__ = MappingProxyType({"eager_defaults": True})  # read what the guard writes
    __server_generated__: ClassVar[tuple[str, ...]] = ("created_at", "updated_at", "withdrawn_at")

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID | None] = _ref("mission")  # plan-pilot-map G-2
    incident_id: Mapped[uuid.UUID | None] = _ref("incident")
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # MARK, LINE, AREA
    symbol: Mapped[str | None] = mapped_column(Text)  # a MARK's only
    shape: Mapped[Any] = mapped_column(
        Geography(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ACTIVE'"))
    reason: Mapped[str | None] = mapped_column(Text)  # set when WITHDRAWN
    created_by: Mapped[uuid.UUID] = _ref("app_user", nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_by: Mapped[uuid.UUID | None] = _ref("app_user")
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )
    withdrawn_by: Mapped[uuid.UUID | None] = _ref("app_user")
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )
