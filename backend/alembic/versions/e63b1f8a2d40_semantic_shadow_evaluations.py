"""add isolated Gemini semantic shadow evaluations

Revision ID: e63b1f8a2d40
Revises: d52a9c7e41b8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e63b1f8a2d40"
down_revision: str = "d52a9c7e41b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    # This is deliberately a separate append-only experiment table.  No column,
    # trigger or foreign-key direction can write semantic output back to the formal
    # match score, gate, rank or workflow status.
    op.create_table(
        "semantic_shadow_evaluations",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("match_result_id", sa.BigInteger(), nullable=False),
        sa.Column("requisition_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("formal_total_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("formal_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("formal_rank", sa.Integer(), nullable=True),
        sa.Column("formal_status", sa.String(length=30), nullable=False),
        sa.Column("semantic_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("synonym_evidence", sa.JSON(), nullable=False),
        sa.Column("transferable_experience_evidence", sa.JSON(), nullable=False),
        sa.Column("concerns", sa.JSON(), nullable=False),
        sa.Column("insufficient_data", sa.JSON(), nullable=False),
        sa.Column("interview_questions", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("generation_status", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("prompt_snapshot", sa.JSON(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("thinking_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "semantic_score >= 0 AND semantic_score <= 100",
            name="ck_sem_shadow_score_range",
        ),
        sa.CheckConstraint(
            "generation_status IN ('completed','fallback')",
            name="ck_sem_shadow_generation_status",
        ),
        sa.CheckConstraint(
            "source IN ('gemini','rules_fallback')",
            name="ck_sem_shadow_source",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND "
            "thinking_tokens >= 0 AND total_tokens >= 0",
            name="ck_sem_shadow_tokens_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["match_results.id"],
            name="fk_sem_shadow_match_result",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requisition_id"],
            ["job_requisitions.id"],
            name="fk_sem_shadow_requisition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name="fk_sem_shadow_candidate",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name="fk_sem_shadow_requested_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_semantic_shadow_evaluations"),
    )
    op.create_index(
        "ix_semantic_shadow_evaluations_match_result_id",
        "semantic_shadow_evaluations",
        ["match_result_id"],
    )
    op.create_index(
        "ix_semantic_shadow_evaluations_requisition_id",
        "semantic_shadow_evaluations",
        ["requisition_id"],
    )
    op.create_index(
        "ix_semantic_shadow_evaluations_candidate_id",
        "semantic_shadow_evaluations",
        ["candidate_id"],
    )
    op.create_index(
        "ix_semantic_shadow_evaluations_requested_by",
        "semantic_shadow_evaluations",
        ["requested_by"],
    )
    op.create_index(
        "ix_semantic_shadow_evaluations_generated_at",
        "semantic_shadow_evaluations",
        ["generated_at"],
    )


def downgrade() -> None:
    op.drop_table("semantic_shadow_evaluations")

