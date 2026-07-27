from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime


class InterviewRecord(TimestampMixin, Base):
    """One structured, appendable record of an application interview session."""

    __tablename__ = "interview_records"
    __table_args__ = (
        CheckConstraint("stage IN ('hr','manager')", name="valid_stage"),
        CheckConstraint(
            "mode IN ('onsite','video','phone','other')",
            name="valid_mode",
        ),
        CheckConstraint(
            "status IN ('planned','in_progress','completed','cancelled','no_show')",
            name="valid_status",
        ),
        CheckConstraint(
            "recommendation IS NULL OR recommendation IN ('advance','hold','reject','offer')",
            name="valid_recommendation",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 1 AND 1440",
            name="valid_duration_minutes",
        ),
        CheckConstraint(
            "overall_rating IS NULL OR overall_rating BETWEEN 1 AND 5",
            name="valid_overall_rating",
        ),
        Index(
            "ix_interview_records_application_interviewed_at",
            "application_id",
            "interviewed_at",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    interviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    questions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    private_notes: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(String(20))
    overall_rating: Mapped[int | None] = mapped_column(Integer)

    # Names are snapshots so the historical record stays attributable even if a
    # user account is renamed or later removed. IDs retain the live relationship.
    interviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    interviewer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    updated_by_name: Mapped[str] = mapped_column(String(100), nullable=False)


class InterviewQuestionPlan(TimestampMixin, Base):
    """Versioned manager-question plan generated for one job application."""

    __tablename__ = "interview_question_plans"
    __table_args__ = (
        CheckConstraint(
            "generation_mode IN ('gemini','rules')",
            name="valid_generation_mode",
        ),
        UniqueConstraint("application_id", "version", name="application_version"),
        Index(
            "ix_interview_question_plans_application_version",
            "application_id",
            "version",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"), index=True
    )
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    questions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    personalization_basis: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100))
    generation_warning: Mapped[str | None] = mapped_column(Text)
    generated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    generated_by_name: Mapped[str] = mapped_column(String(100), nullable=False)
