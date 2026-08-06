"""add per-requisition blind review toggle

Revision ID: e1b7d4a92c60
Revises: d38c1a5e97b4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1b7d4a92c60"
down_revision: str | None = "d38c1a5e97b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Blind review stays the default. The NOT NULL server default backfills every
    # existing requisition with true, so interviews already in flight keep hiding
    # each side's evaluation until both stages are submitted, exactly as before.
    #
    # sa.true() compiles to native 1 on SQLite instead of the quoted TEXT literal
    # 'true'. The quoted spelling is what e7b2c91d5f40 had to clean up after: any
    # non-empty string reads back as True, so a later false would be ignored.
    with op.batch_alter_table("job_requisitions") as batch:
        batch.add_column(
            sa.Column(
                "blind_review_enabled",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("job_requisitions") as batch:
        batch.drop_column("blind_review_enabled")
