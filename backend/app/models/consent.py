from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime


class ConsentNotice(TimestampMixin, Base):
    """A versioned recruitment privacy notice / consent clause (PDPA §8/§9).

    Only one notice may be ``is_active`` at any moment; the activation workflow
    (see :mod:`app.services.consent`) deactivates every other row when a version
    is turned on so candidates always consent against a single current text.
    """

    __tablename__ = "consent_notices"
    __table_args__ = (
        UniqueConstraint("version", name="uq_consent_notices_version"),
        CheckConstraint("version >= 1", name="ck_consent_notices_positive_version"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    purpose_code: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class CandidateConsent(Base):
    """Immutable record that a candidate consented to a specific notice version."""

    __tablename__ = "candidate_consents"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("consent_notices.id"), index=True, nullable=False
    )
    # Redundant copy of the version so the exact consented text stays traceable
    # even if the notice row is ever renumbered or archived.
    notice_version: Mapped[int] = mapped_column(Integer, nullable=False)
    consented_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(30), default="hr_manual", server_default="hr_manual", nullable=False
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
