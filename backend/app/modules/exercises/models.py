import uuid
from datetime import datetime
from types import MappingProxyType
from typing import Any

from sqlalchemy import DateTime, FetchedValue, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


def _ref(table: str, nullable: bool = True) -> Mapped[Any]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id"), nullable=nullable)


class Exercise(Base):
    """An exercise (PC-51, EXR-02, EXR-04): a scenario run in EXERCISE mode, RUNNING, then
    COMPLETED or ABANDONED once; or a seeded ILLUSTRATIVE one, added COMPLETED with its own
    past dates. The database writes a real exercise's start and end times."""

    __tablename__ = "exercise"
    __mapper_args__ = MappingProxyType({"eager_defaults": True})  # read what the guard writes

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    mission_id: Mapped[uuid.UUID] = _ref("mission", nullable=False)
    scenario_id: Mapped[uuid.UUID | None] = _ref("scenario")  # null for an illustrative one
    scenario_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_run.id"), unique=True
    )
    incident_id: Mapped[uuid.UUID | None] = _ref("incident")  # the scored one, set when ended
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # TABLETOP, FUNCTIONAL, FULL_SCALE
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'RUNNING'"))
    overall_score: Mapped[int | None] = mapped_column(SmallInteger)
    participants: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)  # for an abandon
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'EXERCISE'"))
    started_by: Mapped[uuid.UUID | None] = _ref("app_user")
    started_at: Mapped[datetime] = created_at()
    ended_by: Mapped[uuid.UUID | None] = _ref("app_user")
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )


class ExerciseScore(Base):
    """One of a completed exercise's five scores (PC-52, EXR-05), frozen; null is "—"."""

    __tablename__ = "exercise_score"
    __mapper_args__ = MappingProxyType({"eager_defaults": True})

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    exercise_id: Mapped[uuid.UUID] = _ref("exercise", nullable=False)
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    measured: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = created_at()
