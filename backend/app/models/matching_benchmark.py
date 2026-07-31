from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime

BENCHMARK_SUITE_STATUSES = ("blind", "revealed")
BENCHMARK_REVIEWER_ROLES = ("hr", "manager")
BENCHMARK_VERDICTS = ("interview", "consider", "reject", "insufficient_data")


class MatchingBenchmarkSuite(TimestampMixin, Base):
    """A synthetic, isolated evaluation suite; never references production talent."""

    __tablename__ = "matching_benchmark_suites"
    __table_args__ = (
        CheckConstraint(
            "status IN ('blind','revealed')",
            name="valid_status",
        ),
        CheckConstraint("case_count >= 0", name="nonnegative_case_count"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    fixture_version: Mapped[str] = mapped_column(String(30), nullable=False)
    fixture_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), default="blind", server_default="blind", nullable=False
    )
    case_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    revealed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revealed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    cases: Mapped[list["MatchingBenchmarkCase"]] = relationship(
        cascade="all, delete-orphan", back_populates="suite"
    )


class MatchingBenchmarkCase(TimestampMixin, Base):
    __tablename__ = "matching_benchmark_cases"
    __table_args__ = (
        UniqueConstraint("suite_id", "case_key", name="uq_benchmark_suite_case_key"),
        UniqueConstraint("suite_id", "sequence", name="uq_benchmark_suite_sequence"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint(
            "expected_verdict IN ('interview','consider','reject','insufficient_data')",
            name="valid_expected_verdict",
        ),
        CheckConstraint(
            "system_score >= 0 AND system_score <= 100",
            name="system_score_range",
        ),
        CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 100",
            name="data_completeness_range",
        ),
        Index("ix_benchmark_cases_suite_job", "suite_id", "job_key"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    suite_id: Mapped[int] = mapped_column(
        ForeignKey("matching_benchmark_suites.id", ondelete="CASCADE"), index=True
    )
    case_key: Mapped[str] = mapped_column(String(80), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    job_key: Mapped[str] = mapped_column(String(50), nullable=False)
    scenario: Mapped[str] = mapped_column(String(40), nullable=False)
    job_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    system_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    system_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    system_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_completeness: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    suite: Mapped[MatchingBenchmarkSuite] = relationship(back_populates="cases")
    ratings: Mapped[list["MatchingBenchmarkRating"]] = relationship(
        cascade="all, delete-orphan", back_populates="case"
    )


class MatchingBenchmarkRating(TimestampMixin, Base):
    __tablename__ = "matching_benchmark_ratings"
    __table_args__ = (
        UniqueConstraint("case_id", "reviewer_id", name="uq_benchmark_case_reviewer"),
        CheckConstraint(
            "reviewer_role IN ('hr','manager')",
            name="valid_reviewer_role",
        ),
        CheckConstraint(
            "verdict IN ('interview','consider','reject','insufficient_data')",
            name="valid_verdict",
        ),
        CheckConstraint(
            "priority_rank IS NULL OR priority_rank BETWEEN 1 AND 10",
            name="valid_priority_rank",
        ),
        Index("ix_benchmark_ratings_case_role", "case_id", "reviewer_role"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("matching_benchmark_cases.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reviewer_role: Mapped[str] = mapped_column(String(12), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    priority_rank: Mapped[int | None] = mapped_column(SmallInteger)

    case: Mapped[MatchingBenchmarkCase] = relationship(back_populates="ratings")

