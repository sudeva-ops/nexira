import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, DateTime, FetchedValue, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, tenant_fk


class AuditLog(Base):
    """Append-only. chain_seq, prev_hash and row_hash are computed by the
    audit_log_chain trigger (D-20); the app never writes them."""

    __tablename__ = "audit_log"
    __server_generated__: ClassVar[tuple[str, ...]] = ("chain_seq", "prev_hash", "row_hash")
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (read RETURNING values)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    chain_seq: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=FetchedValue()
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    prev_hash: Mapped[str | None] = mapped_column(Text, server_default=FetchedValue())
    row_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
