"""add application interview tracking

Revision ID: b72e1f9a3c51
Revises: a61d9e8f2b40
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b72e1f9a3c51"
down_revision: str | None = "a61d9e8f2b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_applications") as batch:
        batch.add_column(sa.Column("interview_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("interview_result", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("interview_notes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("interview_updated_by", sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            "fk_job_applications_interview_updated_by_users",
            "users",
            ["interview_updated_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_job_applications_interview_updated_by",
            ["interview_updated_by"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("job_applications") as batch:
        batch.drop_index("ix_job_applications_interview_updated_by")
        batch.drop_constraint(
            "fk_job_applications_interview_updated_by_users",
            type_="foreignkey",
        )
        batch.drop_column("interview_updated_by")
        batch.drop_column("interview_notes")
        batch.drop_column("interview_result")
        batch.drop_column("interview_at")
