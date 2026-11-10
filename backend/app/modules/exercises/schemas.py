import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LaunchIn(BaseModel):
    """EXR-02. Only the template and the kind: the source, mission and times are never accepted
    (review of Prompt 113, L1)."""

    model_config = ConfigDict(extra="forbid")

    template: str = Field(min_length=1, max_length=100)  # the scenario's code
    kind: Literal["TABLETOP", "FUNCTIONAL", "FULL_SCALE"]


class AbandonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class TemplateOut(BaseModel):
    code: str
    name: str
    mission_id: uuid.UUID
    mission_code: str
    theme: str
    scenes: int  # after scene 0, each played with Next inject
    running: bool  # its mission has a running exercise
    can_launch: bool


class SceneOut(BaseModel):
    scene_no: int
    name: str  # never the scene's expected result, which gives the answer away (plan §2)


class RunOut(BaseModel):
    status: str  # IDLE, PLAYING, PAUSED, FINISHED
    current_scene: int
    scenes: list[SceneOut]


class ScoreOut(BaseModel):
    dimension: str
    score: int | None  # None is "—"
    measured: dict[str, Any]


class ExerciseSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    status: str  # RUNNING, COMPLETED, ABANDONED
    source: str  # EXERCISE, or ILLUSTRATIVE for the seeded history
    mission_id: uuid.UUID
    mission_code: str
    scenario_code: str | None
    incident_id: uuid.UUID | None
    incident_reference: str | None
    overall_score: int | None
    participants: int | None
    started_at: datetime
    ended_at: datetime | None


class ExerciseOut(ExerciseSummaryOut):
    reason: str | None
    scores: list[ScoreOut]  # once completed, frozen
    run: RunOut | None  # while running
    can_act: bool  # next inject, end, abandon


class KpisOut(BaseModel):
    this_year: int
    average: int | None
    average_last_year: int | None
    took_part: int
    personnel: int
    templates: int


class ExercisesOut(BaseModel):
    kpis: KpisOut
    exercises: list[ExerciseSummaryOut]
