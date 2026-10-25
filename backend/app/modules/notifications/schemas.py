import uuid
from datetime import datetime

from pydantic import BaseModel


class CampaignOut(BaseModel):
    id: uuid.UUID
    reference: str
    incident_id: uuid.UUID | None
    campaign_type: str  # ALERT, CHECKIN, ADVISORY, TEST
    message: str
    channels: list[str]
    status: str  # DRAFT, SENDING, SENT, CANCELLED
    created_by_type: str
    created_at: datetime
    sent_at: datetime | None
    escalate_after_s: int
    recipients: int
    deliveries: dict[str, int]  # by status: QUEUED, SENT, DELIVERED, READ, FAILED
    simulated: bool  # D-19: Phase 1 channels are simulated
