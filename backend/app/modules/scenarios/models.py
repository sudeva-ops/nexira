import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, tenant_fk, uuid_pk


class Scenario(Base):
    __tablename__ = "scenario"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ScenarioEvent(Base):
    __tablename__ = "scenario_event"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario.id", ondelete="CASCADE"), nullable=False
    )
    scene_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    offset_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ScenarioRun(Base):
    __tablename__ = "scenario_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DEMO'"))
    current_scene: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'IDLE'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
