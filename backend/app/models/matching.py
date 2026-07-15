from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime

MATCH_STATUSES = (
    "ineligible",
    "recommended",
    "shortlisted",
    "contacted",
    "interview",
    "offered",
    "hired",
    "rejected_by_manager",
    "withdrawn",
)


class MatchResult(TimestampMixin, Base):
    __tablename__ = "match_results"
    __table_args__ = (
        UniqueConstraint("requisition_id", "candidate_id", name="uq_match_requisition_candidate"),
        CheckConstraint("total_score >= 0 AND total_score <= 100", name="total_score_range"),
        CheckConstraint("rank IS NULL OR rank > 0", name="positive_rank"),
        CheckConstraint(
            "status IN (" + ",".join(f"'{value}'" for value in MATCH_STATUSES) + ")",
            name="valid_status",
        ),
        Index("ix_match_results_requisition_rank", "requisition_id", "rank"),
        Index("ix_match_results_requisition_score", "requisition_id", "total_score"),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    requisition_id: Mapped[int] = mapped_column(
        ForeignKey("job_requisitions.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(30), default="recommended", server_default="recommended", nullable=False
    )
    feedback_reason: Mapped[str | None] = mapped_column(String(200))
    feedback_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    feedback_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    computed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    candidate = relationship("Candidate")
    requisition = relationship("JobRequisition")
