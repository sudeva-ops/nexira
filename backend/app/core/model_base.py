"""Declarative base and column helpers shared by all module models.

Models mirror docs/schema/nexira_schema.sql; the database is created by Alembic
from that file, never from this metadata.
"""

import uuid
from datetime import datetime
from typing import Any, ClassVar

from geoalchemy2 import Geography
from sqlalchemy import DateTime, FetchedValue, ForeignKey, MetaData, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Values for geography(Point,4326) columns: a WKBElement when read; when writing,
# a WKTElement or an EWKT string such as "SRID=4326;POINT(36.8245 -1.2838)".
GeoPoint = Any


class Base(DeclarativeBase):
    metadata = MetaData()

    # Columns the database sets (triggers or defaults the app must not override).
    # A before_flush guard in app/core/db.py rejects any write to them.
    __server_generated__: ClassVar[tuple[str, ...]] = ()


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False)


def geo_point(nullable: bool = False) -> Mapped[GeoPoint]:
    return mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=nullable
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


def updated_at() -> Mapped[datetime]:
    """Set on insert by default and on update by the set_updated_at() trigger."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        server_onupdate=FetchedValue(),
    )
