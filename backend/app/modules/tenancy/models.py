import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, created_at, tenant_fk, uuid_pk


class Tenant(Base):
    """Readable by nexira_api for its own row only; only the kill-switch columns are
    writable (D-17). Tenants are created by nexira_owner (plan G-03)."""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    hosting_region: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'in-country'")
    )
    oidc_issuer: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # D-04
    agents_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    agents_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agents_paused_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id")
    )
    created_at: Mapped[datetime] = created_at()


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    external_id: Mapped[str] = mapped_column(Text, nullable=False)  # OIDC sub (D-04)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()


class Role(Base):
    __tablename__ = "role"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class UserRole(Base):
    """mission_id NULL means the role applies to all missions (D-05)."""

    __tablename__ = "user_role"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("role.id", ondelete="CASCADE"), nullable=False
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission.id")
    )


class ReferenceCounter(Base):
    """Written only by next_reference() (D-18)."""

    __tablename__ = "reference_counter"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant.id"), primary_key=True
    )
    prefix: Mapped[str] = mapped_column(Text, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("0"))
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
