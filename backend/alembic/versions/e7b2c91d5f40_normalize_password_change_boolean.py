"""normalize legacy SQLite password-change boolean values

Revision ID: e7b2c91d5f40
Revises: d4a7f18c2e63
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b2c91d5f40"
down_revision: str | None = "d4a7f18c2e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return

    # e15b9d4c7a83 originally used the quoted server default ``'false'``. SQLite
    # stored that as TEXT on accounts which already existed when the column was
    # added. SQLAlchemy's Boolean result processor treats any non-empty string as
    # True, so those accounts were incorrectly blocked with "Password change
    # required". Normalize only recognized boolean spellings, preserving every
    # real forced-change flag and leaving all credential columns untouched.
    op.execute(
        sa.text(
            """
            UPDATE users
               SET must_change_password = 0
             WHERE typeof(must_change_password) = 'text'
               AND lower(trim(must_change_password)) IN ('0', 'false', 'f', 'no', 'n', 'off')
            """
        )
    )

    # Fix the legacy table default as well as the rows already affected by it.
    # Alembic's SQLite batch mode safely recreates the table because SQLite cannot
    # alter a column default in place. ``sa.false()`` compiles to native ``0`` on
    # SQLite instead of the quoted TEXT literal ``'false'``.
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "must_change_password",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
    op.execute(
        sa.text(
            """
            UPDATE users
               SET must_change_password = 1
             WHERE typeof(must_change_password) = 'text'
               AND lower(trim(must_change_password)) IN ('1', 'true', 't', 'yes', 'y', 'on')
            """
        )
    )


def downgrade() -> None:
    # Data normalization is intentionally irreversible. Reintroducing textual
    # booleans would recreate the authentication bug.
    pass
