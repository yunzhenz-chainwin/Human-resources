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
    # Some preserved local databases were created from the current ORM metadata
    # before this branch revision was stamped. Keep this migration safe for those
    # databases instead of failing with a duplicate-column/index error.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("system_issues")}
    if "category" not in columns:
        op.add_column(
            "system_issues",
            sa.Column("category", sa.String(length=30), server_default="other", nullable=False),
        )

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("system_issues")}
    index_name = op.f("ix_system_issues_category")
    if index_name not in indexes:
        op.create_index(index_name, "system_issues", ["category"])


def downgrade() -> None:
    op.drop_index(op.f("ix_system_issues_category"), table_name="system_issues")
    op.drop_column("system_issues", "category")
