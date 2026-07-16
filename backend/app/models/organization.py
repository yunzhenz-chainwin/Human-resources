from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    parent: Mapped[Department | None] = relationship(remote_side=[id])


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin','it','hr','manager')", name="valid_role"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Access tokens whose iat predates this instant are rejected, so a password
    # reset/change immediately invalidates already-issued access tokens.
    tokens_valid_after: Mapped[datetime | None] = mapped_column(UTCDateTime())

    department: Mapped[Department | None] = relationship()
