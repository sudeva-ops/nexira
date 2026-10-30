import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base


class WeatherCurrent(Base):
    """Current simulated conditions, one row per mission (PC-20, D-35). Written by the
    simulated feed; D-19: shown as simulated."""

    __tablename__ = "weather_current"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id"), primary_key=True
    )
    mission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id"), primary_key=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)  # CLEAR, CLOUD, RAIN, ...
    wind_kph: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gust_kph: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rain_mm: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, server_default=text("0")
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'xWeather (simulated)'")
    )
