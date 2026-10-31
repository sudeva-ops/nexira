import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base


class MissionClimateRisk(Base):
    """Long-term climate exposure, one row per mission (PC-25, HZ-08). Illustrative and
    fictional; D-19: shown as simulated. Seeded; never updated or deleted in the pilot."""

    __tablename__ = "mission_climate_risk"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id"), primary_key=True
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), primary_key=True
    )
    hazards: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    score_today: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_2050: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Illustrative climate model (simulated)'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
