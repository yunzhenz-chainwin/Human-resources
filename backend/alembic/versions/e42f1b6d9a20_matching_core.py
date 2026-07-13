"""add deterministic matching results

Revision ID: e42f1b6d9a20
Revises: c91e2a7b845f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e42f1b6d9a20"
down_revision: str | None = "c91e2a7b845f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "match_results",
        sa.Column("id", BIGINT_PK, primary_key=True),
        sa.Column(
            "requisition_id",
            sa.BigInteger(),
            sa.ForeignKey("job_requisitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.BigInteger(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gate_passed", sa.Boolean(), nullable=False),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("rank", sa.Integer()),
        sa.Column("status", sa.String(30), server_default="recommended", nullable=False),
        sa.Column("feedback_reason", sa.String(200)),
        sa.Column("feedback_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("feedback_at", sa.DateTime(timezone=True)),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "requisition_id", "candidate_id", name="uq_match_requisition_candidate"
        ),
        sa.CheckConstraint(
            "total_score >= 0 AND total_score <= 100",
            name="ck_match_results_total_score_range",
        ),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_match_results_positive_rank"),
        sa.CheckConstraint(
            "status IN ('ineligible','recommended','shortlisted','contacted','interview',"
            "'offered','hired','rejected_by_manager','withdrawn')",
            name="ck_match_results_valid_status",
        ),
    )
    op.create_index("ix_match_results_requisition_id", "match_results", ["requisition_id"])
    op.create_index("ix_match_results_candidate_id", "match_results", ["candidate_id"])
    op.create_index(
        "ix_match_results_requisition_rank", "match_results", ["requisition_id", "rank"]
    )
    op.create_index(
        "ix_match_results_requisition_score",
        "match_results",
        ["requisition_id", "total_score"],
    )


def downgrade() -> None:
    op.drop_table("match_results")
