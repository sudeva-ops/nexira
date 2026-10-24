import uuid

from pydantic import BaseModel


class SceneOut(BaseModel):
    scene_no: int
    name: str
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
