"""add interviewer-entered 0-100 overall score to interview records

Revision ID: c4e9b7d21f65
Revises: b6f0e4a2c913
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e9b7d21f65"
down_revision: str | None = "b6f0e4a2c913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # overall_score is a separate interviewer input, not a rescaling of the 1-5
    # overall_rating. Existing rows stay NULL on purpose: deriving a score the
    # interviewer never entered would fabricate evaluation evidence.
    with op.batch_alter_table("interview_records") as batch:
        batch.add_column(sa.Column("overall_score", sa.Integer()))
        batch.create_check_constraint(
            "valid_overall_score",
            "overall_score IS NULL OR overall_score BETWEEN 0 AND 100",
        )


def downgrade() -> None:
    with op.batch_alter_table("interview_records") as batch:
        batch.drop_constraint("valid_overall_score", type_="check")
        batch.drop_column("overall_score")
