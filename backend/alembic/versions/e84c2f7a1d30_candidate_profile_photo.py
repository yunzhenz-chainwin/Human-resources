"""add private candidate profile photo metadata

Revision ID: e84c2f7a1d30
Revises: d21f8e3a4c90
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e84c2f7a1d30"
down_revision: str | None = "d21f8e3a4c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("photo_path", sa.String(length=500), nullable=True))
    op.add_column(
        "candidates", sa.Column("photo_content_type", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "candidates", sa.Column("photo_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("candidates", "photo_updated_at")
    op.drop_column("candidates", "photo_content_type")
    op.drop_column("candidates", "photo_path")
