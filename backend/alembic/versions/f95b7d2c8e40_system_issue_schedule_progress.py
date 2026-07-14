"""add schedule and progress to system issues

Revision ID: f95b7d2c8e40
Revises: e84c2f7a1d30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f95b7d2c8e40"
down_revision: str | None = "e84c2f7a1d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_issues",
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "system_issues",
        sa.Column("expected_completion_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_issues", "expected_completion_date")
    op.drop_column("system_issues", "progress_percent")
