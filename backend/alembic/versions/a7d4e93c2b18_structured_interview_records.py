"""add structured interview records

Revision ID: a7d4e93c2b18
Revises: f2c7a91d4e60
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d4e93c2b18"
down_revision: str | None = "f2c7a91d4e60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_records",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("interviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(length=20), nullable=True),
        sa.Column("overall_rating", sa.Integer(), nullable=True),
        sa.Column("interviewer_id", sa.BigInteger(), nullable=True),
        sa.Column("interviewer_name", sa.String(length=100), nullable=False),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_name", sa.String(length=100), nullable=False),
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
        sa.CheckConstraint("stage IN ('hr','manager')", name="ck_interview_records_valid_stage"),
        sa.CheckConstraint(
            "mode IN ('onsite','video','phone','other')",
            name="ck_interview_records_valid_mode",
        ),
        sa.CheckConstraint(
            "status IN ('planned','in_progress','completed','cancelled','no_show')",
            name="ck_interview_records_valid_status",
        ),
        sa.CheckConstraint(
            "recommendation IS NULL OR recommendation IN ('advance','hold','reject','offer')",
            name="ck_interview_records_valid_recommendation",
        ),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 1 AND 1440",
            name="ck_interview_records_valid_duration_minutes",
        ),
        sa.CheckConstraint(
            "overall_rating IS NULL OR overall_rating BETWEEN 1 AND 5",
            name="ck_interview_records_valid_overall_rating",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["job_applications.id"],
            name="fk_interview_records_application_id_job_applications",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["interviewer_id"],
            ["users.id"],
            name="fk_interview_records_interviewer_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name="fk_interview_records_updated_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_interview_records"),
    )
    op.create_index(
        "ix_interview_records_application_id",
        "interview_records",
        ["application_id"],
    )
    op.create_index(
        "ix_interview_records_interviewer_id",
        "interview_records",
        ["interviewer_id"],
    )
    op.create_index(
        "ix_interview_records_updated_by_id",
        "interview_records",
        ["updated_by_id"],
    )
    op.create_index(
        "ix_interview_records_application_interviewed_at",
        "interview_records",
        ["application_id", "interviewed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_records_application_interviewed_at",
        table_name="interview_records",
    )
    op.drop_index("ix_interview_records_updated_by_id", table_name="interview_records")
    op.drop_index("ix_interview_records_interviewer_id", table_name="interview_records")
    op.drop_index("ix_interview_records_application_id", table_name="interview_records")
    op.drop_table("interview_records")
