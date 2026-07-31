"""persist versioned manager interview question plans

Revision ID: f6a2d4c8b901
Revises: 4a1d9f0b3c22, e7b2c91d5f40
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a2d4c8b901"
down_revision: tuple[str, str] = ("4a1d9f0b3c22", "e7b2c91d5f40")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_question_plans",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("personalization_basis", sa.JSON(), nullable=False),
        sa.Column("generation_mode", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("generation_warning", sa.Text(), nullable=True),
        sa.Column("generated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("generated_by_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generation_mode IN ('gemini','rules')",
            name=op.f("ck_interview_question_plans_valid_generation_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["job_applications.id"],
            name=op.f("fk_interview_question_plans_application_id_job_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_id"], ["users.id"],
            name=op.f("fk_interview_question_plans_generated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_question_plans")),
        sa.UniqueConstraint(
            "application_id", "version",
            name=op.f("uq_interview_question_plans_application_version"),
        ),
    )
    op.create_index(
        op.f("ix_interview_question_plans_application_id"),
        "interview_question_plans", ["application_id"], unique=False,
    )
    op.create_index(
        op.f("ix_interview_question_plans_context_hash"),
        "interview_question_plans", ["context_hash"], unique=False,
    )
    op.create_index(
        op.f("ix_interview_question_plans_generated_by_id"),
        "interview_question_plans", ["generated_by_id"], unique=False,
    )
    op.create_index(
        "ix_interview_question_plans_application_version",
        "interview_question_plans", ["application_id", "version"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_question_plans_application_version",
        table_name="interview_question_plans",
    )
    op.drop_index(
        op.f("ix_interview_question_plans_generated_by_id"),
        table_name="interview_question_plans",
    )
    op.drop_index(
        op.f("ix_interview_question_plans_context_hash"),
        table_name="interview_question_plans",
    )
    op.drop_index(
        op.f("ix_interview_question_plans_application_id"),
        table_name="interview_question_plans",
    )
    op.drop_table("interview_question_plans")
