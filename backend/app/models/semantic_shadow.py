from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import BIGINT_PK, Base, TimestampMixin, UTCDateTime


class SemanticShadowEvaluation(TimestampMixin, Base):
    """Experimental semantic assessment stored beside, never inside, formal matching.

    The table deliberately has no relationship that can cascade an evaluation back into
    ``match_results``.  Formal score, gate, rank and workflow status are captured only as
    immutable snapshots for later offline comparison.
    """

    __tablename__ = "semantic_shadow_evaluations"
    __table_args__ = (
        CheckConstraint(
            "semantic_score >= 0 AND semantic_score <= 100",
            name="semantic_shadow_score_range",
        ),
        CheckConstraint(
            "generation_status IN ('completed','fallback')",
            name="semantic_shadow_generation_status",
        ),
        CheckConstraint(
            "source IN ('gemini','rules_fallback')",
            name="semantic_shadow_source",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND "
            "thinking_tokens >= 0 AND total_tokens >= 0",
            name="semantic_shadow_token_usage_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True)
    match_result_id: Mapped[int] = mapped_column(
        ForeignKey("match_results.id", ondelete="CASCADE"), index=True, nullable=False
    )
    requisition_id: Mapped[int] = mapped_column(
        ForeignKey("job_requisitions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True, nullable=False
    )
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # Immutable comparison snapshots.  Nothing in this model is used by the formal
    # matching service to update or re-rank MatchResult rows.
    formal_total_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    formal_gate_passed: Mapped[bool] = mapped_column(nullable=False)
    formal_rank: Mapped[int | None] = mapped_column(Integer)
    formal_status: Mapped[str] = mapped_column(String(30), nullable=False)

    semantic_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    synonym_evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    transferable_experience_evidence: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    concerns: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    insufficient_data: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    interview_questions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)

    source: Mapped[str] = mapped_column(String(30), nullable=False)
    generation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    # This is the exact allow-listed, de-identified input sent to the model, not the
    # original resume and never an API key or raw response.
    prompt_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    thinking_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(60))
    # Only a controlled diagnostic category is stored.  Provider response bodies can
    # contain unexpected data, so they are intentionally never persisted here.
    error_detail: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False, index=True
    )
