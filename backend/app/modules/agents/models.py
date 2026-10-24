import uuid
from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # 0 AUTO · 1 AUTO_WITH_NOTICE · 2 APPROVE · 3 SENIOR_APPROVAL · 4 ADVISE_ONLY
    autonomy_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("2")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    model_ref: Mapped[str | None] = mapped_column(Text)


class ActionPolicy(Base):
    """Policy floors. An action type with no row is level 4, advise only (D-12)."""

    __tablename__ = "action_policy"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    min_autonomy_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # One entry per approval step; '|' separates alternative roles (D-16).
    approver_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    is_undoable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )  # D-13
    decision_deadline_s: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("900")
    )


class AgentProposal(Base):
    """effective_level and deadline_at are set by the agent_proposal_level trigger
    (D-12); the app never writes them. Approval rows are created by a trigger (D-16)."""

    __tablename__ = "agent_proposal"
    __server_generated__: ClassVar[tuple[str, ...]] = ("effective_level", "deadline_at")
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012  (read RETURNING values)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent.id"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id")
    )
    proposal_key: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action: Mapped[str] = mapped_column(Text, nullable=False)
    action_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )  # D-14
    risk_if_no_action: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    is_proactive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    effective_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=FetchedValue(), server_onupdate=FetchedValue()
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'PENDING'"))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_proposal.id")
    )
    edited_action: Mapped[str | None] = mapped_column(Text)
    edited_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), server_onupdate=FetchedValue()
    )
    undo_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposalApproval(Base):
    """Rows are created undecided by a trigger; steps are decided in order and once,
    by distinct people (D-16)."""

    __tablename__ = "proposal_approval"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_proposal.id", ondelete="CASCADE"), nullable=False
    )
    step_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    required_role: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    decision: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
