from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chain_seq: int
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any]
    prev_hash: str | None
    row_hash: str


class AuditVerifyOut(BaseModel):
    intact: bool
    first_broken_seq: int | None
    rows: int
