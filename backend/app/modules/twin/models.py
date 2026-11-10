import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


def _site() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("site.id"), nullable=False)


class SiteZone(Base):
    """A zone of a site's floor plan, in plan units (PC-39, TWN-01). Seeded; read-only."""

    __tablename__ = "site_zone"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    site_id: Mapped[uuid.UUID] = _site()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # OFFICE, SUITE, CONFERENCE, COMMS, SAFE_ROOM, LOBBY, CONSULAR, MUSTER, GATE
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    w: Mapped[int] = mapped_column(Integer, nullable=False)
    h: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer)  # SAFE_ROOM and MUSTER only
    created_at: Mapped[datetime] = created_at()


class SiteRoute(Base):
    """An evacuation route on the plan, leaving by a gate (PC-40, TWN-04)."""

    __tablename__ = "site_route"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    site_id: Mapped[uuid.UUID] = _site()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'EVACUATION'"))
    path: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)  # [[x, y], ...]
    exit_zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = created_at()


class SitePresence(Base):
    """Who is in which zone now (PC-41, TWN-02). Staff are people of the site's mission;
    guards and visitors are labels, never names. Never a location observation (D-43)."""

    __tablename__ = "site_presence"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    site_id: Mapped[uuid.UUID] = _site()
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # STAFF, GUARD, VISITOR
    person_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("person.id"))
    label: Mapped[str | None] = mapped_column(Text)  # "Guard 2", "Visitor 7"
    since: Mapped[datetime] = created_at()  # written by the database on insert and each move
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'Access control + Wi-Fi presence (simulated)'"),
    )


class SiteSensor(Base):
    """A sensor or system of a site (PC-42, TWN-03); only status and detail change. A camera
    carries its mount (PC-53, TWN-08)."""

    __tablename__ = "site_sensor"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    site_id: Mapped[uuid.UUID] = _site()
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(Text, nullable=False)
    # GATE, BADGE_READER, CCTV, SAFE_ROOM, ACCESS, ALARM
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # OK, DEGRADED, FAULT, OFFLINE
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'OK'"))
    detail: Mapped[str | None] = mapped_column(Text)
    status_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = created_at()
    # PC-53 (TWN-08): a camera's mount, in plan units; all set for CCTV, all null otherwise.
    mount_x: Mapped[int | None] = mapped_column(Integer)
    mount_y: Mapped[int | None] = mapped_column(Integer)
    heading_deg: Mapped[int | None] = mapped_column(Integer)  # 0 = up the plan, clockwise
    fov_deg: Mapped[int | None] = mapped_column(Integer)
    range_u: Mapped[int | None] = mapped_column(Integer)


class SiteReadinessItem(Base):
    """An emergency readiness item (PC-42, TWN-05): done once, by a person of the tenant."""

    __tablename__ = "site_readiness_item"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    site_id: Mapped[uuid.UUID] = _site()
    label: Mapped[str] = mapped_column(Text, nullable=False)
    done_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
