import uuid

from pydantic import BaseModel


class SceneOut(BaseModel):
    scene_no: int
    name: str
    expect: str | None  # the expected result, shown by the presenter bar
    events: int


class ScenarioStateOut(BaseModel):
    code: str
    name: str
    run_id: uuid.UUID
    status: str  # IDLE, PLAYING, PAUSED, FINISHED
    current_scene: int
    position: int  # events of the current scene already played
    scene_complete: bool
    scenes: list[SceneOut]


class NormalDayIn(BaseModel):
    on: bool


class NormalDayOut(BaseModel):
    """TWN-13 (D-53): whether the Site Twin's normal day runs for this tenant."""

    on: bool
