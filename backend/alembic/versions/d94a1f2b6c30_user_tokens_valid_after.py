"""add users.tokens_valid_after for access-token invalidation

Revision ID: d94a1f2b6c30
Revises: c83f2a6d4e70
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d94a1f2b6c30"
down_revision: str | None = "c83f2a6d4e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Timestamp of the last credential change; access tokens issued (iat) before
    # this instant are rejected in get_current_user so a password reset/change
    # immediately invalidates already-issued access tokens.
    op.add_column(
        "users",
        sa.Column("tokens_valid_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "tokens_valid_after")
