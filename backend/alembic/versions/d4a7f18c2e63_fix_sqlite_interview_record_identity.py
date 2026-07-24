"""fix SQLite interview record identity generation

Revision ID: d4a7f18c2e63
Revises: c9f6a12e4d70
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a7f18c2e63"
down_revision: str | None = "c9f6a12e4d70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite only aliases an exact ``INTEGER PRIMARY KEY`` to its rowid.  The
    # original table migration used BIGINT, so inserts that omitted ``id``
    # failed with ``NOT NULL constraint failed: interview_records.id`` even
    # though the ORM correctly treats this key as auto-generated.
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table("interview_records", recreate="always") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
            autoincrement=True,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table("interview_records", recreate="always") as batch:
        batch.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
            autoincrement=False,
        )
