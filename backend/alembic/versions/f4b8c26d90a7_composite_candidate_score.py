"""add configurable composite score weights and the persisted composite score

Revision ID: f4b8c26d90a7
Revises: e1b7d4a92c60
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4b8c26d90a7"
down_revision: str | None = "e1b7d4a92c60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All three columns are nullable with no server default on purpose.
    #
    # job_requisitions.composite_score_weights NULL means "use the built-in
    # defaults", the same convention match_weights already uses, so existing
    # requisitions keep the documented 20/15/25/15/25 split without a backfill.
    #
    # job_applications.composite_score_breakdown NULL is what distinguishes an
    # application whose composite was never computed from one that was computed
    # and came out null; backfilling either column would erase that difference,
    # and the composite is only ever written by an interview submission anyway.
    with op.batch_alter_table("job_requisitions") as batch:
        batch.add_column(sa.Column("composite_score_weights", sa.JSON(), nullable=True))
    with op.batch_alter_table("job_applications") as batch:
        batch.add_column(sa.Column("composite_score", sa.Numeric(5, 2), nullable=True))
        batch.add_column(sa.Column("composite_score_breakdown", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_applications") as batch:
        batch.drop_column("composite_score_breakdown")
        batch.drop_column("composite_score")
    with op.batch_alter_table("job_requisitions") as batch:
        batch.drop_column("composite_score_weights")
