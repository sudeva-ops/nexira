import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


class NotificationCampaign(Base):
    __tablename__ = "notification_campaign"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    reference: Mapped[str] = mapped_column(Text, nullable=False)  # next_reference('NTF', false)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id")
    )
    campaign_type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    translations: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )  # D-15
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    audience_filter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'DRAFT'"))
    created_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalate_after_s: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("600")
    )  # D-07
    created_at: Mapped[datetime] = created_at()


class NotificationDelivery(Base):
    __tablename__ = "notification_delivery"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_campaign.id", ondelete="CASCADE"),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'QUEUED'"))
    provider_ref: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
