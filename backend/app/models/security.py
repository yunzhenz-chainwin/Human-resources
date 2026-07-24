from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    jti_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SkillCatalog(TimestampMixin, Base):
    __tablename__ = "skill_catalog"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", "category", name="uq_tag_name_category"),)

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="candidate", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class SystemSetting(TimestampMixin, Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(String(255))
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    details: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )


class RetentionStorageDeletion(TimestampMixin, Base):
    """Durable outbox for deleting candidate files after database erasure.

    Candidate identifiers and original filenames are intentionally absent. The
    locator is an opaque random storage key or an internal photo path and is
    removed along with the row once deletion succeeds.
    """

    __tablename__ = "retention_storage_deletions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('resume','candidate_photo')", name="valid_retention_storage_kind"
        ),
        UniqueConstraint("kind", "locator", name="uq_retention_storage_kind_locator"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    locator: Mapped[str] = mapped_column(String(1000), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(100))


class SystemIssue(TimestampMixin, Base):
    """Operational issue tracker. It must never contain candidate data."""

    __tablename__ = "system_issues"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    expected_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reproduction_steps: Mapped[str | None] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
