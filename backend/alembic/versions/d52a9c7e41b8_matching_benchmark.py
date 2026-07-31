"""add isolated matching benchmark suites and blind ratings

Revision ID: d52a9c7e41b8
Revises: c27d8e5f4a61
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d52a9c7e41b8"
down_revision: str = "c27d8e5f4a61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "matching_benchmark_suites",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("fixture_version", sa.String(length=30), nullable=False),
        sa.Column("fixture_hash", sa.String(length=64), nullable=False),
        sa.Column("scoring_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="blind", nullable=False),
        sa.Column("case_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revealed_by_user_id", BIGINT_PK, nullable=True),
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
            "status IN ('blind','revealed')",
            name="ck_matching_benchmark_suites_valid_status",
        ),
        sa.CheckConstraint(
            "case_count >= 0",
            name="ck_matching_benchmark_suites_nonnegative_case_count",
        ),
        sa.ForeignKeyConstraint(
            ["revealed_by_user_id"],
            ["users.id"],
            name="fk_matching_benchmark_suites_revealed_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matching_benchmark_suites"),
        sa.UniqueConstraint("key", name="uq_matching_benchmark_suites_key"),
    )
    op.create_table(
        "matching_benchmark_cases",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("suite_id", BIGINT_PK, nullable=False),
        sa.Column("case_key", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("job_key", sa.String(length=50), nullable=False),
        sa.Column("scenario", sa.String(length=40), nullable=False),
        sa.Column("job_profile", sa.JSON(), nullable=False),
        sa.Column("candidate_profile", sa.JSON(), nullable=False),
        sa.Column("expected_verdict", sa.String(length=24), nullable=False),
        sa.Column("system_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("system_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("system_breakdown", sa.JSON(), nullable=False),
        sa.Column("data_completeness", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
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
            "sequence > 0",
            name="ck_matching_benchmark_cases_positive_sequence",
        ),
        sa.CheckConstraint(
            "expected_verdict IN ('interview','consider','reject','insufficient_data')",
            name="ck_matching_benchmark_cases_valid_expected_verdict",
        ),
        sa.CheckConstraint(
            "system_score >= 0 AND system_score <= 100",
            name="ck_matching_benchmark_cases_system_score_range",
        ),
        sa.CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 100",
            name="ck_matching_benchmark_cases_data_completeness_range",
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["matching_benchmark_suites.id"],
            name="fk_matching_benchmark_cases_suite_id_matching_benchmark_suites",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matching_benchmark_cases"),
        sa.UniqueConstraint("suite_id", "case_key", name="uq_benchmark_suite_case_key"),
        sa.UniqueConstraint("suite_id", "sequence", name="uq_benchmark_suite_sequence"),
    )
    op.create_index(
        "ix_matching_benchmark_cases_suite_id",
        "matching_benchmark_cases",
        ["suite_id"],
    )
    op.create_index(
        "ix_benchmark_cases_suite_job",
        "matching_benchmark_cases",
        ["suite_id", "job_key"],
    )
    op.create_table(
        "matching_benchmark_ratings",
        sa.Column("id", BIGINT_PK, nullable=False),
        sa.Column("case_id", BIGINT_PK, nullable=False),
        sa.Column("reviewer_id", BIGINT_PK, nullable=False),
        sa.Column("reviewer_role", sa.String(length=12), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("priority_rank", sa.SmallInteger(), nullable=True),
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
            "reviewer_role IN ('hr','manager')",
            name="ck_matching_benchmark_ratings_valid_reviewer_role",
        ),
        sa.CheckConstraint(
            "verdict IN ('interview','consider','reject','insufficient_data')",
            name="ck_matching_benchmark_ratings_valid_verdict",
        ),
        sa.CheckConstraint(
            "priority_rank IS NULL OR priority_rank BETWEEN 1 AND 10",
            name="ck_matching_benchmark_ratings_valid_priority_rank",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["matching_benchmark_cases.id"],
            name="fk_matching_benchmark_ratings_case_id_matching_benchmark_cases",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name="fk_matching_benchmark_ratings_reviewer_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matching_benchmark_ratings"),
        sa.UniqueConstraint("case_id", "reviewer_id", name="uq_benchmark_case_reviewer"),
    )
    op.create_index(
        "ix_matching_benchmark_ratings_case_id",
        "matching_benchmark_ratings",
        ["case_id"],
    )
    op.create_index(
        "ix_matching_benchmark_ratings_reviewer_id",
        "matching_benchmark_ratings",
        ["reviewer_id"],
    )
    op.create_index(
        "ix_benchmark_ratings_case_role",
        "matching_benchmark_ratings",
        ["case_id", "reviewer_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_benchmark_ratings_case_role", table_name="matching_benchmark_ratings")
    op.drop_index(
        "ix_matching_benchmark_ratings_reviewer_id",
        table_name="matching_benchmark_ratings",
    )
    op.drop_index(
        "ix_matching_benchmark_ratings_case_id",
        table_name="matching_benchmark_ratings",
    )
    op.drop_table("matching_benchmark_ratings")
    op.drop_index("ix_benchmark_cases_suite_job", table_name="matching_benchmark_cases")
    op.drop_index(
        "ix_matching_benchmark_cases_suite_id",
        table_name="matching_benchmark_cases",
    )
    op.drop_table("matching_benchmark_cases")
    op.drop_table("matching_benchmark_suites")
