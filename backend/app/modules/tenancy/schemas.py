import uuid

from pydantic import BaseModel


class RoleOut(BaseModel):
    code: str
    mission_id: uuid.UUID | None
    mission_code: str | None


class MeOut(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    roles: list[RoleOut]
