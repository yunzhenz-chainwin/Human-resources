"""add HR-only private interview notes

Revision ID: c9f6a12e4d70
Revises: b8e5f04d3c29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9f6a12e4d70"
down_revision: str | None = "b8e5f04d3c29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("interview_records") as batch:
        batch.add_column(sa.Column("private_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("interview_records") as batch:
        batch.drop_column("private_notes")
