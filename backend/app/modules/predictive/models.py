import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Date, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


def _mission() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("mission.id"), nullable=False)


class RiskIndex(Base):
    """A mission's risk index for one day (PC-46, PRD-01): ILLUSTRATIVE history before today,
    then one COMPUTED row a day, updated by the snapshot during that day only."""

    __tablename__ = "risk_index"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = _mission()
    day: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0..100
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # driver -> points
    source: Mapped[str] = mapped_column(Text, nullable=False)  # COMPUTED, ILLUSTRATIVE
    computed_at: Mapped[datetime] = created_at()  # written by the database


class MissionEvent(Base):
    """A scheduled event in a mission's calendar (PC-47, PRD-05). Simulated; fixed once added."""

    __tablename__ = "mission_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = _mission()
    # RALLY, ELECTION, HOLIDAY, SUMMIT, SPORTS, OTHER
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    place_label: Mapped[str | None] = mapped_column(Text)
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    attendance: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1..30
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative events calendar (simulated)'")
    )
    created_at: Mapped[datetime] = created_at()
