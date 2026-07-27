"""add category to IT system issues

Revision ID: 4a1d9f0b3c22
Revises: f95b7d2c8e40
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a1d9f0b3c22"
down_revision: str | None = "f95b7d2c8e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "system_issues",
        sa.Column("category", sa.String(length=30), server_default="other", nullable=False),
    )
    op.create_index(op.f("ix_system_issues_category"), "system_issues", ["category"])


def downgrade() -> None:
    op.drop_index(op.f("ix_system_issues_category"), table_name="system_issues")
    op.drop_column("system_issues", "category")
