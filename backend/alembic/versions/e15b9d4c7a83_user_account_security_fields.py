"""add account-security fields to users (must_change_password, lockout)

Revision ID: e15b9d4c7a83
Revises: d94a1f2b6c30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e15b9d4c7a83"
down_revision: str | None = "d94a1f2b6c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Force a credential change on next login (e.g. after an IT reset).
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            # Use a SQL boolean expression instead of the quoted string literal
            # ``'false'``. SQLite otherwise stores that literal as TEXT for rows
            # which predate this column; SQLAlchemy then interprets the non-empty
            # string as truthy and incorrectly forces a password change.
            server_default=sa.false(),
        ),
    )
    # Durable brute-force throttle: consecutive failures + optional temporary lock.
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "must_change_password")
