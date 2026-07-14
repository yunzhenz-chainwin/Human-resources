"""persist explainable per-file resume source detection

Revision ID: d31c8a7e9f20
Revises: b84e2d6a77c1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d31c8a7e9f20"
down_revision: str | None = "b84e2d6a77c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("resume_files") as batch:
        batch.add_column(sa.Column("requested_source_platform", sa.String(20)))
        batch.add_column(sa.Column("source_confidence", sa.Numeric(3, 2)))
        batch.add_column(sa.Column("source_evidence", sa.JSON()))
        batch.add_column(
            sa.Column(
                "source_review_required",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )
        batch.add_column(sa.Column("source_reviewed_by", sa.BigInteger()))
        batch.add_column(sa.Column("source_reviewed_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_resume_files_source_reviewed_by_users",
            "users",
            ["source_reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_resume_files_valid_source_confidence",
            "source_confidence IS NULL OR (source_confidence >= 0 AND source_confidence <= 1)",
        )


def downgrade() -> None:
    with op.batch_alter_table("resume_files") as batch:
        batch.drop_constraint("ck_resume_files_valid_source_confidence", type_="check")
        batch.drop_constraint(
            "fk_resume_files_source_reviewed_by_users", type_="foreignkey"
        )
        batch.drop_column("source_reviewed_at")
        batch.drop_column("source_reviewed_by")
        batch.drop_column("source_review_required")
        batch.drop_column("source_evidence")
        batch.drop_column("source_confidence")
        batch.drop_column("requested_source_platform")
